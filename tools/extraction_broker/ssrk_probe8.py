"""
ssrk_masters_01: SSRK site / ledger masters and one day of consignment-sale HEADERS. Small reads on live production, named columns only, no address / phone / e-mail / tax-number columns.
  ADMSITE (457 rows)  site master: store size (area), start and close dates, POS flag, site type
  FINGL (576), FINGRP (115)  ledger master and ledger groups
  SALCSMAIN (280 k rows, header table)  one day of sales documents with their cost amount, to test whether header-level cost gives COGS by site and day
"""
from __future__ import annotations

import packages
from packages import Dataset

SSRK_MASTERS_01: tuple[Dataset, ...] = (
    Dataset("a1_sites", "master", "Site master: code, name, store size, start / close dates, POS flag, site type, operating unit, status.",
            sql=("SELECT code, name, shrtname, store_size, store_startdt, store_closedt, operationstartdate, ispos, sitetype, admou_code, psite_group_code, ext "
                 "FROM SSRK.ADMSITE ORDER BY code FETCH FIRST 2000 ROWS ONLY")),
    Dataset("a2_ledgers", "master", "Ledger master: code, name, group, type.",
            sql="SELECT glcode, glname, grpcode, type, srctype, costapp, slapp, ext FROM SSRK.FINGL ORDER BY glcode FETCH FIRST 5000 ROWS ONLY"),
    Dataset("a3_groups", "master", "Ledger groups with their parent.",
            sql="SELECT grpcode, grpname, parcode, ext, type, seq FROM SSRK.FINGRP ORDER BY grpcode FETCH FIRST 1000 ROWS ONLY"),
    Dataset("c1_cs_day", "extract", "Consignment-sale headers dated 2026-10-06 (codes, site, amounts, cost, release status).",
            sql=("SELECT cscode, csno, csdate, admsite_code, admsite_code_owner, grsamt, discount, netamt, extaxamt, site_costamt, qty, status, release_status, ycode "
                 "FROM SSRK.SALCSMAIN WHERE csdate >= DATE '2026-10-06' AND csdate < DATE '2026-10-07' ORDER BY cscode FETCH FIRST 20000 ROWS ONLY")),
    Dataset("c2_cs_months", "extract", "Consignment-sale header count, net and cost by month, FY 25-26 and 26-27 (an aggregate over the header table only).",
            sql=("SELECT trunc(csdate, 'MM') AS month, count(*) AS docs, sum(netamt) AS netamt, sum(extaxamt) AS extaxamt, sum(site_costamt) AS site_costamt "
                 "FROM SSRK.SALCSMAIN WHERE csdate >= DATE '2025-04-01' AND csdate < DATE '2026-10-08' GROUP BY trunc(csdate, 'MM') ORDER BY 1 FETCH FIRST 40 ROWS ONLY")),
)
packages.PACKAGES["ssrk_masters_01"] = SSRK_MASTERS_01
