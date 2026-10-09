"""Cash serving views over gold_fpa.cash_drawer_store (+ voucher_lines for month-to-date and last activity).
Store Till Cash = ledger 1000000008 (Cash Drawer) by cost-tag site. Bank-ledger book: NO source in gold_fpa yet (requested from 01-Data Extraction)
so cash.v_bank_ledger is empty and the bank card shows no ledgers."""
TILL_LEDGER = 1000000008

RELATIONS = {
    "cash.v_serving_run": """SELECT 'CASH-' || to_char(as_of_date, 'YYYYMMDD') AS run_id, as_of_date, as_of_date AS till_balance_date, 'verified' AS recon_state,
        'live' AS publication_state, 'gold_fpa-1' AS contract_version, max(_loaded_at) AS extract_finished_at, max(_loaded_at) AS loaded_at,
        count(*) AS expected_store_rows, 0 AS expected_bank_rows FROM gold_fpa.cash_drawer_store GROUP BY as_of_date""",
    "cash.v_store_till": f"""SELECT 'CASH-' || to_char(c.as_of_date, 'YYYYMMDD') AS run_id, c.site_code, coalesce(c.store_name, 'Site ' || c.site_code) AS store_name,
        c.cumulative_balance, coalesce(m.mtd_debit, 0) AS mtd_debit, coalesce(m.mtd_credit, 0) AS mtd_credit,
        c.fy_debit_posted AS fytd_debit, c.fy_credit_posted AS fytd_credit, m.last_activity_date
        FROM gold_fpa.cash_drawer_store c
        LEFT JOIN (SELECT tag_site_code, sum(damount) FILTER (WHERE entdt >= date_trunc('month', current_date)) AS mtd_debit,
                          sum(camount) FILTER (WHERE entdt >= date_trunc('month', current_date)) AS mtd_credit, max(entdt) AS last_activity_date
                   FROM gold_fpa.voucher_lines WHERE glcode = {TILL_LEDGER} AND release_status = 'P' AND entdt <= current_date GROUP BY 1) m
               ON m.tag_site_code = c.site_code""",
    "cash.v_bank_ledger": """SELECT NULL::text AS run_id, NULL::bigint AS ledger_code, NULL::text AS ledger_name, NULL::text AS gl_type, NULL::text AS nature,
        NULL::boolean AS extinct, NULL::boolean AS has_movement, NULL::numeric AS opening_balance, NULL::numeric AS posted_dr, NULL::numeric AS posted_cr,
        NULL::numeric AS posted_closing, NULL::numeric AS unposted_dr, NULL::numeric AS unposted_cr, NULL::numeric AS unposted_movement,
        NULL::numeric AS including_unposted, NULL::numeric AS future_net, NULL::date AS last_posted_date, NULL::date AS last_entry_date,
        NULL::date AS register_report_date, NULL::text AS sites, NULL::text AS source WHERE false""",
    "cash.v_control": """SELECT 'CASH-' || to_char(c.period, 'YYYYMMDD') AS run_id, 'STORE_ROWS' AS control_id, 'all stores' AS dimension, 'extract' AS left_layer,
        c.row_count AS left_value, 'mart' AS right_layer, count(s.*)::numeric AS right_value, c.row_count - count(s.*) AS variance,
        CASE WHEN c.row_count = count(s.*) THEN 'PASS' ELSE 'FAIL' END AS verdict
        FROM gold_fpa.control_totals c, gold_fpa.cash_drawer_store s WHERE c.table_name = 'cash_drawer_store' GROUP BY c.period, c.row_count
        UNION ALL
        SELECT 'CASH-' || to_char(c.period, 'YYYYMMDD'), 'CUMULATIVE_BALANCE', 'all stores', 'extract', c.sum_amount::numeric, 'mart', sum(s.cumulative_balance),
        c.sum_amount::numeric - sum(s.cumulative_balance), CASE WHEN abs(c.sum_amount::numeric - sum(s.cumulative_balance)) < 0.005 THEN 'PASS' ELSE 'FAIL' END
        FROM gold_fpa.control_totals c, gold_fpa.cash_drawer_store s WHERE c.table_name = 'cash_drawer_store' GROUP BY c.period, c.sum_amount""",
}
