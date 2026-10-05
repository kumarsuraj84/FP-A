# Sales Phase 0: probe log

All probes ran through the Inventory Automation broker, MISRETAIL only, sequentially, within the broker guard. Parameters are literal dates inside each SQL text (no bind variables). Durations are the broker's reported seconds (the manifest does not store them; a short query reports about 6 s because of 2 s polling plus job start). The guard hash is the query hash stored in the run manifest. Results are in the git-ignored inbox and are not committed.

Service coordination: probes 03a to 03e ran between 16:18 and 16:28 IST, probes 04a to 04c between 17:55 and 18:10 IST (04b and 04c read only the MISRETAIL POS cube), and probes 05a to 05e between 18:30 and 18:52 IST (they read the POS summary instance tables directly; each ran only after the other session confirmed its own run had finished), after the finance session's `run_20261005_022` had completed (14 of 14 datasets) and with no `broker.py` process active. No other run started during that window (the newest run folders were this work's own). Probes 01 and 02 overlapped with the finance session's runs 020 and 021, which failed with timeouts; causation is not established.

## sales_probe_01 (run_20261005_018, created 2026-10-05T10:03:13+00:00)

| dataset | kind | status | rows | cap | seconds | guard hash |
|---|---|---|---|---|---|---|
| s1_objects | metadata | ok | 16 | 500 | 6.1 | d1c5d7e050 |
| s2_calendar_candidates | metadata | ok | 28 | 2000 | 6.1 | 33b4a239b0 |
| s3_table_stats | metadata | ok | 24 | 500 | 6.1 | ab92b4e260 |
| s4_columns | metadata | ok | 936 | 20000 | 10.1 | b14249df76 |
| s5_indexes | metadata | ok | 0 | 2000 | 6.1 | 580d491aa0 |
| s6_index_columns | metadata | ok | 0 | 5000 | 6.1 | 25afc17819 |
| s7_view_dependencies | metadata | ok | 31 | 5000 | 6.1 | c208a5196d |
| s8_procedures | metadata | ok | 6 | 500 | 6.1 | 89d8463683 |
| s9_procedure_source | metadata | ok | 116 | 20000 | 6.1 | 42e692b4f2 |
| s10_table_comments | metadata | ok | 0 | 500 | 6.1 | 0785579001 |
| s11_column_comments | metadata | ok | 0 | 5000 | 6.1 | ed8a4b7e22 |

Notes:
- `s5_indexes`: 0 rows: no index visible on the candidate tables (or not visible to the extraction login).
- `s10_table_comments`: 0 rows: no table comments.
- `s11_column_comments`: 0 rows: no column comments.

SQL:

### s1_objects

```sql
SELECT owner, object_name, object_type, status, TO_CHAR(created, 'YYYY-MM-DD') AS created, TO_CHAR(last_ddl_time, 'YYYY-MM-DD') AS last_ddl FROM all_objects WHERE owner = 'MISRETAIL' AND object_name IN ('T_SALE_COMPARE_ABV_ASP', 'V_SALE_COMPARE_ABV_ASP', 'T_SALE_COMPARE_ASP_ABV', 'V_SALE_COMPARE_ASP_ABV', 'T_SALE_COMPARE_DAY_WISE', 'T_SALE_COMPARE_CONSOLIDATED', 'T_SALE_COMPARE_BILL_CUT', 'V_SALE_COMPARE_BILL_CUT', 'T_STORE_WISE_DAY_SALE', 'V_DAYWISE_BILLCUT', 'V_CFO_DASHBOARD_SL_V', 'CUBE$POSBILLSUMM', 'T_STORE_OPENING_DATE', 'T_STORE_SALE_TARGET', 'T_CUSTOM_COGS', 'ITEM_MV', 'T_FINANCIAL_YEAR_NEW') FETCH FIRST 500 ROWS ONLY
```

### s2_calendar_candidates

```sql
SELECT owner, object_name, object_type, TO_CHAR(created, 'YYYY-MM-DD') AS created, TO_CHAR(last_ddl_time, 'YYYY-MM-DD') AS last_ddl FROM all_objects WHERE owner = 'MISRETAIL' AND object_type IN ('TABLE', 'VIEW', 'MATERIALIZED VIEW') AND REGEXP_LIKE(object_name, '(FEST|HOLI|DIWALI|CALEND|SHIFT|DATE_?MAP|LY_?DATE|EVENT|FINANCIAL_YEAR|DAY_?MAP|COMPARE_?DATE|NEW_?BILLDATE|DAY_?TYPE|WEEK_?MAP)', 'i') FETCH FIRST 2000 ROWS ONLY
```

### s3_table_stats

```sql
SELECT owner, table_name, num_rows, TO_CHAR(last_analyzed, 'YYYY-MM-DD') AS last_analyzed, partitioned FROM all_tables WHERE owner = 'MISRETAIL' AND (table_name IN ('T_SALE_COMPARE_ABV_ASP', 'V_SALE_COMPARE_ABV_ASP', 'T_SALE_COMPARE_ASP_ABV', 'V_SALE_COMPARE_ASP_ABV', 'T_SALE_COMPARE_DAY_WISE', 'T_SALE_COMPARE_CONSOLIDATED', 'T_SALE_COMPARE_BILL_CUT', 'V_SALE_COMPARE_BILL_CUT', 'T_STORE_WISE_DAY_SALE', 'V_DAYWISE_BILLCUT', 'V_CFO_DASHBOARD_SL_V', 'CUBE$POSBILLSUMM', 'T_STORE_OPENING_DATE', 'T_STORE_SALE_TARGET', 'T_CUSTOM_COGS', 'ITEM_MV', 'T_FINANCIAL_YEAR_NEW') OR table_name IN (SELECT object_name FROM all_objects WHERE owner = 'MISRETAIL' AND object_type IN ('TABLE', 'VIEW', 'MATERIALIZED VIEW') AND REGEXP_LIKE(object_name, '(FEST|HOLI|DIWALI|CALEND|SHIFT|DATE_?MAP|LY_?DATE|EVENT|FINANCIAL_YEAR|DAY_?MAP|COMPARE_?DATE|NEW_?BILLDATE|DAY_?TYPE|WEEK_?MAP)', 'i'))) FETCH FIRST 500 ROWS ONLY
```

### s4_columns

```sql
SELECT owner, table_name, column_name, data_type, data_length, nullable, column_id FROM all_tab_columns WHERE owner = 'MISRETAIL' AND (table_name IN ('T_SALE_COMPARE_ABV_ASP', 'V_SALE_COMPARE_ABV_ASP', 'T_SALE_COMPARE_ASP_ABV', 'V_SALE_COMPARE_ASP_ABV', 'T_SALE_COMPARE_DAY_WISE', 'T_SALE_COMPARE_CONSOLIDATED', 'T_SALE_COMPARE_BILL_CUT', 'V_SALE_COMPARE_BILL_CUT', 'T_STORE_WISE_DAY_SALE', 'V_DAYWISE_BILLCUT', 'V_CFO_DASHBOARD_SL_V', 'CUBE$POSBILLSUMM', 'T_STORE_OPENING_DATE', 'T_STORE_SALE_TARGET', 'T_CUSTOM_COGS', 'ITEM_MV', 'T_FINANCIAL_YEAR_NEW') OR table_name IN (SELECT object_name FROM all_objects WHERE owner = 'MISRETAIL' AND object_type IN ('TABLE', 'VIEW', 'MATERIALIZED VIEW') AND REGEXP_LIKE(object_name, '(FEST|HOLI|DIWALI|CALEND|SHIFT|DATE_?MAP|LY_?DATE|EVENT|FINANCIAL_YEAR|DAY_?MAP|COMPARE_?DATE|NEW_?BILLDATE|DAY_?TYPE|WEEK_?MAP)', 'i'))) FETCH FIRST 20000 ROWS ONLY
```

### s5_indexes

```sql
SELECT owner, index_name, table_name, uniqueness, status, num_rows, TO_CHAR(last_analyzed, 'YYYY-MM-DD') AS last_analyzed FROM all_indexes WHERE table_owner = 'MISRETAIL' AND (table_name IN ('T_SALE_COMPARE_ABV_ASP', 'V_SALE_COMPARE_ABV_ASP', 'T_SALE_COMPARE_ASP_ABV', 'V_SALE_COMPARE_ASP_ABV', 'T_SALE_COMPARE_DAY_WISE', 'T_SALE_COMPARE_CONSOLIDATED', 'T_SALE_COMPARE_BILL_CUT', 'V_SALE_COMPARE_BILL_CUT', 'T_STORE_WISE_DAY_SALE', 'V_DAYWISE_BILLCUT', 'V_CFO_DASHBOARD_SL_V', 'CUBE$POSBILLSUMM', 'T_STORE_OPENING_DATE', 'T_STORE_SALE_TARGET', 'T_CUSTOM_COGS', 'ITEM_MV', 'T_FINANCIAL_YEAR_NEW') OR table_name IN (SELECT object_name FROM all_objects WHERE owner = 'MISRETAIL' AND object_type IN ('TABLE', 'VIEW', 'MATERIALIZED VIEW') AND REGEXP_LIKE(object_name, '(FEST|HOLI|DIWALI|CALEND|SHIFT|DATE_?MAP|LY_?DATE|EVENT|FINANCIAL_YEAR|DAY_?MAP|COMPARE_?DATE|NEW_?BILLDATE|DAY_?TYPE|WEEK_?MAP)', 'i'))) FETCH FIRST 2000 ROWS ONLY
```

### s6_index_columns

