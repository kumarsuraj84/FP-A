# Finance Mart (PROPOSED)
DDL: `backend/app/mart/schema.sql`. Built now: registry, config_audit, `stg_finance_entry` (immutable raw + lineage), `fact_finance_entry` (typed, lineage columns: source system/object/cube/FY/row key/extract+load timestamps), `recon_run`.
Deferred until discovery proves support: dim_store/gl/subledger/vendor, fact_creditor_outstanding, fact_vendor_advance, fact_unreconciled_item, fact_cash_bank, fact_budget, fact_store_pnl, fact_mop/tds/petty_cash/service_expense/committed_spend.
`fact_finance_entry` columns follow the brief's field list — UNVERIFIED against live.
