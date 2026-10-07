"""
ssrk_meta_probe_02: SSRK vs MISRETAIL comparison and index / partition plan for the finance tables. Metadata only (ALL_* dictionary views); no data object is read.
"""
from __future__ import annotations

import packages
from packages import Dataset

_FIN = ("'FINPOST','FINCOSTTAG','FINVCHMAIN','FINVCHDET','FINJRNMAIN','FINJRNDET','FINCHQMAIN','FINCHQDET','FINGL','FINGL_SITE','FINSL','FINSL_GL','FINSL_GL_SITE','FINSLOP','FINGLOP','FINGLBUD','FINNAR'")

SSRK_META_PROBE_02: tuple[Dataset, ...] = (
    Dataset("m1_tables", "metadata", "MISRETAIL tables with optimizer statistics.",
            sql="SELECT table_name, num_rows, last_analyzed, partitioned FROM all_tables WHERE owner = 'MISRETAIL' ORDER BY table_name FETCH FIRST 3000 ROWS ONLY"),
    Dataset("m2_views", "metadata", "MISRETAIL views (names and definition length).",
            sql="SELECT view_name, text_length FROM all_views WHERE owner = 'MISRETAIL' ORDER BY view_name FETCH FIRST 3000 ROWS ONLY"),
    Dataset("m3_columns", "metadata", "Columns of every MISRETAIL table and view.",
            sql="SELECT table_name, column_id, column_name, data_type, data_length, data_precision, data_scale, nullable FROM all_tab_columns WHERE owner = 'MISRETAIL' ORDER BY table_name, column_id FETCH FIRST 100000 ROWS ONLY"),
    Dataset("i1_indexes", "metadata", "Indexes on the SSRK finance tables.",
            sql=f"SELECT table_name, index_name, index_type, uniqueness, partitioned, status, num_rows, distinct_keys, last_analyzed FROM all_indexes WHERE owner = 'SSRK' AND table_owner = 'SSRK' AND table_name IN ({_FIN}) ORDER BY table_name, index_name FETCH FIRST 2000 ROWS ONLY"),
    Dataset("i2_index_columns", "metadata", "Indexed columns, in order, for those indexes.",
            sql=f"SELECT table_name, index_name, column_position, column_name, descend FROM all_ind_columns WHERE index_owner = 'SSRK' AND table_owner = 'SSRK' AND table_name IN ({_FIN}) ORDER BY table_name, index_name, column_position FETCH FIRST 5000 ROWS ONLY"),
    Dataset("i3_partitioning", "metadata", "Partitioning scheme of the SSRK finance tables (if any).",
            sql=f"SELECT name, object_type, column_name, column_position FROM all_part_key_columns WHERE owner = 'SSRK' AND name IN ({_FIN}) ORDER BY name, column_position FETCH FIRST 500 ROWS ONLY"),
    Dataset("i4_partitions", "metadata", "Partitions of the SSRK finance tables (name, position, row estimate).",
            sql=f"SELECT table_name, partition_name, partition_position, num_rows, last_analyzed FROM all_tab_partitions WHERE table_owner = 'SSRK' AND table_name IN ({_FIN}) ORDER BY table_name, partition_position FETCH FIRST 5000 ROWS ONLY"),
    Dataset("i5_constraints", "metadata", "Primary and unique keys on the SSRK finance tables.",
            sql=f"SELECT table_name, constraint_name, constraint_type, status FROM all_constraints WHERE owner = 'SSRK' AND constraint_type IN ('P','U') AND table_name IN ({_FIN}) ORDER BY table_name, constraint_name FETCH FIRST 2000 ROWS ONLY"),
)
packages.PACKAGES["ssrk_meta_probe_02"] = SSRK_META_PROBE_02
