"""Related Party Transactions (intercompany), read-only, FPA_SOURCE=gold only. Finance bearer token required (party names and document codes).

  GET /api/v1/related-party/summary                    creditors (register sub-ledgers), loans (if a loan table exists in gold_fpa), candidates, controls
  GET /api/v1/related-party/intercompany              intercompany loan, interest and service charges derived from the ledger (gold/intercompany.py)
  GET /api/v1/related-party/items?sub_ledger_code=     open bills of one registered party (same shape as the creditors finance items, incl. document_code)

Money is exact Decimal serialised as text, in RUPEES (INR); `*_cr` fields are crore (rupees / 10,000,000). payable = sum of credit items, debit_balance = sum of
debit items, net = payable - debit_balance (positive = we owe). These sub-ledgers are excluded from the main creditors relation (see gold/creditors.py),
so main + related = all, which `controls` proves. Nothing here writes.
"""
from __future__ import annotations

import re
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query, Request

from ..creditors_api import repository as repo
from ..creditors_api.router import database, finance_gate, ok
from . import creditors as gc, db as gold, intercompany as ic, related_gl as rgl, related_register as rr

router = APIRouter(prefix="/api/v1/related-party")
ZERO = Decimal(0)
CR = Decimal(10_000_000)
LOAN_TABLE = re.compile(r"(loan|interco)", re.I)
LOAN_UNAVAILABLE = "Intercompany loan data not loaded in gold_fpa yet"
CANDIDATE_RE = r"^(citykart (retail|ventures|stores)|ckspl)|cross ?charge"
AGE_KEYS = [k for k, _ in repo.AGE_BUCKETS] + ["UNCLASSIFIED"]


def _cr(x: Decimal) -> Decimal:
    return (x / CR).quantize(Decimal("0.0001"))


def _session(request: Request):
    if not gold.enabled():
        raise HTTPException(501, "Related Party Transactions is available only on the gold source")
    finance_gate(request)
    return database(request).session("finance")


def _totals(conn, relation: str, run_id: str) -> dict:
    return conn.execute(f"""SELECT coalesce(sum(abs(pending)) FILTER (WHERE drcr = 'Cr'), 0) AS payable, coalesce(sum(abs(pending)) FILTER (WHERE drcr = 'Dr'), 0) AS debit_balance,
        coalesce(sum(pending), 0) AS signed_net, count(DISTINCT sub_ledger_code) AS parties, count(*) AS items FROM {relation} WHERE extraction_run_id = %s""", (run_id,)).fetchone()


def _pack(t: dict) -> dict:
    return {"payable": t["payable"], "debit_balance": t["debit_balance"], "net": t["payable"] - t["debit_balance"], "payable_cr": _cr(t["payable"]),
            "debit_balance_cr": _cr(t["debit_balance"]), "net_cr": _cr(t["payable"] - t["debit_balance"]), "parties": t["parties"], "items": t["items"]}


def _by_party(conn, relation: str, run_id: str) -> list[dict]:
    rows = conn.execute(f"""SELECT sub_ledger_code, coalesce(sum(abs(pending)) FILTER (WHERE drcr = 'Cr'), 0) AS payable, coalesce(sum(abs(pending)) FILTER (WHERE drcr = 'Dr'), 0) AS debit_balance,
        count(*) AS items, min(document_date) FILTER (WHERE drcr = 'Cr') AS oldest_doc, max(document_age_days) FILTER (WHERE drcr = 'Cr') AS max_age_days
        FROM {relation} WHERE extraction_run_id = %s GROUP BY sub_ledger_code""", (run_id,)).fetchall()
    age = {}
    for r in conn.execute(f"SELECT sub_ledger_code, document_age_bucket AS b, sum(abs(pending)) AS a FROM {relation} WHERE extraction_run_id = %s AND drcr = 'Cr' GROUP BY 1, 2", (run_id,)):
        key = "UNCLASSIFIED" if r["b"].startswith("UNCLASSIFIED") else r["b"]
        d = age.setdefault(r["sub_ledger_code"], {})
        d[key] = d.get(key, ZERO) + r["a"]
    live = {r["sub_ledger_code"]: r for r in rows}
    out = []
    for reg in rr.load():                                   # every registered party is listed, even with no open items
        x = live.get(reg["sub_ledger_code"])
        p, d = (x["payable"], x["debit_balance"]) if x else (ZERO, ZERO)
        out.append({**{k: reg[k] for k in ("sub_ledger_code", "party_name", "group_entity", "relationship", "status")}, "basis": reg["basis"], "note": reg["note"],
                    "payable": p, "debit_balance": d, "net": p - d, "payable_cr": _cr(p), "debit_balance_cr": _cr(d), "net_cr": _cr(p - d),
                    "items": x["items"] if x else 0, "oldest_doc": x["oldest_doc"] if x else None, "max_age_days": x["max_age_days"] if x else None,
                    "ageing": {k: age.get(reg["sub_ledger_code"], {}).get(k, ZERO) for k in AGE_KEYS}})
    return sorted(out, key=lambda r: r["payable"], reverse=True)


