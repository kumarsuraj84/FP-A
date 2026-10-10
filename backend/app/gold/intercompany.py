"""Intercompany loan, interest and service charges, derived from the LEDGER (gold_fpa.voucher_lines), read-only.

HoldCo = Citykart Ventures (gold entity VENTURES), SubCo = Citykart Stores (gold entity RETAIL). There are no separate intercompany tables: the ledgers that carry
the loan, the interest and the quarterly service charges are listed in config/mgmt/intercompany_ledgers.csv (git-ignored; real finance data) and read here.

Columns: role (loan | interest_accrual | interest_expense | interest_payable | service_income | service_charge | other), pair_id (LOAN | INTEREST | SERVICE | OTHER),
entity (VENTURES | RETAIL), glcode, glname, side (asset | liability | income | expense), status (proposed | confirmed), note.
Site and party codes collide across entities, so every read is filtered on (entity, glcode). voucher_lines starts 2025-04-01: no opening balance exists, only movement.

Maths: each ledger's `net` is oriented as the amount it carries (asset / expense: debit - credit; liability / income: credit - debit). A pair compares the HoldCo
compare-ledgers with the SubCo compare-ledgers; difference = holdco_net - subco_net. A difference is NEVER forced to zero.
"""
from __future__ import annotations

import csv
import logging
import os
import re
import threading
import time
from decimal import Decimal
from pathlib import Path

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[3]
CR = Decimal(10_000_000)
ZERO = Decimal(0)
TOL = Decimal("5")                                  # rupees: below this a difference is rounding (the interest ledgers differ by 2 rupees)
BILLING_MIN = Decimal("1000000")                    # 0.10 Cr: a month with this much service posting on either side is a billing month
ROLES = ("loan", "loan_uncarried", "interest_accrual", "interest_expense", "interest_payable", "interest_memo", "service_income", "service_charge", "other")
SIDES = ("asset", "liability", "income", "expense")
STATUSES = ("proposed", "confirmed")
ENTITY_SIDE = {"VENTURES": "holdco", "RETAIL": "subco"}
ENTITY_NAME = {"holdco": "HoldCo (Citykart Ventures)", "subco": "SubCo (Citykart Stores)"}
CANDIDATE_RE = r"(loan|interco|due to|due from|advance (to|from)|group compan|cross ?charge|ckspl|ckvpl|crpl|citykart|related part|subsidiar|holding co)"
BALANCE_NOTE = "Opening balance before 2025-04 is not in the data, so only the movement since 2025-04 is shown"
PARTIAL_BASIS = "Cost-tagged voucher lines since Apr-2025, a partial view: this is a movement, not the loan balance"
FULL_BASIS = "Full ledger history from gold_fpa.related_party_gl_lines (every line of the loan ledgers, from 2016)"
TABLE = "gold_fpa.related_party_gl_lines"
PARTY_ONLY_ROLES = ("interest_expense",)            # the Interest Account ledger holds other parties' interest too: take only the lines posted to the group company
RECONCILE_NOTE = "To be reconciled: full ledger detail is being added to gold_fpa (related_party_gl_lines)"
FULL_TABLE = "related_party_gl_lines"
PAIRS = {
    "LOAN": {"label": "Intercompany loan (HoldCo lends to SubCo)", "holdco": ("loan",), "subco": ("loan",), "memo": ("loan_uncarried",)},
    "INTEREST": {"label": "Interest on the intercompany loan", "holdco": ("interest_accrual",), "subco": ("interest_payable",), "memo": ("interest_expense", "interest_memo")},
    "SERVICE": {"label": "Quarterly service charges (HoldCo bills SubCo)", "holdco": ("service_income",), "subco": ("service_charge",), "memo": ()},
}
_cache: list[dict] | None = None
TTL = 60
_memo: dict = {}
_memo_lock = threading.Lock()


def path() -> Path:
    return Path(os.environ.get("FPA_INTERCOMPANY_LEDGERS") or ROOT / "config" / "mgmt" / "intercompany_ledgers.csv")