```sql
SELECT index_name, table_name, column_name, column_position FROM all_ind_columns WHERE table_owner = 'MISRETAIL' AND (table_name IN ('T_SALE_COMPARE_ABV_ASP', 'V_SALE_COMPARE_ABV_ASP', 'T_SALE_COMPARE_ASP_ABV', 'V_SALE_COMPARE_ASP_ABV', 'T_SALE_COMPARE_DAY_WISE', 'T_SALE_COMPARE_CONSOLIDATED', 'T_SALE_COMPARE_BILL_CUT', 'V_SALE_COMPARE_BILL_CUT', 'T_STORE_WISE_DAY_SALE', 'V_DAYWISE_BILLCUT', 'V_CFO_DASHBOARD_SL_V', 'CUBE$POSBILLSUMM', 'T_STORE_OPENING_DATE', 'T_STORE_SALE_TARGET', 'T_CUSTOM_COGS', 'ITEM_MV', 'T_FINANCIAL_YEAR_NEW') OR table_name IN (SELECT object_name FROM all_objects WHERE owner = 'MISRETAIL' AND object_type IN ('TABLE', 'VIEW', 'MATERIALIZED VIEW') AND REGEXP_LIKE(object_name, '(FEST|HOLI|DIWALI|CALEND|SHIFT|DATE_?MAP|LY_?DATE|EVENT|FINANCIAL_YEAR|DAY_?MAP|COMPARE_?DATE|NEW_?BILLDATE|DAY_?TYPE|WEEK_?MAP)', 'i'))) FETCH FIRST 5000 ROWS ONLY
```

### s7_view_dependencies

```sql
SELECT name, type, referenced_owner, referenced_name, referenced_type FROM all_dependencies WHERE owner = 'MISRETAIL' AND name IN ('T_SALE_COMPARE_ABV_ASP', 'V_SALE_COMPARE_ABV_ASP', 'T_SALE_COMPARE_ASP_ABV', 'V_SALE_COMPARE_ASP_ABV', 'T_SALE_COMPARE_DAY_WISE', 'T_SALE_COMPARE_CONSOLIDATED', 'T_SALE_COMPARE_BILL_CUT', 'V_SALE_COMPARE_BILL_CUT', 'T_STORE_WISE_DAY_SALE', 'V_DAYWISE_BILLCUT', 'V_CFO_DASHBOARD_SL_V', 'CUBE$POSBILLSUMM', 'T_STORE_OPENING_DATE', 'T_STORE_SALE_TARGET', 'T_CUSTOM_COGS', 'ITEM_MV', 'T_FINANCIAL_YEAR_NEW') FETCH FIRST 5000 ROWS ONLY
```

### s8_procedures

```sql
SELECT owner, object_name, object_type, status, TO_CHAR(last_ddl_time, 'YYYY-MM-DD') AS last_ddl FROM all_objects WHERE owner = 'MISRETAIL' AND object_type IN ('PROCEDURE', 'PACKAGE', 'PACKAGE BODY', 'FUNCTION') AND REGEXP_LIKE(object_name, '(COMPAR|CONSOLID|BILL_?CUT|ABV|DAY_?SALE)', 'i') FETCH FIRST 500 ROWS ONLY
```

### s9_procedure_source

```sql
SELECT name, type, line, text FROM all_source WHERE owner = 'MISRETAIL' AND name IN ('PROC_T_SALES_COMPARISION', 'PROC_T_SALE_CONSOLIDATED') ORDER BY name, type, line FETCH FIRST 20000 ROWS ONLY
```

### s10_table_comments

```sql
SELECT table_name, table_type, comments FROM all_tab_comments WHERE owner = 'MISRETAIL' AND (table_name IN ('T_SALE_COMPARE_ABV_ASP', 'V_SALE_COMPARE_ABV_ASP', 'T_SALE_COMPARE_ASP_ABV', 'V_SALE_COMPARE_ASP_ABV', 'T_SALE_COMPARE_DAY_WISE', 'T_SALE_COMPARE_CONSOLIDATED', 'T_SALE_COMPARE_BILL_CUT', 'V_SALE_COMPARE_BILL_CUT', 'T_STORE_WISE_DAY_SALE', 'V_DAYWISE_BILLCUT', 'V_CFO_DASHBOARD_SL_V', 'CUBE$POSBILLSUMM', 'T_STORE_OPENING_DATE', 'T_STORE_SALE_TARGET', 'T_CUSTOM_COGS', 'ITEM_MV', 'T_FINANCIAL_YEAR_NEW') OR table_name IN (SELECT object_name FROM all_objects WHERE owner = 'MISRETAIL' AND object_type IN ('TABLE', 'VIEW', 'MATERIALIZED VIEW') AND REGEXP_LIKE(object_name, '(FEST|HOLI|DIWALI|CALEND|SHIFT|DATE_?MAP|LY_?DATE|EVENT|FINANCIAL_YEAR|DAY_?MAP|COMPARE_?DATE|NEW_?BILLDATE|DAY_?TYPE|WEEK_?MAP)', 'i'))) AND comments IS NOT NULL FETCH FIRST 500 ROWS ONLY
```

### s11_column_comments

```sql
SELECT table_name, column_name, comments FROM all_col_comments WHERE owner = 'MISRETAIL' AND (table_name IN ('T_SALE_COMPARE_ABV_ASP', 'V_SALE_COMPARE_ABV_ASP', 'T_SALE_COMPARE_ASP_ABV', 'V_SALE_COMPARE_ASP_ABV', 'T_SALE_COMPARE_DAY_WISE', 'T_SALE_COMPARE_CONSOLIDATED', 'T_SALE_COMPARE_BILL_CUT', 'V_SALE_COMPARE_BILL_CUT', 'T_STORE_WISE_DAY_SALE', 'V_DAYWISE_BILLCUT', 'V_CFO_DASHBOARD_SL_V', 'CUBE$POSBILLSUMM', 'T_STORE_OPENING_DATE', 'T_STORE_SALE_TARGET', 'T_CUSTOM_COGS', 'ITEM_MV', 'T_FINANCIAL_YEAR_NEW') OR table_name IN (SELECT object_name FROM all_objects WHERE owner = 'MISRETAIL' AND object_type IN ('TABLE', 'VIEW', 'MATERIALIZED VIEW') AND REGEXP_LIKE(object_name, '(FEST|HOLI|DIWALI|CALEND|SHIFT|DATE_?MAP|LY_?DATE|EVENT|FINANCIAL_YEAR|DAY_?MAP|COMPARE_?DATE|NEW_?BILLDATE|DAY_?TYPE|WEEK_?MAP)', 'i'))) AND comments IS NOT NULL FETCH FIRST 5000 ROWS ONLY
```

## sales_probe_02 (run_20261005_019, created 2026-10-05T10:09:41+00:00)

| dataset | kind | status | rows | cap | seconds | guard hash |
|---|---|---|---|---|---|---|
| k1_calendar_date_plan | master | ok | 455 | 1000 | 6.1 | 8e75b0dc63 |
| k2_festival_data | master | ok | 56 | 1000 | 6.1 | 90739ebdb3 |
| k3_festival_detail | master | ok | 51 | 1000 | 6.1 | cf4d85931a |
| k4_newdate_fest | master | ok | 124 | 1000 | 6.1 | 82b49d2432 |
| k5_newdate_festo | master | ok | 136 | 1000 | 6.1 | 420488ffdb |
| k6_holi_ly | master | ok | 62 | 1000 | 6.1 | 07937ec81c |
| k7_holi_lly | master | ok | 62 | 1000 | 6.1 | 27fc637d9f |
| k8_key_events | master | ok | 35 | 1000 | 6.1 | d64f327c69 |
| k9_store_festival_filter | master | ok | 164 | 1000 | 6.1 | 256bb84041 |
| k10_store_compare_festival | master | ok | 89 | 1000 | 6.1 | 1d5dddccbf |
| k11_bi_store_compare | master | ok | 105 | 1000 | 6.1 | 68d06af49b |
| k12_store_master | master | ok | 341 | 1000 | 6.1 | 4b9d196b9c |
| a1_abvasp_by_day | extract | ok | 31 | 3000 | 6.1 | b31e7a0b68 |
| a2_abvasp_status_values | extract | ok | 18 | 500 | 6.1 | e5691ac4e2 |
| a3_abvasp_grain | extract | ok | 1 | 5 | 6.1 | 69a75bcaac |
| a4_daywise_by_month | extract | ok | 2 | 500 | 14.2 | ba7c1c5893 |
| a5_daywise_by_day | extract | ok | 5 | 100 | 6.1 | d6c5cde567 |
| a6_storedaysale_by_month | extract | ok | 1 | 100 | 14.2 | 129d6d6faf |
| a7_cfo_by_day | extract | ok | 88 | 200 | 269.3 | cce7ae88f1 |
| a8_cfo_by_month | extract | ok | 19 | 100 | 564.9 | 31ed1d9ef5 |
| a9_cfo_site_in_master | extract | ok | 3 | 10 | 220.6 | e746fecc93 |
| a10_pos_by_month | extract | ok | 38 | 200 | 184.3 | 9923aae102 |
| a11_pos_store_day | extract | ok | 0 | 1000 | 42.7 | 5440998c38 |
| a12_cfo_store_day | extract | ok | 206 | 1000 | 125.1 | 55863b8abf |
| a13_consolidated_by_month | extract | ok | 7 | 100 | 46.7 | c4f021f946 |

Notes:
- `a11_pos_store_day`: INVALID EVIDENCE: returned 0 rows because the filter used ISVOID = 'N' while the cube stores 'No' / 'Yes' (author error). Not genuine zero activity. Superseded by c4_pos_store_day.

SQL:

### k1_calendar_date_plan

```sql
SELECT TO_CHAR("CURRENT_DATE", 'YYYY-MM-DD') AS current_date_v, TO_CHAR(ly_mapped_date, 'YYYY-MM-DD') AS ly_mapped_date FROM MISRETAIL.T_CALENDER_DATE_PLAN FETCH FIRST 1000 ROWS ONLY
```

