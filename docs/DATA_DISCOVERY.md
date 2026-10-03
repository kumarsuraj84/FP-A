# Data Discovery
> **NO LIVE FINANCIAL DATA HAS YET BEEN VALIDATED.** Discovery has not run; status BLOCKED (no Oracle access yet).

## Principles
Low load, metadata first, no guessed names, labelled output (CONFIRMED / UNVERIFIED / BLOCKED), no secrets in output (`redact`), generated JSON goes to git-ignored `reports/generated/`.

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

## Recommended first live pass (controlled, in this order)
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
