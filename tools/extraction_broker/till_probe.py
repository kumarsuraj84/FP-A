"""
till_probe_01: where could STORE TILL CASH come from in the live SSRK tables? Step 1, cheap reads only: the payment-mode master, the settlement detail by type (small tables joined on the settlement date),
the payout table by mode, and the indexes of the 79 M-row bill-payment table (to decide whether it can be read by date at all). Every table is SSRK-qualified. No bill-level data.
"""
from __future__ import annotations

import packages
from packages import Dataset

_FY = "s.stlmfor >= DATE '2026-04-01' AND s.stlmfor < DATE '2026-10-05'"

TILL_PROBE_01: tuple[Dataset, ...] = (
    Dataset("m1_modes", "master", "Payment-mode master.", sql="SELECT code, name, shortcode, type, issettlementapplicable, isextinct FROM SSRK.PSITE_MOP ORDER BY code FETCH FIRST 100 ROWS ONLY"),
    Dataset("m2_stlm_params_oth", "master", "Settlement parameter master (other).", sql="SELECT code, name, display_order, type, isextinct FROM SSRK.PSITE_STLM_PARAM_OTH ORDER BY code FETCH FIRST 100 ROWS ONLY"),
    Dataset("s1_stlm_detail_by_type", "extract", "Day-end settlement detail by type, sub-type and mode: lines and amount, FY 26-27 to 04 Oct 2026.",
            sql=("SELECT d.type, d.subtype, d.psite_mop_code, count(*) AS lines_n, count(DISTINCT s.admsite_code) AS sites, sum(d.amount) AS amount "
                 f"FROM SSRK.PSITE_POSSTLMDETAIL d JOIN SSRK.PSITE_POSSTLM s ON s.code = d.psite_posstlm_code WHERE {_FY} GROUP BY d.type, d.subtype, d.psite_mop_code ORDER BY 1, 2, 3 FETCH FIRST 500 ROWS ONLY")),
    Dataset("s2_stlm_status", "extract", "Settlements by status, FY 26-27 to 04 Oct: count, sites, days.",
            sql=(f"SELECT s.status, count(*) AS settlements, count(DISTINCT s.admsite_code) AS sites, min(s.stlmfor) AS first_day, max(s.stlmfor) AS last_day FROM SSRK.PSITE_POSSTLM s WHERE {_FY} GROUP BY s.status FETCH FIRST 50 ROWS ONLY")),
    Dataset("s3_payout_by_mode", "extract", "Payments through the till (PSITE_POSPAYMOP) by source and mode, FY 26-27 to 04 Oct.",
            sql=("SELECT p.source, p.moptype, p.mopshortcode, count(*) AS lines_n, count(DISTINCT p.admsite_code) AS sites, sum(p.amount) AS amount FROM SSRK.PSITE_POSPAYMOP p "
                 "WHERE p.entrydate >= DATE '2026-04-01' AND p.entrydate < DATE '2026-10-05' GROUP BY p.source, p.moptype, p.mopshortcode ORDER BY 1, 2, 3 FETCH FIRST 200 ROWS ONLY")),
    Dataset("i1_billmop_indexes", "metadata", "Indexes of PSITE_POSBILLMOP and PSITE_POSBILL.",
            sql=("SELECT i.table_name, i.index_name, i.uniqueness, c.column_position, c.column_name FROM all_indexes i JOIN all_ind_columns c ON c.index_owner = i.owner AND c.index_name = i.index_name "
                 "WHERE i.owner = 'SSRK' AND i.table_name IN ('PSITE_POSBILLMOP', 'PSITE_POSBILL', 'PSITE_POSPAYMOP', 'PSITE_POSSTLM') ORDER BY i.table_name, i.index_name, c.column_position FETCH FIRST 300 ROWS ONLY")),
)
packages.PACKAGES["till_probe_01"] = TILL_PROBE_01


_J = "FROM SSRK.PSITE_POSSTLMDETAIL d JOIN SSRK.PSITE_POSSTLM s ON s.code = d.psite_posstlm_code JOIN SSRK.ADMSITE a ON a.code = s.admsite_code"
TILL_PROBE_02: tuple[Dataset, ...] = (
    Dataset("t1_store_fytd", "extract", "Cash summary per store and sub-type: FY26-27 to 04 Oct and month-to-date (Oct), lines and amount, all settlement statuses.",
            sql=("SELECT s.admsite_code AS site_code, a.shrtname AS store_name, d.subtype, count(*) AS lines_n, sum(d.amount) AS fytd_amount, "
                 "sum(CASE WHEN s.stlmfor >= DATE '2026-10-01' THEN d.amount ELSE 0 END) AS mtd_amount, max(s.stlmfor) AS last_day "
                 f"{_J} WHERE d.type = 'CashSummary' AND d.psite_mop_code = 112 AND s.stlmfor >= DATE '2026-04-01' AND s.stlmfor < DATE '2026-10-05' "
                 "GROUP BY s.admsite_code, a.shrtname, d.subtype FETCH FIRST 5000 ROWS ONLY")),
    Dataset("t2_store_last_days", "extract", "Cash summary lines of the last two days (03 and 04 Oct) per store, with the settlement status.",
            sql=("SELECT s.admsite_code AS site_code, s.stlmfor AS day, s.status, d.subtype, d.particulars, d.amount "
                 f"{_J} WHERE d.type = 'CashSummary' AND d.psite_mop_code = 112 AND s.stlmfor >= DATE '2026-10-03' AND s.stlmfor < DATE '2026-10-05' ORDER BY s.admsite_code, s.stlmfor FETCH FIRST 5000 ROWS ONLY")),
    Dataset("t3_ptc_heads", "extract", "What the 'PTC Head' payout lines are: particulars with lines and amount, FY26-27 to 04 Oct.",
            sql=("SELECT d.particulars, count(*) AS lines_n, sum(d.amount) AS amount "
                 f"{_J} WHERE d.type = 'CashSummary' AND d.subtype = 'PTC Head' AND s.stlmfor >= DATE '2026-04-01' AND s.stlmfor < DATE '2026-10-05' GROUP BY d.particulars ORDER BY 3 FETCH FIRST 300 ROWS ONLY")),
)
packages.PACKAGES["till_probe_02"] = TILL_PROBE_02


def _one_store(site: int) -> str:
    return ("SELECT m.admsite_code AS site_code, m.moptype, m.mopshortcode, count(*) AS lines_n, sum(m.baseamt) AS baseamt, sum(m.basetender) AS basetender, sum(m.adjbaseamt) AS adjbaseamt, "
            "sum(CASE WHEN m.billdate >= DATE '2026-10-01' THEN m.baseamt ELSE 0 END) AS mtd_baseamt "
            f"FROM SSRK.PSITE_POSBILLMOP m WHERE m.admsite_code = {site} AND m.billdate >= DATE '2026-04-01' AND m.billdate < DATE '2026-10-05' GROUP BY m.admsite_code, m.moptype, m.mopshortcode FETCH FIRST 100 ROWS ONLY")


TILL_PROBE_03: tuple[Dataset, ...] = (
    Dataset("b1_store_43", "extract", "Bill-level payment lines of ONE store (site 43), FY26-27 to 04 Oct, by mode type: the cash tender against the settlement's POS Bill figure.", sql=_one_store(43)),
)
packages.PACKAGES["till_probe_03"] = TILL_PROBE_03