### k2_festival_data

```sql
SELECT festival_date, year_type, diwali, chat, modified_date FROM MISRETAIL.T_FESTIVAL_DATA FETCH FIRST 1000 ROWS ONLY
```

### k3_festival_detail

```sql
SELECT festival_date, holiday_name, prior_date_15_days, prior_date_20_days, holiday FROM MISRETAIL.T_FESTIVAL_DETAIL FETCH FIRST 1000 ROWS ONLY
```

### k4_newdate_fest

```sql
SELECT TO_CHAR(old_date, 'YYYY-MM-DD') AS old_date, TO_CHAR(new_date, 'YYYY-MM-DD') AS new_date, week_no FROM MISRETAIL.T_NEW_DATE_TWO_YEAR_COMP_FEST FETCH FIRST 1000 ROWS ONLY
```

### k5_newdate_festo

```sql
SELECT TO_CHAR(old_date, 'YYYY-MM-DD') AS old_date, TO_CHAR(new_date, 'YYYY-MM-DD') AS new_date, week_no FROM MISRETAIL.T_NEW_DATE_TWO_YEAR_COMP_FESTO FETCH FIRST 1000 ROWS ONLY
```

### k6_holi_ly

```sql
SELECT TO_CHAR(old_date, 'YYYY-MM-DD') AS old_date, TO_CHAR(new_date, 'YYYY-MM-DD') AS new_date FROM MISRETAIL.T_NEW_DATE_HOLI_TY_VS_LY FETCH FIRST 1000 ROWS ONLY
```

### k7_holi_lly

```sql
SELECT TO_CHAR(old_date, 'YYYY-MM-DD') AS old_date, TO_CHAR(new_date, 'YYYY-MM-DD') AS new_date FROM MISRETAIL.T_NEW_DATE_HOLI_TY_VS_LLY FETCH FIRST 1000 ROWS ONLY
```

### k8_key_events

```sql
SELECT event, type, priority_type FROM MISRETAIL.T_KEY_LODGER_EVENT FETCH FIRST 1000 ROWS ONLY
```

### k9_store_festival_filter

```sql
SELECT site_code, store_name, festival_filter FROM MISRETAIL.T_STORE_FESTIVAL_FILTER FETCH FIRST 1000 ROWS ONLY
```

### k10_store_compare_festival

```sql
SELECT site_code, store_name, store_eligible, city, district, new_state FROM MISRETAIL.T_STORE_COMPARE_FESTIVAL FETCH FIRST 1000 ROWS ONLY
```

### k11_bi_store_compare

```sql
SELECT site_code, store_name, TO_CHAR(store_date, 'YYYY-MM-DD') AS store_date, year_comparision FROM MISRETAIL.T_BI_STORE_COMPARE_FESTIVE FETCH FIRST 1000 ROWS ONLY
```

### k12_store_master

```sql
SELECT site_code, store_name, TO_CHAR(opening_date, 'YYYY-MM-DD') AS opening_date, store_status, store_current_status, cluster_type, region_type, state, festival_grouping, holi_group, dc_status, store_type, TO_CHAR(last_bill_date, 'YYYY-MM-DD') AS last_bill_date FROM MISRETAIL.T_STORE_OPENING_DATE FETCH FIRST 1000 ROWS ONLY
```

### a1_abvasp_by_day

```sql
SELECT TO_CHAR(new_billdate, 'YYYY-MM-DD') AS new_billdate_v, COUNT(*) AS row_n, COUNT(DISTINCT store_name) AS stores, COUNT(DISTINCT sale_bucket) AS buckets, TO_CHAR(SUM(ty_bill_count), 'TM9') AS ty_bills, TO_CHAR(SUM(ly_bill_count), 'TM9') AS ly_bills, TO_CHAR(SUM(lly_bill_count), 'TM9') AS lly_bills, TO_CHAR(SUM(ty_sl_v), 'TM9') AS ty_sl_v, TO_CHAR(SUM(ly_sl_v), 'TM9') AS ly_sl_v, TO_CHAR(SUM(lly_sl_v), 'TM9') AS lly_sl_v, TO_CHAR(SUM(ty_sl_q), 'TM9') AS ty_sl_q, TO_CHAR(SUM(ly_sl_q), 'TM9') AS ly_sl_q FROM MISRETAIL.T_SALE_COMPARE_ABV_ASP WHERE new_billdate >= DATE '2024-01-01' GROUP BY new_billdate ORDER BY new_billdate FETCH FIRST 3000 ROWS ONLY
```

### a2_abvasp_status_values

```sql
SELECT year_comparison, ly_status, final_status, cashback_filter, COUNT(*) AS row_n, TO_CHAR(MIN(new_billdate), 'YYYY-MM-DD') AS first_day, TO_CHAR(MAX(new_billdate), 'YYYY-MM-DD') AS last_day FROM MISRETAIL.T_SALE_COMPARE_ABV_ASP WHERE new_billdate >= DATE '2024-01-01' GROUP BY year_comparison, ly_status, final_status, cashback_filter FETCH FIRST 500 ROWS ONLY
```

### a3_abvasp_grain

```sql
SELECT COUNT(*) AS row_n, COUNT(DISTINCT store_name || '|' || TO_CHAR(new_billdate, 'YYYYMMDD') || '|' || sale_bucket) AS distinct_keys, COUNT(ty_bill_count) AS n_ty_bills, COUNT(ly_bill_count) AS n_ly_bills, COUNT(ty_sl_v) AS n_ty_v, COUNT(ly_sl_v) AS n_ly_v, TO_CHAR(MIN(new_billdate), 'YYYY-MM-DD') AS first_day, TO_CHAR(MAX(new_billdate), 'YYYY-MM-DD') AS last_day FROM MISRETAIL.T_SALE_COMPARE_ABV_ASP WHERE new_billdate >= DATE '2000-01-01' FETCH FIRST 5 ROWS ONLY
```

### a4_daywise_by_month

```sql
SELECT TO_CHAR(TRUNC(bill_date, 'MM'), 'YYYY-MM-DD') AS bill_month, year_comparison, COUNT(*) AS row_n, COUNT(DISTINCT store_name) AS stores, TO_CHAR(MIN(bill_date), 'YYYY-MM-DD') AS first_day, TO_CHAR(MAX(bill_date), 'YYYY-MM-DD') AS last_day, TO_CHAR(SUM(ty_sl_v), 'TM9') AS ty_sl_v, TO_CHAR(SUM(ty_sl_q), 'TM9') AS ty_sl_q, TO_CHAR(SUM(ty_sl_tax), 'TM9') AS ty_tax, TO_CHAR(SUM(ty_sl_cogs), 'TM9') AS ty_cogs, TO_CHAR(SUM(ly_sl_v), 'TM9') AS ly_sl_v, TO_CHAR(SUM(ly_sl_q), 'TM9') AS ly_sl_q, TO_CHAR(SUM(lly_sl_v), 'TM9') AS lly_sl_v, TO_CHAR(SUM(lly_sl_q), 'TM9') AS lly_sl_q FROM MISRETAIL.T_SALE_COMPARE_DAY_WISE WHERE bill_date >= DATE '2025-04-01' GROUP BY TRUNC(bill_date, 'MM'), year_comparison FETCH FIRST 500 ROWS ONLY
```

### a5_daywise_by_day

```sql
SELECT TO_CHAR(bill_date, 'YYYY-MM-DD') AS bill_date_v, COUNT(*) AS row_n, COUNT(DISTINCT store_name) AS stores, TO_CHAR(SUM(ty_sl_v), 'TM9') AS ty_sl_v, TO_CHAR(SUM(ty_sl_q), 'TM9') AS ty_sl_q, TO_CHAR(SUM(ly_sl_v), 'TM9') AS ly_sl_v, TO_CHAR(SUM(ly_sl_q), 'TM9') AS ly_sl_q, TO_CHAR(SUM(lly_sl_v), 'TM9') AS lly_sl_v FROM MISRETAIL.T_SALE_COMPARE_DAY_WISE WHERE bill_date >= DATE '2026-09-01' AND bill_date <= DATE '2026-10-05' GROUP BY bill_date ORDER BY bill_date FETCH FIRST 100 ROWS ONLY
```

### a6_storedaysale_by_month

```sql
SELECT TO_CHAR(TRUNC(billdate, 'MM'), 'YYYY-MM-DD') AS bill_month, COUNT(*) AS row_n, COUNT(DISTINCT store_name) AS stores, TO_CHAR(MIN(billdate), 'YYYY-MM-DD') AS first_day, TO_CHAR(MAX(billdate), 'YYYY-MM-DD') AS last_day, TO_CHAR(SUM(qty), 'TM9') AS qty, TO_CHAR(SUM(value), 'TM9') AS value FROM MISRETAIL.T_STORE_WISE_DAY_SALE WHERE billdate >= DATE '2025-04-01' GROUP BY TRUNC(billdate, 'MM') FETCH FIRST 100 ROWS ONLY
```

### a7_cfo_by_day

```sql
SELECT TO_CHAR(billdate, 'YYYY-MM-DD') AS bill_date_v, COUNT(*) AS row_n, COUNT(DISTINCT admsite_code) AS stores, TO_CHAR(SUM(bill_count), 'TM9') AS bills, TO_CHAR(SUM(sl_v), 'TM9') AS sl_v, TO_CHAR(SUM(sl_q), 'TM9') AS sl_q, TO_CHAR(SUM(tax_v), 'TM9') AS tax_v FROM MISRETAIL.V_CFO_DASHBOARD_SL_V WHERE (billdate >= DATE '2025-08-25' AND billdate <= DATE '2025-10-10') OR (billdate >= DATE '2026-08-25' AND billdate <= DATE '2026-10-05') GROUP BY billdate ORDER BY billdate FETCH FIRST 200 ROWS ONLY
```

