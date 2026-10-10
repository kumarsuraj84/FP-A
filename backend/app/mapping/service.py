"""Mapping Governance: ledger -> management group and site -> location type as versioned, effective-dated, approved rules (migration 009).

A standing rule is not a correction. A change creates a NEW VERSION that supersedes the rule in force (the old version ends the month before); an ACTIVE rule is never edited. The engine
reads the rules in force in each month (config.py), so a past month stays reproducible. Impact preview re-runs the management P&L with the proposed rule laid over the mapping.
The legacy CSV files are imported once as ACTIVE version 1 (administrator, source legacy_csv_import) and validated against the engine before FPA_MAPPING_SOURCE is switched to app."""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import psycopg

from ..adjustments.service import Problem, db_error, month_start
from ..auth.service import Actor, audit
from ..mgmt import config as cfg
from ..mgmt import service as msvc

DOMAINS = ("LEDGER_GROUP", "SITE_LOCATION")
MAKERS = ("fpa_manager", "controller", "admin", "finance_reviewer")
CHECKERS = ("fpa_manager", "finance_reviewer", "controller", "admin")
BASELINE_FROM = date(2000, 1, 1)
GROUPS = sorted(set(cfg.KEY_OF_GROUP) | {cfg.EXCLUDED})


def need(actor: Actor, roles: tuple, what: str) -> None:
    if actor.role not in roles:
        raise Problem(f"Your role ({actor.role}) cannot {what}.", 403)


def view(r: dict) -> dict:
    out = {k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in r.items()}
    out["effective_from"] = r["effective_from"].strftime("%Y-%m")
    out["effective_to"] = r["effective_to"].strftime("%Y-%m") if r["effective_to"] else None
    out["in_force_now"] = r["status"] in ("ACTIVE", "RETIRED") and r["effective_from"] <= date.today().replace(day=1) and (r["effective_to"] is None or r["effective_to"] >= date.today().replace(day=1))
    return out


def fetch(conn, mapping_id: str) -> dict:
    r = conn.execute("SELECT * FROM mapping_rule WHERE mapping_id = %s", (mapping_id,)).fetchone()
    if r is None:
        raise Problem("No such mapping.", 404)
    return r


def event(conn, actor: Actor, mapping_id: str, etype: str, to: str, comment: str | None = None) -> None:
    try:
        conn.execute("INSERT INTO mapping_event (mapping_id, event_type, to_status, actor_user_id, comment) VALUES (%s, %s, %s, %s, %s)", (mapping_id, etype, to, actor.user_id, comment))
    except psycopg.Error as e:
        conn.rollback()
        raise db_error(e) from None
    audit(conn, actor.email, "mapping_" + etype.lower(), "mapping_rule", str(mapping_id), {"to_status": to, "comment": comment}, actor.user_id)


def in_force(conn, domain: str, key: str, month: date) -> dict | None:
    return conn.execute("""SELECT * FROM mapping_rule WHERE domain = %s AND source_key = %s AND status IN ('ACTIVE', 'RETIRED') AND effective_from <= %s AND (effective_to IS NULL OR effective_to >= %s)
                           ORDER BY version DESC LIMIT 1""", (domain, key, month, month)).fetchone()


def shape(p: dict) -> dict:
    domain = str(p.get("domain", "")).upper()
    if domain not in DOMAINS:
        raise Problem("Choose a mapping domain: LEDGER_GROUP or SITE_LOCATION.")
    key, value = str(p.get("source_key", "")).strip(), str(p.get("mapped_value", "")).strip()
    if not key:
        raise Problem("Enter the ledger name or the site code.")
    if domain == "LEDGER_GROUP" and value not in GROUPS:
        raise Problem("The management group must be one of the Management P&L groups (or EXCLUDED for inventory-flow ledgers).")
    if domain == "SITE_LOCATION":
        if not key.isdigit():
            raise Problem("A site code is a number.")
        if value not in ("STORES", "DC", "HO"):
            raise Problem("The location type is STORES, DC or HO.")
    reason = str(p.get("reason", "")).strip()
    if len(reason) < 10:
        raise Problem("Explain why in at least 10 characters.")
    att = {k: str(p[k]).strip() for k in ("major_group", "category", "location_rule", "note", "short_name") if p.get(k)}
    return {"domain": domain, "source_key": key, "mapped_value": value, "attrs": att, "effective_from": month_start(str(p.get("effective_from", ""))), "reason": reason,
            "evidence_ref": (str(p.get("evidence_ref", "")).strip() or None)}


