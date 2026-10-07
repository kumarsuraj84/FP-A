"""
ssrk_meta_probe_01: SSRK source DISCOVERY, metadata only (SSRK is live production). Dictionary views ALL_TABLES / ALL_VIEWS / ALL_TAB_COMMENTS / ALL_TAB_COLUMNS,
restricted to owner SSRK. Row counts come from optimizer statistics (never COUNT(*)); no data object is read. Each query is capped; run one at a time by the broker.
"""
from __future__ import annotations

import packages
from packages import Dataset

SSRK_META_PROBE_01: tuple[Dataset, ...] = (
    Dataset("s1_tables", "metadata", "SSRK tables with optimizer statistics (row estimate, last analysed).",
            sql="SELECT table_name, num_rows, last_analyzed, partitioned, temporary, iot_type FROM all_tables WHERE owner = 'SSRK' ORDER BY table_name FETCH FIRST 6000 ROWS ONLY"),
    Dataset("s2_views", "metadata", "SSRK views (names and definition length only).",
            sql="SELECT view_name, text_length FROM all_views WHERE owner = 'SSRK' ORDER BY view_name FETCH FIRST 6000 ROWS ONLY"),
    Dataset("s3_comments", "metadata", "Table and view comments written by the application owners.",
            sql="SELECT table_name, table_type, comments FROM all_tab_comments WHERE owner = 'SSRK' AND comments IS NOT NULL ORDER BY table_name FETCH FIRST 20000 ROWS ONLY"),
    Dataset("s4_columns", "metadata", "Columns of every SSRK table and view (names, types, nullability).",
            sql="SELECT table_name, column_id, column_name, data_type, data_length, data_precision, data_scale, nullable FROM all_tab_columns WHERE owner = 'SSRK' ORDER BY table_name, column_id FETCH FIRST 300000 ROWS ONLY"),
)
packages.PACKAGES["ssrk_meta_probe_01"] = SSRK_META_PROBE_01
