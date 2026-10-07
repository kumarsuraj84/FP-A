"""
ssrk_books_probe_01: (1) the small entry-type / cost-centre masters, (2) ONE month (April 2026) of live ledger postings from SSRK.FINPOST, aggregated, so it can be reconciled to the
verified P&L run run_20261007_005 before anything else is built on it.
Postings are limited to profit-and-loss ledgers (FINGL.TYPE E or I), the financial year (YCODE 51), a POSTCODE lower bound (primary-key range, keeps the scan to the year's tail of the table)
and the exact ENTDT month. They are aggregated by owner site, reference site, ledger, entry type and release status so that BOTH candidate site dimensions can be tested against the register.
One query on live production; no narration, party or cheque columns.
"""
from __future__ import annotations

import packages
from packages import Dataset

SSRK_BOOKS_PROBE_01: tuple[Dataset, ...] = (
    Dataset("e1_entry_types", "master", "Entry-type master: code, name, group, prefix.",
            sql="SELECT enttype, entname, entgrpcode, prefix FROM SSRK.FINENTTYPE ORDER BY enttype FETCH FIRST 500 ROWS ONLY"),
    Dataset("e2_entry_groups", "master", "Entry groups.",
            sql="SELECT entgrpcode, entgrpname FROM SSRK.FINENTGRP ORDER BY entgrpcode FETCH FIRST 100 ROWS ONLY"),
    Dataset("e3_cost_centres", "master", "Cost-centre master.",
            sql="SELECT costcode, costname, ext FROM SSRK.FINCOST ORDER BY costcode FETCH FIRST 1000 ROWS ONLY"),
    Dataset("b1_april_2026", "extract", "April 2026 P&L-ledger postings by owner site, reference site, ledger, entry type and release status.",
            sql=("SELECT p.admsite_code_owner AS owner_site, p.ref_admsite_code AS ref_site, p.glcode, p.enttype, p.release_status, "
                 "count(*) AS lines_n, sum(p.damount) AS debit, sum(p.camount) AS credit, min(p.postcode) AS min_postcode "
                 "FROM SSRK.FINPOST p JOIN SSRK.FINGL g ON g.glcode = p.glcode "
                 "WHERE p.ycode = 51 AND p.postcode >= 1131000000 AND p.entdt >= DATE '2026-04-01' AND p.entdt < DATE '2026-05-01' AND g.type IN ('E', 'I') "
                 "GROUP BY p.admsite_code_owner, p.ref_admsite_code, p.glcode, p.enttype, p.release_status FETCH FIRST 300000 ROWS ONLY")),
)
packages.PACKAGES["ssrk_books_probe_01"] = SSRK_BOOKS_PROBE_01


_APR = ("p.ycode = 51 AND p.postcode >= 1131000000 AND p.entdt >= DATE '2026-04-01' AND p.entdt < DATE '2026-05-01' AND g.type IN ('E', 'I')")
SSRK_BOOKS_PROBE_02: tuple[Dataset, ...] = (
    Dataset("t1_tagged_april", "extract", "April 2026 P&L-ledger postings split by FINCOSTTAG: site of the cost tag, ledger, entry type, release status.",
            sql=("SELECT c.admsite_code AS tag_site, c.ref_admsite_code AS tag_ref_site, p.glcode, p.enttype, p.release_status, count(*) AS lines_n, sum(c.damount) AS debit, sum(c.camount) AS credit "
                 "FROM SSRK.FINPOST p JOIN SSRK.FINGL g ON g.glcode = p.glcode JOIN SSRK.FINCOSTTAG c ON c.postcode = p.postcode "
                 f"WHERE {_APR} GROUP BY c.admsite_code, c.ref_admsite_code, p.glcode, p.enttype, p.release_status FETCH FIRST 300000 ROWS ONLY")),
    Dataset("t2_untagged_april", "extract", "April 2026 P&L-ledger postings with NO cost tag, by owner site and reference site.",
            sql=("SELECT p.admsite_code_owner AS owner_site, p.ref_admsite_code AS ref_site, p.glcode, p.enttype, p.release_status, count(*) AS lines_n, sum(p.damount) AS debit, sum(p.camount) AS credit "
                 "FROM SSRK.FINPOST p JOIN SSRK.FINGL g ON g.glcode = p.glcode "
                 f"WHERE {_APR} AND NOT EXISTS (SELECT 1 FROM SSRK.FINCOSTTAG c WHERE c.postcode = p.postcode) "
                 "GROUP BY p.admsite_code_owner, p.ref_admsite_code, p.glcode, p.enttype, p.release_status FETCH FIRST 300000 ROWS ONLY")),
)
packages.PACKAGES["ssrk_books_probe_02"] = SSRK_BOOKS_PROBE_02


def _month(name: str, y: int, m: int, lower: int):
    nxt = (y + (m == 12), m % 12 + 1)
    cond = (f"p.ycode = 51 AND p.postcode >= {lower} AND p.entdt >= DATE '{y}-{m:02d}-01' AND p.entdt < DATE '{nxt[0]}-{nxt[1]:02d}-01' AND g.type IN ('E', 'I')")
    return Dataset(name, "extract", f"{y}-{m:02d} P&L-ledger postings split by FINCOSTTAG: cost-tag site, ledger, entry type, release status.",
                   sql=("SELECT c.admsite_code AS tag_site, p.glcode, p.enttype, p.release_status, count(*) AS lines_n, sum(c.damount) AS debit, sum(c.camount) AS credit, min(p.postcode) AS min_postcode "
                        "FROM SSRK.FINPOST p JOIN SSRK.FINGL g ON g.glcode = p.glcode JOIN SSRK.FINCOSTTAG c ON c.postcode = p.postcode "
                        f"WHERE {cond} GROUP BY c.admsite_code, p.glcode, p.enttype, p.release_status FETCH FIRST 300000 ROWS ONLY"))


SSRK_BOOKS_FY27: tuple[Dataset, ...] = (
    _month("m_2026_05", 2026, 5, 1131500000), _month("m_2026_06", 2026, 6, 1131950000), _month("m_2026_07", 2026, 7, 1132400000),
    _month("m_2026_08", 2026, 8, 1132650000), _month("m_2026_09", 2026, 9, 1133100000), _month("m_2026_10", 2026, 10, 1133600000),
)
packages.PACKAGES["ssrk_books_fy27_01"] = SSRK_BOOKS_FY27