def create(conn, actor: Actor, p: dict) -> dict:
    need(actor, MAKERS, "propose mappings")
    s = shape(p)
    cur = in_force(conn, s["domain"], s["source_key"], s["effective_from"]) or conn.execute(
        "SELECT * FROM mapping_rule WHERE domain = %s AND source_key = %s AND status = 'ACTIVE' ORDER BY version DESC LIMIT 1", (s["domain"], s["source_key"])).fetchone()
    if cur and cur["status"] == "ACTIVE":
        if s["effective_from"] <= cur["effective_from"]:
            raise Problem(f"The rule in force starts {cur['effective_from'].strftime('%Y-%m')}; a new version must start after that month.", 409)
        if cur["mapped_value"] == s["mapped_value"]:
            raise Problem("The key is already mapped to that value from then on.", 409)
    supersedes, version = (cur["mapping_id"], cur["version"] + 1) if cur and cur["status"] == "ACTIVE" else (None, 1)
    if supersedes is None and conn.execute("SELECT 1 FROM mapping_rule WHERE domain = %s AND source_key = %s AND status = 'ACTIVE'", (s["domain"], s["source_key"])).fetchone():
        raise Problem("An active rule exists from a later month; propose the change against it.", 409)
    import json
    try:
        row = conn.execute("""INSERT INTO mapping_rule (domain, source_key, mapped_value, attrs, effective_from, version, supersedes_id, reason, evidence_ref, requested_by)
                              VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s) RETURNING mapping_id""",
                           (s["domain"], s["source_key"], s["mapped_value"], json.dumps(s["attrs"]), s["effective_from"], version, supersedes, s["reason"], s["evidence_ref"], actor.user_id)).fetchone()
    except psycopg.errors.UniqueViolation:
        conn.rollback()
        raise Problem("A proposal for this key is already pending: finish or withdraw it first.", 409) from None
    except psycopg.Error as e:
        conn.rollback()
        raise db_error(e) from None
    mid = str(row["mapping_id"])
    event(conn, actor, mid, "CREATED", "DRAFT")
    conn.commit()
    return view(fetch(conn, mid))


ACTIONS = {
    "submit": ("SUBMITTED", "SUBMITTED", MAKERS, False), "approve": ("APPROVED", "APPROVED", CHECKERS, False), "activate": ("ACTIVATED", "ACTIVE", CHECKERS, False),
    "reject": ("REJECTED", "REJECTED", CHECKERS, True), "withdraw": ("WITHDRAWN", "WITHDRAWN", MAKERS, False), "void": ("VOIDED", "WITHDRAWN", CHECKERS, True), "retire": ("RETIRED", "RETIRED", CHECKERS, True),
}


def act(conn, actor: Actor, mapping_id: str, action: str, comment: str | None) -> dict:
    if action not in ACTIONS:
        raise Problem("Unknown action.", 404)
    etype, to, roles, reason = ACTIONS[action]
    need(actor, roles, action + " mappings")
    if reason and len((comment or "").strip()) < 10:
        raise Problem("Give a reason of at least 10 characters.")
    fetch(conn, mapping_id)
    event(conn, actor, mapping_id, etype, to, comment)
    conn.commit()
    if action in ("activate", "retire"):
        cfg.clear_mapping_cache()
        msvc._cache.clear()
    return view(fetch(conn, mapping_id))


def comment(conn, actor: Actor, mapping_id: str, text: str) -> dict:
    if len((text or "").strip()) < 3:
        raise Problem("Write a comment.")
    fetch(conn, mapping_id)
    event(conn, actor, mapping_id, "COMMENTED", "DRAFT", text.strip())
    conn.commit()
    return view(fetch(conn, mapping_id))


