# FP&A project rules

## Oracle access is READ-ONLY at the database LOGIN-account level (absolute rule)

- `MISRETAIL` is CityKart's Oracle MIS / Data Warehouse (NOT the live Ginesys transactional server) and is an appropriate READ SOURCE for FP&A.
  Architecture: `Ginesys / operational systems -> MISRETAIL Data Warehouse -> FP&A read-only extraction -> PostgreSQL finance mart -> API -> CFO application`.
- FP&A MAY read required finance/reporting data from the `MISRETAIL` schema/objects. Do not describe it as the live ERP, and do not treat it as prohibited as a source.
- FP&A must NEVER LOGIN as the `MISRETAIL` schema-owner/admin account, or any account with write-capable privileges. Connect only with a dedicated read-only Oracle user that has SELECT on the required `MISRETAIL` objects.
- Do not rely only on the application's SQL guard (`assert_read_only`). The Oracle login account itself must be unable to modify data or schema.
- Before ANY Oracle discovery or extraction:
  1. Run `python -m app.cli oracle-check`.
  2. Inspect the privilege classification.
  3. Proceed only if the LOGIN account is `APPEARS_READ_ONLY`.
  4. If any write-capable privilege is detected (`WRITE_CAPABLE_PRIVILEGES_PRESENT`), STOP immediately and report the privilege names. Do not run discovery.
- The FP&A account must hold only `CREATE SESSION` plus explicit `SELECT` grants on required finance objects and metadata views (`ALL_OBJECTS`, `ALL_TAB_COLUMNS`, `ALL_VIEWS`, `ALL_DEPENDENCIES`, `ALL_CONSTRAINTS`, `ALL_CONS_COLUMNS`, `ALL_INDEXES`, `ALL_IND_COLUMNS`, ...).
- It must NOT hold: INSERT, UPDATE, DELETE, MERGE, CREATE, ALTER, DROP, GRANT, EXECUTE, LOCK, ADMINISTER (or `ANY` equivalents), DBA, or legacy CONNECT/RESOURCE roles that bring excess privileges.
- Never test read-only status by attempting writes. Never change Oracle data, schema or grants, create objects, or call mutating packages.
- Never decrypt, copy, expose or reuse another application's Oracle credential (e.g. Inventory Automation) for FP&A.
- Do not run Gate 2 until Gate 1 has been reviewed by the user.
- All Oracle activity in FP&A is source discovery and read-only extraction only.

## Controlled extraction through Inventory Automation (approved 2026-10-04)

FP&A application code must never authenticate to Oracle using the `MISRETAIL` owner/admin account. For controlled source discovery and extraction, FP&A may consume Parquet files produced by the existing Inventory Automation extraction service, which uses its own separately managed Oracle connection:

`MISRETAIL DW -> Inventory Automation SELECT-only extractor -> Parquet + manifest -> FP&A inbox (data/inbox/)`

**Scope (frozen 2026-10-04):**
- **Never query SSRK for FP&A. SSRK is live production and out of scope.** The same applies to `GINARCHIVE`, `GINVIEW`, `GINSSOT`, `REPORT`, `COGS_MIGRATION`, any `PUBLIC` synonym (these resolve to SSRK objects) and every other schema.
- FP&A finance discovery and extraction must use the **MISRETAIL data warehouse** through the existing Inventory Automation SELECT-only extraction engine.
- FP&A itself must not authenticate to Oracle using MISRETAIL credentials.
- The broker guard enforces this in code, not just in words: metadata queries must restrict to owner `'MISRETAIL'`, data objects must be `MISRETAIL`-qualified, and any other schema name (even inside a string literal) is rejected.

- FP&A must not decrypt, copy, expose, log or reuse Inventory Automation database credentials. The broker (`tools/extraction_broker/`) only talks to the running app on localhost and never reads connection details beyond its numeric id.
- Every extraction run through Inventory Automation must be SELECT-only, bounded, capped, streamed, auditable and isolated:
  - the broker's own guard runs first (the app validates SQL only at save time and its engine does not re-check): single SELECT/WITH, no DML/DDL/PL/SQL/locking/packages/db-links/INTO, and a hard row cap on every query;
  - discovery before extraction, and metadata before data: no blind `COUNT(*)` on finance objects (use `ALL_TABLES` statistics); data queries must be bounded by a date predicate, name their columns, and run one at a time;
  - `platform.db` is backed up before the broker changes it; FP&A queries are added only under the `FPA__` name prefix (immutable, hash-suffixed); existing Inventory Automation queries and its production behaviour are never modified.
- Output is Parquet plus `manifest.json` only. FP&A validates the manifest (presence, size, sha256, row counts, status) before loading anything. The inbox is git-ignored: the files hold real data and are never committed.

## Connectivity

- ODBC via pyodbc, Windows DSN `ORACLE CONNECTION`, driver `Oracle in OraClient12Home1` (64-bit), Python 3.11.
- Credentials live only in git-ignored `backend/.env` (`ORACLE_USER`, `ORACLE_PASSWORD`). Never commit or print them.
