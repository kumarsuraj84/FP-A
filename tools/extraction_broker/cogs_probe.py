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
