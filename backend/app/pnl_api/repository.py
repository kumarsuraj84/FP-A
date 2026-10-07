"""SQL and arithmetic for the store P&L actuals API: reads over the serving views of ONE run (candidate or live). Money is exact (Decimal, serialised as text by the router).

Definitions (one place, so every page agrees):
  Revenue          GL ledgers in section REVENUE, credit less debit: net sales EX-GST (the POS and the COGS table include GST; the books do not).
  COGS             the COGS table (T_CUSTOM_COGS), site x month, as stored. It has no posting status, so it is the same in the posted and the all-entries basis.
  Other COGS items GL ledgers in section COGS_BOOKS (purchase discounts and the like), credit less debit: a profit effect, shown on its own line.
  Gross margin     Revenue - COGS + Other COGS items.
  Store opex       GL ledgers in section STORE_OPEX, credit less debit (a cost is negative): shown as a negative number.
  Contribution     Gross margin + Store opex. It is BEFORE other income, finance cost and any head-office allocation.
  Excluded         ledgers the finance mapping does not know (section UNMAPPED): never in a total, always listed with their amounts.
Basis: "posted" counts Posted entries only; "all" adds Unposted entries (the current month is largely unposted: provisional). Budget is not held anywhere: it is always null.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

ZERO = Decimal(0)
SECTION_ORDER = ["REVENUE", "COGS_BOOKS", "STORE_OPEX", "OTHER_INCOME", "FINANCE_COST"]
SECTION_LABEL = {"REVENUE": "Net sales (ex-GST)", "COGS_BOOKS": "Other COGS items (books)", "STORE_OPEX": "Store operating expenses", "OTHER_INCOME": "Other income", "FINANCE_COST": "Finance cost"}
BUDGET_NOTE = "Budget is not available for FY26-27 (the FY25-26 plan ended in March 2026). It is shown blank."
NOT_IN_MASTER = "(not in site master)"
SALES_LEDGER = "Sales - POS"
STATE_LABEL = {"live": "Live", "verified_candidate": "Verified candidate (not published)", "superseded": "Superseded", "withdrawn": "Withdrawn"}
FILTER_FIELDS = {"region": "region_type", "cluster": "cluster_type", "state": "state", "vintage": "store_current_status", "status": "store_status"}


def data_state(run: dict) -> str:
    return {"live": "live", "unpublished": "verified_candidate", "superseded": "superseded", "withdrawn": "withdrawn"}[run["publication_state"]]


def serving_run(conn, run_id: str | None = None) -> dict | None:
    if run_id:
        return conn.execute("SELECT * FROM pnl.v_serving_run WHERE run_id = %s", (run_id,)).fetchone()
    return conn.execute("SELECT * FROM pnl.v_serving_run ORDER BY (publication_state = 'live') DESC, loaded_at DESC LIMIT 1").fetchone()


def list_runs(conn) -> list[dict]:
    return conn.execute("SELECT * FROM pnl.v_serving_run ORDER BY loaded_at DESC").fetchall()


def controls(conn, run_id: str) -> dict:
    rows = conn.execute("SELECT left_layer, right_layer, count(*) AS total, count(*) FILTER (WHERE verdict = 'PASS') AS passed, coalesce(max(abs(variance)), 0) AS max_abs_variance "
                        "FROM pnl.v_control WHERE run_id = %s GROUP BY 1, 2 ORDER BY 1, 2", (run_id,)).fetchall()
    return {"layers": [{"from": r["left_layer"], "to": r["right_layer"], "controls": r["total"], "passed": r["passed"], "failed": r["total"] - r["passed"], "max_abs_variance": r["max_abs_variance"]} for r in rows],
            "total": sum(r["total"] for r in rows), "passed": sum(r["passed"] for r in rows), "failed": sum(r["total"] - r["passed"] for r in rows)}


# ───────────── periods ─────────────


def month_start(s: str) -> date:
    y, m = s.split("-")
    return date(int(y), int(m), 1)


def add_months(d: date, n: int) -> date:
    k = d.year * 12 + d.month - 1 + n
    return date(k // 12, k % 12 + 1, 1)


def months_between(lo: date, hi: date) -> list[date]:
    out, d = [], lo
    while d <= hi:
        out.append(d)
        d = add_months(d, 1)
    return out


def default_period(run: dict) -> tuple[date, date]:
    a = run["as_of_date"]
    fy = date(a.year if a.month >= 4 else a.year - 1, 4, 1)
    return fy, date(a.year, a.month, 1)


def pct(a: Decimal, b: Decimal) -> Decimal | None:
    return None if not b else (a * 100 / b).quantize(Decimal("0.0001"))


# ───────────── data access ─────────────


def sites(conn, run_id: str) -> dict[str, dict]:
    return {r["site_code"]: r for r in conn.execute("SELECT * FROM pnl.v_site WHERE run_id = %s", (run_id,)).fetchall()}


def store_set(conn, run_id: str) -> set[str]:
    """A store is a site with sales POSTED IN THE BOOKS (ledger 'Sales - POS') in this run. Everything else (head office, depots, and the few sites that only appear in the COGS table) is non-store:
    its costs count for the company, never for a store. Sites with COGS-table sales but no books sales are listed on the reconciliation view."""
    rows = conn.execute("SELECT DISTINCT site_code FROM pnl.v_gl_site_month WHERE run_id = %s AND ledger_name = %s", (run_id, SALES_LEDGER)).fetchall()
    return {r["site_code"] for r in rows}


def site_months(conn, run_id: str, basis: str) -> dict[tuple[str, date], dict]:
    """Per site and month, every P&L line (books side from the GL, COGS from the COGS table), for the whole run."""
    cond = "AND release_status = 'Posted'" if basis == "posted" else ""
    out: dict[tuple[str, date], dict] = defaultdict(lambda: {"revenue": ZERO, "cogs": ZERO, "cogs_books": ZERO, "opex": ZERO, "other_income": ZERO, "finance_cost": ZERO, "unmapped": ZERO, "unposted_net": ZERO, "unposted_revenue": ZERO, "table_sales": ZERO})
    keymap = {"REVENUE": "revenue", "COGS_BOOKS": "cogs_books", "STORE_OPEX": "opex", "OTHER_INCOME": "other_income", "FINANCE_COST": "finance_cost", "UNMAPPED": "unmapped"}
    for r in conn.execute(f"SELECT site_code, month, section, sum(credit - debit) AS net FROM pnl.v_gl_site_month WHERE run_id = %s {cond} GROUP BY 1, 2, 3", (run_id,)).fetchall():
        out[(r["site_code"], r["month"])][keymap[r["section"]]] += r["net"]
    for r in conn.execute("SELECT site_code, month, sum(credit - debit) AS net, sum(CASE WHEN section = 'REVENUE' THEN credit - debit ELSE 0 END) AS rev FROM pnl.v_gl_site_month "
                          "WHERE run_id = %s AND release_status = 'Unposted' AND section <> 'UNMAPPED' GROUP BY 1, 2", (run_id,)).fetchall():
        out[(r["site_code"], r["month"])]["unposted_net"] += r["net"]
        out[(r["site_code"], r["month"])]["unposted_revenue"] += r["rev"]
    for r in conn.execute("SELECT site_code, month, sum(cogs_v) AS cogs, sum(sl_v - tax_amt) AS ts FROM pnl.v_cogs_site_month WHERE run_id = %s GROUP BY 1, 2", (run_id,)).fetchall():
        a = out[(r["site_code"], r["month"])]
        a["cogs"] += r["cogs"]
        a["table_sales"] += r["ts"]
    return out


def finish(a: dict) -> dict:
    gm = a["revenue"] - a["cogs"] + a["cogs_books"]
    contribution = gm + a["opex"]
    return {**a, "gross_margin": gm, "gross_margin_pct": pct(gm, a["revenue"]), "contribution": contribution, "contribution_pct": pct(contribution, a["revenue"]), "opex_pct": pct(-a["opex"], a["revenue"])}


def add(into: dict, a: dict) -> None:
    for k in ("revenue", "cogs", "cogs_books", "opex", "other_income", "finance_cost", "unmapped", "unposted_net", "unposted_revenue", "table_sales"):
        into[k] += a[k]


def blank() -> dict:
    return {"revenue": ZERO, "cogs": ZERO, "cogs_books": ZERO, "opex": ZERO, "other_income": ZERO, "finance_cost": ZERO, "unmapped": ZERO, "unposted_net": ZERO, "unposted_revenue": ZERO, "table_sales": ZERO}


def matches(site: dict | None, filters: dict) -> bool:
    for k, want in filters.items():
        if not want:
            continue
        have = (site or {}).get(FILTER_FIELDS[k]) if site else None
        if (have if have is not None else NOT_IN_MASTER) != want:
            return False
    return True


def aggregate(data: dict, site_filter, month_lo: date, month_hi: date) -> dict:
    t = blank()
    for (site, mon), a in data.items():
        if month_lo <= mon <= month_hi and site_filter(site):
            add(t, a)
    return t


def period_totals(data: dict, site_filter, lo: date, hi: date) -> dict:
    return finish(aggregate(data, site_filter, lo, hi))


def last_year(lo: date, hi: date, first_month: date) -> tuple[date, date] | None:
    a, b = add_months(lo, -12), add_months(hi, -12)
    return (a, b) if a >= first_month else None


def pl_lines(conn, run_id: str, basis: str, lo: date, hi: date, site_codes: set[str] | None) -> list[dict]:
    cond = "AND release_status = 'Posted'" if basis == "posted" else ""
    params: list = [run_id, lo, hi]
    sc = ""
    if site_codes is not None:
        sc = "AND site_code = ANY(%s)"
        params.append(sorted(site_codes))
    rows = conn.execute(f"SELECT section, group_label, sum(credit - debit) AS net, count(DISTINCT glcode) AS ledgers FROM pnl.v_gl_site_month WHERE run_id = %s AND month BETWEEN %s AND %s {cond} {sc} "
                        "AND section <> 'UNMAPPED' GROUP BY 1, 2", params).fetchall()
    order = {s: i for i, s in enumerate(SECTION_ORDER)}
    return sorted(({"section": r["section"], "section_label": SECTION_LABEL[r["section"]], "group_label": r["group_label"], "amount": r["net"], "ledgers": r["ledgers"]} for r in rows),
                  key=lambda r: (order[r["section"]], r["amount"] if r["section"] == "STORE_OPEX" else -r["amount"], r["group_label"]))


def unmapped_ledgers(conn, run_id: str, basis: str, lo: date, hi: date, limit: int = 60) -> dict:
    cond = "AND release_status = 'Posted'" if basis == "posted" else ""
    rows = conn.execute(f"SELECT glcode, ledger_name, sum(credit - debit) AS net, sum(debit) AS debit, sum(credit) AS credit, count(DISTINCT site_code) AS sites FROM pnl.v_gl_site_month "
                        f"WHERE run_id = %s AND section = 'UNMAPPED' AND month BETWEEN %s AND %s {cond} GROUP BY 1, 2 ORDER BY abs(sum(credit - debit)) DESC, 2", (run_id, lo, hi)).fetchall()
    return {"count": len(rows), "net": sum((r["net"] for r in rows), ZERO), "gross_abs": sum((abs(r["net"]) for r in rows), ZERO), "ledgers": rows[:limit]}


def unmapped_run_count(conn, run_id: str) -> int:
    """Ledgers with no finance group anywhere in the run (every loaded month): the period view can show fewer."""
    return conn.execute("SELECT count(DISTINCT glcode) AS n FROM pnl.v_gl_site_month WHERE run_id = %s AND section = 'UNMAPPED'", (run_id,)).fetchone()["n"]


def provisional_months(data: dict, lo: date, hi: date) -> list[date]:
    seen = {m for (s, m), a in data.items() if lo <= m <= hi and a["unposted_revenue"] != 0}
    return sorted(seen)


def tieout_by_month(conn, run_id: str, lo: date, hi: date) -> list[dict]:
    return conn.execute("SELECT month, count(*) AS site_months, count(*) FILTER (WHERE tied) AS tied, sum(books_sales) AS books_sales, sum(cogs_table_sales_ex_gst) AS table_sales, sum(difference) AS difference, "
                        "coalesce(max(abs(difference)), 0) AS max_abs_difference FROM pnl.v_sales_tieout WHERE run_id = %s AND month BETWEEN %s AND %s GROUP BY 1 ORDER BY 1", (run_id, lo, hi)).fetchall()


def untied(conn, run_id: str, lo: date, hi: date, limit: int = 25) -> list[dict]:
    return conn.execute("SELECT t.site_code, s.store_name, t.month, t.books_sales, t.cogs_table_sales_ex_gst, t.difference FROM pnl.v_sales_tieout t LEFT JOIN pnl.v_site s ON s.run_id = t.run_id AND s.site_code = t.site_code "
                        "WHERE t.run_id = %s AND NOT t.tied AND t.month BETWEEN %s AND %s ORDER BY abs(t.difference) DESC, t.site_code LIMIT %s", (run_id, lo, hi, limit)).fetchall()


def cogs_only_sites(conn, run_id: str) -> list[dict]:
    return conn.execute("SELECT c.site_code, s.store_name, sum(c.sl_v - c.tax_amt) AS sales_ex_gst, sum(c.cogs_v) AS cogs FROM pnl.v_cogs_site_month c LEFT JOIN pnl.v_site s ON s.run_id = c.run_id AND s.site_code = c.site_code "
                        "WHERE c.run_id = %s AND NOT EXISTS (SELECT 1 FROM pnl.v_gl_site_month g WHERE g.run_id = c.run_id AND g.site_code = c.site_code AND g.ledger_name = %s) "
                        "GROUP BY 1, 2 ORDER BY 3 DESC", (run_id, SALES_LEDGER)).fetchall()


def ledgers_of_group(conn, run_id: str, basis: str, lo: date, hi: date, site: str, group_label: str) -> list[dict]:
    cond = "AND release_status = 'Posted'" if basis == "posted" else ""
    return conn.execute(f"SELECT glcode, ledger_name, month, sum(credit - debit) AS net, sum(lines) AS lines FROM pnl.v_gl_site_month WHERE run_id = %s AND site_code = %s AND group_label = %s "
                        f"AND month BETWEEN %s AND %s {cond} GROUP BY 1, 2, 3 ORDER BY 2, 3", (run_id, site, group_label, lo, hi)).fetchall()