### a8_cfo_by_month

```sql
SELECT TO_CHAR(TRUNC(billdate, 'MM'), 'YYYY-MM-DD') AS bill_month, COUNT(*) AS row_n, COUNT(DISTINCT admsite_code) AS stores, TO_CHAR(SUM(bill_count), 'TM9') AS bills, TO_CHAR(SUM(sl_v), 'TM9') AS sl_v, TO_CHAR(SUM(sl_q), 'TM9') AS sl_q, TO_CHAR(SUM(tax_v), 'TM9') AS tax_v FROM MISRETAIL.V_CFO_DASHBOARD_SL_V WHERE billdate >= DATE '2025-04-01' GROUP BY TRUNC(billdate, 'MM') FETCH FIRST 100 ROWS ONLY
```

### a9_cfo_site_in_master

```sql
SELECT TO_CHAR(billdate, 'YYYY-MM-DD') AS bill_date_v, COUNT(*) AS row_n, COUNT(CASE WHEN admsite_code IN (SELECT site_code FROM MISRETAIL.T_STORE_OPENING_DATE) THEN 1 END) AS in_store_master, COUNT(CASE WHEN admsite_code IN (SELECT site_code FROM MISRETAIL.T_STORE_OPENING_DATE WHERE store_status = 'ACTIVE') THEN 1 END) AS in_active_master FROM MISRETAIL.V_CFO_DASHBOARD_SL_V WHERE (billdate >= DATE '2025-09-15' AND billdate <= DATE '2025-09-15') OR (billdate >= DATE '2026-09-15' AND billdate <= DATE '2026-09-15') OR (billdate >= DATE '2026-09-30' AND billdate <= DATE '2026-09-30') GROUP BY billdate FETCH FIRST 10 ROWS ONLY
```

### a10_pos_by_month

```sql
SELECT TO_CHAR(TRUNC(billdate, 'MM'), 'YYYY-MM-DD') AS bill_month, isvoid, COUNT(*) AS row_n, COUNT(DISTINCT sitecode || '|' || billno) AS distinct_bills, COUNT(CASE WHEN netamt < 0 THEN 1 END) AS negative_net_bills, COUNT(CASE WHEN returnamt <> 0 THEN 1 END) AS bills_with_returns, COUNT(CASE WHEN billqty < 0 THEN 1 END) AS negative_qty_bills, TO_CHAR(SUM(netamt), 'TM9') AS net, TO_CHAR(SUM(returnamt), 'TM9') AS returns, TO_CHAR(SUM(taxableamt), 'TM9') AS taxable, TO_CHAR(SUM(taxamt), 'TM9') AS tax, TO_CHAR(SUM(billqty), 'TM9') AS qty, COUNT(DISTINCT sitecode) AS sites FROM MISRETAIL.CUBE$POSBILLSUMM WHERE billdate >= DATE '2025-04-01' GROUP BY TRUNC(billdate, 'MM'), isvoid FETCH FIRST 200 ROWS ONLY
```

### a11_pos_store_day

```sql
SELECT TO_CHAR(sitecode) AS site_code, COUNT(DISTINCT billno) AS bills, TO_CHAR(SUM(netamt), 'TM9') AS net, TO_CHAR(SUM(billqty), 'TM9') AS qty, TO_CHAR(SUM(taxamt), 'TM9') AS tax FROM MISRETAIL.CUBE$POSBILLSUMM WHERE billdate >= DATE '2026-09-15' AND billdate <= DATE '2026-09-15' AND isvoid = 'N' GROUP BY sitecode FETCH FIRST 1000 ROWS ONLY
```

### a12_cfo_store_day

```sql
SELECT TO_CHAR(admsite_code) AS site_code, TO_CHAR(SUM(bill_count), 'TM9') AS bills, TO_CHAR(SUM(sl_v), 'TM9') AS net, TO_CHAR(SUM(sl_q), 'TM9') AS qty, TO_CHAR(SUM(tax_v), 'TM9') AS tax FROM MISRETAIL.V_CFO_DASHBOARD_SL_V WHERE billdate >= DATE '2026-09-15' AND billdate <= DATE '2026-09-15' GROUP BY admsite_code FETCH FIRST 1000 ROWS ONLY
```

### a13_consolidated_by_month

```sql
SELECT TO_CHAR(TRUNC(bill_date, 'MM'), 'YYYY-MM-DD') AS bill_month, COUNT(*) AS row_n, COUNT(DISTINCT store_name) AS stores, TO_CHAR(SUM(ty_sl_v), 'TM9') AS ty_sl_v, TO_CHAR(SUM(ly_sl_v), 'TM9') AS ly_sl_v, TO_CHAR(SUM(ty_sl_q), 'TM9') AS ty_sl_q FROM MISRETAIL.T_SALE_COMPARE_CONSOLIDATED WHERE bill_date >= DATE '2025-04-01' GROUP BY TRUNC(bill_date, 'MM') FETCH FIRST 100 ROWS ONLY
```

## sales_probe_03a (run_20261005_023, created 2026-10-05T10:48:43+00:00)

| dataset | kind | status | rows | cap | seconds | guard hash |
|---|---|---|---|---|---|---|
| v1_status | metadata | ok | 13 | 200 | 6.8 | be82534c17 |
| v2_dependencies | metadata | ok | 33 | 2000 | 6.1 | 21197d05e1 |
| v3_errors | metadata | ok | 0 | 500 | 6.1 | 0884bf8f6e |
| v4_view_text | metadata | ok | 8 | 20 | 6.1 | 0957b7b56c |
| v5_columns | metadata | ok | 181 | 2000 | 6.1 | a25e785b44 |
| v6_stats | metadata | ok | 5 | 100 | 6.1 | cb6abe5d80 |

Notes:
- `v3_errors`: 0 rows: the dictionary records no compile errors for the two INVALID views (status only).

SQL:

### v1_status

```sql
SELECT object_name, object_type, status, TO_CHAR(created, 'YYYY-MM-DD HH24:MI') AS created, TO_CHAR(last_ddl_time, 'YYYY-MM-DD HH24:MI') AS last_ddl FROM all_objects WHERE owner = 'MISRETAIL' AND object_name IN ('V_SALE_COMPARE_ABV_ASP', 'V_SALE_COMPARE_ASP_ABV', 'V_SALE_COMPARE_DAY_WISE', 'V_SALE_COMPARE_CONSOLIDATED', 'V_SALE_BUCKET_WISE', 'V_DAYWISE_BILLCUT', 'V_SALE_COMPARE_BILL_CUT', 'V_DUMMY_REMOVE', 'T_NEW_DATE_TWO_YEAR_COMP_20', 'T_NEW_DATE_TWO_YEAR_COMP_ADHOC', 'T_STORE_COMPARE', 'T_STORE_COMPARE_120', 'T_CALENDER_DATE_PLAN') FETCH FIRST 200 ROWS ONLY
```

### v2_dependencies

```sql
SELECT name, type, referenced_owner, referenced_name, referenced_type FROM all_dependencies WHERE owner = 'MISRETAIL' AND name IN ('V_SALE_COMPARE_ABV_ASP', 'V_SALE_COMPARE_ASP_ABV', 'V_SALE_COMPARE_DAY_WISE', 'V_SALE_COMPARE_CONSOLIDATED', 'V_SALE_BUCKET_WISE', 'V_DAYWISE_BILLCUT', 'V_SALE_COMPARE_BILL_CUT', 'V_DUMMY_REMOVE') ORDER BY name, referenced_name FETCH FIRST 2000 ROWS ONLY
```

### v3_errors

```sql
SELECT name, type, sequence, line, position, attribute, text FROM all_errors WHERE owner = 'MISRETAIL' AND name IN ('V_SALE_COMPARE_ABV_ASP', 'V_SALE_COMPARE_ASP_ABV', 'V_SALE_COMPARE_DAY_WISE', 'V_SALE_COMPARE_CONSOLIDATED', 'V_SALE_BUCKET_WISE', 'V_DAYWISE_BILLCUT', 'V_SALE_COMPARE_BILL_CUT', 'V_DUMMY_REMOVE') ORDER BY name, sequence FETCH FIRST 500 ROWS ONLY
```

### v4_view_text

```sql
SELECT view_name, text_length, text FROM all_views WHERE owner = 'MISRETAIL' AND view_name IN ('V_SALE_COMPARE_ABV_ASP', 'V_SALE_COMPARE_ASP_ABV', 'V_SALE_COMPARE_DAY_WISE', 'V_SALE_COMPARE_CONSOLIDATED', 'V_SALE_BUCKET_WISE', 'V_DAYWISE_BILLCUT', 'V_SALE_COMPARE_BILL_CUT', 'V_DUMMY_REMOVE') FETCH FIRST 20 ROWS ONLY
```

### v5_columns

```sql
SELECT table_name, column_name, data_type, data_length, column_id FROM all_tab_columns WHERE owner = 'MISRETAIL' AND table_name IN ('V_SALE_COMPARE_ABV_ASP', 'V_SALE_COMPARE_ASP_ABV', 'V_SALE_COMPARE_DAY_WISE', 'V_SALE_COMPARE_CONSOLIDATED', 'V_SALE_BUCKET_WISE', 'V_DAYWISE_BILLCUT', 'V_SALE_COMPARE_BILL_CUT', 'V_DUMMY_REMOVE', 'T_NEW_DATE_TWO_YEAR_COMP_20', 'T_NEW_DATE_TWO_YEAR_COMP_ADHOC', 'T_STORE_COMPARE', 'T_STORE_COMPARE_120', 'T_CALENDER_DATE_PLAN') ORDER BY table_name, column_id FETCH FIRST 2000 ROWS ONLY
```

