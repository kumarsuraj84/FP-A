"""SQL for the entry-level drill API. Reads over the serving views of ONE entry run. Money is exact (Decimal, serialised as text by the router).

Every list returns its PARENT figure (what the card above it says), the sum of its CHILD rows and an explicit `reconciles` flag: exact equality, zero tolerance.
Masked reads (entry_api_reader) never see an entry number, narration, reference, cheque field, preparer, releaser or a raw sub-ledger code: the database refuses.
"""
from __future__ import annotations

from decimal import Decimal

ZERO = Decimal(0)
NO_ATTACHMENT = {"available": False, "message": "No verified attachment source available"}
BEFORE_COVERAGE_MESSAGE = "Entry drill unavailable — source register coverage before Apr 2023 not available."
BANK_STATUS = "PROVISIONAL · NOT BANK-RECONCILED"
FILTERS = {
    "posted": "e.release_status = 'Posted' AND trim(e.entry_type_long) <> 'Opening' AND e.entry_date <= %(rd)s",
    "unposted": "e.release_status = 'Unposted' AND trim(e.entry_type_long) <> 'Opening' AND e.entry_date <= %(rd)s",
    "opening": "trim(e.entry_type_long) = 'Opening'",
}


class Lineage(Exception):
    """The drill the caller asked for belongs to a different snapshot than the figure it came from."""


def data_state(run: dict) -> str:
    return {"live": "live", "unpublished": "verified_candidate", "superseded": "superseded", "withdrawn": "withdrawn"}[run["publication_state"]]


def serving_run(conn, run_id: str | None = None) -> dict | None:
    if run_id:
        return conn.execute("SELECT * FROM entry.v_serving_run WHERE entry_run_id = %s", (run_id,)).fetchone()
    return conn.execute("SELECT * FROM entry.v_serving_run ORDER BY (publication_state = 'live') DESC, loaded_at DESC LIMIT 1").fetchone()


def check_lineage(run: dict, *, cash_run: str | None = None, creditors_run: str | None = None) -> None:
    """E11: a drill never crosses run / as-of context. The caller names the domain run it is looking at; it must be the one this entry run was built against."""
    if cash_run is not None and cash_run != run["cash_run_id"]:
        raise Lineage(f"these entries were built against cash run {run['cash_run_id']}, not {cash_run}: a different snapshot")
    if creditors_run is not None and creditors_run != run["creditors_run_id"]:
        raise Lineage(f"these entries were built against creditors run {run['creditors_run_id']}, not {creditors_run}: a different snapshot")


def controls(conn, run_id: str) -> dict:
    rows = conn.execute("SELECT left_layer, right_layer, count(*) AS total, count(*) FILTER (WHERE verdict = 'PASS') AS passed, coalesce(max(abs(variance)), 0) AS max_abs_variance "
                        "FROM entry.v_control WHERE entry_run_id = %s GROUP BY 1, 2 ORDER BY 1, 2", (run_id,)).fetchall()
    return {"layers": [{"from": r["left_layer"], "to": r["right_layer"], "controls": r["total"], "passed": r["passed"], "failed": r["total"] - r["passed"], "max_abs_variance": r["max_abs_variance"]} for r in rows],
            "total": sum(r["total"] for r in rows), "passed": sum(r["passed"] for r in rows), "failed": sum(r["total"] - r["passed"] for r in rows)}


