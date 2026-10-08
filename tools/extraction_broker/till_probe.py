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
