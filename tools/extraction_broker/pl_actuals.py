"""
pl_actuals_01: store P&L ACTUALS from the books. Revenue ex-GST, store opex and the other income / expense ledgers by site, ledger, month and posting status, straight from the site GL
registers (MISRETAIL only, SELECT only, nothing from SSRK-backed views): T$FINREGSITE_877 (Apr 2023 to Mar 2026) and T$FINREGSITE_844 (FY26-27). COGS is NOT here: it comes from
T_CUSTOM_COGS in its own package (cogs_scan_01). Budget is not extracted (left blank).

One small aggregate query per month (a single heavy query kept failing), a different-shape control per register (totals by month and status, no site or ledger) before and after,
masters (GL master, ledger -> finance group, group -> major group, site master). The as-of date is explicit and must equal the register's own report date.
"""
from __future__ import annotations

from datetime import date

import packages
from packages import Dataset

_O = packages.OWNER
_CUR = packages._ENTRY_SITE
_OLD = packages._ALLYEARS
_GL = f'{_O}."MAS$FINGL"'
_TM9 = packages._TM9
FROM_MONTH = date(2025, 4, 1)      # last year (FY25-26) plus the current year: the window the COGS table was scanned for
FY_START = date(2026, 4, 1)        # the current register starts here; earlier months come from the all-years register
DEFAULT_AS_OF = "2026-10-05"       # placeholder so the package is listed; the broker REQUIRES --as-of and reconfigures
PL_TYPES = "g.type IN ('Income', 'Expense')"


def _months(as_of: date) -> list[date]:
    out, d = [], FROM_MONTH
    while d <= as_of:
        out.append(d)
        d = _next(d)
    return out


def _next(d: date) -> date:
    return date(d.year + (d.month == 12), d.month % 12 + 1, 1)


def _register(m: date) -> str:
    return _CUR if m >= FY_START else _OLD


def _upper(m: date, as_of: date) -> str:
    """Exclusive upper bound of the month's window; the as-of day itself is included and nothing after it (future-dated entries are never read)."""
    return min(_next(m), date.fromordinal(as_of.toordinal() + 1)).isoformat()


def _month_sql(m: date, as_of: date) -> str:
    return ("SELECT TO_CHAR(r.sitecode) AS site_code, TO_CHAR(r.entry_glcode) AS glcode, r.entry_type_short AS entry_type_short, r.release_status AS release_status, "
            f"{_TM9('SUM(r.debit)', 'debit')}, {_TM9('SUM(r.credit)', 'credit')}, COUNT(*) AS lines_n "
            f"FROM {_register(m)} r JOIN {_GL} g ON g.glcode = r.entry_glcode "
            f"WHERE {PL_TYPES} AND r.entry_date >= DATE '{m.isoformat()}' AND r.entry_date < DATE '{_upper(m, as_of)}' "
            "GROUP BY r.sitecode, r.entry_glcode, r.entry_type_short, r.release_status FETCH FIRST 100000 ROWS ONLY")


def _control_sql(register: str, lo: date, upper_exclusive: str) -> str:
    """A different shape over the same rows: totals by month and status only (no site, no ledger). The monthly chunks must add up to it exactly."""
    return ("SELECT TO_CHAR(r.entry_date, 'YYYY-MM') AS month, r.release_status AS release_status, COUNT(*) AS lines_n, "
            f"{_TM9('SUM(r.debit)', 'debit')}, {_TM9('SUM(r.credit)', 'credit')} "
            f"FROM {register} r JOIN {_GL} g ON g.glcode = r.entry_glcode "
            f"WHERE {PL_TYPES} AND r.entry_date >= DATE '{lo.isoformat()}' AND r.entry_date < DATE '{upper_exclusive}' "
            "GROUP BY TO_CHAR(r.entry_date, 'YYYY-MM'), r.release_status FETCH FIRST 500 ROWS ONLY")


def _register_sql() -> str:
    return (f"SELECT COUNT(*) AS register_rows, TO_CHAR(MAX(r.report_date), 'YYYY-MM-DD') AS register_report_date FROM {_CUR} r "
            f"WHERE r.entry_date >= DATE '{FY_START.isoformat()}' FETCH FIRST 5 ROWS ONLY")


def aligned_window(as_of: date) -> tuple[date, date, date]:
    """(last year's as-of month, first day, last day) of the window that matches 1..N of this year's as-of month."""
    from calendar import monthrange

    lym = date(as_of.year - 1, as_of.month, 1)
    return lym, lym, date(as_of.year - 1, as_of.month, min(as_of.day, monthrange(as_of.year - 1, as_of.month)[1]))


def _aligned_sql(as_of: date) -> str:
    lym, first, last = aligned_window(as_of)
    upper = date.fromordinal(last.toordinal() + 1).isoformat()
    return ("SELECT TO_CHAR(r.sitecode) AS site_code, TO_CHAR(r.entry_glcode) AS glcode, r.entry_type_short AS entry_type_short, r.release_status AS release_status, "
            f"{_TM9('SUM(r.debit)', 'debit')}, {_TM9('SUM(r.credit)', 'credit')}, COUNT(*) AS lines_n "
            f"FROM {_register(lym)} r JOIN {_GL} g ON g.glcode = r.entry_glcode "
            f"WHERE {PL_TYPES} AND r.entry_date >= DATE '{first.isoformat()}' AND r.entry_date < DATE '{upper}' "
            "GROUP BY r.sitecode, r.entry_glcode, r.entry_type_short, r.release_status FETCH FIRST 100000 ROWS ONLY")