def entry(conn, run_id: str, ref: str, finance: bool = False) -> dict | None:
    h = conn.execute("SELECT entry_ref, site_code, entry_type_short, entry_type_long, entry_date, release_status, line_count, total_dr, total_cr, selections FROM entry.v_entry_header WHERE entry_run_id = %s AND entry_ref = %s", (run_id, ref)).fetchone()
    if h is None:
        return None
    lines = conn.execute("SELECT line_no, ledger_code, ledger_name, ledger_nature, sub_ledger_ref, debit, credit, release_status, cube_name FROM entry.v_entry_line WHERE entry_run_id = %s AND entry_ref = %s ORDER BY line_no", (run_id, ref)).fetchall()
    bills = conn.execute("SELECT source_row_key AS item_ref, link_status, coverage FROM entry.v_creditor_bill_link WHERE entry_run_id = %s AND entry_ref = %s ORDER BY source_row_key", (run_id, ref)).fetchall()
    out = {**h, "lines": lines, "balanced": h["total_dr"] == h["total_cr"], "linked_bills": bills, "attachment": NO_ATTACHMENT}
    if finance:
        ident = conn.execute("SELECT site_code, entry_type_short, entry_no, created_by_site FROM entry.v_entry_identity WHERE entry_run_id = %s AND entry_ref = %s", (run_id, ref)).fetchone()
        text = {r["line_no"]: r for r in conn.execute("SELECT * FROM entry.v_entry_line_text WHERE entry_run_id = %s AND entry_ref = %s", (run_id, ref)).fetchall()}
        out["identity"] = ident
        for ln in out["lines"]:
            t = text.get(ln["line_no"], {})
            ln["text"] = {k: t.get(k) for k in ("sub_ledger_code", "narration", "reference_no", "reference_date", "cheque_no", "cheque_date", "counter_ledgers", "prepared_by", "prepared_on", "modified_by", "modified_on", "released_by", "released_on")}
    return out


def bill_link(conn, run_id: str, item_ref: str) -> dict | None:
    k = conn.execute("SELECT source_row_key AS item_ref, creditors_run_id, ledger_code, bill_amount, link_status, not_linked_reason, key_used, matched_entries, entry_ref, entry_net_amount, amount_agrees, coverage "
                     "FROM entry.v_creditor_bill_link WHERE entry_run_id = %s AND source_row_key = %s", (run_id, item_ref)).fetchone()
    if k is None:
        return None
    if k["not_linked_reason"] == "REGISTER_COVERAGE_UNAVAILABLE":
        k["message"] = BEFORE_COVERAGE_MESSAGE
    elif k["link_status"] == "AMBIGUOUS":
        k["message"] = f"{k['matched_entries']} entries match this bill; none is selected."
    elif k["link_status"] == "NOT_LINKED":
        k["message"] = "No register entry matches this bill."
    return k


def link_summary(conn, run_id: str) -> dict:
    rows = conn.execute("SELECT link_status, coverage, count(*) AS bills FROM entry.v_creditor_bill_link WHERE entry_run_id = %s GROUP BY 1, 2 ORDER BY 1, 2", (run_id,)).fetchall()
    return {"by_status_and_coverage": rows, "total": sum(r["bills"] for r in rows)}


# ───────────── bank ─────────────


def bank_ledgers(conn, run: dict) -> list[dict]:
    rd = run["register_report_date"]
    return conn.execute(
        "SELECT e.ledger_code, e.ledger_name, "
        "coalesce(sum(e.debit) FILTER (WHERE trim(e.entry_type_long) = 'Opening'), 0) AS opening_dr, coalesce(sum(e.credit) FILTER (WHERE trim(e.entry_type_long) = 'Opening'), 0) AS opening_cr, "
        "coalesce(sum(e.debit) FILTER (WHERE e.release_status = 'Posted' AND trim(e.entry_type_long) <> 'Opening' AND e.entry_date <= %(rd)s), 0) AS posted_dr, "
        "coalesce(sum(e.credit) FILTER (WHERE e.release_status = 'Posted' AND trim(e.entry_type_long) <> 'Opening' AND e.entry_date <= %(rd)s), 0) AS posted_cr, "
        "coalesce(sum(e.debit) FILTER (WHERE e.release_status = 'Unposted' AND trim(e.entry_type_long) <> 'Opening' AND e.entry_date <= %(rd)s), 0) AS unposted_dr, "
        "coalesce(sum(e.credit) FILTER (WHERE e.release_status = 'Unposted' AND trim(e.entry_type_long) <> 'Opening' AND e.entry_date <= %(rd)s), 0) AS unposted_cr, "
        "count(DISTINCT e.entry_ref) AS entries FROM entry.v_bank_entry e WHERE e.entry_run_id = %(run)s GROUP BY e.ledger_code, e.ledger_name ORDER BY e.ledger_code",
        {"run": run["entry_run_id"], "rd": rd}).fetchall()


