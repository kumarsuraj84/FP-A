"""
ssrk_logic_probe_01: where do the reporting tables come from? Metadata only (ALL_DEPENDENCIES, ALL_OBJECTS): stored programs that reference the COGS / P&L reporting tables, and
programs whose name looks finance-related. Program TEXT is a second, separate step. Nothing is executed and no data object is read.
"""
from __future__ import annotations

import packages
from packages import Dataset

SSRK_LOGIC_PROBE_01: tuple[Dataset, ...] = (
    Dataset("g1_dependents", "metadata", "Objects that reference the COGS / P&L reporting tables or the POS and consignment-sale detail tables.",
            sql=("SELECT owner, name, type, referenced_owner, referenced_name FROM all_dependencies WHERE referenced_name IN "
                 "('T_CUSTOM_COGS','T_FINANCE_P_AND_L_STORE_MAP','T_FINANCE_P_AND_L_BUDGET','T_STORE_OPENING_DATE','SALCSDET','SALCSMAIN','PSITE_POSBILL','FINPOST') "
                 "ORDER BY referenced_name, owner, name FETCH FIRST 5000 ROWS ONLY")),
    Dataset("g2_programs", "metadata", "Stored programs (procedures, functions, packages, triggers) with finance-looking names.",
            sql=("SELECT owner, object_name, object_type, status, last_ddl_time FROM all_objects WHERE owner IN ('SSRK','MISRETAIL') "
                 "AND object_type IN ('PROCEDURE','FUNCTION','PACKAGE','PACKAGE BODY','VIEW','MATERIALIZED VIEW') "
                 "AND (object_name LIKE '%COGS%' OR object_name LIKE '%P_AND_L%' OR object_name LIKE '%PNL%' OR object_name LIKE '%PROFIT%' OR object_name LIKE '%FINANCE%' OR object_name LIKE '%STORE_OPENING%') "
                 "ORDER BY owner, object_name FETCH FIRST 2000 ROWS ONLY")),
)
packages.PACKAGES["ssrk_logic_probe_01"] = SSRK_LOGIC_PROBE_01