### v6_stats

```sql
SELECT table_name, num_rows, TO_CHAR(last_analyzed, 'YYYY-MM-DD') AS last_analyzed FROM all_tables WHERE owner = 'MISRETAIL' AND table_name IN ('V_SALE_COMPARE_ABV_ASP', 'V_SALE_COMPARE_ASP_ABV', 'V_SALE_COMPARE_DAY_WISE', 'V_SALE_COMPARE_CONSOLIDATED', 'V_SALE_BUCKET_WISE', 'V_DAYWISE_BILLCUT', 'V_SALE_COMPARE_BILL_CUT', 'V_DUMMY_REMOVE', 'T_NEW_DATE_TWO_YEAR_COMP_20', 'T_NEW_DATE_TWO_YEAR_COMP_ADHOC', 'T_STORE_COMPARE', 'T_STORE_COMPARE_120', 'T_CALENDER_DATE_PLAN') FETCH FIRST 100 ROWS ONLY
```

## sales_probe_03b (run_20261005_024, created 2026-10-05T10:51:16+00:00)

| dataset | kind | status | rows | cap | seconds | guard hash |
|---|---|---|---|---|---|---|
| w1_status | metadata | ok | 5 | 50 | 6.2 | 5f1305513e |
| w2_dependencies | metadata | ok | 23 | 1000 | 6.1 | ff9f3fc464 |
| w3_view_text | metadata | ok | 5 | 20 | 6.2 | 28c6118c49 |
| w4_map_comp_20 | master | ok | 62 | 1000 | 6.1 | cc8cf3048e |
| w5_map_comp_adhoc | master | ok | 428 | 1000 | 6.1 | 45d1cac688 |
| w6_store_compare_120 | master | ok | 120 | 1000 | 6.1 | 0aecb967f7 |

Notes:

SQL:

### w1_status

```sql
SELECT object_name, object_type, status, TO_CHAR(last_ddl_time, 'YYYY-MM-DD HH24:MI') AS last_ddl FROM all_objects WHERE owner = 'MISRETAIL' AND object_name IN ('V_CFO_DASHBOARD_SL_V', 'V_COMPARE_TY_LY_LLY_DAY_V1', 'V_COMPARE_TY_LY_LLY_CONSO', 'V_STORE_WISE_MC_STATUS', 'V_COMPARE_TY_LY_LLY_DAY_WISE') FETCH FIRST 50 ROWS ONLY
```

### w2_dependencies

```sql
SELECT name, referenced_owner, referenced_name, referenced_type FROM all_dependencies WHERE owner = 'MISRETAIL' AND name IN ('V_CFO_DASHBOARD_SL_V', 'V_COMPARE_TY_LY_LLY_DAY_V1', 'V_COMPARE_TY_LY_LLY_CONSO', 'V_STORE_WISE_MC_STATUS', 'V_COMPARE_TY_LY_LLY_DAY_WISE') ORDER BY name, referenced_name FETCH FIRST 1000 ROWS ONLY
```

### w3_view_text

```sql
SELECT view_name, text_length, text FROM all_views WHERE owner = 'MISRETAIL' AND view_name IN ('V_CFO_DASHBOARD_SL_V', 'V_COMPARE_TY_LY_LLY_DAY_V1', 'V_COMPARE_TY_LY_LLY_CONSO', 'V_STORE_WISE_MC_STATUS', 'V_COMPARE_TY_LY_LLY_DAY_WISE') FETCH FIRST 20 ROWS ONLY
```

### w4_map_comp_20

```sql
SELECT TO_CHAR(old_date, 'YYYY-MM-DD') AS old_date, TO_CHAR(new_date, 'YYYY-MM-DD') AS new_date, week_no FROM MISRETAIL.T_NEW_DATE_TWO_YEAR_COMP_20 FETCH FIRST 1000 ROWS ONLY
```

### w5_map_comp_adhoc

```sql
SELECT TO_CHAR(old_date, 'YYYY-MM-DD') AS old_date, TO_CHAR(new_date, 'YYYY-MM-DD') AS new_date, week_no FROM MISRETAIL.T_NEW_DATE_TWO_YEAR_COMP_ADHOC FETCH FIRST 1000 ROWS ONLY
```

### w6_store_compare_120

```sql
SELECT site_code, store_name, state, city_name, year_comparision_2026 FROM MISRETAIL.T_STORE_COMPARE_120 FETCH FIRST 1000 ROWS ONLY
```

## sales_probe_03c (run_20261005_025, created 2026-10-05T10:53:33+00:00)

| dataset | kind | status | rows | cap | seconds | guard hash |
|---|---|---|---|---|---|---|
| c1_pos_day_totals | extract | ok | 2 | 5 | 30.7 | f46a72d3bc |
| c2_pos_day_totals_ly | extract | ok | 2 | 5 | 22.2 | b63ce7ed73 |
| c3_pos_rows_per_bill | extract | ok | 0 | 50 | 22.3 | 5f17f43328 |
| c4_pos_store_day | extract | ok | 206 | 1000 | 22.3 | c7955c5edd |

Notes:
- `c3_pos_rows_per_bill`: 0 rows by design of the result: BILLNO is null on every cube row, so the query's `billno IS NOT NULL` filter excluded everything. This is itself the finding.

SQL:

### c1_pos_day_totals

```sql
SELECT isvoid, COUNT(*) AS row_n, COUNT(billno) AS billno_present, COUNT(DISTINCT billno) AS distinct_billno, COUNT(DISTINCT CASE WHEN billno IS NOT NULL THEN sitecode || '|' || billno END) AS distinct_site_bill, MIN(LENGTH(billno)) AS billno_len_min, MAX(LENGTH(billno)) AS billno_len_max, COUNT(CASE WHEN netamt < 0 THEN 1 END) AS negative_net_rows, COUNT(CASE WHEN returnamt <> 0 THEN 1 END) AS return_rows, COUNT(DISTINCT sitecode) AS sites, TO_CHAR(SUM(netamt), 'TM9') AS net, TO_CHAR(SUM(taxamt), 'TM9') AS tax, TO_CHAR(SUM(taxableamt), 'TM9') AS taxable, TO_CHAR(SUM(billqty), 'TM9') AS qty FROM MISRETAIL.CUBE$POSBILLSUMM WHERE billdate >= DATE '2026-09-15' AND billdate <= DATE '2026-09-15' GROUP BY isvoid FETCH FIRST 5 ROWS ONLY
```

### c2_pos_day_totals_ly

```sql
SELECT isvoid, COUNT(*) AS row_n, COUNT(billno) AS billno_present, COUNT(DISTINCT billno) AS distinct_billno, COUNT(DISTINCT CASE WHEN billno IS NOT NULL THEN sitecode || '|' || billno END) AS distinct_site_bill, MIN(LENGTH(billno)) AS billno_len_min, MAX(LENGTH(billno)) AS billno_len_max, COUNT(CASE WHEN netamt < 0 THEN 1 END) AS negative_net_rows, COUNT(CASE WHEN returnamt <> 0 THEN 1 END) AS return_rows, COUNT(DISTINCT sitecode) AS sites, TO_CHAR(SUM(netamt), 'TM9') AS net, TO_CHAR(SUM(taxamt), 'TM9') AS tax, TO_CHAR(SUM(taxableamt), 'TM9') AS taxable, TO_CHAR(SUM(billqty), 'TM9') AS qty FROM MISRETAIL.CUBE$POSBILLSUMM WHERE billdate >= DATE '2025-09-15' AND billdate <= DATE '2025-09-15' GROUP BY isvoid FETCH FIRST 5 ROWS ONLY
```

### c3_pos_rows_per_bill

```sql
SELECT rows_per_bill, COUNT(*) AS bills FROM (SELECT COUNT(*) AS rows_per_bill FROM MISRETAIL.CUBE$POSBILLSUMM WHERE billdate >= DATE '2026-09-15' AND billdate <= DATE '2026-09-15' AND isvoid = 'No' AND billno IS NOT NULL GROUP BY sitecode, billno) GROUP BY rows_per_bill ORDER BY rows_per_bill FETCH FIRST 50 ROWS ONLY
```

### c4_pos_store_day

```sql
SELECT TO_CHAR(sitecode) AS site_code, COUNT(DISTINCT CASE WHEN billno IS NOT NULL THEN billno END) AS bills, TO_CHAR(SUM(netamt), 'TM9') AS net, TO_CHAR(SUM(billqty), 'TM9') AS qty, TO_CHAR(SUM(taxamt), 'TM9') AS tax FROM MISRETAIL.CUBE$POSBILLSUMM WHERE billdate >= DATE '2026-09-15' AND billdate <= DATE '2026-09-15' AND isvoid = 'No' GROUP BY sitecode FETCH FIRST 1000 ROWS ONLY
```

## sales_probe_03d (run_20261005_026, created 2026-10-05T10:56:24+00:00)

| dataset | kind | status | rows | cap | seconds | guard hash |
|---|---|---|---|---|---|---|
| d1_bucket_view_store_day | extract | ok | 206 | 1000 | 59.0 | a23f0ff7d4 |

Notes:

SQL:

### d1_bucket_view_store_day

```sql
SELECT store_name, TO_CHAR(SUM(bill_count), 'TM9') AS bills, TO_CHAR(SUM(sale_v), 'TM9') AS sale_v, TO_CHAR(SUM(sale_q), 'TM9') AS sale_q, COUNT(*) AS bucket_rows, TO_CHAR(SUM(CASE WHEN sale_bucket = 'NEGATIVE SALE' THEN bill_count ELSE 0 END), 'TM9') AS negative_sale_bills FROM MISRETAIL.V_SALE_BUCKET_WISE WHERE billdate >= DATE '2026-09-15' AND billdate <= DATE '2026-09-15' GROUP BY store_name FETCH FIRST 1000 ROWS ONLY
```

