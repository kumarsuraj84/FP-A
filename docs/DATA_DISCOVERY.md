# Data Discovery
> **NO LIVE FINANCIAL DATA HAS YET BEEN VALIDATED.** Discovery has not run; status BLOCKED (no Oracle access yet).

## Principles
Low load, metadata first, no guessed names, labelled output (CONFIRMED / UNVERIFIED / BLOCKED), no secrets in output (`redact`), generated JSON goes to git-ignored `reports/generated/`.

## Execution model
**Cloud Claude = coding + GitHub. A CityKart-network PC = all Oracle execution.** The cloud environment cannot reach CityKart Oracle and must not be asked to. Oracle is Oracle-only in this phase: PostgreSQL is NOT needed for source discovery (it is needed later for mart DDL validation, staging, promotion and reconciliation persistence).

## Windows local runbook (gated; each command runs ONE gate and stops)
```
cd /d D:\AI_WORKING\FPA                  (if your folder is "FP&A" quote it: cd /d "D:\AI_WORKING\FP&A")
git fetch origin
git checkout ccr-fa52f263-etuoeq
git pull
cd backend
py -3.11 -m venv .venv                    (py -3.12 if installed)
.venv\Scripts\activate
pip install -e ".[dev,odbc]"
python -m pytest -q
copy ..\.env.example .env
notepad .env                              (set ORACLE_ODBC_DSN etc.; .env is git-ignored; never print or commit it)
```
**Gate 1 - environment** `python -m app.cli discovery-run-01 --gate 1` (registry-status + oracle-check + privilege inspection; stops if the connection fails; warns if the account holds write-capable privileges - get a SELECT-only account first).
**Gate 2 - cube registry + finance objects** `... --gate 2`. STOP and review `reports\generated\cube_registry_discovery.json`, then YOU confirm the SITE_REG current mapping (the runner never does):
`python -m app.cli registry-confirm SITE_REG --copy <ID> --object OWNER.NAME --evidence-file reports\generated\cube_registry_discovery.json --evidence-row <N>` (add `--access-mode shared --discriminator-column C --discriminator-value V` if it is a shared object).
**Gate 3 - object + key metadata** `... --gate 3 [--site-copy <ID>]` (metadata only). Read the column list it prints.
**Gate 4 - ONE light profile** `... --gate 4 --date-col X --debit-col X --credit-col X --site-col X --gl-col X [--sl-col X] [--release-col X]` (column names from gate 3; one aggregate scan + one bounded sample; stops without scanning if the optimizer estimates >20M rows unless `--allow-large`).
**Gate 5 - release groups + OUTSTANDING** `... --gate 5`. First pass does the release-status aggregate and lists FINOTSD candidate rows. Then YOU run `registry-add --source-type OUTSTANDING --logical-cube CUBE$FINOTSD --copy-id <ID> --date-from YYYY-MM-DD --date-to YYYY-MM-DD` and `registry-confirm OUTSTANDING ...`, and re-run gate 5 (metadata + key discovery only, no scan).
Ad-hoc helpers: `discover-keys SOURCE --copy ID`, `profile-group SOURCE --copy ID --group-col C [--debit-col C --credit-col C]` (one aggregate scan, one column, max 100 groups - code-like columns only).

## Outputs
Everything lands in `reports\generated\` (git-ignored). **Share only `LIVE_DISCOVERY_01_SUMMARY.json`** (rewritten after every gate; structural + aggregate only; whitelist-built; credentials, DSN, Oracle user, local paths, sample rows, narrations, party names are excluded; columns named like USER/EMAIL/CREATED_BY are dropped from cube-list rows; a final redaction pass scrubs configured secrets). It also lists every Oracle query run, its kind (METADATA / DATA_SAMPLE / DATA_AGGREGATE) and runtime - the data-table queries are the ones that touched transaction tables.
**NEVER share or commit:** `.env`; `LOCAL_ONLY_*.json` (sample rows - may contain transaction data); `cube_registry_discovery.json`, `pnl_definitions.json`, `object_*`, `keys_*`, `profile_light_*`, `group_*` (detailed local artifacts); `registry_overlay.json`, `local_entries.json`, `discovery_run_01_state.json`.

## Connectivity
Two drivers, one guarded client (`app/oracle/client.py`). **ODBC** (matches the existing CityKart extraction app; `pip install -e ".[dev,odbc]"`): set `ORACLE_ODBC_DSN=<Windows DSN name>` in `backend/.env` (plus `ORACLE_USER`/`ORACLE_PASSWORD` only if the DSN doesn't store them; or `ORACLE_ODBC_CONNECTION_STRING`). The Python bitness (64-bit) must match the ODBC driver/DSN bitness. **oracledb thin**: `ORACLE_DSN` + user + password. Named binds are converted to positional `?` for ODBC (strict: missing/unused binds raise). Rows come back with upper-case keys on both drivers. `oracle-check` prints driver, `USER`, `v$version` banner (if granted) and UTC time.

## Commands (run from `backend/`; SELECT-only account)
```
python -m app.cli registry-status
python -m app.cli oracle-check
python -m app.cli discover-cube-registry
python -m app.cli registry-confirm SITE_REG --copy 844 --object OWNER.NAME \
   --evidence-file reports/generated/cube_registry_discovery.json --evidence-row <N> [--access-mode shared --discriminator-column <C> --discriminator-value <V>]
