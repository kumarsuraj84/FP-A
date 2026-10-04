# Creditors pilot mart (schema `cred`)

Design: `docs/creditors_pilot/MART_PROPOSAL.md`. Scratch UAT evidence: `docs/creditors_pilot/MART_SCRATCH_UAT_EVIDENCE.md`.

- `sql/000_roles.sql`  five NOLOGIN roles (`cred_owner`, `cred_loader`, `cred_verifier`, `cred_api_reader`, `cred_finance_reader`). Cluster-wide; run by the DB admin.
- `sql/001_cred_schema.sql`  schema `cred`, owned by `cred_owner`: immutable run-versioned tables, controlled functions, masked and named views, grants.
- `migrate.py`  applies both scripts to one database as an administrator.
- `tests/test_cred_mart_db.py`  the UAT. It builds a PRIVATE temporary PostgreSQL instance from the installed binaries (own folder, random localhost port) and deletes it afterwards. It never connects to any configured database.

## Running the UAT

    python -m pytest tools/creditors_mart/tests/test_cred_mart_db.py -q

## Creating the real pilot database (admin steps, after the scratch UAT is accepted)

1. As the database admin: `CREATE DATABASE fpa_pilot;` (empty, separate from the application database `fpa`).
2. In YOUR terminal only (never in the repository or in chat):
   `set FPA_PG_ADMIN_URL=postgresql://<admin>:<password>@localhost:5432/fpa_pilot`
3. `python tools/creditors_mart/migrate.py`
4. Attach LOGIN roles or passwords to the five roles yourself; nothing here stores a credential.
