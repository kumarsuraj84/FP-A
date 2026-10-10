"""Detectors: turn what the platform already computes into exception CANDIDATES (ranked later by service.ingest). Thresholds are fixed and UNCALIBRATED (labelled so in the
inbox) until Finance has reviewed twelve months of history. Evidence carries a small snapshot (observed, reference, run id, drill link), never a finance record.
Candidate fields: exception_type, domain, entity, site_code, metric_id, period (date), subject_key, title, severity, materiality, recency, actionability (0-100), escalated,
evidence, drill_link, source_run_id."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from ..adjustments import templates as tpl
from ..mgmt import engine as eng
from ..mgmt import service as msvc

D = Decimal
# UNCALIBRATED thresholds
LINE_VARIANCE_PCT = D("15")          # percent change month on month
LINE_VARIANCE_MIN_CR = D("0.25")     # and at least this many crore
UNMAPPED_MIN_CR = D("0.05")
STALE_APPROVAL_DAYS = 3
VARIANCE_LINES = ("revenue", "material_cost", "rent", "employee_cost", "power_fuel", "advertisement", "freight", "other_expenses", "dc_cost", "ho_cost")
REVENUE_LINES = ("revenue",)


def clamp(x) -> float:
    return float(max(D(0), min(D(100), D(x))))


def last_complete_month(g) -> tuple[str, str | None]:
    months = msvc.available_months(g)
    asof = msvc.as_of(g)
    last = months[-1]
    if asof and asof.strftime("%Y-%m") == last and asof.day < 28 and len(months) > 1:
        return months[-2], last
    return last, None


def recency(m: str) -> float:
    y, mo = int(m[:4]), int(m[5:7])
    age = (date.today().year - y) * 12 + date.today().month - mo
    return clamp(100 - 25 * max(age, 0))


def line_variance(g) -> list[dict]:
    month, _ = last_complete_month(g)
    months = eng.month_list(month, month)
    prev = (date(int(month[:4]), int(month[5:7]), 1) - timedelta(days=1)).strftime("%Y-%m")
    ctx = msvc.run(g, prev, month)
    L = {x["key"]: x for x in ctx["lines"]}
    out = []
    for k in VARIANCE_LINES:
        cur, old = L[k]["values"][month]["total"], L[k]["values"][prev]["total"]
        change = cur - old
        if old == 0 or abs(change) < LINE_VARIANCE_MIN_CR:
            continue
        pct = change / abs(old) * 100
        if abs(pct) < LINE_VARIANCE_PCT:
            continue
        domain = "REVENUE" if k in REVENUE_LINES else "EXPENSE"
        out.append({"exception_type": "LINE_MONTH_MOVE", "domain": domain, "entity": "CONSOLIDATED", "metric_id": k, "period": date(int(month[:4]), int(month[5:7]), 1), "subject_key": k,
                    "title": f"{eng.LABEL[k]} moved {pct:+.0f}% against {prev}", "severity": clamp(abs(pct) * 2), "materiality": clamp(abs(change) * 20), "recency": recency(month), "actionability": 60,
                    "escalated": False, "evidence": {"month": month, "reference_month": prev, "observed_cr": str(cur), "reference_cr": str(old), "change_cr": str(change), "change_pct": f"{pct:.1f}", "basis": "management total"},
                    "drill_link": f"/mgmt?from_month={month}&to_month={month}", "source_run_id": ctx.get("run_id")})
    return out


def unmapped(g) -> list[dict]:
    month, _ = last_complete_month(g)
    ctx = msvc.run(g, month, month)
    out = []
    for e in ctx["book"].exceptions.values():
        if abs(e["amount_cr"]) >= UNMAPPED_MIN_CR and month in e["months"]:
            out.append({"exception_type": "UNMAPPED_LEDGER", "domain": "MAPPING", "entity": None, "metric_id": "ledger_map", "period": date(int(month[:4]), int(month[5:7]), 1), "subject_key": e["ledger"],
                        "title": f"Ledger '{e['ledger']}' has no management group", "severity": 55, "materiality": clamp(abs(e["amount_cr"]) * 30), "recency": recency(month), "actionability": 90,
                        "escalated": False, "evidence": {"ledger": e["ledger"], "net_cr": str(e["amount_cr"]), "reason": e["reason"]}, "drill_link": "/mgmt/mapping"})
    return out


def control_failures(g) -> list[dict]:
    month, partial = last_complete_month(g)
    out = []
    for r in g.execute("SELECT run_id, control_id, dimension, left_value, right_value, variance, verdict FROM pnl.v_control WHERE verdict <> 'PASS'").fetchall():
        is_partial = partial is not None and r["dimension"] == partial
        out.append({"exception_type": "CONTROL_FAIL", "domain": "CONTROLS", "entity": None, "metric_id": r["control_id"], "period": None, "subject_key": f"{r['control_id']}:{r['dimension']}",
                    "title": f"Control {r['control_id']} fails for {r['dimension']}" + (" (partial month, probably a cut-off difference)" if is_partial else ""),
                    "severity": 45 if is_partial else 90, "materiality": 50, "recency": 100, "actionability": 70, "escalated": not is_partial,
                    "evidence": {"control": r["control_id"], "dimension": r["dimension"], "source": str(r["left_value"]), "extract": str(r["right_value"]), "variance": str(r["variance"])},
                    "drill_link": "/mgmt", "source_run_id": r["run_id"]})
    return out


def provision_gaps(app) -> list[dict]:
    today = date.today()
    lo = date(today.year - 1, today.month, 1).strftime("%Y-%m")
    cal = tpl.calendar(app, lo, today.strftime("%Y-%m"))
    out = []
    for row in cal["rows"]:
        for m, c in row["cells"].items():
            if c["state"] == "missing":
                out.append({"exception_type": "PROVISION_MISSING", "domain": "CLOSE", "entity": row["entity"], "metric_id": row["line"], "period": date(int(m[:4]), int(m[5:7]), 1), "subject_key": row["template_id"],
                            "title": f"Provision '{row['name']}' is missing for {m}", "severity": 70, "materiality": 50, "recency": recency(m), "actionability": 95, "escalated": m == today.strftime("%Y-%m"),
                            "evidence": {"template": row["name"], "month": m}, "drill_link": "/adjustments"})
    return out


def stale_approvals(app) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=STALE_APPROVAL_DAYS)
    out = []
    for kind, table, idcol, status, at in (("ADJUSTMENT", "adjustment", "adjustment_id", "REVIEW", "submitted_at"), ("CORRECTION", "correction_request", "request_id", "SUBMITTED", "submitted_at")):
        for r in app.execute(f"SELECT {idcol} AS id, {at} AS at FROM {table} WHERE status = %s AND {at} < %s", (status, cutoff)).fetchall():
            out.append({"exception_type": f"{kind}_AWAITING_APPROVAL", "domain": "CLOSE", "entity": None, "metric_id": kind.lower(), "period": None, "subject_key": str(r["id"]),
                        "title": f"A {kind.lower()} has waited more than {STALE_APPROVAL_DAYS} days for approval", "severity": 50, "materiality": 30, "recency": 100, "actionability": 100, "escalated": False,
                        "evidence": {"submitted_at": r["at"].isoformat()}, "drill_link": "/adjustments" if kind == "ADJUSTMENT" else "/corrections"})
    return out


def intercompany(g) -> list[dict]:
    try:
        from ..gold import intercompany as ic
        d = ic.compute(g)
    except Exception:  # noqa: BLE001  not configured on this install
        return []
    out = []
    if not d["controls"].get("loan_mirrors", True) and d["pairs"]:
        out.append({"exception_type": "INTERCOMPANY_MIRROR", "domain": "RELATED_PARTY", "entity": None, "metric_id": "loan_mirror", "period": None, "subject_key": "LOAN",
                    "title": "The intercompany loan does not mirror between HoldCo and SubCo", "severity": 75, "materiality": 60, "recency": 80, "actionability": 60, "escalated": False,
                    "evidence": {"variance_cr": str(d["controls"].get("loan_mirror_variance_cr"))}, "drill_link": "/related"})
    return out


def run_all(app, g) -> list[dict]:
    out, errors = [], []
    for name, fn, arg in (("line_variance", line_variance, g), ("unmapped", unmapped, g), ("control_failures", control_failures, g), ("provision_gaps", provision_gaps, app),
                          ("stale_approvals", stale_approvals, app), ("intercompany", intercompany, g)):
        try:
            out += fn(arg)
        except Exception as e:  # noqa: BLE001  one detector failing must not hide the others
            errors.append(f"{name}: {type(e).__name__}")
    return out, errors
