"""Cash serving views over gold_fpa.cash_drawer_store (+ voucher_lines for month-to-date and last activity).
Store Till Cash = ledger 1000000008 (Cash Drawer) by cost-tag site. Bank-ledger book: NO source in gold_fpa yet (requested from 01-Data Extraction)
so cash.v_bank_ledger is empty and the bank card shows no ledgers."""
TILL_LEDGER = 1000000008

RELATIONS = {
    "cash.v_serving_run": """SELECT 'CASH-' || to_char(as_of_date, 'YYYYMMDD') AS run_id, as_of_date, as_of_date AS till_balance_date, 'verified' AS recon_state,
        'live' AS publication_state, 'gold_fpa-1' AS contract_version, max(_loaded_at) AS extract_finished_at, max(_loaded_at) AS loaded_at,
        count(*) AS expected_store_rows, (SELECT count(*) FROM gold_fpa.bank_ledger_book)::int AS expected_bank_rows FROM gold_fpa.cash_drawer_store GROUP BY as_of_date""",
    "cash.v_store_till": f"""SELECT 'CASH-' || to_char(c.as_of_date, 'YYYYMMDD') AS run_id, c.site_code, coalesce(c.store_name, 'Site ' || c.site_code) AS store_name,
        c.cumulative_balance, coalesce(m.mtd_debit, 0) AS mtd_debit, coalesce(m.mtd_credit, 0) AS mtd_credit,
        c.fy_debit_posted AS fytd_debit, c.fy_credit_posted AS fytd_credit, m.last_activity_date
        FROM gold_fpa.cash_drawer_store c
        LEFT JOIN (SELECT tag_site_code, sum(damount) FILTER (WHERE entdt >= date_trunc('month', current_date)) AS mtd_debit,
                          sum(camount) FILTER (WHERE entdt >= date_trunc('month', current_date)) AS mtd_credit, max(entdt) AS last_activity_date
                   FROM (SELECT * FROM gold_fpa.voucher_lines WHERE entity = 'RETAIL') WHERE glcode = {TILL_LEDGER} AND release_status = 'P' AND entdt <= current_date GROUP BY 1) m
               ON m.tag_site_code = c.site_code""",
    # gold_fpa.bank_ledger_book: 34 bank/cash ledgers, RETAIL entity only. The old mart had three sources; gold has ONE ledger register:
    #   site_register  = the ledger book (all 34 ledgers)  - what the Cash page shows
    #   gl_register    = the same register (there is no independent second source, so the cross-check is trivially true)
    #   prior_year_closing = prior-year closing per ledger, used for the 'opening ties to prior-year closing' test (2 ledgers do not tie)
    "cash.v_bank_ledger": """SELECT 'CASH-' || to_char(register_report_date, 'YYYYMMDD') AS run_id, ledger_code, ledger_name, gl_type, nature, extinct, has_movement,
        opening_balance, posted_dr, posted_cr, posted_closing, unposted_dr, unposted_cr, unposted_movement, including_unposted, future_net,
        last_posted_date, last_entry_date, register_report_date, sites, s.src AS source
        FROM gold_fpa.bank_ledger_book CROSS JOIN (VALUES ('site_register'), ('gl_register')) AS s(src)
        UNION ALL
        SELECT 'CASH-' || to_char(register_report_date, 'YYYYMMDD'), ledger_code, ledger_name, gl_type, nature, extinct, false,
        coalesce(prior_year_closing, 0), 0, 0, coalesce(prior_year_closing, 0), 0, 0, 0, coalesce(prior_year_closing, 0), 0, NULL, NULL, register_report_date, sites, 'prior_year_closing'
        FROM gold_fpa.bank_ledger_book""",
    "cash.v_control": """SELECT 'CASH-' || to_char(c.period, 'YYYYMMDD') AS run_id, 'STORE_ROWS' AS control_id, 'all stores' AS dimension, 'extract' AS left_layer,
        c.row_count AS left_value, 'mart' AS right_layer, count(s.*)::numeric AS right_value, c.row_count - count(s.*) AS variance,
        CASE WHEN c.row_count = count(s.*) THEN 'PASS' ELSE 'FAIL' END AS verdict
        FROM gold_fpa.control_totals c, gold_fpa.cash_drawer_store s WHERE c.table_name = 'cash_drawer_store' GROUP BY c.period, c.row_count
        UNION ALL
        SELECT 'CASH-' || to_char(c.period, 'YYYYMMDD'), 'CUMULATIVE_BALANCE', 'all stores', 'extract', c.sum_amount::numeric, 'mart', sum(s.cumulative_balance),
        c.sum_amount::numeric - sum(s.cumulative_balance), CASE WHEN abs(c.sum_amount::numeric - sum(s.cumulative_balance)) < 0.005 THEN 'PASS' ELSE 'FAIL' END
        FROM gold_fpa.control_totals c, gold_fpa.cash_drawer_store s WHERE c.table_name = 'cash_drawer_store' GROUP BY c.period, c.sum_amount
        UNION ALL
        SELECT 'CASH-' || to_char(c.period, 'YYYYMMDD'), 'BANK_POSTED_CLOSING', c.group_key, 'extract', c.sum_amount::numeric, 'mart', coalesce(sum(b.posted_closing), 0),
        c.sum_amount::numeric - coalesce(sum(b.posted_closing), 0), CASE WHEN abs(c.sum_amount::numeric - coalesce(sum(b.posted_closing), 0)) < 0.005 THEN 'PASS' ELSE 'FAIL' END
        FROM gold_fpa.control_totals c LEFT JOIN gold_fpa.bank_ledger_book b ON b.nature = c.group_key
        WHERE c.table_name = 'bank_ledger_book' GROUP BY c.period, c.group_key, c.sum_amount""",
}
