# Handover note — CityKart FP&A / CFO Finance OS

**Repo:** github.com/kumarsuraj84/FP-A · **Branch:** `ccr-fa52f263-etuoeq` (never merge to main without explicit approval) · **Foundation head approved by review:** `37ec8424`; later commit `218e649` adds ODBC.
**Local clone (user's PC):** `D:\AI_WORKING\FPA` → work in `backend\` (venv `.venv`, Python 3.11, `pip install -e ".[dev,odbc]"`).
**Status:** NO LIVE FINANCIAL DATA HAS YET BEEN VALIDATED. Live Oracle discovery has not run in any Claude session. The user ran the discovery commands on their own PC but the output has not been shared yet.

## Why a new session
The earlier session was a cloud container: no Oracle credentials, no route to the company network, no access to `D:\`. Live discovery needs a session whose terminal runs ON the user's PC (Claude Code desktop/CLI in `D:\AI_WORKING\FPA`), where the ODBC data source already used by CityKart's existing extraction app is available.

## What exists (all tested, 121 passing, synthetic fixtures only)
- `app/oracle/client.py` — SELECT-only guard (secondary control) + ODBC (pyodbc) or oracledb-thin driver; strict named→`?` bind conversion; upper-case row keys. PRIMARY safety = the Oracle account must be SELECT-only (user should provide a dedicated one, not the extraction app's login).
- `app/registry/` — logical dataset (source_type, logical_cube_name, copy_id) is separate from the physical Oracle object (owner, name, type, access mode SEPARATE_OBJECT | SHARED_DISCRIMINATOR + discriminator col/value). All seeded SITE_REG copies (687,749,805,548,874,902,844 = FY20-21…FY26-27) are UNVERIFIED with no physical object; hints exist only for `MISRETAIL.T$FINREGSITE_844/_902` (existence-check candidates, never used to build SQL). Copy ids are NOT chronological.
- `app/discovery/` — `cube_registry.py` (locates `OLAP_DATACUBE_LIST`, bounded read, hint existence checks, `confirm_mapping`), `definitions.py` (P&L object definitions, metadata only), `profiler.py` (LIGHT default ≤1 aggregate scan; DEEP = chunked null counts, only on request).
- `app/registry/evidence.py` — structured mapping evidence (artifact path+sha256, row index+snapshot); `MACHINE_VERIFIED` (copy id + object name found as exact cell values in the evidence row) vs `OPERATOR_CONFIRMED`. Matcher is generic until OLAP_DATACUBE_LIST's real columns are known.
- `app/ingest/` — source-row identity = (system, owner, object NAME, copy_id, discriminator col, discriminator value, row_key; `''` for none), idempotent promotion with tombstones. Canonical finance transaction key is UNKNOWN (reserved `canonical_txn_key`); no cross-copy dedupe.
- `app/mart/schema.sql` + `bootstrap_admin.sql` (btree_gist installed by DB admin, schema fails fast if missing). Never run on a real Postgres yet.
- `app/ageing/buckets.py` — bucket maths only (0-30,31-60,61-90,91-180,181-365,>365); date basis undecided; no creditor/advance logic. `app/recon/framework.py` — zero-tolerance recon gate.
- CLI (`python -m app.cli`): `registry-status`, `oracle-check`, `discover-cube-registry`, `discover-definitions`, `registry-confirm`, `discover-object`, `profile-source --mode light|deep`. Outputs go to git-ignored `reports/generated/`; `.env` lives in `backend\` (see `.env.example`: `ORACLE_ODBC_DSN`, optional user/password).
- Docs: ARCHITECTURE, FINANCE_SOURCE_REGISTRY, DATA_DISCOVERY, FINANCE_MART, RECONCILIATION, CFO_PRODUCT_SCOPE, KNOWN_GAPS, DECISIONS (D-1…D-19), STAGE1_REPORT.

> **Update (tooling patch):** use `python -m app.cli discovery-run-01 --gate N` (see docs/DATA_DISCOVERY.md, Windows runbook) instead of running phases by hand; it implements Gates 1-5 below, adds `discover-keys`, `profile-group`, `registry-add`, and writes the shareable `reports/generated/LIVE_DISCOVERY_01_SUMMARY.json`.

## Task for the new session: controlled first live pass (user-approved prompt, abridged)
Hard rules: SELECT-only; no DEEP profiling; no ingestion; no creditor/advance/cash/P&L/BS business logic; no frontend; no merge; no credentials or raw finance data in Git; stop if anything looks unsafe or heavy.
- **A** `registry-status`, `oracle-check` (record driver, user, version, UTC time; never test read-only by writing).
- **B** `discover-cube-registry`: document real `OLAP_DATACUBE_LIST` columns/semantics; table of finance rows for SITE_REG/FINREGSITE, GL_REG/FINREG, OUTSTANDING/FINOTSD, MOP/BILLCOLL, BUDGET, TDS, PETTY CASH, SERINV, SERORD. No mappings from similar names.
- **C** `discover-definitions`: `V_FINANCE_P_AND_L_%`, `T_FINANCE_P_AND_L_%`, `T_FINANCE_RAJEEV_%` plus `V_FINANCE_CASH_CUMLATIVE_BLNC`, `V_FINANCE_MOP_OUTPUT`, `T_FINANCE_CREDIT_SETTLEMENT`: names, owners, types, columns, view SQL, underlying objects.
- **D** Resolve ONLY SITE_REG FY26-27 (don't assume 844); determine separate vs shared; `registry-confirm` with `--evidence-file/--evidence-row`; then `registry-status`, `discover-object`; record columns (site, GL, SL, voucher no/date, type, narration, debit, credit, release status, created/modified/released), optimizer row estimate + last-analyzed.
- **E** ONE light profile of current SITE_REG using discovered column names: exact count, min/max date, debit/credit totals, distinct site/GL/SL, bounded unordered sample, release-status distribution (at most one extra aggregate). Stop if large/unsafe.
- **F** Validate coverage: FY26-27 dates? latest txn date, refresh date, released vs unreleased, numeric usable debit/credit, site and SL detail present.
- **G** NO ingestion. Inspect Oracle constraint/index metadata for a stable source row key (PK, unique index, voucher+line…); do not invent concatenated keys unless none exists.
- **H** Only if A–G fine: OUTSTANDING (`CUBE$FINOTSD`) mapping + metadata-only `discover-object`; assess suitability for creditor ageing (GL, subledger/vendor, doc no/date, DUE DATE, debit/credit, outstanding/adjusted amounts, site, type). Stop before ageing.
- Possible small addition: CLI command for constraint/index metadata (Phase G) so it is reproducible.
- **Deliverable:** `docs/LIVE_DISCOVERY_01.md` with sections A–J (environment; cube registry; existing finance objects; SITE_REG current FY; row-identity candidates; OUTSTANDING metadata; differences from prior docs; risks; next queries for creditors/advances/cash/P&L/unreconciled; Finance questions only where data cannot answer — empty if none). Run tests, report count, list commands run, any table scans, runtimes, commit SHA, then STOP for review.

## Principles to keep
Debit balance on a creditor ≠ automatically a vendor advance. Document age ≠ overdue age; use ERP due date if present (evaluate first). Don't ask Finance what the database can show. Trust live evidence over prior docs and record discrepancies. Order after discovery: creditors + advances + unreconciled → cash position → approved P&L → only then CFO UI. Reconciliation variance must be exactly ₹0 for accepted scopes.

## Prior-documentation claims (UNVERIFIED until live)
Cube codes/FY map above; `MISRETAIL.CUBE$BILLCOLL` shared with `CUBENAME='MOP_<FY>'` (from CityKart data-model docs); fiscal year Apr–Mar; MOP/settlement/cash objects `V_FINANCE_MOP_OUTPUT`, `T_FINANCE_CREDIT_SETTLEMENT`, `V_FINANCE_CASH_CUMLATIVE_BLNC`.
