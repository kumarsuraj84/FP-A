"""
cash_live_probe_01: Cash from the live SSRK tables, discovery step. The 34 bank / cash ledgers of the verified Cash run (run_20261005_013) are looked up in the live ledger master and the
opening-balance table, and the till ledger (CASH IN HAND (STORES), 1114925459) is aggregated by site and day for FY 26-27 up to 04 Oct 2026, in two ways (cost-tag site and owner site),
so each can be compared with the verified store-till figures. Read only; aggregates and masters; no narration, cheque or party columns.
"""
from __future__ import annotations

import packages
from packages import Dataset

_GLS = "131, 135, 176, 241, 254, 1000000007, 1000000009, 1000000373, 1000000569, 1000000773, 1000000815, 1114332438, 1114925451, 1114925454, 1114925455, 1114925456, 1114925457, 1114925458, 1114925459, 1114925460, 1114925491, 1114925651, 1114925711, 1114925731, 1114926111, 1114926112, 1114926113, 1114926211, 1114927274, 1114927514, 1114927634, 1114927694, 1114927714, 1114927994"
_TILL = ("p.ycode = 51 AND p.postcode >= 1131000000 AND p.entdt >= DATE '2026-04-01' AND p.entdt < DATE '2026-10-05' AND p.glcode = 1114925459")

CASH_LIVE_PROBE_01: tuple[Dataset, ...] = (
    Dataset("a1_ledgers", "master", "Live ledger master and group for the 34 bank / cash ledgers of the verified run.",
            sql=("SELECT g.glcode, g.glname, g.type, g.srctype, g.grpcode, p.grpname, g.ext, g.costapp, g.slapp FROM SSRK.FINGL g LEFT JOIN SSRK.FINGRP p ON p.grpcode = g.grpcode "
                 f"WHERE g.glcode IN ({_GLS}) ORDER BY g.glcode FETCH FIRST 200 ROWS ONLY")),
    Dataset("a2_opening", "master", "Opening balances of those ledgers (FINGLOP) for the current and previous financial year.",
            sql=(f"SELECT o.glcode, o.ycode, o.opdamt, o.opcamt, o.admou_code FROM SSRK.FINGLOP o WHERE o.glcode IN ({_GLS}) AND o.ycode IN (50, 51) ORDER BY o.glcode, o.ycode FETCH FIRST 500 ROWS ONLY")),
    Dataset("a3_groups", "master", "Ledger groups (to see which are bank and cash).", sql="SELECT grpcode, grpname, parcode FROM SSRK.FINGRP ORDER BY grpcode FETCH FIRST 500 ROWS ONLY"),
    Dataset("a4_till_costtag_site", "extract", "Till ledger by cost-tag site and day, FY26-27 to 04 Oct, with release status.",
            sql=("SELECT c.admsite_code AS site_code, TRUNC(p.entdt) AS d, p.release_status AS status, count(*) AS lines_n, sum(c.damount) AS debit, sum(c.camount) AS credit "
                 f"FROM SSRK.FINPOST p JOIN SSRK.FINCOSTTAG c ON c.postcode = p.postcode WHERE {_TILL} GROUP BY c.admsite_code, TRUNC(p.entdt), p.release_status FETCH FIRST 100000 ROWS ONLY")),
    Dataset("a5_till_owner_site", "extract", "Till ledger by owner site and day, FY26-27 to 04 Oct, with release status.",
            sql=("SELECT p.admsite_code_owner AS site_code, TRUNC(p.entdt) AS d, p.release_status AS status, count(*) AS lines_n, sum(p.damount) AS debit, sum(p.camount) AS credit "
                 f"FROM SSRK.FINPOST p WHERE {_TILL} GROUP BY p.admsite_code_owner, TRUNC(p.entdt), p.release_status FETCH FIRST 100000 ROWS ONLY")),
)
packages.PACKAGES["cash_live_probe_01"] = CASH_LIVE_PROBE_01


CASH_LATE_PROBE_01: tuple[Dataset, ...] = (
    Dataset("l1_late_prior_year", "extract", "Postings on AXIS BANK-8218 (CKSPL) dated in FY25-26 but created on or after 05 Oct 2026 (what moved the prior-year closing).",
            sql=("SELECT p.postcode, p.entcode, p.entno, p.entdt, p.enttype, p.damount, p.camount, p.release_status, p.time AS created_time, p.release_time "
                 "FROM SSRK.FINPOST p WHERE p.entdt >= DATE '2025-04-01' AND p.entdt <= DATE '2026-03-31' AND p.glcode = 1114927514 AND p.ycode = 50 AND p.time >= DATE '2026-10-04' ORDER BY p.postcode FETCH FIRST 200 ROWS ONLY")),
)
packages.PACKAGES["cash_late_probe_01"] = CASH_LATE_PROBE_01


CASH_LATE_PROBE_02: tuple[Dataset, ...] = (
    Dataset("l2_late_by_created_month", "extract", "AXIS BANK-8218 (CKSPL), FY25-26 postings by the month they were CREATED: lines, debit, credit.",
            sql=("SELECT TRUNC(p.time, 'MM') AS created_month, p.release_status, count(*) AS lines_n, sum(p.damount) AS debit, sum(p.camount) AS credit, min(p.entdt) AS first_entry_date, max(p.entdt) AS last_entry_date "
                 "FROM SSRK.FINPOST p WHERE p.entdt >= DATE '2025-04-01' AND p.entdt <= DATE '2026-03-31' AND p.glcode = 1114927514 AND p.ycode = 50 GROUP BY TRUNC(p.time, 'MM'), p.release_status ORDER BY 1 FETCH FIRST 100 ROWS ONLY")),
)
packages.PACKAGES["cash_late_probe_02"] = CASH_LATE_PROBE_02