def bank_entries(conn, run: dict, ledger_code: str, status: str, limit: int, offset: int) -> dict:
    where = FILTERS[status]
    p = {"run": run["entry_run_id"], "ledger": ledger_code, "rd": run["register_report_date"], "limit": limit, "offset": offset}
    rows = conn.execute(
        f"SELECT e.entry_ref, e.entry_date, e.entry_type_short, e.entry_type_long, e.release_status, sum(e.debit) AS debit, sum(e.credit) AS credit, count(*) AS ledger_lines FROM entry.v_bank_entry e "
        f"WHERE e.entry_run_id = %(run)s AND e.ledger_code = %(ledger)s AND {where} GROUP BY e.entry_ref, e.entry_date, e.entry_type_short, e.entry_type_long, e.release_status ORDER BY e.entry_date, e.entry_ref LIMIT %(limit)s OFFSET %(offset)s", p).fetchall()
    tot = conn.execute(f"SELECT count(DISTINCT e.entry_ref) AS entries, coalesce(sum(e.debit), 0) AS debit, coalesce(sum(e.credit), 0) AS credit FROM entry.v_bank_entry e WHERE e.entry_run_id = %(run)s AND e.ledger_code = %(ledger)s AND {where}", p).fetchone()
    return {"entries": rows, "total": tot}


# ───────────── till ─────────────


def till_stores(conn, run: dict) -> list[dict]:
    return conn.execute(
        "SELECT d.site_code, d.cumulative_balance AS balance, (SELECT coalesce(sum(x.debit), 0) FROM entry.v_till_day x WHERE x.entry_run_id = d.entry_run_id AND x.site_code = d.site_code) AS total_debit, "
        "(SELECT coalesce(sum(x.credit), 0) FROM entry.v_till_day x WHERE x.entry_run_id = d.entry_run_id AND x.site_code = d.site_code) AS total_credit, "
        "(SELECT count(*) FROM entry.v_till_day x WHERE x.entry_run_id = d.entry_run_id AND x.site_code = d.site_code AND (x.debit <> 0 OR x.credit <> 0)) AS active_days "
        "FROM entry.v_till_day d WHERE d.entry_run_id = %s AND d.day = %s ORDER BY d.cumulative_balance DESC, d.site_code", (run["entry_run_id"], run["till_balance_date"])).fetchall()


def till_days(conn, run: dict, site: str) -> list[dict]:
    return conn.execute("SELECT day, debit, credit, cumulative_balance FROM entry.v_till_day WHERE entry_run_id = %s AND site_code = %s AND (debit <> 0 OR credit <> 0) ORDER BY day", (run["entry_run_id"], site)).fetchall()


def till_day_row(conn, run: dict, site: str, day) -> dict | None:
    return conn.execute("SELECT day, debit, credit, cumulative_balance FROM entry.v_till_day WHERE entry_run_id = %s AND site_code = %s AND day = %s", (run["entry_run_id"], site, day)).fetchone()


def till_entries(conn, run: dict, site: str, day) -> dict:
    rows = conn.execute(
        "SELECT entry_ref, entry_type_short, entry_type_long, sum(debit) AS debit, sum(credit) AS credit, min(release_status) AS release_status FROM entry.v_cash_drawer_entry "
        "WHERE entry_run_id = %s AND site_code = %s AND day = %s GROUP BY entry_ref, entry_type_short, entry_type_long ORDER BY entry_type_long, entry_ref", (run["entry_run_id"], site, day)).fetchall()
    return {"entries": rows, "debit": sum((r["debit"] for r in rows), ZERO), "credit": sum((r["credit"] for r in rows), ZERO)}