def listing(conn, domain: str | None, status: str | None, search: str | None, limit: int, offset: int) -> dict:
    where, args = [], []
    for col, val in (("domain", domain), ("status", status)):
        if val:
            where.append(f"{col} = %s")
            args.append(val.upper())
    if search:
        where.append("source_key ILIKE %s")
        args.append(f"%{search}%")
    w = ("WHERE " + " AND ".join(where)) if where else ""
    counts = {r["status"]: r["n"] for r in conn.execute("SELECT status, count(*) AS n FROM mapping_rule GROUP BY status").fetchall()}
    total = conn.execute(f"SELECT count(*) AS n FROM mapping_rule {w}", args).fetchone()["n"]
    rows = conn.execute(f"SELECT * FROM mapping_rule {w} ORDER BY (status IN ('SUBMITTED', 'APPROVED', 'DRAFT')) DESC, source_key, version DESC LIMIT %s OFFSET %s", args + [limit, offset]).fetchall()
    return {"total": total, "counts": counts, "source_in_use": cfg.mapping_source(), "items": [view(r) for r in rows], "groups": GROUPS}


def history(conn, mapping_id: str) -> dict:
    r = fetch(conn, mapping_id)
    ev = [dict(x) for x in conn.execute("""SELECT e.seq, e.event_type, e.from_status, e.to_status, e.comment, e.at, u.email AS actor_email FROM mapping_event e LEFT JOIN app_user u ON u.user_id = e.actor_user_id
                                           WHERE e.mapping_id = %s ORDER BY e.seq""", (mapping_id,)).fetchall()]
    chain = [view(x) for x in conn.execute("SELECT * FROM mapping_rule WHERE domain = %s AND source_key = %s AND status NOT IN ('REJECTED', 'WITHDRAWN') ORDER BY version", (r["domain"], r["source_key"])).fetchall()]
    return {"events": ev, "versions": chain}


# --------------------------------------------------------------------------- impact preview and validation

CHANGED = 0.00005


def run_lines(g, lo: str, hi: str) -> dict:
    ctx = msvc.run(g, lo, hi)
    return {x["key"]: x for x in ctx["lines"] if x["kind"] != "pct"}


def diff_lines(a: dict, b: dict, months: list[str]) -> list[dict]:
    out = []
    for k, la in a.items():
        lb = b[k]
        tot = lb["total"]["total"] - la["total"]["total"]
        per = {m: lb["values"][m]["total"] - la["values"][m]["total"] for m in months}
        if abs(tot) > Decimal(str(CHANGED)) or any(abs(v) > Decimal(str(CHANGED)) for v in per.values()):
            out.append({"key": k, "label": la["label"], "before": la["total"]["total"], "after": lb["total"]["total"], "change": tot.quantize(Decimal("0.0001")),
                        "by_month": {m: v.quantize(Decimal("0.0001")) for m, v in per.items() if abs(v) > Decimal(str(CHANGED))}})
    return out


def preview(gold, rule: dict) -> dict:
    """The management P&L before and after the rule, from its effective month to the latest month. Nothing is written."""
    if gold is None:
        raise Problem("The management data (gold_fpa) is not available, so the impact cannot be previewed.", 503)
    with gold.session("pnl") as g:
        months_all = msvc.available_months(g)
        lo = max(rule["effective_from"].strftime("%Y-%m"), months_all[0])
        hi = months_all[-1]
        if lo > hi:
            return {"from_month": lo, "to_month": hi, "lines": [], "note": "The rule starts after the latest month of data: no month is affected yet."}
        months = [m for m in months_all if lo <= m <= hi]
        with cfg.forced(None, None):
            before = run_lines(g, lo, hi)
        with cfg.forced(None, {"domain": rule["domain"], "source_key": rule["source_key"], "mapped_value": rule["mapped_value"], "effective_from": rule["effective_from"], "attrs": rule.get("attrs") or {}}):
            after = run_lines(g, lo, hi)
    changed = diff_lines(before, after, months)
    return {"from_month": lo, "to_month": hi, "lines": changed, "note": "Management total in crore before and after the rule, month by month. A mapping moves cost between lines (the total of all lines changes only when a ledger enters or leaves the P&L)."}


def preview_saved(conn, gold, mapping_id: str) -> dict:
    r = fetch(conn, mapping_id)
    return preview(gold, {**r})


def preview_payload(gold, p: dict) -> dict:
    s = shape(p)
    return preview(gold, s)


