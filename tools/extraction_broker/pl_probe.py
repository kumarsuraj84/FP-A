"""
pl_meta_probe_01: what the GL master and its group master look like, so the P&L can be grouped from the books' own hierarchy (ledger -> group -> nature) instead of the finance ledger map
(which has naming gaps). Dictionary views and the GL master only. MISRETAIL only; no register rows are read.
"""
from __future__ import annotations

import packages
from packages import Dataset

_O = packages.OWNER

PL_META_PROBE_01: tuple[Dataset, ...] = (
    Dataset("a1_group_objects", "metadata", "Tables and views whose name suggests a GL group master.",
            sql=f"SELECT object_name, object_type, status FROM all_objects WHERE owner = '{_O}' AND (object_name LIKE 'MAS$FINGR%' OR object_name LIKE '%FINGRP%' OR object_name LIKE '%FINGROUP%' OR object_name LIKE 'MAS$FINGL%') FETCH FIRST 100 ROWS ONLY"),
    Dataset("a2_group_columns", "metadata", "Columns of those objects.",
            sql=f"SELECT table_name, column_name, data_type, column_id FROM all_tab_columns WHERE owner = '{_O}' AND (table_name LIKE 'MAS$FINGR%' OR table_name LIKE '%FINGRP%' OR table_name LIKE '%FINGROUP%') FETCH FIRST 300 ROWS ONLY"),
    Dataset("a3_gl_nature_type", "master", "GL master: how many ledgers per nature, type and whether extinct (counts only).",
            sql=f"SELECT nature, type, extinct, COUNT(*) AS ledgers FROM {_O}.\"MAS$FINGL\" GROUP BY nature, type, extinct FETCH FIRST 200 ROWS ONLY"),
)
packages.PACKAGES["pl_meta_probe_01"] = PL_META_PROBE_01
