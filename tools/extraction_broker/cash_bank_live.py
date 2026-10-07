"""
cash_bank_live_01: the 34 BANK and CASH ledger book figures of the Cash pilot, read from the LIVE SSRK tables instead of the temporary MISRETAIL registers (T$FINREGSITE_844, T$FINREG_901, T$FINREG_886).
Store till cash is NOT here: it comes from a MISRETAIL view whose rule is not known (see docs/ssrk/SSRK_META_DISCOVERY.md, part 11).

The cash pilot's own position SQL (cash_pilot_01 datasets e2, e3, e4 and the c2 control) is pointed at inline views that rebuild the registers' rows:
  ledgers   SSRK.FINGL: TYPE A with SRCTYPE B = Bank, SRCTYPE C = Cash (the cube's "nature"); EXT = Y means extinct
  opening   SSRK.FINGLOP for the financial year (YCODE 51 now, 50 for the prior year), as an 'Opening' row
  movement  SSRK.FINPOST for those ledgers and that year, entry type name from SSRK.FINENTTYPE, release status P = Posted, U = Unposted, site = the owner site
Verified for April to October on the 05 Oct run: opening equals FINGLOP exactly, and in the site register all 34 ledgers sit on a single site, so the site and GL registers coincide.
AS-OF: the live tables hold only the current position, so the as-of date must be today. Read only, guard-checked, capped.
"""
from __future__ import annotations

from datetime import date

import packages
from packages import Dataset

_GL_VIEW = ("(SELECT g.glcode AS glcode, g.glname AS glname, CASE g.type WHEN 'A' THEN 'Asset' WHEN 'L' THEN 'Liability' WHEN 'E' THEN 'Expense' WHEN 'I' THEN 'Income' END AS type, "
            "CASE g.srctype WHEN 'B' THEN 'Bank' WHEN 'C' THEN 'Cash' END AS nature, CASE g.ext WHEN 'Y' THEN 'Yes' ELSE 'No' END AS extinct FROM SSRK.FINGL g)")
_BANK_GLS = "SELECT glcode FROM SSRK.FINGL WHERE type = 'A' AND srctype IN ('B', 'C')"


def _register(as_of: str, ycode: int, fy_start: str, until: str | None) -> str:
    """A register's rows: one 'Opening' row per ledger from FINGLOP, plus the year's postings."""
    upto = f" AND p.entdt <= DATE '{until}'" if until else ""
    opening = (f"SELECT DATE '{as_of}' AS report_date, o.glcode AS entry_glcode, 'Opening' AS entry_type_long, 'Posted' AS release_status, DATE '{fy_start}' AS entry_date, "
               f"o.opdamt AS debit, o.opcamt AS credit, NULL AS sitecode FROM SSRK.FINGLOP o WHERE o.ycode = {ycode} AND o.glcode IN ({_BANK_GLS})")
    movement = (f"SELECT DATE '{as_of}' AS report_date, p.glcode AS entry_glcode, TRIM(et.entname) AS entry_type_long, CASE p.release_status WHEN 'P' THEN 'Posted' ELSE 'Unposted' END AS release_status, "
                f"p.entdt AS entry_date, p.damount AS debit, p.camount AS credit, p.admsite_code_owner AS sitecode FROM SSRK.FINPOST p JOIN SSRK.FINENTTYPE et ON et.enttype = p.enttype "
                f"WHERE p.ycode = {ycode} AND p.entdt >= DATE '{fy_start}'{upto} AND p.glcode IN ({_BANK_GLS})")
    return f"({opening} UNION ALL {movement})"


def datasets(as_of: str) -> tuple[Dataset, ...]:
    fy = "2026-04-01"
    reg = _register(as_of, 51, fy, None)
    prior = _register(as_of, 50, "2025-04-01", "2026-03-31")
    rd = f"DATE '{as_of}'"
    bank = f'{packages.OWNER}."MAS$FINGL"'

    def pos(tbl, since, until, label, extra=""):
        sql = packages._position(tbl, since, until if until else rd, packages._BANK_LEDGERS, label, extra)
        return sql.replace(packages._BANK_LEDGERS, _BANK_GLS).replace(bank, _GL_VIEW)

    c2 = packages._bank_totals(reg, fy, rd, _BANK_GLS)
    return (
        Dataset("c2_bank_control_pre", "extract", "Source control before the extract: bank/cash ledger totals (no per-ledger grouping), live.", sql=c2, role="control_pre"),
        Dataset("e2_bank_site_register", "extract", "The bank/cash ledgers by site register (live postings; owner site): opening, posted, unposted, future, last dates.",
                sql=pos(reg, fy, None, "site_register", ", COUNT(DISTINCT t.sitecode) AS sites") + " FETCH FIRST 200 ROWS ONLY", role="extract"),
        Dataset("e3_bank_gl_register", "extract", "The same ledgers as a GL register (live postings), as the second source.",
                sql=pos(reg, fy, None, "gl_register") + " FETCH FIRST 200 ROWS ONLY", role="extract"),
        Dataset("e4_bank_prior_year_closing", "extract", "The same ledgers for FY 25-26 to 31 Mar 2026 (closing that must equal this year's opening).",
                sql=pos(prior, "2025-04-01", "DATE '2026-03-31'", "prior_year_closing") + " FETCH FIRST 200 ROWS ONLY", role="extract"),
        Dataset("c2_bank_control_post", "extract", "The same bank control after the extract.", sql=c2, role="control_post"),
    )


def meta(as_of: str) -> dict:
    return {"halt_on_failure": True,
            "contract": {"contract": "cash-bank-live-1.0", "rules_version": "1", "fy_start": "2026-04-01", "as_of": as_of,
                         "position_rule": packages.CASH_RULES["position_rule"], "bank_status": packages.CASH_RULES["bank_status"],
                         "scope": {"bank_ledgers": "SSRK.FINGL type A and srctype B or C (34 ledgers)", "till": "not included"}}}


def configure_bank(as_of: str, today: date | None = None) -> None:
    try:
        d = date.fromisoformat(as_of)
    except ValueError:
        raise ValueError("the as-of date must be a real date written YYYY-MM-DD") from None
    if d.isoformat() != as_of:
        raise ValueError("the as-of date must be written YYYY-MM-DD")
    if d != (today or date.today()):
        raise ValueError("cash_bank_live_01 reads the LIVE position, so the as-of date must be today")
    packages.PACKAGES["cash_bank_live_01"] = datasets(as_of)
    packages.PACKAGE_META["cash_bank_live_01"] = meta(as_of)


configure_bank(date.today().isoformat())
