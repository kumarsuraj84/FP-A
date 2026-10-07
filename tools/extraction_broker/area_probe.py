"""
store_area_probe_01: the store AREA column of the site master (MISRETAIL.T_STORE_OPENING_DATE), with the other columns needed for per-square-foot measures and peer groups.
Master read only (one row per site, no names beyond what the P&L already shows, no e-mail, no coordinates). Registered into the broker's package table from here.
"""
from __future__ import annotations

import packages
from packages import Dataset

_O = packages.OWNER
_DT = packages._DT

STORE_AREA_PROBE_01: tuple[Dataset, ...] = (
    Dataset("a1_site_area", "master", "Site master: area, opening date, last bill date, status, format, grade, city and district.",
            sql=(f"SELECT site_code, area, {_DT('opening_date', 'opening_date')}, {_DT('last_bill_date', 'last_bill_date')}, store_status, store_current_status, st_type, store_type, store_grade, city_name, district "
                 f"FROM {_O}.T_STORE_OPENING_DATE FETCH FIRST 2000 ROWS ONLY")),
    Dataset("a2_area_column", "metadata", "The AREA column: type, precision, comment (units).",
            sql=f"SELECT c.table_name, c.column_name, c.data_type, c.data_precision, c.data_scale, c.num_nulls, c.num_distinct FROM all_tab_columns c WHERE c.owner = '{_O}' AND c.table_name = 'T_STORE_OPENING_DATE' AND c.column_name = 'AREA' FETCH FIRST 5 ROWS ONLY"),
    Dataset("a3_area_comment", "metadata", "Comment on the AREA column, if any.",
            sql=f"SELECT column_name, comments FROM all_col_comments WHERE owner = '{_O}' AND table_name = 'T_STORE_OPENING_DATE' AND column_name = 'AREA' FETCH FIRST 5 ROWS ONLY"),
)
packages.PACKAGES["store_area_probe_01"] = STORE_AREA_PROBE_01
