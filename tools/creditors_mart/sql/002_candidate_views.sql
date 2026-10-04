-- Creditors pilot mart, migration 002: verified-candidate views for the Creditors API preview, and a migration ledger.
-- Applied by the administrator through migrate.py (which applies only what is pending). Objects owned by cred_owner.
-- A "candidate" is a run whose reconciliation reached at least `verified` and whose data has not been purged. It may still be unpublished:
-- this is what lets the API and the UI be inspected and reconciled BEFORE promotion.

SET ROLE cred_owner;

CREATE TABLE cred.schema_migration (
  version     text PRIMARY KEY,
  description text NOT NULL,
  applied_at  timestamptz NOT NULL DEFAULT now(),
  applied_by  text NOT NULL DEFAULT current_user
);
CREATE TRIGGER no_mutation BEFORE UPDATE OR DELETE ON cred.schema_migration FOR EACH ROW EXECUTE FUNCTION cred.deny_mutation();
INSERT INTO cred.schema_migration (version, description) VALUES
  ('001', 'cred schema: immutable runs, controlled functions, masked and named views, grants'),
  ('002', 'verified-candidate views for the API preview; migration ledger');

CREATE VIEW cred.v_candidate_run AS
SELECT r.extraction_run_id, r.as_of_date, r.recon_state, r.publication_state, r.contract_version, r.rules_version,
       r.expected_rows, r.expected_identity_rows, r.loaded_at
FROM cred.run r
WHERE r.recon_state IN ('verified', 'api_verified', 'ui_verified') AND r.data_purged_at IS NULL;

-- masked items of candidate runs (no vendor name, no vendor or document codes)
CREATE VIEW cred.v_open_item_candidate AS
SELECT a.* FROM cred.v_open_item_any_run a JOIN cred.v_candidate_run c USING (extraction_run_id);

-- Finance only: the same items with names and codes
CREATE VIEW cred.v_open_item_named_candidate AS
SELECT n.* FROM cred.v_open_item_named_any_run n JOIN cred.v_candidate_run c USING (extraction_run_id);

CREATE VIEW cred.v_control_candidate AS
SELECT x.* FROM cred.v_control_result_any_run x JOIN cred.v_candidate_run c USING (extraction_run_id);

GRANT SELECT ON cred.v_candidate_run, cred.v_control_candidate TO cred_verifier, cred_finance_reader;
GRANT SELECT ON cred.v_open_item_candidate TO cred_verifier;
GRANT SELECT ON cred.v_open_item_named_candidate TO cred_finance_reader;

RESET ROLE;
