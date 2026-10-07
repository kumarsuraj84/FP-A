"""
cogs_meta_probe_01: metadata-only confirmation about MISRETAIL.T_CUSTOM_COGS (the materialised site x barcode x day sales / COGS table). Dictionary views only (ALL_*), owner MISRETAIL,
no data is read. Registered into the broker's package table from here (the table itself lives in packages.py).
"""
from __future__ import annotations

import packages
from packages import Dataset

_O = packages.OWNER
_T = "T_CUSTOM_COGS"

COGS_META_PROBE_01: tuple[Dataset, ...] = (
    Dataset("m1_indexes", "metadata", "Any index on T_CUSTOM_COGS (would make a date filter cheap).",
            sql=f"SELECT index_name, uniqueness, status, num_rows, TO_CHAR(last_analyzed, 'YYYY-MM-DD') AS last_analyzed FROM all_indexes WHERE table_owner = '{_O}' AND table_name = '{_T}' FETCH FIRST 200 ROWS ONLY"),
    Dataset("m2_table", "metadata", "Rows, blocks, partitioning, compression and last analysis of T_CUSTOM_COGS.",
            sql=f"SELECT num_rows, blocks, partitioned, compression, TO_CHAR(last_analyzed, 'YYYY-MM-DD') AS last_analyzed FROM all_tables WHERE owner = '{_O}' AND table_name = '{_T}' FETCH FIRST 5 ROWS ONLY"),
    Dataset("m3_partitions", "metadata", "Partition keys of T_CUSTOM_COGS, if any.",
            sql=f"SELECT name, column_name, column_position FROM all_part_key_columns WHERE owner = '{_O}' AND name = '{_T}' FETCH FIRST 50 ROWS ONLY"),
    Dataset("m4_comments", "metadata", "Table and column comments on T_CUSTOM_COGS (definitions, settlement lag).",
            sql=f"SELECT column_name, comments FROM all_col_comments WHERE owner = '{_O}' AND table_name = '{_T}' FETCH FIRST 50 ROWS ONLY"),
    Dataset("m5_table_comment", "metadata", "Table comment on T_CUSTOM_COGS.",
            sql=f"SELECT table_name, comments FROM all_tab_comments WHERE owner = '{_O}' AND table_name = '{_T}' FETCH FIRST 5 ROWS ONLY"),
)
packages.PACKAGES["cogs_meta_probe_01"] = COGS_META_PROBE_01


# cogs_scan_01: ONE aggregate pass over T_CUSTOM_COGS (104M rows, no index, no partition: a full scan). Site x month, April 2025 to the newest bill date. SELECT-only, date-bounded, capped.
# Gives COGS and sales per store per month for the P&L and the evidence for the tie-out to the GL ledger "Sales - POS" (ex-GST) and to POS taxable: does SL_V include GST, how far behind is the table.
_TM9 = packages._TM9
COGS_SCAN_01: tuple[Dataset, ...] = (
    Dataset("g1_site_month", "extract", "T_CUSTOM_COGS by site and month, 1 Apr 2025 onward: rows, bill days, sales value, tax, COGS, quantity, first and last bill date.",
            sql=("SELECT TO_CHAR(c.sitecode) AS site_code, TO_CHAR(c.billdate, 'YYYY-MM') AS month, COUNT(*) AS rows_n, COUNT(DISTINCT c.billdate) AS bill_days, "
                 f"{_TM9('SUM(c.custom_sl_v)', 'sl_v')}, {_TM9('SUM(c.taxamt)', 'tax_amt')}, {_TM9('SUM(c.custom_cogs_v)', 'cogs_v')}, {_TM9('SUM(c.custom_sl_q)', 'sl_q')}, "
                 "COUNT(c.taxamt) AS tax_rows, TO_CHAR(MIN(c.billdate), 'YYYY-MM-DD') AS first_bill, TO_CHAR(MAX(c.billdate), 'YYYY-MM-DD') AS last_bill "
                 f"FROM {_O}.{_T} c WHERE c.billdate >= DATE '2025-04-01' GROUP BY c.sitecode, TO_CHAR(c.billdate, 'YYYY-MM') FETCH FIRST 20000 ROWS ONLY"),
            role=""),
)
packages.PACKAGES["cogs_scan_01"] = COGS_SCAN_01
packages.PACKAGE_META["cogs_scan_01"] = {"timeout_s": 900, "attempts": 1}   # a heavy scan is never repeated automatically


# cogs_scan_02: the same single pass, now also splitting each month into its first N days (N = the as-of day of the month) and the rest, so a day-aligned comparison
# (1..7 Oct this year against 1..7 Oct last year) is exact. Every other month is the sum of the two parts. Bounded above by the as-of date.
def cogs_scan_02(as_of_iso: str) -> tuple[Dataset, ...]:
    from datetime import date as _d

    n = _d.fromisoformat(as_of_iso).day
    return (
        Dataset("g1_site_month", "extract", f"T_CUSTOM_COGS by site, month and 'first {n} days' flag, 1 Apr 2025 to the as-of date: rows, bill days, sales value, tax, COGS, quantity, first and last bill date.",
                sql=("SELECT TO_CHAR(c.sitecode) AS site_code, TO_CHAR(c.billdate, 'YYYY-MM') AS month, CASE WHEN TO_NUMBER(TO_CHAR(c.billdate, 'DD')) <= " + str(n) + " THEN 1 ELSE 0 END AS early, "
                     "COUNT(*) AS rows_n, COUNT(DISTINCT c.billdate) AS bill_days, "
                     f"{_TM9('SUM(c.custom_sl_v)', 'sl_v')}, {_TM9('SUM(c.taxamt)', 'tax_amt')}, {_TM9('SUM(c.custom_cogs_v)', 'cogs_v')}, {_TM9('SUM(c.custom_sl_q)', 'sl_q')}, "
                     "COUNT(c.taxamt) AS tax_rows, TO_CHAR(MIN(c.billdate), 'YYYY-MM-DD') AS first_bill, TO_CHAR(MAX(c.billdate), 'YYYY-MM-DD') AS last_bill "
                     f"FROM {_O}.{_T} c WHERE c.billdate >= DATE '2025-04-01' AND c.billdate <= DATE '{as_of_iso}' "
                     "GROUP BY c.sitecode, TO_CHAR(c.billdate, 'YYYY-MM'), CASE WHEN TO_NUMBER(TO_CHAR(c.billdate, 'DD')) <= " + str(n) + " THEN 1 ELSE 0 END FETCH FIRST 40000 ROWS ONLY"),
                role=""),
    )


def configure_cogs(as_of: str) -> None:
    from datetime import date as _d

    try:
        d = _d.fromisoformat(as_of)
    except ValueError:
        raise ValueError("the as-of date must be a real date written YYYY-MM-DD") from None
    if d.isoformat() != as_of:
        raise ValueError("the as-of date must be written YYYY-MM-DD")
    packages.PACKAGES["cogs_scan_02"] = cogs_scan_02(as_of)
    packages.PACKAGE_META["cogs_scan_02"] = {"timeout_s": 900, "attempts": 1, "contract": {"contract": "cogs-scan-1.1", "as_of_cutoff": as_of, "aligned_days": d.day}}   # a heavy scan is never repeated automatically


configure_cogs("2026-10-05")
