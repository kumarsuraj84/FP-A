# Creditors pilot mart (schema `cred`)

Design: `docs/creditors_pilot/MART_PROPOSAL.md`. Scratch UAT evidence: `docs/creditors_pilot/MART_SCRATCH_UAT_EVIDENCE.md`.

- `sql/000_roles.sql`  six NOLOGIN roles (`cred_owner`, `cred_loader`, `cred_verifier`, `cred_promoter`, `cred_api_reader`, `cred_finance_reader`). Cluster-wide; run by the DB admin.
- `sql/001_cred_schema.sql`  schema `cred`, owned by `cred_owner`: immutable run-versioned tables, controlled functions, masked and named views, grants.
- `migrate.py`  applies both scripts to one database as an administrator.
- `tests/test_cred_mart_db.py`  the UAT. It builds a PRIVATE temporary PostgreSQL instance from the installed binaries (own folder, random localhost port) and deletes it afterwards. It never connects to any configured database.

## Running the UAT

    python -m pytest tools/creditors_mart/tests/test_cred_mart_db.py -q

## Creating the real pilot database (administrator)

Run these in YOUR OWN terminal from the repository root. Each asks for the admin connection; the password is hidden and never stored.

    python tools/creditors_mart/migrate.py --create-database fpa_pilot
    python tools/creditors_mart/verify_install.py fpa_pilot

- `migrate.py` creates the empty database if missing, then applies the reviewed migrations. It refuses `fpa`, `postgres` and the template databases, and refuses a non-admin account.
- `verify_install.py` is read-only: owners, role attributes, the whole privilege matrix, guard triggers, and that nothing is loaded. It writes `docs/creditors_pilot/MART_REAL_INSTALL_EVIDENCE.md` (database and role names only).
- Scripted alternative: PowerShell `$env:FPA_PG_ADMIN_URL = "postgresql://<admin>:<password>@localhost:5432/postgres"` (a password containing `@ : /` must be percent-encoded in a URL, e.g. `@` as `%40`).
- Then attach LOGIN roles or passwords to the six roles yourself. Nothing here stores a credential.

## The loader login and the first load

1. `python tools/creditors_mart/setup_loader.py`  (administrator, own terminal, hidden prompt). Creates or re-keys `cred_loader_login` (member of `cred_loader` only, no admin attributes) with a random password stored only as a SCRAM hash in the database and in the git-ignored `.secrets/cred_loader.env`; creates a random 64-character `vendor_ref_salt` once and keeps it for ever. It proves the restrictions by logging in as that account. Nothing secret is printed.
2. `python tools/creditors_mart/loader.py load data/inbox/run_YYYYMMDD_NNN`  (reads `.secrets/cred_loader.env`; preflight, one transaction, controls, commit or full rollback; ends `loaded` / `unpublished`).
3. `python tools/creditors_mart/loader.py verify run_YYYYMMDD_NNN`  (separate gate: `verified`, still unpublished).
