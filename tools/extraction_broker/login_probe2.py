"""
misretail_visibility_probe_01: which MISRETAIL objects the CURRENT read-only login can see, by object type, and whether the finance registers and cubes used by the existing pipelines are visible. Metadata only.
"""
from __future__ import annotations

import packages
from packages import Dataset

MISRETAIL_VISIBILITY_PROBE_01: tuple[Dataset, ...] = (
    Dataset("v1_types", "metadata", "MISRETAIL objects visible to the login, by type.",
            sql="SELECT object_type, status, count(*) AS objects FROM all_objects WHERE owner = 'MISRETAIL' GROUP BY object_type, status ORDER BY object_type FETCH FIRST 200 ROWS ONLY"),
    Dataset("v2_finance_objects", "metadata", "MISRETAIL objects whose name looks like a finance register or cube.",
            sql="SELECT object_name, object_type, status, last_ddl_time FROM all_objects WHERE owner = 'MISRETAIL' AND (object_name LIKE 'T$%' OR object_name LIKE '%FIN%' OR object_name LIKE '%OUTSTAND%' OR object_name LIKE '%CUBE%' OR object_name LIKE '%LEDGER%') ORDER BY object_name FETCH FIRST 2000 ROWS ONLY"),
    Dataset("v3_synonyms", "metadata", "Synonyms visible in the MISRETAIL schema.",
            sql="SELECT synonym_name, table_owner, table_name FROM all_synonyms WHERE owner = 'MISRETAIL' ORDER BY synonym_name FETCH FIRST 2000 ROWS ONLY"),
)
packages.PACKAGES["misretail_visibility_probe_01"] = MISRETAIL_VISIBILITY_PROBE_01