def parse(text: str) -> list[dict]:
    """Rows need a valid entity and a numeric glcode; duplicates on (entity, glcode) keep the first; unknown role -> other, unknown status -> proposed."""
    out, seen = [], set()
    for row in csv.DictReader(text.splitlines()):
        row = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
        ent, code = row.get("entity", "").upper(), row.get("glcode", "")
        if ent not in ENTITY_SIDE or not code.isdigit() or (ent, int(code)) in seen:
            continue
        seen.add((ent, int(code)))
        role, side, status = row.get("role", "").lower(), row.get("side", "").lower(), row.get("status", "").lower()
        out.append({"role": role if role in ROLES else "other", "pair_id": row.get("pair_id", "").upper() or "OTHER", "entity": ent, "glcode": int(code), "glname": row.get("glname", ""),
                    "side": side if side in SIDES else "asset", "status": status if status in STATUSES else "proposed", "note": row.get("note", "")})
    return out


def load(force: bool = False) -> list[dict]:
    global _cache
    if _cache is None or force:
        p = path()
        if p.exists():
            _cache = parse(p.read_text(encoding="utf-8-sig"))
        else:
            log.warning("intercompany ledger list %s not found: the intercompany section is empty", p)
            _cache = []
    return _cache


def reload() -> list[dict]:
    clear_cache()
    return load(force=True)


def reported_path() -> Path:
    return Path(os.environ.get("FPA_INTERCOMPANY_REPORTED") or ROOT / "config" / "mgmt" / "intercompany_reported.csv")


def load_reported() -> list[dict]:
    """Full-ledger figures reported by Finance / the silver layer (balance-sheet ledgers are only partly in voucher_lines). Static config, not computed here."""
    p = reported_path()
    if not p.exists():
        return []
    out = []
    for row in csv.DictReader(p.read_text(encoding="utf-8-sig").splitlines()):
        row = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
        if row.get("entity", "").upper() not in ENTITY_SIDE or not row.get("glcode", "").isdigit():
            continue
        amt = Decimal(row["amount_rupees"]) if row.get("amount_rupees") else None
        dc = row.get("drcr", "").capitalize() if row.get("drcr", "").capitalize() in ("Dr", "Cr") else None
        out.append({"entity": row["entity"].upper(), "side": ENTITY_SIDE[row["entity"].upper()], "glcode": int(row["glcode"]), "glname": row.get("glname", ""), "lines": int(row["lines"]) if row.get("lines", "").isdigit() else None,
                    "amount": amt, "amount_cr": _cr(amt) if amt is not None else None, "drcr": dc, "last_entry": row.get("last_entry") or None, "approx": row.get("approx", "").lower() == "yes", "note": row.get("note", "")})
    return out


def reported_block(rep: list[dict], ledgers: list[dict] | None = None) -> dict:
    """The 'Reported by the ledger (silver)' block with the live difference between the two full loan ledgers.
    The ledgers are found by their role in the intercompany ledger list (loan on each side, loan_uncarried at SubCo), never by glcode; when a ledger has several
    reported rows (the whole ledger and a per-party subset) the one with the most lines is the whole ledger."""
    roles = {(l["entity"], l["glcode"]): l["role"] for l in (load() if ledgers is None else ledgers)}

    def pick(entity: str, role: str):
        rows = [r for r in rep if r["entity"] == entity and roles.get((r["entity"], r["glcode"])) == role and r["amount"] is not None]
        return max(rows, key=lambda r: r["lines"] or 0, default=None)
    hold, sub, old = pick("VENTURES", "loan"), pick("RETAIL", "loan"), pick("RETAIL", "loan_uncarried")
    blk = {"source": "silver", "ledgers": rep, "note": RECONCILE_NOTE + ". These are reported figures, not computed from voucher_lines.", "loan_difference": None, "loan_difference_cr": None, "after_old_debit_cr": None}
    if hold and sub:
        d = sub["amount"] - hold["amount"]
        blk.update({"loan_difference": d, "loan_difference_cr": _cr(d), "loan_difference_text": "SubCo Unsecured Loans (Cr) minus HoldCo Unsecured Loan (Dr)"})
        if old:
            blk["after_old_debit_cr"] = _cr(d - old["amount"])
    return blk