## sales_probe_03e (run_20261005_027, created 2026-10-05T10:58:05+00:00)

| dataset | kind | status | rows | cap | seconds | guard hash |
|---|---|---|---|---|---|---|
| r1_readers_of_mapping_tables | metadata | ok | 63 | 2000 | 6.9 | 4ab115c9b1 |

Notes:

SQL:

### r1_readers_of_mapping_tables

```sql
SELECT referenced_name, name, type FROM all_dependencies WHERE owner = 'MISRETAIL' AND referenced_owner = 'MISRETAIL' AND referenced_name IN ('T_CALENDER_DATE_PLAN', 'T_NEW_DATE_TWO_YEAR_COMP_20', 'T_NEW_DATE_TWO_YEAR_COMP_ADHOC', 'T_NEW_DATE_TWO_YEAR_COMP_FEST', 'T_NEW_DATE_TWO_YEAR_COMP_FESTO', 'T_NEW_DATE_HOLI_TY_VS_LY', 'T_NEW_DATE_HOLI_TY_VS_LLY', 'T_STORE_COMPARE_120', 'T_STORE_COMPARE', 'T_WEEK_AUGUST') ORDER BY referenced_name, name FETCH FIRST 2000 ROWS ONLY
```

## sales_probe_04a (run_20261005_030, created 2026-10-05T12:25:08+00:00)

| dataset | kind | status | rows | cap | seconds | guard hash |
|---|---|---|---|---|---|---|
| f1_status | metadata | ok | 11 | 100 | 6.2 | 2684d02b77 |
| f2_dependencies | metadata | ok | 52 | 1000 | 6.1 | 9540c5708d |
| f3_view_text | metadata | ok | 11 | 40 | 6.1 | 03a97d33b4 |

Notes:

SQL:

### f1_status

```sql
SELECT object_name, object_type, status, TO_CHAR(created, 'YYYY-MM-DD HH24:MI') AS created, TO_CHAR(last_ddl_time, 'YYYY-MM-DD HH24:MI') AS last_ddl FROM all_objects WHERE owner = 'MISRETAIL' AND object_name IN ('V_COMPARE_TY_LY_LLY_FESTIVAL', 'V_COMPARE_TY_LY_LLY_FEST_GV', 'V_SALE_COMPARISION_FESTIVAL', 'V_COMPARE_HOLI', 'V_COMPARE_HOLI_2019', 'V_PDC_SALE_COMPARE_PART_1', 'V_PDC_SALE_COMPARE_PART_2', 'V_WEEKLY_SL_FESTIVAL_WISE', 'V_FOOTFALL_HOLI_COMPARE', 'V_COMPARE_TY_LY_LLY_DAY_V1', 'V_COMPARE_TY_LY_LLY_CONSO') FETCH FIRST 100 ROWS ONLY
```

### f2_dependencies

```sql
SELECT name, referenced_owner, referenced_name, referenced_type FROM all_dependencies WHERE owner = 'MISRETAIL' AND name IN ('V_COMPARE_TY_LY_LLY_FESTIVAL', 'V_COMPARE_TY_LY_LLY_FEST_GV', 'V_SALE_COMPARISION_FESTIVAL', 'V_COMPARE_HOLI', 'V_COMPARE_HOLI_2019', 'V_PDC_SALE_COMPARE_PART_1', 'V_PDC_SALE_COMPARE_PART_2', 'V_WEEKLY_SL_FESTIVAL_WISE', 'V_FOOTFALL_HOLI_COMPARE', 'V_COMPARE_TY_LY_LLY_DAY_V1', 'V_COMPARE_TY_LY_LLY_CONSO') ORDER BY name, referenced_name FETCH FIRST 1000 ROWS ONLY
```

### f3_view_text

```sql
SELECT view_name, text_length, text FROM all_views WHERE owner = 'MISRETAIL' AND view_name IN ('V_COMPARE_TY_LY_LLY_FESTIVAL', 'V_COMPARE_TY_LY_LLY_FEST_GV', 'V_SALE_COMPARISION_FESTIVAL', 'V_COMPARE_HOLI', 'V_COMPARE_HOLI_2019', 'V_PDC_SALE_COMPARE_PART_1', 'V_PDC_SALE_COMPARE_PART_2', 'V_WEEKLY_SL_FESTIVAL_WISE', 'V_FOOTFALL_HOLI_COMPARE', 'V_COMPARE_TY_LY_LLY_DAY_V1', 'V_COMPARE_TY_LY_LLY_CONSO') FETCH FIRST 40 ROWS ONLY
```

## sales_probe_04b (run_20261005_031, created 2026-10-05T12:28:17+00:00)

| dataset | kind | status | rows | cap | seconds | guard hash |
|---|---|---|---|---|---|---|
| h1_2022_diwali | extract | ok | 2 | 5 | 26.7 | d946fc604b |
| h2_2023_diwali | extract | ok | 2 | 5 | 26.3 | cd2650730e |
| h3_2024_diwali | extract | ok | 2 | 5 | 42.5 | 5a3bf62e8c |
| h4_2025_holi | extract | ok | 2 | 5 | 62.9 | cf62f70544 |
| h5_2025_eid_fitr | extract | ok | 2 | 5 | 42.6 | 796333f977 |
| m1_cube_store_day_aug26 | extract | ok | 6122 | 20000 | 50.6 | b5da41706c |

Notes:

SQL:

### h1_2022_diwali

```sql
SELECT isvoid, COUNT(*) AS row_n, COUNT(DISTINCT sitecode) AS sites, TO_CHAR(SUM(netamt), 'TM9') AS net, TO_CHAR(SUM(taxamt), 'TM9') AS tax, TO_CHAR(SUM(taxableamt), 'TM9') AS taxable, TO_CHAR(SUM(billqty), 'TM9') AS qty, COUNT(CASE WHEN netamt < 0 THEN 1 END) AS negative_rows FROM MISRETAIL.CUBE$POSBILLSUMM WHERE billdate >= DATE '2022-10-24' AND billdate <= DATE '2022-10-24' GROUP BY isvoid FETCH FIRST 5 ROWS ONLY
```

### h2_2023_diwali

```sql
SELECT isvoid, COUNT(*) AS row_n, COUNT(DISTINCT sitecode) AS sites, TO_CHAR(SUM(netamt), 'TM9') AS net, TO_CHAR(SUM(taxamt), 'TM9') AS tax, TO_CHAR(SUM(taxableamt), 'TM9') AS taxable, TO_CHAR(SUM(billqty), 'TM9') AS qty, COUNT(CASE WHEN netamt < 0 THEN 1 END) AS negative_rows FROM MISRETAIL.CUBE$POSBILLSUMM WHERE billdate >= DATE '2023-11-12' AND billdate <= DATE '2023-11-12' GROUP BY isvoid FETCH FIRST 5 ROWS ONLY
```

### h3_2024_diwali

```sql
SELECT isvoid, COUNT(*) AS row_n, COUNT(DISTINCT sitecode) AS sites, TO_CHAR(SUM(netamt), 'TM9') AS net, TO_CHAR(SUM(taxamt), 'TM9') AS tax, TO_CHAR(SUM(taxableamt), 'TM9') AS taxable, TO_CHAR(SUM(billqty), 'TM9') AS qty, COUNT(CASE WHEN netamt < 0 THEN 1 END) AS negative_rows FROM MISRETAIL.CUBE$POSBILLSUMM WHERE billdate >= DATE '2024-11-01' AND billdate <= DATE '2024-11-01' GROUP BY isvoid FETCH FIRST 5 ROWS ONLY
```

### h4_2025_holi

```sql
SELECT isvoid, COUNT(*) AS row_n, COUNT(DISTINCT sitecode) AS sites, TO_CHAR(SUM(netamt), 'TM9') AS net, TO_CHAR(SUM(taxamt), 'TM9') AS tax, TO_CHAR(SUM(taxableamt), 'TM9') AS taxable, TO_CHAR(SUM(billqty), 'TM9') AS qty, COUNT(CASE WHEN netamt < 0 THEN 1 END) AS negative_rows FROM MISRETAIL.CUBE$POSBILLSUMM WHERE billdate >= DATE '2025-03-14' AND billdate <= DATE '2025-03-14' GROUP BY isvoid FETCH FIRST 5 ROWS ONLY
```

### h5_2025_eid_fitr

```sql
SELECT isvoid, COUNT(*) AS row_n, COUNT(DISTINCT sitecode) AS sites, TO_CHAR(SUM(netamt), 'TM9') AS net, TO_CHAR(SUM(taxamt), 'TM9') AS tax, TO_CHAR(SUM(taxableamt), 'TM9') AS taxable, TO_CHAR(SUM(billqty), 'TM9') AS qty, COUNT(CASE WHEN netamt < 0 THEN 1 END) AS negative_rows FROM MISRETAIL.CUBE$POSBILLSUMM WHERE billdate >= DATE '2025-03-31' AND billdate <= DATE '2025-03-31' GROUP BY isvoid FETCH FIRST 5 ROWS ONLY
```

### m1_cube_store_day_aug26