def validate(conn, gold, lo: str | None, hi: str | None) -> dict:
    """Is the app mapping the same as the legacy CSV? Key by key for the current month, and by running the management P&L under each source for a window."""
    if gold is None:
        raise Problem("The management data (gold_fpa) is not available.", 503)
    with cfg.forced("csv", None):
        csv_l, csv_s = cfg.ledger_map(), cfg.site_loc()
    cfg.clear_mapping_cache()
    with cfg.forced("app", None):
        app_l, app_s = cfg.ledger_map(), cfg.site_loc()
    diffs = []
    for k in sorted(set(csv_l) | set(app_l)):
        a, b = csv_l.get(k), app_l.get(k)
        if (a or {}).get("mgmt_group") != (b or {}).get("mgmt_group"):
            diffs.append({"domain": "LEDGER_GROUP", "key": k, "csv": (a or {}).get("mgmt_group"), "app": (b or {}).get("mgmt_group")})
    for k in sorted(set(csv_s) | set(app_s)):
        a, b = csv_s.get(k), app_s.get(k)
        if (a or {}).get("location_type") != (b or {}).get("location_type"):
            diffs.append({"domain": "SITE_LOCATION", "key": str(k), "csv": (a or {}).get("location_type"), "app": (b or {}).get("location_type")})
    with gold.session("pnl") as g:
        months = msvc.available_months(g)
        lo = lo or months[0]
        hi = hi or months[-1]
        with cfg.forced("csv", None):
            a = run_lines(g, lo, hi)
        with cfg.forced("app", None):
            b = run_lines(g, lo, hi)
    mlist = [m for m in months if lo <= m <= hi]
    line_diffs = diff_lines(a, b, mlist)
    n_app = conn.execute("SELECT count(*) AS n FROM mapping_rule WHERE status IN ('ACTIVE', 'RETIRED')").fetchone()["n"]
    return {"window": [lo, hi], "csv_ledgers": len(csv_l), "app_ledgers": len(app_l), "csv_sites": len(csv_s), "app_sites": len(app_s), "active_rules": n_app, "key_differences": diffs[:200], "key_difference_count": len(diffs),
            "line_differences": line_diffs, "identical": not diffs and not line_diffs,
            "note": "Identical means every mapped key and every Management P&L line total agree under both sources: safe to set FPA_MAPPING_SOURCE=app."}


# --------------------------------------------------------------------------- the one-time baseline import

def import_baseline(conn, actor: Actor) -> dict:
    """Legacy CSV files -> ACTIVE version 1 rules (event IMPORTED). Administrator only. Idempotent: a key that already has an ACTIVE rule is skipped."""
    if actor.role != "admin":
        raise Problem("Only an administrator imports the legacy baseline.", 403)
    import json
    made, skipped = {"LEDGER_GROUP": 0, "SITE_LOCATION": 0}, 0
    with cfg.forced("csv", None):
        ledgers = [r for r in cfg._ledger_map_csv().values() if r.get("source") != "engine_default" and r.get("mgmt_group")]
        sites = list(cfg.site_loc().values())
    items = [("LEDGER_GROUP", r["ledger"], r["mgmt_group"], {k: r.get(k, "") for k in ("major_group", "category", "location_rule", "note") if r.get(k)}) for r in ledgers]
    items += [("SITE_LOCATION", str(r["site_code"]), r["location_type"], {k: r.get(k, "") for k in ("short_name",) if r.get(k)} | ({"note": r["reason"]} if r.get("reason") else {})) for r in sites]
    for domain, key, value, attrs in items:
        if conn.execute("SELECT 1 FROM mapping_rule WHERE domain = %s AND source_key = %s AND status IN ('ACTIVE', 'RETIRED')", (domain, key)).fetchone():
            skipped += 1
            continue
        try:
            row = conn.execute("""INSERT INTO mapping_rule (domain, source_key, mapped_value, attrs, effective_from, source, reason, evidence_ref, requested_by)
                                  VALUES (%s, %s, %s, %s::jsonb, %s, 'legacy_csv_import', 'Baseline imported once from the legacy CSV mapping files.', 'config/mgmt (legacy)', %s) RETURNING mapping_id""",
                               (domain, key, value, json.dumps(attrs), BASELINE_FROM, actor.user_id)).fetchone()
        except psycopg.Error as e:
            conn.rollback()
            raise db_error(e) from None
        mid = str(row["mapping_id"])
        event(conn, actor, mid, "CREATED", "DRAFT")
        event(conn, actor, mid, "IMPORTED", "ACTIVE", "Version 1 from the legacy CSV baseline.")
        made[domain] += 1
    conn.commit()
    cfg.clear_mapping_cache()
    return {"imported": made, "skipped_existing": skipped, "next": "Run validate; when it reports identical, set FPA_MAPPING_SOURCE=app and restart the API."}