python -m app.cli discover-object SITE_REG --copy 844 [--object OWNER.NAME]          # metadata only
python -m app.cli profile-source SITE_REG --copy 844 --mode light \
   --date-col <C> --debit-col <C> --credit-col <C> --distinct-col <C> [--sample-order-by <C>]
python -m app.cli profile-source SITE_REG --copy 844 --mode deep   # only after light looked safe
python -m app.cli discover-definitions            # V_FINANCE_P_AND_L_%, T_FINANCE_P_AND_L_%, T_FINANCE_RAJEEV_%
```
Column-name flags are required because column names are UNVERIFIED; take them from `discover-object` output.

## Oracle load pattern
**oracle-check**: 1 trivial query. **discover-cube-registry**: ~3 metadata queries + 1 read of OLAP_DATACUBE_LIST (bounded to 5000 rows; one query, filtered across character columns if the list is large) + 1 `ALL_OBJECTS` lookup per hint. **discover-object**: 2 metadata queries, **0 table scans, 0 row reads**. **profile-source --mode light**: 2 metadata queries + *at most one* aggregate scan of the object (row count/min-max date/sums/distincts folded into one statement, only if requested) + one bounded sample (`FETCH FIRST n`; unordered unless `--sample-order-by`, since ordering forces a sort). With no aggregate flags light mode does no full scan. **deep**: light + `ceil(columns/100)` null-count scans (36 columns → 1 scan). **discover-definitions**: metadata only (`ALL_OBJECTS`, `ALL_VIEWS`, `ALL_TAB_COLUMNS`). Row counts default to optimizer stats (`ALL_TABLES.NUM_ROWS`, may be stale/absent for views).

## Recommended first live pass (controlled, in this order; the gated runner automates it)
1. `oracle-check` 2. `discover-cube-registry` (locate/read `OLAP_DATACUBE_LIST`) 3. `discover-definitions` (finance P&L objects) 4. resolve SITE_REG FY26-27 (`registry-confirm` with evidence) 5. `discover-object` (metadata only) 6. `profile-source --mode light` 7. compare findings with prior documentation and record discrepancies. No deep profiles until this looks safe; then GL → FINOTSD/outstanding → creditor structure → advances → cash/bank → approved P&L logic.

## Discovery agenda (answer from the database before involving Finance)
1. Cube→object resolution via `OLAP_DATACUBE_LIST`; separate-object vs shared-discriminator; refresh dates; current/auto-refresh flags.
2. Structure/coverage/release-status of SITE_REG then GL_REG, MOP, FINOTSD etc.
3. Existing approved reporting: extract definitions of `V_FINANCE_P_AND_L_*`, `T_FINANCE_P_AND_L_*`, `T_FINANCE_RAJEEV_*`; derive revenue/expense mapping and allocations from them.
4. Creditor structure: FINSL/FINGL/FINOTSD patterns (subledger types, document/due dates, adjustment links, balance sign distribution).
5. Vendor advances: profile creditor subledgers' debit balances and their transaction histories; classification must come from this evidence (a debit creditor balance can mean advance, excess payment, return/credit-note timing, misposting, opening-balance issue…).
6. Cash/bank: candidate GLs from FINGL/FINGRP grouping, FINGLOP opening logic, reconciliation status fields.
7. Only the residue goes to Finance (see KNOWN_GAPS).

## Facts from CityKart data-model docs (CONFIRMED by documentation, not re-verified live)
Fiscal year Apr–Mar; CHAR columns need TRIM; MOP in `MISRETAIL.CUBE$BILLCOLL` (`CUBENAME='MOP_<FY>'`, BILLTYPE `POSBill`); settlement `T_FINANCE_CREDIT_SETTLEMENT`; cash balance `V_FINANCE_CASH_CUMLATIVE_BLNC`; `V_FINANCE_MOP_OUTPUT`. Note: this documents `CUBE$BILLCOLL` as a *shared* object with a `CUBENAME` discriminator, while SITE_REG copies are described as separate `T$…_<id>` objects — i.e. both architectures may coexist, which is why mode is per-entry.
