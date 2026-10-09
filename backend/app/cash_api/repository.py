"""SQL for the Cash API: reads over the serving views of ONE run (candidate or live). Money is exact (Decimal, serialised as text by the router).

Figures here are of three kinds and are never blended:
  * Store Till Cash   : till cash held in stores. It EXCLUDES bank balances.
  * Bank ledger book  : ledger figures from the books (opening, posted, unposted). PROVISIONAL, NOT BANK-RECONCILED. Never added to till cash.
  * Creditors         : read from the creditors mart (one source of truth), with that run's own data state.
"""
from __future__ import annotations

from decimal import Decimal

from ..creditors_api import repository as creditors

ZERO = Decimal(0)
BANK_STATUS = "PROVISIONAL · NOT BANK-RECONCILED"
TILL_LABEL = "Store Till Cash"
UNAVAILABLE = [
    {"id": "bank_reconciled_cash", "label": "Bank-reconciled cash", "reason": "No bank statement or reconciliation is available from the current sources. The ledger-book position below is provisional."},
    {"id": "consolidated_cash", "label": "Consolidated cash position", "reason": "Needs reconciled bank balances; store till cash is not the company's cash."},
    {"id": "cash_forecast", "label": "Cash forecast (7 / 15 / 30 days)", "reason": "No forecast source exists. A projection is not shown, and none is estimated."},
    {"id": "inventory", "label": "Inventory working capital", "reason": "No credible current stock valuation source was found; only the year-end closing stock is in the books."},
    {"id": "receivables", "label": "Receivables", "reason": "A source exists (Sundry Debtors) and its semantics are understood; the contract, extract and verification are not built yet."},
    {"id": "vendor_advances", "label": "Vendor advances", "reason": "No source has been identified."},
    {"id": "payroll", "label": "Payroll obligations", "reason": "No source has been identified."},
    {"id": "statutory", "label": "Statutory liabilities", "reason": "No source has been identified."},
    {"id": "capex", "label": "Capex commitments", "reason": "No source has been identified."},
]


def data_state(run: dict) -> str:
    return {"live": "live", "unpublished": "verified_candidate", "superseded": "superseded", "withdrawn": "withdrawn"}[run["publication_state"]]


def serving_run(conn, run_id: str | None = None) -> dict | None:
    """The live run if any, otherwise the newest verified candidate (or the named run if it may be served)."""
    if run_id:
        return conn.execute("SELECT * FROM cash.v_serving_run WHERE run_id = %s", (run_id,)).fetchone()
    return conn.execute("SELECT * FROM cash.v_serving_run ORDER BY (publication_state = 'live') DESC, loaded_at DESC LIMIT 1").fetchone()


def list_runs(conn) -> list[dict]:
    return conn.execute("SELECT * FROM cash.v_serving_run ORDER BY loaded_at DESC").fetchall()


def till(conn, run_id: str) -> dict:
    t = conn.execute(
        "SELECT count(*) AS stores, coalesce(sum(cumulative_balance), 0) AS store_till_cash, coalesce(sum(mtd_debit), 0) AS mtd_debit, coalesce(sum(mtd_credit), 0) AS mtd_credit, "
        "coalesce(sum(fytd_debit), 0) AS fytd_debit, coalesce(sum(fytd_credit), 0) AS fytd_credit, count(*) FILTER (WHERE cumulative_balance < 0) AS stores_negative, "
        "count(*) FILTER (WHERE cumulative_balance > 0) AS stores_with_cash, max(last_activity_date) AS last_activity_date FROM cash.v_store_till WHERE run_id = %s", (run_id,)).fetchone()
    big = conn.execute("SELECT store_name, site_code, cumulative_balance FROM cash.v_store_till WHERE run_id = %s ORDER BY cumulative_balance DESC, site_code LIMIT 1", (run_id,)).fetchone()
    t["largest_store"] = big
    t["label"] = TILL_LABEL
    t["note"] = "excludes bank balances"
    return t


def store_rows(conn, run_id: str, sort: str = "balance", descending: bool = True, limit: int = 100, offset: int = 0) -> dict:
    col = {"balance": "cumulative_balance", "mtd_debit": "mtd_debit", "mtd_credit": "mtd_credit", "fytd_debit": "fytd_debit", "name": "store_name", "activity": "last_activity_date"}.get(sort, "cumulative_balance")
    rows = conn.execute(f"SELECT site_code, store_name, cumulative_balance, mtd_debit, mtd_credit, fytd_debit, fytd_credit, last_activity_date FROM cash.v_store_till WHERE run_id = %s "
                        f"ORDER BY {col} {'DESC' if descending else 'ASC'} NULLS LAST, site_code LIMIT %s OFFSET %s", (run_id, limit, offset)).fetchall()
    return {"returned": len(rows), "limit": limit, "offset": offset, "stores": rows}


