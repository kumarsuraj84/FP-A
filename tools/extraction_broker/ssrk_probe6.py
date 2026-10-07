"""
ssrk_day_sample_01: ONE day (2026-10-06) of SSRK finance postings, a bounded sample on live production.
Access path: FINPOST.POSTCODE >= 1133929721 (primary-key range scan, ~55 k postings; the grid probe showed the key tracks the entry date but back-dated entries exist, so the real predicate is the ENTDT window).
No narration, cheque or party-name columns are read. FINCOSTTAG is read through its POSTCODE index by joining to the same postings. Row caps apply to every dataset; one query at a time.
"""
from __future__ import annotations

import packages
from packages import Dataset

_W = "p.postcode >= 1133929721 AND p.entdt >= DATE '2026-10-06' AND p.entdt < DATE '2026-10-07'"

SSRK_DAY_SAMPLE_01: tuple[Dataset, ...] = (
    Dataset("d1_postings", "extract", "FINPOST postings dated 2026-10-06 (codes, dates, amounts, release status and sites only).",
            sql=("SELECT p.postcode, p.entcode, p.entno, p.entdt, p.enttype, p.docno, p.docdt, p.duedt, p.glcode, p.slcode, p.damount, p.camount, p.adjamt, p.ycode, "
                 "p.release_status, p.admsite_code_owner, p.ref_admsite_code, p.admou_code "
                 f"FROM SSRK.FINPOST p WHERE {_W} ORDER BY p.postcode FETCH FIRST 20000 ROWS ONLY")),
    Dataset("d2_totals", "extract", "Postings, debit and credit totals for the same window (a balance check).",
            sql=("SELECT count(*) AS postings, sum(p.damount) AS debit, sum(p.camount) AS credit, min(p.postcode) AS min_postcode, max(p.postcode) AS max_postcode "
                 f"FROM SSRK.FINPOST p WHERE {_W} FETCH FIRST 1 ROWS ONLY")),
    Dataset("d3_by_type", "extract", "The same window by entry type and release status.",
            sql=("SELECT p.enttype, p.release_status, count(*) AS postings, sum(p.damount) AS debit, sum(p.camount) AS credit "
                 f"FROM SSRK.FINPOST p WHERE {_W} GROUP BY p.enttype, p.release_status ORDER BY p.enttype, p.release_status FETCH FIRST 500 ROWS ONLY")),
    Dataset("d4_costtag", "extract", "FINCOSTTAG rows of those postings (cost-centre split).",
            sql=("SELECT c.postcode, c.costcode, c.glcode, c.slcode, c.damount, c.camount, c.admsite_code, c.ref_admsite_code "
                 f"FROM SSRK.FINCOSTTAG c JOIN SSRK.FINPOST p ON p.postcode = c.postcode WHERE {_W} ORDER BY c.postcode FETCH FIRST 20000 ROWS ONLY")),
)
packages.PACKAGES["ssrk_day_sample_01"] = SSRK_DAY_SAMPLE_01
