"""
ssrk_cube_probe_01: how the MIS cubes (MIS_CUBE$FINREGSITE, MIS_CUBE$FINOTSD, ...) are produced in SSRK. Metadata only: stored programs by name, objects that reference the cube templates,
and the cube template tables' columns / sizes for the finance cubes. Nothing is executed.
"""
from __future__ import annotations

import packages
from packages import Dataset

SSRK_CUBE_PROBE_01: tuple[Dataset, ...] = (
    Dataset("u1_programs", "metadata", "Stored programs in SSRK (procedures, functions, packages) with cube / MIS / register names.",
            sql=("SELECT object_name, object_type, status, last_ddl_time FROM all_objects WHERE owner = 'SSRK' AND object_type IN ('PROCEDURE','FUNCTION','PACKAGE','PACKAGE BODY','TYPE') "
                 "AND (object_name LIKE '%CUBE%' OR object_name LIKE 'MIS%' OR object_name LIKE '%REGISTER%' OR object_name LIKE '%FINREG%' OR object_name LIKE '%OUTSTAND%') "
                 "ORDER BY object_name FETCH FIRST 3000 ROWS ONLY")),
    Dataset("u2_all_programs_count", "metadata", "All stored-program names in SSRK (to see the naming families).",
            sql=("SELECT object_name, object_type FROM all_objects WHERE owner = 'SSRK' AND object_type IN ('PROCEDURE','FUNCTION','PACKAGE') ORDER BY object_name FETCH FIRST 6000 ROWS ONLY")),
    Dataset("u3_dependents", "metadata", "Objects that reference the finance cube templates.",
            sql=("SELECT owner, name, type, referenced_name FROM all_dependencies WHERE referenced_owner = 'SSRK' AND referenced_name IN "
                 "('MIS_CUBE$FINREGSITE','MIS_CUBE$FINREG','MIS_CUBE$FINOTSD','MIS_CUBE$BANKREG','MIS_CUBE$POSBILLSUMM','GLOBAL_CUBE_SITE') ORDER BY referenced_name, name FETCH FIRST 3000 ROWS ONLY")),
    Dataset("u4_cube_columns", "metadata", "Columns of the finance cube templates.",
            sql=("SELECT table_name, column_id, column_name, data_type, data_length, data_precision, data_scale FROM all_tab_columns WHERE owner = 'SSRK' AND table_name IN "
                 "('MIS_CUBE$FINREGSITE','MIS_CUBE$FINOTSD','MIS_CUBE$BANKREG','MIS_CUBE$POSBILLSUMM','MIS_CUBE$BUDGETANALYSIS') ORDER BY table_name, column_id FETCH FIRST 1000 ROWS ONLY")),
    Dataset("u5_cube_tables_elsewhere", "metadata", "Tables named like a cube copy (T$...) in any visible schema.",
            sql=("SELECT owner, object_name, object_type FROM all_objects WHERE object_name LIKE 'T$%' AND object_type IN ('TABLE','VIEW','MATERIALIZED VIEW') ORDER BY owner, object_name FETCH FIRST 3000 ROWS ONLY")),
)
packages.PACKAGES["ssrk_cube_probe_01"] = SSRK_CUBE_PROBE_01