BANK_COLS = ("ledger_code, ledger_name, gl_type, nature, extinct, has_movement, opening_balance, posted_dr, posted_cr, posted_closing, unposted_dr, unposted_cr, unposted_movement, "
             "including_unposted, future_net, last_posted_date, last_entry_date, register_report_date, sites")


def bank_rows(conn, run_id: str, source: str = "site_register") -> list[dict]:
    return conn.execute(f"SELECT {BANK_COLS} FROM cash.v_bank_ledger WHERE run_id = %s AND source = %s ORDER BY posted_closing, ledger_code", (run_id, source)).fetchall()


def bank_review(conn, run_id: str) -> dict:
    site = bank_rows(conn, run_id, "site_register")
    sums = lambda rows, k: sum((r[k] for r in rows), ZERO)  # noqa: E731
    moving = [r for r in site if r["has_movement"]]
    gl = bank_rows(conn, run_id, "gl_register")
    tie = conn.execute(
        "SELECT count(*) FILTER (WHERE s.opening_balance <> p.posted_closing + p.unposted_movement) AS broken, count(*) AS ledgers FROM cash.v_bank_ledger s "
        "JOIN cash.v_bank_ledger p ON p.run_id = s.run_id AND p.ledger_code = s.ledger_code AND p.source = 'prior_year_closing' WHERE s.run_id = %s AND s.source = 'site_register'", (run_id,)).fetchone()
    driver = min(moving, key=lambda r: r["posted_closing"]) if moving else None
    return {
        "status": BANK_STATUS,
        "source": "site_register",
        "register_report_date": max((r["register_report_date"] for r in moving if r["register_report_date"]), default=None),
        "last_posted_date": max((r["last_posted_date"] for r in moving if r["last_posted_date"]), default=None),
        "totals": {"opening_balance": sums(site, "opening_balance"), "posted_closing": sums(site, "posted_closing"), "unposted_movement": sums(site, "unposted_movement"),
                   "including_unposted": sums(site, "including_unposted")},
        "ledgers_total": len(site), "ledgers_with_movement": len(moving), "ledgers_without_movement": len(site) - len(moving),
        "driver": None if not driver else {"ledger_code": driver["ledger_code"], "ledger_name": driver["ledger_name"], "posted_closing": driver["posted_closing"], "including_unposted": driver["including_unposted"]},
        "ledgers": moving,
        "cross_check": {"gl_register_posted_closing": sums(gl, "posted_closing"), "gl_register_including_unposted": sums(gl, "including_unposted"),
                        "gl_register_report_date": max((r["register_report_date"] for r in gl if r["register_report_date"]), default=None),
                        "posted_agrees_with_gl_register": sums(site, "posted_closing") == sums(gl, "posted_closing")},
        "opening_ties_to_prior_year_closing": {"ledgers_checked": tie["ledgers"], "ledgers_not_tying": tie["broken"]},
    }


def controls(conn, run_id: str) -> dict:
    rows = conn.execute("SELECT left_layer, right_layer, count(*) AS total, count(*) FILTER (WHERE verdict = 'PASS') AS passed, coalesce(max(abs(variance)), 0) AS max_abs_variance "
                        "FROM cash.v_control WHERE run_id = %s GROUP BY 1, 2 ORDER BY 1, 2", (run_id,)).fetchall()
    return {"layers": [{"from": r["left_layer"], "to": r["right_layer"], "controls": r["total"], "passed": r["passed"], "failed": r["total"] - r["passed"], "max_abs_variance": r["max_abs_variance"]} for r in rows],
            "total": sum(r["total"] for r in rows), "passed": sum(r["passed"] for r in rows), "failed": sum(r["total"] - r["passed"] for r in rows)}


def creditor_obligations(db) -> dict:
    """Creditor figures read through the creditors repository (the same functions and rules as /creditors), for the creditors run in service."""
    with db.session("candidate") as c:
        run = creditors.current_run(c)
    if run is None:
        return {"available": False, "reason": "No verified creditors run is available."}
    src = creditors.source_for(run, False)
    rid = run["extraction_run_id"]
    with db.session(src.role) as conn:
        s = creditors.summary(conn, src, rid)
        due = {d["state"]: d for d in creditors.due_status(conn, src, rid)}
    return {
        "available": True, "creditors_run_id": rid, "as_of_date": run["as_of_date"], "data_state": creditors.data_state(run),
        "credit_outstanding": s["credit_outstanding"], "creditor_debit_balance": s["creditor_debit_balance"], "signed_net": s["signed_net"],
        "past_due_credit": s["past_due_credit"], "not_yet_due_credit": due["NOT_YET_DUE"]["credit_outstanding"], "due_unavailable_credit": s["due_unavailable_credit"],
        "credit_items": s["credit_items"], "credit_vendors": s["credit_vendors"],
        **({"related_party_excluded": s["related_party_excluded"]} if "related_party_excluded" in s else {}),
    }
