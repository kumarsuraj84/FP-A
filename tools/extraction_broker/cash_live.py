"""
cash_live_01: the complete Cash pilot (store till cash + bank / cash ledger book figures) read from the LIVE SSRK tables instead of the temporary MISRETAIL objects.

  bank / cash ledgers   exactly as cash_bank_live_01 (FINGL, FINGLOP, FINPOST, FINENTTYPE)
  store till cash       ledger 1000000008 "Cash Drawer" (cost-centre applicable): SSRK.FINCOSTTAG by store (ADMSITE_CODE) and day
        opening   = the store's balance on that ledger for everything dated before 2026-04-01 (all history), counted as debit (or credit, if negative) on 2026-04-01
        movement  = the day's debit and credit; cumulative balance = opening + running (debit - credit), filled for every store with activity this financial year on every day that has any activity in the ledger
        store name = ADMSITE.SHRTNAME
Verified against the 05 Oct run, store by store: cumulative balance equal for 198 of 209 stores (docs/ssrk/SSRK_META_DISCOVERY.md, part 14).
The till SQL (c1 control, e1 extract) is written for the live ledger, one materialised pass over the ledger's cost tags, with the same output columns as the pilot's. AS-OF = today (live tables hold the current position only). Read only, guard-checked, capped.
"""
from __future__ import annotations

from datetime import date, timedelta

import cash_bank_live
import packages
from packages import Dataset

_GL = 1000000008
_FY = "2026-04-01"


def _cte(as_of: str) -> str:
    """Two simple aggregations (the shapes that run fast on the live table): everything before the financial year per store, collapsed into one carrier row dated 2026-03-31, and
    the financial year per store and day."""
    nxt = (date.fromisoformat(as_of) + timedelta(days=1)).isoformat()
    return (f"WITH b AS (SELECT c.admsite_code AS site, DATE '2026-03-31' AS d, sum(c.damount) AS dr, sum(c.camount) AS cr FROM SSRK.FINCOSTTAG c "
            f"WHERE c.glcode = {_GL} AND c.entdt >= DATE '2005-01-01' AND c.entdt < DATE '{_FY}' GROUP BY c.admsite_code "
            f"UNION ALL SELECT c.admsite_code, TRUNC(c.entdt), sum(c.damount), sum(c.camount) FROM SSRK.FINCOSTTAG c "
            f"WHERE c.glcode = {_GL} AND c.entdt >= DATE '{_FY}' AND c.entdt < DATE '{nxt}' GROUP BY c.admsite_code, TRUNC(c.entdt)), "
            f"p AS (SELECT max(b.d) AS till FROM b WHERE b.d >= DATE '{_FY}' AND b.d <= DATE '{as_of}' AND (b.dr <> 0 OR b.cr <> 0)), "
            f"act AS (SELECT b.site AS site FROM b WHERE b.d >= DATE '{_FY}' AND b.d <= DATE '{as_of}' GROUP BY b.site), "
            f"op AS (SELECT b.site AS site, sum(b.dr - b.cr) AS opening FROM b WHERE b.d < DATE '{_FY}' GROUP BY b.site) ")


def _till_c1(as_of: str) -> str:
    """Source control, a different shape from the extract: totals over all active stores with no per-store grouping and no running sums."""
    tm = packages._TM9
    return (_cte(as_of) + "SELECT TO_CHAR(max(p.till), 'YYYY-MM-DD') AS till_date, (SELECT count(*) FROM act) AS stores_with_a_row, "
            + tm("(SELECT sum(b2.dr - b2.cr) FROM b b2 WHERE b2.d <= p.till AND b2.site IN (SELECT site FROM act))", "sum_cumulative") + ", "
            + tm(f"(SELECT sum(b3.dr) FROM b b3 WHERE b3.d >= TRUNC(p.till, 'MM') AND b3.d >= DATE '{_FY}' AND b3.d <= p.till AND b3.site IN (SELECT site FROM act))", "mtd_debit") + ", "
            + tm(f"(SELECT sum(b4.cr) FROM b b4 WHERE b4.d >= TRUNC(p.till, 'MM') AND b4.d >= DATE '{_FY}' AND b4.d <= p.till AND b4.site IN (SELECT site FROM act))", "mtd_credit") + ", "
            + tm(f"(SELECT sum(b5.dr) FROM b b5 WHERE b5.d >= DATE '{_FY}' AND b5.d <= p.till AND b5.site IN (SELECT site FROM act)) + (SELECT nvl(sum(greatest(o.opening, 0)), 0) FROM op o WHERE o.site IN (SELECT site FROM act))", "fytd_debit") + ", "
            + tm(f"(SELECT sum(b6.cr) FROM b b6 WHERE b6.d >= DATE '{_FY}' AND b6.d <= p.till AND b6.site IN (SELECT site FROM act)) + (SELECT nvl(sum(greatest(-o2.opening, 0)), 0) FROM op o2 WHERE o2.site IN (SELECT site FROM act))", "fytd_credit")
            + " FROM p FETCH FIRST 5 ROWS ONLY")


