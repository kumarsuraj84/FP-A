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
- Never decrypt or reuse another application's Oracle credential (e.g. Inventory Automation) for FP&A.
- Do not run Gate 2 until Gate 1 has been reviewed by the user.
- All Oracle activity in FP&A is source discovery and read-only extraction only.

## Connectivity

- ODBC via pyodbc, Windows DSN `ORACLE CONNECTION`, driver `Oracle in OraClient12Home1` (64-bit), Python 3.11.
- Credentials live only in git-ignored `backend/.env` (`ORACLE_USER`, `ORACLE_PASSWORD`). Never commit or print them.