def table_source(conn) -> dict:
    """Is the full-ledger table there? Checked at request time. When it is, ledgers it carries are read from it; the others (service charges) from voucher_lines."""
    cols = [r["column_name"] for r in conn.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = 'gold_fpa' AND table_name = %s ORDER BY ordinal_position", (FULL_TABLE,)).fetchall()]
    return {"table": TABLE, "present": bool(cols), "columns": cols, "used": bool(cols),
            "note": ("Used for every ledger it carries (loan, interest); the service-charge ledgers are not in it, so they are read from voucher_lines." if cols else
                     "Not in gold_fpa yet: figures come from voucher_lines (cost-tagged lines since Apr-2025, a partial view).")}


def _cr(x: Decimal) -> Decimal:
    return (x / CR).quantize(Decimal("0.0001"))


def net(side: str, dr: Decimal, cr: Decimal) -> Decimal:
    """Amount carried by a ledger: asset / expense = Dr - Cr; liability / income = Cr - Dr."""
    return dr - cr if side in ("asset", "expense") else cr - dr


def table_present(conn) -> bool:
    return conn.execute("SELECT to_regclass(%s) IS NOT NULL AS ok", (TABLE,)).fetchone()["ok"]


def fetch(conn, ledgers: list[dict], use_table: bool | None = None) -> list[dict]:
    """Monthly Dr / Cr per configured (entity, glcode). A ledger the full-ledger table carries is read from there (all history); the others from voucher_lines
    (glcode index). Each row says which source it came from."""
    if not ledgers:
        return []
    use_table = table_present(conn) if use_table is None else use_table
    rows, from_table = [], set()
    if use_table:
        party_only = {f"{l['entity']}:{l['glcode']}" for l in ledgers if l["role"] in PARTY_ONLY_ROLES}
        keys = sorted({f"{l['entity']}:{l['glcode']}" for l in ledgers})
        for r in conn.execute(f"""SELECT entity, glcode, to_char(date_trunc('month', entry_date), 'YYYY-MM') AS month, sum(debit) AS dr, sum(credit) AS cr, count(*) AS lines
            FROM {TABLE} WHERE (entity || ':' || glcode::text) = ANY(%s) AND ((entity || ':' || glcode::text) <> ALL(%s) OR reason LIKE 'party\\_%%') GROUP BY 1, 2, 3 ORDER BY 3, 1, 2""",
                              (keys, sorted(party_only) or [""])).fetchall():
            rows.append({**r, "source": "related_party_gl_lines"}); from_table.add((r["entity"], r["glcode"]))
    rest = [l for l in ledgers if (l["entity"], l["glcode"]) not in from_table]
    if rest:
        codes = sorted({l["glcode"] for l in rest})
        keys = sorted({f"{l['entity']}:{l['glcode']}" for l in rest})
        for r in conn.execute("""SELECT entity, glcode, coalesce(to_char(date_trunc('month', entdt), 'YYYY-MM'), 'undated') AS month, sum(damount) AS dr, sum(camount) AS cr, count(*) AS lines
            FROM gold_fpa.voucher_lines WHERE glcode = ANY(%s) AND (entity || ':' || glcode::text) = ANY(%s) GROUP BY 1, 2, 3 ORDER BY 3, 1, 2""", (codes, keys)).fetchall():
            rows.append({**r, "source": "voucher_lines"})
    return rows


def fy_of(month: str) -> str:
    """Financial year by its starting April: 2020-04 .. 2021-03 is FY2020."""
    if month == "undated":
        return "undated"
    y, m = int(month[:4]), int(month[5:7])
    return f"FY{y if m >= 4 else y - 1}"


def _ledger_key(ledgers: list[dict]) -> tuple:
    return tuple(sorted((l["entity"], l["glcode"], l["role"]) for l in ledgers))


def fetch_candidates(conn, ledgers: list[dict]) -> list[dict]:
    """Cached for TTL seconds per ledger list: the distinct-name scan of voucher_lines changes only on re-extraction."""
    key = ("cand", _ledger_key(ledgers))
    with _memo_lock:
        hit = _memo.get(key)
        if hit and time.time() - hit[0] < TTL * 5:
            return hit[1]
    out = _fetch_candidates(conn, ledgers)
    with _memo_lock:
        _memo[key] = (time.time(), out)
    return out


def _fetch_candidates(conn, ledgers: list[dict]) -> list[dict]:
    """Ledgers whose NAME looks intercompany but that are not in the config list. Names are per entity (dim_ledger is SubCo only), so the distinct
    (entity, glcode, glname) set is read from voucher_lines (about 450 rows, 0.4 s) and amounts then come from the glcode index."""
    have = {(l["entity"], l["glcode"]) for l in ledgers}
    names = [r for r in conn.execute("SELECT DISTINCT entity, glcode, glname, ledger_type FROM gold_fpa.voucher_lines").fetchall() if re.search(CANDIDATE_RE, r["glname"] or "", re.I)]
    names = [n for n in names if (n["entity"], n["glcode"]) not in have]
    if not names:
        return []
    by_key = {(n["entity"], n["glcode"]): n for n in names}
    rows = conn.execute("""SELECT entity, glcode, sum(damount) AS dr, sum(camount) AS cr, count(*) AS lines FROM gold_fpa.voucher_lines WHERE glcode = ANY(%s) GROUP BY 1, 2""",
                        (sorted({n["glcode"] for n in names}),)).fetchall()
    out = []
    for r in rows:
        n = by_key.get((r["entity"], r["glcode"]))
        if n is None:
            continue
        out.append({"entity": r["entity"], "side": ENTITY_SIDE.get(r["entity"], r["entity"]), "glcode": r["glcode"], "glname": n["glname"], "ledger_type": n["ledger_type"], "lines": r["lines"],
                    "dr": r["dr"], "cr": r["cr"], "net": r["dr"] - r["cr"], "dr_cr": _cr(r["dr"]), "cr_cr": _cr(r["cr"]), "net_cr": _cr(r["dr"] - r["cr"]),
                    "reason": f"Name matches '{re.search(CANDIDATE_RE, n['glname'], re.I).group(0)}'; not in the intercompany ledger list, so NOT included in any figure above"})
    return sorted(out, key=lambda c: (-(c["dr"] + c["cr"]), c["glname"]))


def _amt(dr: Decimal, cr: Decimal) -> dict:
    return {"dr": dr, "cr": cr, "dr_cr": _cr(dr), "cr_cr": _cr(cr)}


def _side(pair_ledgers: list[dict], agg: dict, monthly: dict, which: str, roles: tuple, memo_roles: tuple) -> dict:
    """One side of a pair: the ledgers (compare ledgers, then memo ledgers) and the totals of the compare ledgers only."""
    leds, dr_t, cr_t, net_t = [], ZERO, ZERO, ZERO
    for l in pair_ledgers:
        if ENTITY_SIDE[l["entity"]] != which or l["role"] not in roles + memo_roles:
            continue
        a = agg.get((l["entity"], l["glcode"]), {"dr": ZERO, "cr": ZERO, "lines": 0})
        n = net(l["side"], a["dr"], a["cr"])
        compare = l["role"] in roles
        leds.append({"glcode": l["glcode"], "glname": l["glname"], "role": l["role"], "side": l["side"], "status": l["status"], "note": l["note"], "compared": compare, "lines": a["lines"], "source": a.get("source"),
                     **_amt(a["dr"], a["cr"]), "net": n, "net_cr": _cr(n)})
        if compare:
            dr_t, cr_t, net_t = dr_t + a["dr"], cr_t + a["cr"], net_t + n
    return {"ledgers": leds, "dr": dr_t, "cr": cr_t, "net": net_t, "dr_cr": _cr(dr_t), "cr_cr": _cr(cr_t), "net_cr": _cr(net_t)}


def _monthly(pair_ledgers: list[dict], by_month: dict, roles: dict) -> list[dict]:
    months = sorted({m for (e, g, m) in by_month for l in pair_ledgers if (l["entity"], l["glcode"]) == (e, g) and l["role"] in roles[ENTITY_SIDE[e]]})
    out = []
    for m in months:
        row, nets = {"month": m}, {}
        for which in ("holdco", "subco"):
            dr = cr = n = ZERO
            for l in pair_ledgers:
                if ENTITY_SIDE[l["entity"]] != which or l["role"] not in roles[which]:
                    continue
                d, c = by_month.get((l["entity"], l["glcode"], m), (ZERO, ZERO))
                dr, cr, n = dr + d, cr + c, n + net(l["side"], d, c)
            row.update({f"{which}_dr": dr, f"{which}_cr": cr, f"{which}_net": n, f"{which}_dr_cr": _cr(dr), f"{which}_cr_cr": _cr(cr), f"{which}_net_cr": _cr(n)})
            nets[which] = n
        diff = nets["holdco"] - nets["subco"]
        row.update({"difference": diff, "difference_cr": _cr(diff), "matches": abs(diff) <= TOL})
        out.append(row)
    return out


def build(ledgers: list[dict], rows: list[dict], candidates: list[dict], coverage_from, as_of) -> dict:
    """Pure maths over already-fetched rows (testable with synthetic data)."""
    agg: dict = {}
    by_month: dict = {}
    lines_m: dict = {}
    for r in rows:
        k = (r["entity"], r["glcode"])
        a = agg.setdefault(k, {"dr": ZERO, "cr": ZERO, "lines": 0})
        a["dr"] += r["dr"]; a["cr"] += r["cr"]; a["lines"] += r.get("lines", 0); a["source"] = r.get("source", "voucher_lines")
        lines_m[(r["entity"], r["glcode"], r["month"])] = lines_m.get((r["entity"], r["glcode"], r["month"]), 0) + r.get("lines", 0)
        d, c = by_month.get((r["entity"], r["glcode"], r["month"]), (ZERO, ZERO))
        by_month[(r["entity"], r["glcode"], r["month"])] = (d + r["dr"], c + r["cr"])

    pairs = []
    for pid, spec in PAIRS.items():
        pl = [l for l in ledgers if l["pair_id"] == pid]
        roles = {"holdco": spec["holdco"], "subco": spec["subco"]}
        monthly = _monthly(pl, by_month, roles)
        h = _side(pl, agg, by_month, "holdco", spec["holdco"], spec["memo"])
        s = _side(pl, agg, by_month, "subco", spec["subco"], spec["memo"])
        diff = h["net"] - s["net"]
        pairs.append({"pair_id": pid, "label": spec["label"], "configured": bool(h["ledgers"] and s["ledgers"]), "holdco": {**h, "monthly": [m for m in monthly if m["holdco_dr"] or m["holdco_cr"]]},
                      "subco": {**s, "monthly": [m for m in monthly if m["subco_dr"] or m["subco_cr"]]},
                      "totals": {"holdco_net": h["net"], "subco_net": s["net"], "difference": diff, "holdco_net_cr": _cr(h["net"]), "subco_net_cr": _cr(s["net"]), "difference_cr": _cr(diff),
                                 "mirrors": bool(h["ledgers"] and s["ledgers"]) and abs(diff) <= TOL},
                      "monthly": monthly, "notes": []})
        srcs = {x["source"] for x in h["ledgers"] + s["ledgers"] if x.get("source")}
        pairs[-1]["source"] = srcs.pop() if len(srcs) == 1 else ("mixed" if srcs else None)
        fy: dict = {}
        for m in monthly:
            f = fy.setdefault(fy_of(m["month"]), {"fy": fy_of(m["month"]), "holdco_net": ZERO, "subco_net": ZERO, "holdco_lines": 0, "subco_lines": 0})
            f["holdco_net"] += m["holdco_net"]; f["subco_net"] += m["subco_net"]
            for l in pl:
                if l["role"] in roles[ENTITY_SIDE[l["entity"]]]:
                    f[ENTITY_SIDE[l["entity"]] + "_lines"] += lines_m.get((l["entity"], l["glcode"], m["month"]), 0)
        pairs[-1]["by_fy"] = [{**f, "difference": f["holdco_net"] - f["subco_net"], "holdco_net_cr": _cr(f["holdco_net"]), "subco_net_cr": _cr(f["subco_net"]),
                               "difference_cr": _cr(f["holdco_net"] - f["subco_net"]), "matches": abs(f["holdco_net"] - f["subco_net"]) <= TOL,
                               "one_sided": (f["holdco_lines"] == 0) != (f["subco_lines"] == 0)} for f in sorted(fy.values(), key=lambda x: x["fy"])]
    P = {p["pair_id"]: p for p in pairs}
    loan, intr, svc = P["LOAN"], P["INTEREST"], P["SERVICE"]

    # LOAN: seen from SubCo (it borrows: credit = drawn, debit = repaid)
    cum, by_m = ZERO, []
    for m in loan["monthly"]:
        n = m["subco_net"]; cum += n
        by_m.append({"month": m["month"], "drawn": m["subco_cr"], "repaid": m["subco_dr"], "net": n, "cumulative": cum, "drawn_cr": m["subco_cr_cr"], "repaid_cr": m["subco_dr_cr"], "net_cr": _cr(n),
                     "cumulative_cr": _cr(cum), "mirrors": m["matches"], "variance_cr": m["difference_cr"]})
    full = loan.get("source") == "related_party_gl_lines"
    unc = next((l for l in loan["subco"]["ledgers"] if l["role"] == "loan_uncarried"), None)
    one_sided = [f for f in loan["by_fy"] if f["one_sided"]]
    gap_pre = sum((f["difference"] for f in one_sided), ZERO)
    loan["notes"] = ([FULL_BASIS + ". Balance per ledger = debit minus credit over the whole history.",
                      "Each financial year from the first one HoldCo carries mirrors exactly; the whole gap sits in earlier SubCo entries that HoldCo does not carry."] if full
                     else [BALANCE_NOTE + ".", "SubCo owes HoldCo the net movement shown (positive = SubCo borrowed more than it repaid since 2025-04)."])
    ix_pay = next((l for l in intr["subco"]["ledgers"] if l["role"] == "interest_payable"), None)
    ix_exp = next((l for l in intr["subco"]["ledgers"] if l["role"] == "interest_expense"), None)
    exp_net = ix_exp["net"] if ix_exp else ZERO
    pay_cr = ix_pay["cr"] if ix_pay else ZERO
    pay_dr = ix_pay["dr"] if ix_pay else ZERO
    interest = {"accrued_holdco": intr["holdco"]["net"], "payable_subco": intr["subco"]["net"], "expense_subco": exp_net,
                "accrued_holdco_cr": intr["holdco"]["net_cr"], "payable_subco_cr": intr["subco"]["net_cr"], "expense_subco_cr": _cr(exp_net),
                "payable_credited_cr": _cr(pay_cr), "payable_debited_cr": _cr(pay_dr), "mirrors": intr["totals"]["mirrors"], "variance_cr": intr["totals"]["difference_cr"],
                "note": (("Full ledger history. HoldCo's accrued-interest ledger is compared with SubCo's accrued-interest ledger; the difference is shown in rupees, not forced to zero. "
                          "SubCo's interest expense is read only from lines posted to the group company, because that ledger also holds other parties' interest. " if intr.get("source") == "related_party_gl_lines" else
                          "Cost-tagged lines since 2025-04 (a partial view), signed. Interest accrued before 2025-04 is not in the data. HoldCo's accrual ledgers are compared with SubCo's. ")
                         + "HoldCo 'Interest Received' also holds bank and mutual-fund interest, so it is not used.")}
    gap = exp_net - pay_cr
    if ix_exp and abs(gap) > TOL and intr.get("source") != "related_party_gl_lines":
        interest["note"] += f" SubCo interest expense ({_cr(exp_net)} Cr) differs from the interest credited to Interest Payable ({_cr(pay_cr)} Cr) by {_cr(gap)} Cr: Finance to explain."
    intr["notes"] = [interest["note"]]
    after_unc = (loan["totals"]["holdco_net"] - (loan["totals"]["subco_net"] + unc["net"])) if unc else None
    loan_block = {"full_history": full, "carried_years_mirror": all(f["matches"] for f in loan["by_fy"] if not f["one_sided"]), "carried_years_variance_cr": _cr(sum((f["difference"] for f in loan["by_fy"] if not f["one_sided"]), ZERO)), "holdco_balance": loan["holdco"]["net"], "subco_balance": loan["subco"]["net"], "holdco_balance_cr": loan["holdco"]["net_cr"], "subco_balance_cr": loan["subco"]["net_cr"],
                  "by_fy": loan["by_fy"], "not_carried": {"pre_carry_gap_cr": _cr(gap_pre), "pre_carry_years": [f["fy"] for f in one_sided],
                                                          "ledger": ({"glcode": unc["glcode"], "glname": unc["glname"], "dr_cr": unc["dr_cr"], "cr_cr": unc["cr_cr"], "net_cr": unc["net_cr"], "lines": unc["lines"]} if unc else None),
                                                          "after_uncarried_difference_cr": _cr(after_unc) if after_unc is not None else None,
                                                          "note": "Not carried by the other side: SubCo entries before the first year HoldCo carries, and a separate SubCo loan ledger with no HoldCo counterpart. Shown, not eliminated."},
                  "net_movement": loan["subco"]["net"], "drawn": loan["subco"]["cr"], "repaid": loan["subco"]["dr"], "net_movement_cr": loan["subco"]["net_cr"], "drawn_cr": loan["subco"]["cr_cr"],
                  "repaid_cr": loan["subco"]["dr_cr"], "by_month": by_m, "balance_note": BALANCE_NOTE, "basis": FULL_BASIS if full else PARTIAL_BASIS, "source": loan.get("source") or "voucher_lines", "mirrors": loan["totals"]["mirrors"], "variance_cr": loan["totals"]["difference_cr"], "interest": interest}

    # SERVICE: quarterly billing months only; small postings in other months are rolled into one line so the totals still tie
    bill, minor = [], {"months": [], "holdco": ZERO, "subco": ZERO, "difference": ZERO}
    for m in svc["monthly"]:
        if max(abs(m["holdco_net"]), abs(m["subco_net"])) >= BILLING_MIN:
            bill.append({"month": m["month"], "holdco": m["holdco_net"], "subco": m["subco_net"], "difference": m["difference"], "holdco_cr": m["holdco_net_cr"], "subco_cr": m["subco_net_cr"], "difference_cr": m["difference_cr"],
                         "matches": m["matches"]})
        else:
            minor["months"].append(m["month"]); minor["holdco"] += m["holdco_net"]; minor["subco"] += m["subco_net"]; minor["difference"] += m["difference"]
    minor.update({"holdco_cr": _cr(minor["holdco"]), "subco_cr": _cr(minor["subco"]), "difference_cr": _cr(minor["difference"])})
    diffs = [b["difference"] for b in bill]
    constant = bool(diffs) and max(diffs) - min(diffs) <= Decimal("10000") and abs(diffs[0]) > TOL
    svc["notes"] = ["Billed quarterly by HoldCo, usually posted in the month after quarter-end (for example the Apr-Jun 2026 quarter was billed in Jul-26).",
                    "HoldCo income is higher than SubCo's charges. This is shown as an unmatched difference and is never forced to zero."]
    if constant:
        svc["notes"].append(f"The difference is a constant {_cr(sum(diffs, ZERO) / len(diffs)).quantize(Decimal('0.001'))} Cr in each of the {len(diffs)} billings: unexplained, Finance to confirm.")
    service = {"billed_holdco": svc["holdco"]["net"], "charged_subco": svc["subco"]["net"], "unmatched": svc["totals"]["difference"], "billed_holdco_cr": svc["holdco"]["net_cr"],
               "charged_subco_cr": svc["subco"]["net_cr"], "unmatched_cr": svc["totals"]["difference_cr"], "billings": len(bill), "by_quarter": bill, "other_months": minor,
               "constant_difference": constant, "notes": svc["notes"]}

    # flags: ledgers that need a Finance explanation
    flags = []
    for l in ledgers:
        a = agg.get((l["entity"], l["glcode"]))
        who = f"{l['glname']} ({ENTITY_NAME[ENTITY_SIDE[l['entity']]]}, ledger {l['glcode']})"
        if a is None or not a["lines"]:
            flags.append({"ledger": who, "glcode": l["glcode"], "entity": l["entity"], "reason": "No postings found for this ledger in the voucher data"})
        elif l["role"] == "other":
            gross = max(a["dr"], a["cr"]); n = a["dr"] - a["cr"]
            if gross and abs(n) <= max(TOL, gross / 1000):
                flags.append({"ledger": who, "glcode": l["glcode"], "entity": l["entity"], "dr_cr": _cr(a["dr"]), "cr_cr": _cr(a["cr"]),
                              "reason": f"Debits and credits are equal ({_cr(a['dr'])} Cr each), so it nets to nil: to be explained"})
            else:
                flags.append({"ledger": who, "glcode": l["glcode"], "entity": l["entity"], "dr_cr": _cr(a["dr"]), "cr_cr": _cr(a["cr"]),
                              "reason": f"Listed as other, not paired with a ledger on the other side; net {_cr(net(l['side'], a['dr'], a['cr']))} Cr"})
    if service["unmatched_cr"] and not svc["totals"]["mirrors"]:
        flags.append({"ledger": "Service charges: HoldCo 'Sales - Service' vs SubCo service expense ledgers", "glcode": None, "entity": None,
                      "reason": f"HoldCo is higher than SubCo by {service['unmatched_cr']} Cr in total; unmatched, not eliminated"})

    s_net, h_net = svc["subco"]["net"], svc["holdco"]["net"]
    effect = {"consolidated_cr": ZERO.quantize(Decimal("0.0001")), "subco_standalone_cr": -_cr(s_net), "holdco_standalone_cr": _cr(h_net),
              "reason": "Neither side is in the Management P&L today (the ledgers are unmapped), so consolidated EBITDA is unaffected; the standalone SubCo and HoldCo views omit these charges.",
              "note": ("If the service charges were included, SubCo EBITDA would be lower by "
                       f"{_cr(s_net)} Cr and HoldCo EBITDA higher by {_cr(h_net)} Cr; on consolidation they cancel, apart from the unmatched {service['unmatched_cr']} Cr.")}
    for p in pairs:
        for side in ("holdco", "subco"):
            p[side]["name"] = ENTITY_NAME[side]
    rep = load_reported()
    return {"as_of_date": as_of, "coverage_from": coverage_from, "sources": {"voucher_lines": "cost-tagged lines since 2025-04, a partial view", "full_ledger": None, "loan": loan.get("source"), "interest": intr.get("source"), "service": svc.get("source")}, "reported_by_ledger": reported_block(rep), "pairs": pairs, "loan": loan_block, "service": service, "flags": flags, "candidates": candidates, "effect_on_ebitda": effect,
            "controls": {"loan_mirror_variance": loan["totals"]["difference"], "loan_mirror_variance_cr": loan["totals"]["difference_cr"], "service_unmatched": svc["totals"]["difference"],
                         "service_unmatched_cr": svc["totals"]["difference_cr"], "interest_variance_cr": intr["totals"]["difference_cr"], "loan_mirrors": loan["totals"]["mirrors"],
                         "loan_carried_years_variance_cr": loan_block["carried_years_variance_cr"], "loan_carried_years_mirror": loan_block["carried_years_mirror"], "loan_pre_carry_gap_cr": loan_block["not_carried"]["pre_carry_gap_cr"]},
            "register": {"path_exists": path().exists(), "ledgers": len(ledgers), "proposed": sum(l["status"] == "proposed" for l in ledgers), "confirmed": sum(l["status"] == "confirmed" for l in ledgers)}}


def clear_cache() -> None:
    with _memo_lock:
        _memo.clear()


def compute(conn) -> dict:
    """Cached for TTL seconds per ledger list so /summary and /intercompany (loaded together) share one build."""
    ledgers = load()
    key = ("compute", _ledger_key(ledgers))
    with _memo_lock:
        hit = _memo.get(key)
        if hit and time.time() - hit[0] < TTL:
            return hit[1]
    out = _compute(conn, ledgers)
    with _memo_lock:
        _memo[key] = (time.time(), out)
    return out


def _compute(conn, ledgers: list[dict]) -> dict:
    rows = fetch(conn, ledgers)
    cov = conn.execute("SELECT min(entdt) AS a, max(entdt) AS b FROM gold_fpa.voucher_lines").fetchone()
    out = build(ledgers, rows, fetch_candidates(conn, ledgers), cov["a"], cov["b"])
    out["sources"]["full_ledger"] = table_source(conn)
    return out
