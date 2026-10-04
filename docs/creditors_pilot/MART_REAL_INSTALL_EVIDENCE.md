# Creditors pilot mart: real database install evidence

Database: `fpa_pilot`. Generated 2026-10-04 07:32 UTC by `tools/creditors_mart/verify_install.py` (read-only catalog queries).
No credential, host or password appears in this file.

**34 of 34 checks pass.**

| Check | Result | Detail |
|---|---|---|
| schema cred exists | PASS |  |
| schema owner is cred_owner | PASS |  |
| every table, view and sequence is owned by cred_owner | PASS | ['cred_owner'] |
| every function is owned by cred_owner | PASS | ['cred_owner'] |
| all six roles exist | PASS | ['cred_api_reader', 'cred_finance_reader', 'cred_loader', 'cred_owner', 'cred_promoter', 'cred_verifier'] |
| no role is superuser / createdb / createrole / replication / bypassrls | PASS |  |
| login state of the cred roles (informational: the administrator attaches logins) | PASS | cred_api_reader=NOLOGIN; cred_finance_reader=NOLOGIN; cred_loader=NOLOGIN; cred_owner=NOLOGIN; cred_promoter=NOLOGIN; cred_verifier=NOLOGIN |
| no role is a member of another cred role (no privilege inheritance between them) | PASS | [] |
| cred_loader: schema USAGE | PASS |  |
| cred_loader: no CREATE in schema cred | PASS |  |
| cred_loader: no CREATE in the database | PASS |  |
| cred_verifier: schema USAGE | PASS |  |
| cred_verifier: no CREATE in schema cred | PASS |  |
| cred_verifier: no CREATE in the database | PASS |  |
| cred_promoter: schema USAGE | PASS |  |
| cred_promoter: no CREATE in schema cred | PASS |  |
| cred_promoter: no CREATE in the database | PASS |  |
| cred_api_reader: schema USAGE | PASS |  |
| cred_api_reader: no CREATE in schema cred | PASS |  |
| cred_api_reader: no CREATE in the database | PASS |  |
| cred_finance_reader: schema USAGE | PASS |  |
| cred_finance_reader: no CREATE in schema cred | PASS |  |
| cred_finance_reader: no CREATE in the database | PASS |  |
| cred_owner: may create in the database (migrations) | PASS |  |
| table privilege matrix matches the design | PASS | 350 grants checked |
| view privilege matrix matches the design (names only for Finance) | PASS | 65 grants checked |
| function privilege matrix matches the design | PASS | 45 grants checked |
| no PUBLIC privilege on any table or view | PASS | [] |
| PUBLIC can execute only the three harmless helpers | PASS | ['caller_is(name)', 'caller_role()', 'maintenance_on()'] |
| immutability guard triggers are present and enabled | PASS | {'control_result': 1, 'identity_snapshot': 2, 'load_rejection': 1, 'open_item': 2, 'policy_change': 1, 'promotion': 1, 'run': 3, 'run_event': 1, 'vendor_snapsho |
| no trigger is disabled | PASS |  |
| security-definer functions pin their search_path | PASS |  |
| initial policy: API layer required, UI layer not yet | PASS | (True, False) |
| no data has been loaded: every table is empty and nothing is live | PASS | {'run': 0, 'vendor_snapshot': 0, 'open_item': 0, 'identity_snapshot': 0, 'control_result': 0, 'run_event': 0, 'load_rejection': 0, 'live_run': 0, 'promotion': 0 |