def candidates(conn, run_id: str) -> list[dict]:
    """Group-looking names in dim_party that are NOT in the register. Listed for the CFO to confirm; never excluded automatically."""
    reg = rr.codes() or [-1]
    rows = conn.execute(f"""SELECT p.slcode AS sub_ledger_code, p.slname AS party_name, p.class_name, p.is_extinct, coalesce(o.items, 0) AS open_items,
        coalesce(o.payable, 0) AS payable, coalesce(o.debit_balance, 0) AS debit_balance
        FROM gold_fpa.dim_party p LEFT JOIN (SELECT sub_ledger_code, count(*) AS items, sum(abs(pending)) FILTER (WHERE drcr = 'Cr') AS payable,
            sum(abs(pending)) FILTER (WHERE drcr = 'Dr') AS debit_balance FROM {gc.items(False, 'main')} WHERE extraction_run_id = %s GROUP BY 1) o ON o.sub_ledger_code = p.slcode
        WHERE p.slname ~* %s AND p.slcode <> ALL(%s) ORDER BY coalesce(o.items, 0) DESC, p.slname, p.slcode LIMIT 300""", (run_id, CANDIDATE_RE, reg)).fetchall()
    for r in rows:
        low = r["party_name"].lower()
        r["reason"] = ("Name looks like a CKSPL cross-charge account" if "cross" in low and "charge" in low.replace(" ", "")
                       else "Name looks like a CityKart group entity") + ("; no open creditor items" if not r["open_items"] else "") + "; not in the register"
    return rows


def loans(conn) -> dict:
    """Generic: any gold_fpa table whose name contains loan / interco(mpany). Columns are returned as-is; nothing is interpreted."""
    names = [r["table_name"] for r in conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'gold_fpa' ORDER BY 1").fetchall() if LOAN_TABLE.search(r["table_name"])]
    if not names:
        return {"available": False, "reason": LOAN_UNAVAILABLE, "tables": [], "rows": []}
    out_rows, tables = [], []
    for n in names:
        quoted = '"' + n.replace('"', '""') + '"'                    # the name comes from information_schema, never from the request
        rows = conn.execute(f"SELECT * FROM gold_fpa.{quoted} LIMIT 500").fetchall()
        tables.append({"table": n, "returned": len(rows), "columns": list(rows[0].keys()) if rows else []})
        out_rows += [{"_table": n, **r} for r in rows]
    return {"available": True, "reason": None, "tables": tables, "rows": out_rows}


def loans_from_ledger(conn) -> dict:
    """The /summary `loans` block. Same shape as before (available, reason, tables, rows) plus source='ledger' and the headline numbers derived from the ledger.
    With no ledger list configured it falls back to the generic table search."""
    if not ic.load():
        return {**loans(conn), "source": "none"}
    d = ic.compute(conn)
    ln = d["loan"]
    return {"available": True, "reason": None, "source": "ledger", "tables": [], "rows": [], "as_of_date": d["as_of_date"], "coverage_from": d["coverage_from"],
            "net_movement": ln["net_movement"], "drawn": ln["drawn"], "repaid": ln["repaid"], "net_movement_cr": ln["net_movement_cr"], "drawn_cr": ln["drawn_cr"], "repaid_cr": ln["repaid_cr"],
            "basis": ln["basis"], "balance_source": ln["source"], "full_history": ln["full_history"], "holdco_balance_cr": ln["holdco_balance_cr"], "subco_balance_cr": ln["subco_balance_cr"], "not_carried": ln["not_carried"], "reported_by_ledger": d["reported_by_ledger"], "sources": d["sources"],
            "mirrors": ln["mirrors"], "variance_cr": ln["variance_cr"], "balance_note": ln["balance_note"], "interest": ln["interest"],
            "service": {k: d["service"][k] for k in ("billed_holdco_cr", "charged_subco_cr", "unmatched_cr")}}


@router.get("/intercompany")
def intercompany(request: Request):
    with _session(request) as conn:
        return ok(ic.compute(conn))


@router.get("/gl-entries")
def gl_entries(request: Request, entity: str | None = Query(None, pattern="^(RETAIL|VENTURES)$"), from_month: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"),
               to_month: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"), basis: str = Query("all", pattern="^(party|ledger|all)$"),
               limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0)):
    """Every GL entry with a group company: party match (related_party_names.csv) OR ledger in intercompany_ledgers.csv. Entry-level rows, summary and mirror check."""
    with _session(request) as conn:
        d = rgl.compute(conn, entity=entity, from_month=from_month, to_month=to_month, basis=basis, limit=limit, offset=offset)
        d["as_of_date"] = conn.execute(f"SELECT max({'entry_date' if d['source']['entries'] == 'related_party_gl_lines' else 'entdt'}) AS d FROM "
                                       f"{ic.TABLE if d['source']['entries'] == 'related_party_gl_lines' else 'gold_fpa.voucher_lines'}").fetchone()["d"]
        return ok(d)