```sql
SELECT TO_CHAR(sitecode) AS site_code, TO_CHAR(billdate, 'YYYY-MM-DD') AS bill_date, isvoid, COUNT(*) AS row_n, TO_CHAR(SUM(netamt), 'TM9') AS net, TO_CHAR(SUM(taxamt), 'TM9') AS tax, TO_CHAR(SUM(taxableamt), 'TM9') AS taxable, TO_CHAR(SUM(billqty), 'TM9') AS qty, TO_CHAR(SUM(returnamt), 'TM9') AS returns, TO_CHAR(SUM(saleamt), 'TM9') AS sale, TO_CHAR(SUM(promoamt), 'TM9') AS promo, TO_CHAR(SUM(grossamt), 'TM9') AS gross, TO_CHAR(SUM(totaldiscountamt), 'TM9') AS discount FROM MISRETAIL.CUBE$POSBILLSUMM WHERE billdate >= DATE '2026-08-01' AND billdate <= DATE '2026-08-31' GROUP BY sitecode, billdate, isvoid FETCH FIRST 20000 ROWS ONLY
```

## sales_probe_04c (run_20261005_032, created 2026-10-05T12:34:41+00:00)

| dataset | kind | status | rows | cap | seconds | guard hash |
|---|---|---|---|---|---|---|
| q1_cube_instance_aug26 | extract | ok | 1 | 20 | 71.1 | 5797db5c9d |
| q2_cube_instance_history_days | extract | ok | 3 | 20 | 58.7 | 4ff76fa1c5 |

Notes:

SQL:

### q1_cube_instance_aug26

```sql
SELECT cube_code, cubename, TO_CHAR(MAX(report_date), 'YYYY-MM-DD') AS report_date, TO_CHAR(MIN(start_date), 'YYYY-MM-DD') AS window_start, TO_CHAR(MAX(end_date), 'YYYY-MM-DD') AS window_end, COUNT(*) AS row_n, TO_CHAR(MIN(billdate), 'YYYY-MM-DD') AS first_bill_date, TO_CHAR(MAX(billdate), 'YYYY-MM-DD') AS last_bill_date FROM MISRETAIL.CUBE$POSBILLSUMM WHERE billdate >= DATE '2026-08-01' AND billdate <= DATE '2026-08-31' GROUP BY cube_code, cubename FETCH FIRST 20 ROWS ONLY
```

### q2_cube_instance_history_days

```sql
SELECT cube_code, cubename, TO_CHAR(MAX(report_date), 'YYYY-MM-DD') AS report_date, TO_CHAR(MIN(start_date), 'YYYY-MM-DD') AS window_start, TO_CHAR(MAX(end_date), 'YYYY-MM-DD') AS window_end, COUNT(*) AS row_n, TO_CHAR(MIN(billdate), 'YYYY-MM-DD') AS first_bill_date, TO_CHAR(MAX(billdate), 'YYYY-MM-DD') AS last_bill_date FROM MISRETAIL.CUBE$POSBILLSUMM WHERE (billdate >= DATE '2022-10-24' AND billdate <= DATE '2022-10-24') OR (billdate >= DATE '2023-11-12' AND billdate <= DATE '2023-11-12') OR (billdate >= DATE '2024-11-01' AND billdate <= DATE '2024-11-01') OR (billdate >= DATE '2025-03-14' AND billdate <= DATE '2025-03-14') OR (billdate >= DATE '2025-03-31' AND billdate <= DATE '2025-03-31') GROUP BY cube_code, cubename FETCH FIRST 20 ROWS ONLY
```

## sales_probe_05a (run_20261005_036, created 2026-10-05T13:00:14+00:00)

| dataset | kind | status | rows | cap | seconds | guard hash |
|---|---|---|---|---|---|---|
| a196_april_by_day | extract | ok | 4 | 200 | 6.5 | df7734b7f3 |
| a809_april_by_day | extract | ok | 54 | 200 | 10.1 | 5166241ee6 |
| a750_april_by_day | extract | ok | 0 | 200 | 10.1 | 7945b075f3 |

Notes:

SQL:

### a196_april_by_day

```sql
SELECT cube_code, TO_CHAR(billdate, 'YYYY-MM-DD') AS bill_date, isvoid, COUNT(*) AS row_n, COUNT(DISTINCT sitecode) AS sites, TO_CHAR(MAX(report_date), 'YYYY-MM-DD') AS report_date, TO_CHAR(MIN(start_date), 'YYYY-MM-DD') AS window_start, TO_CHAR(MAX(end_date), 'YYYY-MM-DD') AS window_end, TO_CHAR(SUM(netamt), 'TM9') AS net, TO_CHAR(SUM(billqty), 'TM9') AS qty, TO_CHAR(SUM(taxableamt), 'TM9') AS taxable, TO_CHAR(SUM(taxamt), 'TM9') AS tax FROM MISRETAIL."T$POSBILLSUMM_196" WHERE billdate >= DATE '2026-04-01' AND billdate <= DATE '2026-04-30' GROUP BY cube_code, billdate, isvoid ORDER BY billdate, isvoid FETCH FIRST 200 ROWS ONLY
```

### a809_april_by_day

```sql
SELECT cube_code, TO_CHAR(billdate, 'YYYY-MM-DD') AS bill_date, isvoid, COUNT(*) AS row_n, COUNT(DISTINCT sitecode) AS sites, TO_CHAR(MAX(report_date), 'YYYY-MM-DD') AS report_date, TO_CHAR(MIN(start_date), 'YYYY-MM-DD') AS window_start, TO_CHAR(MAX(end_date), 'YYYY-MM-DD') AS window_end, TO_CHAR(SUM(netamt), 'TM9') AS net, TO_CHAR(SUM(billqty), 'TM9') AS qty, TO_CHAR(SUM(taxableamt), 'TM9') AS taxable, TO_CHAR(SUM(taxamt), 'TM9') AS tax FROM MISRETAIL."T$POSBILLSUMM_809" WHERE billdate >= DATE '2026-04-01' AND billdate <= DATE '2026-04-30' GROUP BY cube_code, billdate, isvoid ORDER BY billdate, isvoid FETCH FIRST 200 ROWS ONLY
```

### a750_april_by_day

```sql
SELECT cube_code, TO_CHAR(billdate, 'YYYY-MM-DD') AS bill_date, isvoid, COUNT(*) AS row_n, COUNT(DISTINCT sitecode) AS sites, TO_CHAR(MAX(report_date), 'YYYY-MM-DD') AS report_date, TO_CHAR(MIN(start_date), 'YYYY-MM-DD') AS window_start, TO_CHAR(MAX(end_date), 'YYYY-MM-DD') AS window_end, TO_CHAR(SUM(netamt), 'TM9') AS net, TO_CHAR(SUM(billqty), 'TM9') AS qty, TO_CHAR(SUM(taxableamt), 'TM9') AS taxable, TO_CHAR(SUM(taxamt), 'TM9') AS tax FROM MISRETAIL."T$POSBILLSUMM_750" WHERE billdate >= DATE '2026-04-01' AND billdate <= DATE '2026-04-30' GROUP BY cube_code, billdate, isvoid ORDER BY billdate, isvoid FETCH FIRST 200 ROWS ONLY
```

## sales_probe_05c (run_20261005_039, created 2026-10-05T13:20:48+00:00)

| dataset | kind | status | rows | cap | seconds | guard hash |
|---|---|---|---|---|---|---|
| c1_aug_null_counts_and_sums | extract | ok | 2 | 5 | 10.5 | f7b4213187 |
| c2_aug_by_tax_slab | extract | ok | 5 | 200 | 6.1 | 580647336f |
| c3_aug_store_day_components | extract | ok | 6046 | 20000 | 6.1 | 853f9c3085 |

Notes:

SQL:

### c1_aug_null_counts_and_sums

```sql
SELECT isvoid, COUNT(*) AS row_n, COUNT(mrpamt) AS n_mrpamt, COUNT(basicamt) AS n_basicamt, COUNT(saleamt) AS n_saleamt, COUNT(returnamt) AS n_returnamt, COUNT(promoamt) AS n_promoamt, COUNT(grossamt) AS n_grossamt, COUNT(itemdiscountamt) AS n_itemdiscountamt, COUNT(billdiscountamt) AS n_billdiscountamt, COUNT(lpdiscountamt) AS n_lpdiscountamt, COUNT(totaldiscountamt) AS n_totaldiscountamt, COUNT(netamt) AS n_netamt, COUNT(taxableamt) AS n_taxableamt, COUNT(taxamt) AS n_taxamt, COUNT(extrataxamt) AS n_extrataxamt, COUNT(taxpercent) AS n_taxpercent, COUNT(billqty) AS n_billqty, TO_CHAR(SUM(mrpamt), 'TM9') AS s_mrpamt, TO_CHAR(SUM(basicamt), 'TM9') AS s_basicamt, TO_CHAR(SUM(saleamt), 'TM9') AS s_saleamt, TO_CHAR(SUM(returnamt), 'TM9') AS s_returnamt, TO_CHAR(SUM(promoamt), 'TM9') AS s_promoamt, TO_CHAR(SUM(grossamt), 'TM9') AS s_grossamt, TO_CHAR(SUM(itemdiscountamt), 'TM9') AS s_itemdiscountamt, TO_CHAR(SUM(billdiscountamt), 'TM9') AS s_billdiscountamt, TO_CHAR(SUM(lpdiscountamt), 'TM9') AS s_lpdiscountamt, TO_CHAR(SUM(totaldiscountamt), 'TM9') AS s_totaldiscountamt, TO_CHAR(SUM(netamt), 'TM9') AS s_netamt, TO_CHAR(SUM(taxableamt), 'TM9') AS s_taxableamt, TO_CHAR(SUM(taxamt), 'TM9') AS s_taxamt, TO_CHAR(SUM(extrataxamt), 'TM9') AS s_extrataxamt, TO_CHAR(SUM(billqty), 'TM9') AS s_billqty FROM MISRETAIL."T$POSBILLSUMM_809" WHERE billdate >= DATE '2026-08-01' AND billdate <= DATE '2026-08-31' GROUP BY isvoid FETCH FIRST 5 ROWS ONLY
```

