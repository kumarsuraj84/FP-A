-- Creditors pilot mart: ROLES. Run once by the database administrator (cluster-wide objects).
-- No passwords here. The admin attaches LOGIN roles (or sets passwords) out of band; none of them is ever stored in the repository.
-- cred_owner  : owns the schema, tables, functions, views and migrations; runs retention (purge) and policy changes. A maintenance identity: no application and no routine workflow connects as this role.
-- cred_loader : inserts a run and its rows during a load and calls the loader functions. Cannot update/delete, promote, or change schema.
-- cred_verifier : reads candidate runs (masked) and records verification results ONLY through controlled functions.
-- cred_promoter : the publication decision: promote_run and demote_to only, plus the minimum run/control metadata to decide. Cannot load, purge, change schema or read vendor names.
-- cred_api_reader : read-only, approved masked API views of the live run. No vendor name, no vendor codes.
-- cash_owner / cash_loader / cash_verifier / cash_promoter / cash_api_reader : the same split for the Cash domain (schema `cash`, migration 004); each is NOLOGIN.
-- entry_owner / entry_loader / entry_verifier / entry_promoter / entry_api_reader / entry_finance_reader : the accounting-entry layer (schema `entry`, migration 005). entry_finance_reader alone may read the restricted text table. All NOLOGIN.
-- cred_finance_reader : read-only Finance / CFO view including vendor names and codes. An Admin application role maps here, never to the owner.
DO $roles$
DECLARE r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['cred_owner', 'cred_loader', 'cred_verifier', 'cred_promoter', 'cred_api_reader', 'cred_finance_reader', 'cash_owner', 'cash_loader', 'cash_verifier', 'cash_promoter', 'cash_api_reader', 'entry_owner', 'entry_loader', 'entry_verifier', 'entry_promoter', 'entry_api_reader', 'entry_finance_reader'] LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('CREATE ROLE %I NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT', r);
    END IF;
  END LOOP;
END
$roles$;
