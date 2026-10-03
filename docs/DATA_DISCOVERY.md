# Data Discovery
**Status: BLOCKED.** The build sandbox has no ORACLE_* variables and no route to the Oracle host, so nothing below has been observed live. No schema, row count, column or total in this repo is invented.

## Runbook (run from a host with read-only Oracle access)
1. Set `ORACLE_DSN/ORACLE_USER/ORACLE_PASSWORD` (read-only account) in `.env`; `python -m app.cli oracle-check`.
2. Inventory: `all_tab_columns` / `all_objects` for `CUBE$*` and the raw tables (FINPOST, FINGL, FINSL, FINGL_SITE, FINJRNDET, FINJRNMAIN, FINGLOP, FINGRP); `all_views`/`all_source` for `V_FINANCE_P_AND_L_*`, `T_FINANCE_P_AND_L_*`, `T_FINANCE_RAJEEV_*` (capture definitions).
3. Per source call `app.discovery.profiler.profile_object(...)` → columns/types, rows, min/max date, debit/credit totals, distinct counts, null rates, samples → write JSON under `reports/generated/` (git-ignored; do not commit raw extracts).
4. Confirm the cube discriminator column, registry codes/date windows, release-status values, and last-refresh metadata.
## Priority questions (answer from live data)
FINOTSD: open items vs balances, doc/due dates, adjustment links · how advances are posted (GL/SL, narration, dr balance on creditor SL) · cash/bank GLs and FINGLOP opening logic · whether finance's approved P&L views match any mart definition.
## Facts from CityKart data-model docs (CONFIRMED by documentation, not re-verified live)
Fiscal year Apr–Mar; CHAR columns need TRIM; MOP lives in `MISRETAIL.CUBE$BILLCOLL` (`CUBENAME='MOP_<FY>'`, BILLTYPE `POSBill`); settlement in `T_FINANCE_CREDIT_SETTLEMENT`; cash balance view `V_FINANCE_CASH_CUMLATIVE_BLNC`; `V_FINANCE_MOP_OUTPUT` exists.