### c2_aug_by_tax_slab

```sql
SELECT taxpercent, taxdescription, COUNT(*) AS row_n, TO_CHAR(SUM(netamt), 'TM9') AS net, TO_CHAR(SUM(taxableamt), 'TM9') AS taxable, TO_CHAR(SUM(taxamt), 'TM9') AS tax, TO_CHAR(SUM(extrataxamt), 'TM9') AS extratax, TO_CHAR(SUM(grossamt), 'TM9') AS gross, TO_CHAR(SUM(totaldiscountamt), 'TM9') AS totaldisc, TO_CHAR(SUM(itemdiscountamt), 'TM9') AS itemdisc, TO_CHAR(SUM(billdiscountamt), 'TM9') AS billdisc, TO_CHAR(SUM(lpdiscountamt), 'TM9') AS lpdisc FROM MISRETAIL."T$POSBILLSUMM_809" WHERE billdate >= DATE '2026-08-01' AND billdate <= DATE '2026-08-31' AND isvoid = 'No' GROUP BY taxpercent, taxdescription FETCH FIRST 200 ROWS ONLY
```

### c3_aug_store_day_components

```sql
SELECT TO_CHAR(sitecode) AS site_code, TO_CHAR(billdate, 'YYYY-MM-DD') AS bill_date, TO_CHAR(SUM(mrpamt), 'TM9') AS mrp, TO_CHAR(SUM(basicamt), 'TM9') AS basic, TO_CHAR(SUM(saleamt), 'TM9') AS sale, TO_CHAR(SUM(returnamt), 'TM9') AS returns, TO_CHAR(SUM(promoamt), 'TM9') AS promo, TO_CHAR(SUM(grossamt), 'TM9') AS gross, TO_CHAR(SUM(itemdiscountamt), 'TM9') AS itemdisc, TO_CHAR(SUM(billdiscountamt), 'TM9') AS billdisc, TO_CHAR(SUM(lpdiscountamt), 'TM9') AS lpdisc, TO_CHAR(SUM(totaldiscountamt), 'TM9') AS totaldisc, TO_CHAR(SUM(netamt), 'TM9') AS net, TO_CHAR(SUM(taxableamt), 'TM9') AS taxable, TO_CHAR(SUM(taxamt), 'TM9') AS tax, TO_CHAR(SUM(extrataxamt), 'TM9') AS extratax, TO_CHAR(SUM(billqty), 'TM9') AS qty FROM MISRETAIL."T$POSBILLSUMM_809" WHERE billdate >= DATE '2026-08-01' AND billdate <= DATE '2026-08-31' AND isvoid = 'No' GROUP BY sitecode, billdate FETCH FIRST 20000 ROWS ONLY
```

## sales_probe_05e (run_20261005_040, created 2026-10-05T13:21:32+00:00)

| dataset | kind | status | rows | cap | seconds | guard hash |
|---|---|---|---|---|---|---|
| e196_april_components | extract | ok | 1 | 5 | 6.2 | af60606364 |
| e809_april_components | extract | ok | 1 | 5 | 6.1 | 5fab6148ec |

Notes:

SQL:

### e196_april_components

```sql
SELECT 196 AS instance_code, COUNT(*) AS row_n, TO_CHAR(SUM(mrpamt), 'TM9') AS s_mrpamt, TO_CHAR(SUM(basicamt), 'TM9') AS s_basicamt, TO_CHAR(SUM(saleamt), 'TM9') AS s_saleamt, TO_CHAR(SUM(returnamt), 'TM9') AS s_returnamt, TO_CHAR(SUM(promoamt), 'TM9') AS s_promoamt, TO_CHAR(SUM(grossamt), 'TM9') AS s_grossamt, TO_CHAR(SUM(itemdiscountamt), 'TM9') AS s_itemdiscountamt, TO_CHAR(SUM(billdiscountamt), 'TM9') AS s_billdiscountamt, TO_CHAR(SUM(lpdiscountamt), 'TM9') AS s_lpdiscountamt, TO_CHAR(SUM(totaldiscountamt), 'TM9') AS s_totaldiscountamt, TO_CHAR(SUM(netamt), 'TM9') AS s_netamt, TO_CHAR(SUM(taxableamt), 'TM9') AS s_taxableamt, TO_CHAR(SUM(taxamt), 'TM9') AS s_taxamt, TO_CHAR(SUM(extrataxamt), 'TM9') AS s_extrataxamt, TO_CHAR(SUM(billqty), 'TM9') AS s_billqty FROM MISRETAIL."T$POSBILLSUMM_196" WHERE billdate >= DATE '2026-04-01' AND billdate <= DATE '2026-04-30' AND isvoid = 'No' FETCH FIRST 5 ROWS ONLY
```

### e809_april_components

```sql
SELECT 809 AS instance_code, COUNT(*) AS row_n, TO_CHAR(SUM(mrpamt), 'TM9') AS s_mrpamt, TO_CHAR(SUM(basicamt), 'TM9') AS s_basicamt, TO_CHAR(SUM(saleamt), 'TM9') AS s_saleamt, TO_CHAR(SUM(returnamt), 'TM9') AS s_returnamt, TO_CHAR(SUM(promoamt), 'TM9') AS s_promoamt, TO_CHAR(SUM(grossamt), 'TM9') AS s_grossamt, TO_CHAR(SUM(itemdiscountamt), 'TM9') AS s_itemdiscountamt, TO_CHAR(SUM(billdiscountamt), 'TM9') AS s_billdiscountamt, TO_CHAR(SUM(lpdiscountamt), 'TM9') AS s_lpdiscountamt, TO_CHAR(SUM(totaldiscountamt), 'TM9') AS s_totaldiscountamt, TO_CHAR(SUM(netamt), 'TM9') AS s_netamt, TO_CHAR(SUM(taxableamt), 'TM9') AS s_taxableamt, TO_CHAR(SUM(taxamt), 'TM9') AS s_taxamt, TO_CHAR(SUM(extrataxamt), 'TM9') AS s_extrataxamt, TO_CHAR(SUM(billqty), 'TM9') AS s_billqty FROM MISRETAIL."T$POSBILLSUMM_809" WHERE billdate >= DATE '2026-04-01' AND billdate <= DATE '2026-04-30' AND isvoid = 'No' FETCH FIRST 5 ROWS ONLY
```

## sales_probe_05d (run_20261005_041, created 2026-10-05T13:21:59+00:00)

| dataset | kind | status | rows | cap | seconds | guard hash |
|---|---|---|---|---|---|---|
| d1_store353_aug_daily | extract | ok | 31 | 40 | 6.5 | a9d28cc3e9 |
| d2_store353_exception_days_by_slab | extract | ok | 10 | 200 | 6.1 | f88242aec2 |

Notes:

SQL:

### d1_store353_aug_daily

```sql
SELECT TO_CHAR(billdate, 'YYYY-MM-DD') AS bill_date, COUNT(*) AS row_n, TO_CHAR(SUM(netamt), 'TM9') AS net, TO_CHAR(SUM(taxableamt), 'TM9') AS taxable, TO_CHAR(SUM(taxamt), 'TM9') AS tax, TO_CHAR(SUM(extrataxamt), 'TM9') AS extratax, TO_CHAR(SUM(grossamt), 'TM9') AS gross, TO_CHAR(SUM(totaldiscountamt), 'TM9') AS totaldisc, TO_CHAR(SUM(returnamt), 'TM9') AS returns, TO_CHAR(SUM(billqty), 'TM9') AS qty FROM MISRETAIL."T$POSBILLSUMM_809" WHERE billdate >= DATE '2026-08-01' AND billdate <= DATE '2026-08-31' AND isvoid = 'No' AND sitecode = 353 GROUP BY billdate ORDER BY billdate FETCH FIRST 40 ROWS ONLY
```

### d2_store353_exception_days_by_slab

```sql
SELECT TO_CHAR(billdate, 'YYYY-MM-DD') AS bill_date, taxpercent, taxdescription, COUNT(*) AS row_n, TO_CHAR(SUM(netamt), 'TM9') AS net, TO_CHAR(SUM(taxableamt), 'TM9') AS taxable, TO_CHAR(SUM(taxamt), 'TM9') AS tax, TO_CHAR(SUM(extrataxamt), 'TM9') AS extratax, TO_CHAR(SUM(billqty), 'TM9') AS qty FROM MISRETAIL."T$POSBILLSUMM_809" WHERE ((billdate >= DATE '2026-08-06' AND billdate <= DATE '2026-08-06') OR (billdate >= DATE '2026-08-22' AND billdate <= DATE '2026-08-22') OR (billdate >= DATE '2026-08-27' AND billdate <= DATE '2026-08-27')) AND isvoid = 'No' AND sitecode = 353 GROUP BY billdate, taxpercent, taxdescription ORDER BY billdate, taxpercent FETCH FIRST 200 ROWS ONLY
```

## Guard and timeout events

None at run time in any probe. The plan stage rejected issues before sending, and they were fixed in the SQL before the run: master dumps needed a row cap; `a9` needed a range predicate instead of `IN`.

## Indirect SSRK exposure

`V_CFO_DASHBOARD_SL_V`, `V_SALE_BUCKET_WISE`, `V_DAYWISE_BILLCUT`, `V_SALE_COMPARE_ABV_ASP` and others are MISRETAIL views that read `SSRK.PSITE_POSBILL`, `SSRK.PSITE_POSBILLITEM` and `SSRK.INVSTOCK` underneath. The broker queries only MISRETAIL objects, but scanning those views reads production tables indirectly (the slowest probes above). Scans of those views should be kept few and narrow.
