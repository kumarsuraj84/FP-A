-- Shared run model, migration 003. One place that says, for EVERY domain: which run, as of when, and in which state.
--
-- It is a VIEW over each domain's own run table, not a copy: a domain's state can never drift from the shared model and nothing about a
-- domain's behaviour changes. Creditors is registered here without touching its tables, functions or numbers. Each later domain
-- adds itself with one more UNION ALL branch in its own migration (CREATE OR REPLACE VIEW keeps the columns).
--
-- Columns: domain, run_id, as_of_date, source_state, mart_state, api_state, publication_state, reconciliation_status,
--          source_updated_at (freshness), loaded_at, is_live.
--   source_state  : a run only exists once its extract passed offline staging validation, so this is 'validated' for every run.
--   mart_state    : 'loaded' (rows in, controls not yet all green) or 'verified' (source -> extract -> mart controls pass).
--   api_state     : 'pending' or 'verified' (mart -> API controls pass).
--   publication_state : unpublished | live | superseded | withdrawn (independent of the reconciliation status).

CREATE SCHEMA core;
REVOKE ALL ON SCHEMA core FROM PUBLIC;

CREATE VIEW core.v_domain_run AS
SELECT 'creditors'::text AS domain,
       r.extraction_run_id AS run_id,
       r.as_of_date,
       'validated'::text AS source_state,
       CASE r.recon_state WHEN 'loaded' THEN 'loaded' ELSE 'verified' END AS mart_state,
       CASE WHEN r.recon_state IN ('api_verified', 'ui_verified') THEN 'verified' ELSE 'pending' END AS api_state,
       r.publication_state,
       r.recon_state AS reconciliation_status,
       r.extract_finished_at AS source_updated_at,
       r.loaded_at,
       (r.publication_state = 'live') AS is_live
FROM cred.run r;

GRANT USAGE ON SCHEMA core TO cred_verifier, cred_api_reader, cred_finance_reader, cred_promoter;
GRANT SELECT ON core.v_domain_run TO cred_verifier, cred_api_reader, cred_finance_reader, cred_promoter;

INSERT INTO cred.schema_migration (version, description) VALUES
  ('003', 'shared run model: core.v_domain_run (a view over each domain run table; creditors registered, numbers and behaviour unchanged)');
