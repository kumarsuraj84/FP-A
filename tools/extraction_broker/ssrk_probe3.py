"""
ssrk_range_probe_01: SSRK finance range discovery, step A. Two tiny reads on live production: the financial-year master (83 rows) and the MIN / MAX of the FINPOST primary key
(answered from the PK index, no table scan). No postings are read. Step B (POSTCODE to date mapping) is built from this result.
"""
from __future__ import annotations

import packages
from packages import Dataset

SSRK_RANGE_PROBE_01: tuple[Dataset, ...] = (
    Dataset("y1_years", "master", "Financial-year master: code, start, end, name.",
            sql="SELECT ycode, dtfr, dtto, yname FROM SSRK.ADMYEAR ORDER BY dtfr FETCH FIRST 200 ROWS ONLY"),
    Dataset("p1_postcode_range", "sample", "Lowest and highest FINPOST primary key (index-only).",
            sql="SELECT min(postcode) AS min_postcode, max(postcode) AS max_postcode FROM SSRK.FINPOST FETCH FIRST 1 ROWS ONLY"),
)
packages.PACKAGES["ssrk_range_probe_01"] = SSRK_RANGE_PROBE_01