def _till_e1(as_of: str) -> str:
    """One row per store: balance on the till date (opening + movement), month and year to date (the opening counts as a debit, or a credit if negative, on 1 April), last activity."""
    tm = packages._TM9
    mv = f"b.d >= DATE '{_FY}' AND b.d <= p.till"
    april = f"CASE WHEN TRUNC(max(p.till), 'MM') = DATE '{_FY}'"
    return (_cte(as_of) + "SELECT TO_CHAR(b.site) AS site_code, a.shrtname AS store_name, TO_CHAR(max(p.till), 'YYYY-MM-DD') AS till_date, "
            + tm(f"nvl(max(o.opening), 0) + sum(CASE WHEN {mv} THEN b.dr - b.cr ELSE 0 END)", "cumulative_balance") + ", "
            + tm(f"sum(CASE WHEN {mv} AND b.d >= TRUNC(p.till, 'MM') THEN b.dr ELSE 0 END) + {april} THEN greatest(nvl(max(o.opening), 0), 0) ELSE 0 END", "mtd_debit") + ", "
            + tm(f"sum(CASE WHEN {mv} AND b.d >= TRUNC(p.till, 'MM') THEN b.cr ELSE 0 END) + {april} THEN greatest(-nvl(max(o.opening), 0), 0) ELSE 0 END", "mtd_credit") + ", "
            + tm(f"sum(CASE WHEN {mv} THEN b.dr ELSE 0 END) + greatest(nvl(max(o.opening), 0), 0)", "fytd_debit") + ", "
            + tm(f"sum(CASE WHEN {mv} THEN b.cr ELSE 0 END) + greatest(-nvl(max(o.opening), 0), 0)", "fytd_credit") + ", "
            + f"TO_CHAR(max(CASE WHEN {mv} AND (b.dr <> 0 OR b.cr <> 0) THEN b.d END), 'YYYY-MM-DD') AS last_activity_date "
            + "FROM b JOIN act ON act.site = b.site JOIN SSRK.ADMSITE a ON a.code = b.site LEFT JOIN op o ON o.site = b.site CROSS JOIN p "
            + "GROUP BY b.site, a.shrtname FETCH FIRST 2000 ROWS ONLY")


def datasets(as_of: str) -> tuple[Dataset, ...]:
    c1, e1 = _till_c1(as_of), _till_e1(as_of)
    bank = {d.name: d for d in cash_bank_live.datasets(as_of)}
    return (
        Dataset("c1_till_control_pre", "extract", "Source control before the extract: till date, stores, total till cash and Dr/Cr totals (no per-store grouping), live.", sql=c1, role="control_pre"),
        bank["c2_bank_control_pre"],
        Dataset("e1_store_till", "extract", "The extract: one row per store with till cash on the till date, month-to-date and year-to-date Dr/Cr, last activity (ledger 1000000008, live).", sql=e1, role="extract"),
        bank["e2_bank_site_register"],
        bank["e3_bank_gl_register"],
        bank["e4_bank_prior_year_closing"],
        Dataset("c1_till_control_post", "extract", "The same till control after the extract.", sql=c1, role="control_post"),
        bank["c2_bank_control_post"],
    )


def meta(as_of: str) -> dict:
    base = packages.PACKAGE_META["cash_pilot_01"]["contract"]
    contract = {**base, "contract": "cash-live-1.0", "till_source": "SSRK.FINCOSTTAG, ledger 1000000008 (Cash Drawer), by store", "bank_source_site": "SSRK.FINPOST (live)",
                "bank_source_gl": "SSRK.FINPOST (live)", "bank_prior_year_source": "SSRK.FINPOST (live), FY25-26", "as_of": as_of,
                "scope": {"till": "SSRK.FINCOSTTAG ledger 1000000008", "bank_ledgers": "SSRK.FINGL type A and srctype B or C"}}
    return {"halt_on_failure": True, "contract": contract}


def configure_cash(as_of: str, today: date | None = None) -> None:
    try:
        d = date.fromisoformat(as_of)
    except ValueError:
        raise ValueError("the as-of date must be a real date written YYYY-MM-DD") from None
    if d.isoformat() != as_of:
        raise ValueError("the as-of date must be written YYYY-MM-DD")
    if d != (today or date.today()):
        raise ValueError("cash_live_01 reads the LIVE position, so the as-of date must be today")
    packages.PACKAGES["cash_live_01"] = datasets(as_of)
    packages.PACKAGE_META["cash_live_01"] = meta(as_of)


configure_cash(date.today().isoformat())


def _base_test(as_of: str) -> tuple[Dataset, ...]:
    return (Dataset("z1_base_only", "extract", "Timing test: the single aggregation pass over the ledger's cost tags (rows and totals).",
                    sql=_cte(as_of) + "SELECT count(*) AS rows_n, sum(b.dr) AS dr, sum(b.cr) AS cr FROM b FETCH FIRST 2 ROWS ONLY"),)


packages.PACKAGES["cash_base_test"] = _base_test(date.today().isoformat())