@router.get("/summary")
def summary(request: Request):
    with _session(request) as conn:
        run = repo.current_run(conn)
        if run is None:
            raise HTTPException(404, "no verified creditor run is available yet")
        rid = run["extraction_run_id"]
        rel = gc.items(True, "related")
        src = repo.Source("finance", rel, gc.CONTROLS, True, True)
        rt, mt, at = (_totals(conn, gc.items(True, s), rid) for s in ("related", "main", "all"))
        variance = mt["payable"] + rt["payable"] - at["payable"]
        variance_dr = mt["debit_balance"] + rt["debit_balance"] - at["debit_balance"]
        variance_net = mt["signed_net"] + rt["signed_net"] - at["signed_net"]
        ok_ = abs(variance) < Decimal("0.05") and abs(variance_dr) < Decimal("0.05") and abs(variance_net) < Decimal("0.05") 
        body = {
            "as_of_date": run["as_of_date"], "extraction_run_id": rid, "currency": "INR", "register": {"path_exists": rr.path().exists(), "parties": len(rr.load()), "proposed": sum(r["status"] == "proposed" for r in rr.load()),
                                                                                                 "confirmed": sum(r["status"] == "confirmed" for r in rr.load())},
            "creditors": {**_pack(rt), "by_party": _by_party(conn, rel, rid),
                          "by_age": repo.document_age(conn, src, rid), "by_due_status": repo.due_status(conn, src, rid)},
            "related_party_gl": rgl.headline(conn), "loans": loans_from_ledger(conn), "candidates": candidates(conn, rid),
            "controls": {"main_plus_related_equals_all": ok_, "variance": variance, "variance_cr": _cr(variance), "debit_variance": variance_dr, "net_variance": variance_net,
                         "main_payable": mt["payable"], "related_payable": rt["payable"], "all_payable": at["payable"],
                         "main_payable_cr": _cr(mt["payable"]), "related_payable_cr": _cr(rt["payable"]), "all_payable_cr": _cr(at["payable"]),
                         "main_debit_balance": mt["debit_balance"], "related_debit_balance": rt["debit_balance"], "all_debit_balance": at["debit_balance"]},
        }
    return ok(body)


@router.get("/items")
def items(request: Request, sub_ledger_code: int, limit: int = Query(500, ge=1, le=2000), offset: int = Query(0, ge=0)):
    reg = {r["sub_ledger_code"]: r for r in rr.load()}
    if sub_ledger_code not in reg:
        raise HTTPException(404, "that sub-ledger is not in the related-party register")
    with _session(request) as conn:
        run = repo.current_run(conn)
        if run is None:
            raise HTTPException(404, "no verified creditor run is available yet")
        rid = run["extraction_run_id"]
        rel = gc.items(True, "related")
        cols = ("source_row_key AS item_ref, ledger_code, ledger_name, drcr, amount, adjusted, pending, document_type, due_date_basis, document_date, due_date, entry_date, document_age_days, "
                "document_age_bucket, overdue_days, due_status, date_quality_status, classification_status, document_code, document_no, document_initial, ref_no, ref_date, created_by_site, sub_ledger_code")
        rows = conn.execute(f"SELECT {cols} FROM {rel} WHERE extraction_run_id = %s AND sub_ledger_code = %s ORDER BY document_date NULLS LAST, 1 LIMIT %s OFFSET %s", (rid, sub_ledger_code, limit, offset)).fetchall()
        n = conn.execute(f"SELECT count(*) AS n FROM {rel} WHERE extraction_run_id = %s AND sub_ledger_code = %s", (rid, sub_ledger_code)).fetchone()["n"]
    p = reg[sub_ledger_code]
    return ok({"as_of_date": run["as_of_date"], "extraction_run_id": rid, "sub_ledger_code": sub_ledger_code, "party_name": p["party_name"], "total_items": n, "returned": len(rows), "limit": limit, "offset": offset, "items": rows})
