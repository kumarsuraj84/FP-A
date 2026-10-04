# Creditors pilot mart (schema `cred`)

Design: `docs/creditors_pilot/MART_PROPOSAL.md`. Scratch UAT evidence: `docs/creditors_pilot/MART_SCRATCH_UAT_EVIDENCE.md`.

- `sql/000_roles.sql`  six NOLOGIN roles (`cred_owner`, `cred_loader`, `cred_verifier`, `cred_promoter`, `cred_api_reader`, `cred_finance_reader`). Cluster-wide; run by the DB admin.
- `sql/001_cred_schema.sql`  schema `cred`, owned by `cred_owner`: immutable run-versioned tables, controlled functions, masked and named views, grants.
- `migrate.py`  applies both scripts to one database as an administrator.
- `tests/test_cred_mart_db.py`  the UAT. It builds a PRIVATE temporary PostgreSQL instance from the installed binaries (own folder, random localhost port) and deletes it afterwards. It never connects to any configured database.

## Running the UAT

    python -m pytest tools/creditors_mart/tests/test_cred_mart_db.py -q

## Creating the real pilot database (administrator)

1. In YOUR terminal only (never a file, never chat): `set FPA_PG_ADMIN_URL=postgresql://<admin>:<password>@localhost:5432/postgres`
2. `python tools/creditors_mart/migrate.py --create-database fpa_pilot`  (creates the empty database if missing, then applies the reviewed migrations; refuses `fpa`, `postgres` and the template databases)
3. `python tools/creditors_mart/verify_install.py fpa_pilot`  (read-only; checks owners, role attributes, the whole privilege matrix, guard triggers and that nothing is loaded; writes `docs/creditors_pilot/MART_REAL_INSTALL_EVIDENCE.md`)
4. Attach LOGIN roles or passwords to the six roles yourself. Nothing here stores a credential.