def _aligned_control_sql(as_of: date) -> str:
    lym, first, last = aligned_window(as_of)
    return _control_sql(_register(lym), first, date.fromordinal(last.toordinal() + 1).isoformat())


def datasets(as_of_iso: str) -> tuple[Dataset, ...]:
    as_of = date.fromisoformat(as_of_iso)
    ms = _months(as_of)
    cur_upper = date.fromordinal(as_of.toordinal() + 1).isoformat()
    return (
        Dataset("c0_register_pre", "extract", "Control before: the current register's row count and report date.", sql=_register_sql(), role="control_pre"),
        Dataset("c1_totals_old_pre", "extract", "Control: P&L-ledger totals by month and status, all-years register.", sql=_control_sql(_OLD, FROM_MONTH, FY_START.isoformat()), role="control_pre"),
        Dataset("c1_totals_cur_pre", "extract", "Control before: P&L-ledger totals by month and status, current register to the as-of date.", sql=_control_sql(_CUR, FY_START, cur_upper), role="control_pre"),
        Dataset("c1_totals_aligned_pre", "extract", "Control: P&L-ledger totals by status for the day-aligned window of last year.", sql=_aligned_control_sql(as_of), role="control_pre"),
        Dataset("m1_gl_master", "master", "GL master: code, name, group code, type, nature, extinct (no address or contact columns).",
                sql=f"SELECT glcode, glname, grpcode, type, nature, extinct FROM {_GL} FETCH FIRST 5000 ROWS ONLY", role="extract"),
        Dataset("m2_ledger_to_group", "master", "Finance ledger -> group (the finance P&L's own mapping).",
                sql=f"SELECT ledger, sk_grp FROM {_O}.T_FINANCE_RAJEEV_P_N_L FETCH FIRST 1000 ROWS ONLY", role="extract"),
        Dataset("m3_group_to_major", "master", "Finance group -> major group.",
                sql=f"SELECT sk_grp, sk_maj_grp FROM {_O}.T_FINANCE_RAJEEV_GROUPING FETCH FIRST 1000 ROWS ONLY", role="extract"),
        Dataset("m4_site_master", "master", "Site master: opening date, status, cluster, region, state, store type, area, format, grade, last bill date.",
                sql=(f"SELECT site_code, store_name, TO_CHAR(opening_date, 'YYYY-MM-DD') AS opening_date, store_status, store_current_status, cluster_type, region_type, state, store_type, "
                     f"area, st_type, store_grade, TO_CHAR(last_bill_date, 'YYYY-MM-DD') AS last_bill_date FROM {_O}.T_STORE_OPENING_DATE FETCH FIRST 2000 ROWS ONLY"), role="extract"),
        *[Dataset(f"g_{m:%Y_%m}", "extract", f"P&L-ledger lines of {m:%Y-%m} by site, ledger, entry type and posting status.", sql=_month_sql(m, as_of), role="extract") for m in ms],
        Dataset("d_ly_aligned", "extract", f"P&L-ledger lines of the same days (1 to {as_of.day}) of last year's as-of month, by site, ledger, entry type and posting status.", sql=_aligned_sql(as_of), role="extract"),
        Dataset("c0_register_post", "extract", "Control after: the current register's row count and report date.", sql=_register_sql(), role="control_post"),
        Dataset("c1_totals_cur_post", "extract", "Control after: the same current-register totals.", sql=_control_sql(_CUR, FY_START, cur_upper), role="control_post"),
    )


def meta(as_of_iso: str) -> dict:
    return {"halt_on_failure": True, "timeout_s": 150, "attempts": 2,
            "contract": {"contract": "pl-actuals-1.1", "rules_version": "2", "as_of_cutoff": as_of_iso, "aligned_days": date.fromisoformat(as_of_iso).day, "ly_aligned_month": aligned_window(date.fromisoformat(as_of_iso))[0].isoformat(), "from_month": FROM_MONTH.isoformat(), "fy_start": FY_START.isoformat(),
                         "registers": {"current": _CUR, "all_years": _OLD}, "ledger_filter": "MAS$FINGL.TYPE in (Income, Expense)",
                         "revenue_basis": "GL ledger credits less debits, ex-GST (POS value includes GST; the GL does not)", "cogs": "not in this package (T_CUSTOM_COGS, cogs_scan_01)", "budget": "not extracted"}}


def configure_pl(as_of: str) -> None:
    try:
        d = date.fromisoformat(as_of)
    except ValueError:
        raise ValueError("the as-of date must be a real date written YYYY-MM-DD") from None
    if d.isoformat() != as_of or d < FY_START:
        raise ValueError("the as-of date must be written YYYY-MM-DD and fall in the current financial year")
    packages.PACKAGES["pl_actuals_01"] = datasets(as_of)
    packages.PACKAGE_META["pl_actuals_01"] = meta(as_of)


configure_pl(DEFAULT_AS_OF)
