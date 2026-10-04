-- Creditors pilot mart, schema `cred` (migration 001). Applied by the database administrator, objects owned by cred_owner.
-- Immutable, run-versioned snapshots. Reconciliation state and publication state are separate concepts.
-- Run on a scratch database first; then the identical file on the pilot database.

DO $pre$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cred_owner') THEN
    RAISE EXCEPTION 'run 000_roles.sql first';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'cred') THEN
    RAISE EXCEPTION 'schema cred already exists: migrations are not re-runnable';
  END IF;
  EXECUTE format('GRANT CONNECT, CREATE ON DATABASE %I TO cred_owner', current_database());
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO cred_loader, cred_verifier, cred_api_reader, cred_finance_reader', current_database());
END
$pre$;

SET ROLE cred_owner;

CREATE SCHEMA cred;
REVOKE ALL ON SCHEMA cred FROM PUBLIC;

-- ───────────────────────────── tables ─────────────────────────────

CREATE TABLE cred.run (
  extraction_run_id      text PRIMARY KEY CHECK (extraction_run_id ~ '^run_[0-9]{8}_[0-9]{3}$'),
  as_of_date             date NOT NULL,
  package                text NOT NULL,
  contract_version       text NOT NULL,
  rules_version          text NOT NULL,
  hash_spec_version      text NOT NULL,
  rules                  jsonb NOT NULL,
  source_object          text NOT NULL,
  scope_ledger_codes     text[] NOT NULL,
  manifest_sha256        char(64) NOT NULL UNIQUE CHECK (manifest_sha256 ~ '^[0-9a-f]{64}$'),
  staging_report_sha256  char(64) NOT NULL CHECK (staging_report_sha256 ~ '^[0-9a-f]{64}$'),
  derived_parquet_sha256 char(64) NOT NULL CHECK (derived_parquet_sha256 ~ '^[0-9a-f]{64}$'),
  extract_started_at     timestamptz NOT NULL,
  extract_finished_at    timestamptz NOT NULL,
  expected_rows          integer NOT NULL CHECK (expected_rows > 0),
  expected_identity_rows integer NOT NULL CHECK (expected_identity_rows >= expected_rows),
  loaded_at              timestamptz NOT NULL DEFAULT now(),
  loaded_by              text NOT NULL DEFAULT current_user,
  -- reconciliation state: has the data been proven? (moves forward only, through controlled functions)
  recon_state            text NOT NULL DEFAULT 'loaded' CHECK (recon_state IN ('loaded', 'verified', 'api_verified', 'ui_verified')),
  -- publication state: is it the live run? Independent of recon_state: a withdrawn run is not thereby "wrong"
  publication_state      text NOT NULL DEFAULT 'unpublished' CHECK (publication_state IN ('unpublished', 'live', 'superseded', 'withdrawn')),
  data_purged_at         timestamptz,
  data_purged_by         text,
  UNIQUE (extraction_run_id, as_of_date),
  CHECK (extract_finished_at >= extract_started_at)
);

CREATE TABLE cred.vendor_snapshot (
  extraction_run_id  text NOT NULL REFERENCES cred.run,
  sub_ledger_code    text NOT NULL,
  vendor_ref         text NOT NULL CHECK (vendor_ref ~ '^V[0-9a-f]{12}$'),   -- stable pseudonym (keyed hash made by the loader), safe for broad viewers
  slid               text,
  vendor_name        text,
  party_class        text,
  party_class_type   text,
  credit_days        integer,
  vendor_extinct     text,
  vendor_fingerprint char(64) NOT NULL CHECK (vendor_fingerprint ~ '^[0-9a-f]{64}$'),
  PRIMARY KEY (extraction_run_id, sub_ledger_code),
  UNIQUE (extraction_run_id, vendor_ref)
);

CREATE TABLE cred.open_item (
  extraction_run_id     text NOT NULL,
  as_of_date            date NOT NULL,
  source_row_key        char(64) NOT NULL CHECK (source_row_key ~ '^[0-9a-f]{64}$'),
  identity_k1_signature char(64) NOT NULL CHECK (identity_k1_signature ~ '^[0-9a-f]{64}$'),
  row_fingerprint       char(64) NOT NULL CHECK (row_fingerprint ~ '^[0-9a-f]{64}$'),
  document_code         text NOT NULL,
  sub_ledger_code       text NOT NULL,
  ledger_code           text NOT NULL,
  ledger_name           text,
  drcr                  char(2) NOT NULL CHECK (drcr IN ('Cr', 'Dr')),
  amount                numeric(24,4) NOT NULL,
  adjusted              numeric(24,4),
  pending               numeric(24,4) NOT NULL,
  document_no           text, document_type text, document_initial text, ref_no text, created_by_site text,
  due_date_basis        text,
  document_date date, due_date date, ref_date date, entry_date date,
  document_date_raw text, due_date_raw text, ref_date_raw text, entry_date_raw text,
  document_age_days     integer,
  document_age_bucket   text NOT NULL CHECK (document_age_bucket IN ('D0_30', 'D31_60', 'D61_90', 'D91_180', 'D181_365', 'D365_PLUS',
                          'UNCLASSIFIED_MISSING', 'UNCLASSIFIED_BEFORE_MIN', 'UNCLASSIFIED_AFTER_AS_OF', 'UNCLASSIFIED_UNPARSEABLE')),
  overdue_days          integer,
  due_status            text NOT NULL CHECK (due_status IN ('NOT_YET_DUE', 'PAST_DUE_OR_DUE_TODAY', 'DUE_UNAVAILABLE', 'DUE_INVALID')),
  date_quality_status   text NOT NULL CHECK (date_quality_status IN ('OK', 'MISSING', 'BEFORE_MIN', 'AFTER_AS_OF', 'UNPARSEABLE')),
  classification_status text NOT NULL CHECK (classification_status IN ('CREDIT_OUTSTANDING', 'CREDITOR_DEBIT_BALANCE_CLASSIFICATION_PENDING')),
  PRIMARY KEY (extraction_run_id, source_row_key),
  FOREIGN KEY (extraction_run_id, as_of_date) REFERENCES cred.run (extraction_run_id, as_of_date),
  FOREIGN KEY (extraction_run_id, sub_ledger_code) REFERENCES cred.vendor_snapshot (extraction_run_id, sub_ledger_code),
  UNIQUE (extraction_run_id, document_code, sub_ledger_code),
  UNIQUE (extraction_run_id, identity_k1_signature),
  CHECK (pending <> 0),
  CHECK ((drcr = 'Cr') = (pending < 0)),
  CHECK (position('|' in document_code) = 0 AND position('|' in sub_ledger_code) = 0 AND document_code <> '' AND sub_ledger_code <> ''),
  CHECK (source_row_key = encode(sha256(convert_to('v1|' || document_code || '|' || sub_ledger_code, 'UTF8')), 'hex')),
  CHECK (identity_k1_signature = encode(sha256(convert_to('v1|' || document_code || '|' || ledger_code || '|' || sub_ledger_code || '|' || drcr, 'UTF8')), 'hex')),
  CHECK ((document_age_days IS NULL) = (document_age_bucket LIKE 'UNCLASSIFIED%')),
  CHECK ((document_age_bucket LIKE 'UNCLASSIFIED%') = (date_quality_status <> 'OK')),
  CHECK ((overdue_days IS NOT NULL) = (due_status = 'PAST_DUE_OR_DUE_TODAY')),
  CHECK ((classification_status = 'CREDIT_OUTSTANDING') = (drcr = 'Cr'))
);

CREATE TABLE cred.identity_snapshot (
  extraction_run_id text NOT NULL REFERENCES cred.run,
  source_row_key    char(64) NOT NULL CHECK (source_row_key ~ '^[0-9a-f]{64}$'),
  ledger_code       text NOT NULL,
  drcr              char(2) NOT NULL CHECK (drcr IN ('Cr', 'Dr')),
  pending           numeric(24,4) NOT NULL,
  entry_date_raw    text,
  PRIMARY KEY (extraction_run_id, source_row_key)
);

CREATE TABLE cred.control_result (
  extraction_run_id text NOT NULL REFERENCES cred.run,
  control_id        text NOT NULL,
  dimension         text NOT NULL,
  left_layer        text NOT NULL,
  left_value        numeric(30,4) NOT NULL,
  right_layer       text NOT NULL,
  right_value       numeric(30,4) NOT NULL,
  variance          numeric(30,4) GENERATED ALWAYS AS (right_value - left_value) STORED,
  verdict           text GENERATED ALWAYS AS (CASE WHEN right_value = left_value THEN 'PASS' ELSE 'FAIL' END) STORED,
  recorded_at       timestamptz NOT NULL DEFAULT now(),
  recorded_by       text NOT NULL DEFAULT current_user,
  PRIMARY KEY (extraction_run_id, control_id, dimension, left_layer, right_layer),
  CHECK ((left_layer, right_layer) IN (('source', 'extract'), ('extract', 'mart'), ('mart', 'api'), ('api', 'ui')))
);

-- append-only history of everything that happens to a run, including failures (kept apart from the two current states)
CREATE TABLE cred.run_event (
  event_id          bigserial PRIMARY KEY,
  extraction_run_id text NOT NULL REFERENCES cred.run,
  event             text NOT NULL CHECK (event IN ('loaded', 'verified', 'verify_failed', 'api_verified', 'api_verify_failed', 'ui_verified', 'ui_verify_failed',
                                                  'promoted', 'superseded', 'withdrawn', 'reinstated', 'data_purged', 'purge_refused')),
  detail            jsonb,
  at                timestamptz NOT NULL DEFAULT now(),
  by                text NOT NULL DEFAULT current_user
);

CREATE TABLE cred.load_rejection (
  rejection_id      bigserial PRIMARY KEY,
  extraction_run_id text NOT NULL,
  manifest_sha256   char(64),
  stage             text NOT NULL CHECK (stage IN ('precheck', 'staging_report', 'load', 'mart_controls', 'promotion')),
  reason            text NOT NULL,
  failed_controls   jsonb,
  attempted_at      timestamptz NOT NULL DEFAULT now(),
  attempted_by      text NOT NULL DEFAULT current_user
);

CREATE TABLE cred.live_run (
  singleton         boolean PRIMARY KEY DEFAULT true CHECK (singleton),
  extraction_run_id text NOT NULL REFERENCES cred.run,
  since             timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE cred.promotion (
  promotion_id      bigserial PRIMARY KEY,
  action            text NOT NULL CHECK (action IN ('promote', 'demote')),
  extraction_run_id text NOT NULL REFERENCES cred.run,          -- the run that became live
  previous_run_id   text REFERENCES cred.run,                   -- the run that stopped being live
  reason            text NOT NULL CHECK (length(reason) > 0),
  at                timestamptz NOT NULL DEFAULT now(),
  by                text NOT NULL DEFAULT current_user
);

-- policy is an append-only history; the latest row is the current policy
CREATE TABLE cred.policy_change (
  change_id         bigserial PRIMARY KEY,
  require_api_layer boolean NOT NULL,
  require_ui_layer  boolean NOT NULL,
  reason            text NOT NULL CHECK (length(reason) > 0),
  at                timestamptz NOT NULL DEFAULT now(),
  by                text NOT NULL DEFAULT current_user
);
INSERT INTO cred.policy_change (require_api_layer, require_ui_layer, reason)
VALUES (true, false, 'initial policy: API layer required before promotion; UI layer required once the UI is connected');

-- ───────────────────────────── helpers and guards ─────────────────────────────

-- who is really calling: the role set with SET ROLE, otherwise the login role (works inside SECURITY DEFINER functions)
CREATE FUNCTION cred.caller_role() RETURNS name LANGUAGE sql STABLE AS
$$ SELECT CASE WHEN current_setting('role') <> 'none' THEN current_setting('role')::name ELSE session_user END $$;

CREATE FUNCTION cred.caller_is(p_role name) RETURNS boolean LANGUAGE sql STABLE AS
$$ SELECT pg_has_role(cred.caller_role(), p_role, 'MEMBER') $$;

CREATE FUNCTION cred.maintenance_on() RETURNS boolean LANGUAGE sql STABLE AS
$$ SELECT coalesce(current_setting('cred.maintenance', true), 'off') = 'on' $$;

-- append-only everywhere; fact deletes only inside the controlled purge function
CREATE FUNCTION cred.deny_mutation() RETURNS trigger LANGUAGE plpgsql AS
$$
BEGIN
  IF TG_OP = 'DELETE' AND TG_TABLE_NAME IN ('open_item', 'vendor_snapshot', 'identity_snapshot') AND cred.maintenance_on() THEN
    RETURN OLD;
  END IF;
  RAISE EXCEPTION '% on cred.% is not allowed: runs are immutable (use the controlled functions)', TG_OP, TG_TABLE_NAME USING ERRCODE = 'insufficient_privilege';
END
$$;

CREATE TRIGGER no_mutation BEFORE UPDATE OR DELETE ON cred.open_item        FOR EACH ROW EXECUTE FUNCTION cred.deny_mutation();
CREATE TRIGGER no_mutation BEFORE UPDATE OR DELETE ON cred.vendor_snapshot  FOR EACH ROW EXECUTE FUNCTION cred.deny_mutation();
CREATE TRIGGER no_mutation BEFORE UPDATE OR DELETE ON cred.identity_snapshot FOR EACH ROW EXECUTE FUNCTION cred.deny_mutation();
CREATE TRIGGER no_mutation BEFORE UPDATE OR DELETE ON cred.control_result   FOR EACH ROW EXECUTE FUNCTION cred.deny_mutation();
CREATE TRIGGER no_mutation BEFORE UPDATE OR DELETE ON cred.run_event        FOR EACH ROW EXECUTE FUNCTION cred.deny_mutation();
CREATE TRIGGER no_mutation BEFORE UPDATE OR DELETE ON cred.load_rejection   FOR EACH ROW EXECUTE FUNCTION cred.deny_mutation();
CREATE TRIGGER no_mutation BEFORE UPDATE OR DELETE ON cred.promotion        FOR EACH ROW EXECUTE FUNCTION cred.deny_mutation();
CREATE TRIGGER no_mutation BEFORE UPDATE OR DELETE ON cred.policy_change    FOR EACH ROW EXECUTE FUNCTION cred.deny_mutation();
CREATE TRIGGER no_delete   BEFORE DELETE ON cred.run                        FOR EACH ROW EXECUTE FUNCTION cred.deny_mutation();

-- a run row can be created only in its starting state, and afterwards only the state columns can change, only by the functions
CREATE FUNCTION cred.guard_run_insert() RETURNS trigger LANGUAGE plpgsql AS
$$
BEGIN
  IF NEW.recon_state <> 'loaded' OR NEW.publication_state <> 'unpublished' OR NEW.data_purged_at IS NOT NULL THEN
    RAISE EXCEPTION 'a run must start as loaded / unpublished' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END
$$;
CREATE TRIGGER run_insert BEFORE INSERT ON cred.run FOR EACH ROW EXECUTE FUNCTION cred.guard_run_insert();

CREATE FUNCTION cred.guard_run_update() RETURNS trigger LANGUAGE plpgsql AS
$$
BEGIN
  IF NOT cred.maintenance_on() THEN
    RAISE EXCEPTION 'cred.run can only change through the controlled functions' USING ERRCODE = 'insufficient_privilege';
  END IF;
  IF (to_jsonb(NEW) - 'recon_state' - 'publication_state' - 'data_purged_at' - 'data_purged_by')
     IS DISTINCT FROM (to_jsonb(OLD) - 'recon_state' - 'publication_state' - 'data_purged_at' - 'data_purged_by') THEN
    RAISE EXCEPTION 'only the state columns of a run may change' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END
$$;
CREATE TRIGGER run_update BEFORE UPDATE ON cred.run FOR EACH ROW EXECUTE FUNCTION cred.guard_run_update();

-- rows can be added to a run only while it is still being loaded
CREATE FUNCTION cred.guard_open_run() RETURNS trigger LANGUAGE plpgsql AS
$$
DECLARE st text; pub text;
BEGIN
  SELECT recon_state, publication_state INTO st, pub FROM cred.run WHERE extraction_run_id = NEW.extraction_run_id;
  IF NOT FOUND THEN RAISE EXCEPTION 'run % does not exist', NEW.extraction_run_id USING ERRCODE = 'foreign_key_violation'; END IF;
  IF st <> 'loaded' OR pub <> 'unpublished' THEN
    RAISE EXCEPTION 'run % is closed (% / %): no rows can be added', NEW.extraction_run_id, st, pub USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN NEW;
END
$$;
CREATE TRIGGER run_open BEFORE INSERT ON cred.open_item         FOR EACH ROW EXECUTE FUNCTION cred.guard_open_run();
CREATE TRIGGER run_open BEFORE INSERT ON cred.vendor_snapshot   FOR EACH ROW EXECUTE FUNCTION cred.guard_open_run();
CREATE TRIGGER run_open BEFORE INSERT ON cred.identity_snapshot FOR EACH ROW EXECUTE FUNCTION cred.guard_open_run();

CREATE FUNCTION cred.current_policy() RETURNS cred.policy_change LANGUAGE sql STABLE AS
$$ SELECT * FROM cred.policy_change ORDER BY change_id DESC LIMIT 1 $$;

-- ───────────────────────────── structural mart checks (computed in SQL) ─────────────────────────────

CREATE FUNCTION cred.mart_checks(p_run text) RETURNS TABLE (check_id text, violations bigint) LANGUAGE sql STABLE SECURITY DEFINER SET search_path = cred, pg_temp AS
$$
  SELECT 'M1_rows_vs_expected', abs((SELECT count(*) FROM cred.open_item WHERE extraction_run_id = p_run) - (SELECT expected_rows FROM cred.run WHERE extraction_run_id = p_run))::bigint
  UNION ALL SELECT 'M2_duplicate_business_key', count(*) FROM (SELECT 1 FROM cred.open_item WHERE extraction_run_id = p_run GROUP BY document_code, sub_ledger_code HAVING count(*) > 1) d
  UNION ALL SELECT 'M3_key_conflicting_identity', count(*) FROM (SELECT 1 FROM cred.open_item WHERE extraction_run_id = p_run GROUP BY source_row_key HAVING count(DISTINCT (document_code, sub_ledger_code)) > 1) d
  UNION ALL SELECT 'M4_key_not_rederivable', count(*) FROM cred.open_item WHERE extraction_run_id = p_run
       AND (source_row_key <> encode(sha256(convert_to('v1|' || document_code || '|' || sub_ledger_code, 'UTF8')), 'hex')
         OR identity_k1_signature <> encode(sha256(convert_to('v1|' || document_code || '|' || ledger_code || '|' || sub_ledger_code || '|' || drcr, 'UTF8')), 'hex'))
  UNION ALL SELECT 'M5_duplicate_k1_signature', count(*) FROM (SELECT 1 FROM cred.open_item WHERE extraction_run_id = p_run GROUP BY identity_k1_signature HAVING count(*) > 1) d
  UNION ALL SELECT 'M6_item_without_vendor', count(*) FROM cred.open_item i WHERE i.extraction_run_id = p_run
       AND NOT EXISTS (SELECT 1 FROM cred.vendor_snapshot v WHERE v.extraction_run_id = i.extraction_run_id AND v.sub_ledger_code = i.sub_ledger_code)
  UNION ALL SELECT 'M7_sign_or_open_violation', count(*) FROM cred.open_item WHERE extraction_run_id = p_run AND (pending = 0 OR (drcr = 'Cr') <> (pending < 0))
  UNION ALL SELECT 'M8_identity_vs_items',
       (SELECT count(*) FROM cred.identity_snapshot s WHERE s.extraction_run_id = p_run AND s.pending <> 0
          AND NOT EXISTS (SELECT 1 FROM cred.open_item i WHERE i.extraction_run_id = s.extraction_run_id AND i.source_row_key = s.source_row_key AND i.pending = s.pending AND i.drcr = s.drcr AND i.ledger_code = s.ledger_code))
     + (SELECT count(*) FROM cred.open_item i WHERE i.extraction_run_id = p_run
          AND NOT EXISTS (SELECT 1 FROM cred.identity_snapshot s WHERE s.extraction_run_id = i.extraction_run_id AND s.source_row_key = i.source_row_key AND s.pending <> 0))
     + abs((SELECT count(*) FROM cred.identity_snapshot WHERE extraction_run_id = p_run) - (SELECT expected_identity_rows FROM cred.run WHERE extraction_run_id = p_run))
  UNION ALL SELECT 'M9_as_of_mismatch', count(*) FROM cred.open_item i JOIN cred.run r USING (extraction_run_id) WHERE i.extraction_run_id = p_run AND i.as_of_date <> r.as_of_date
  UNION ALL SELECT 'M10_derived_inconsistent', count(*) FROM cred.open_item WHERE extraction_run_id = p_run
       AND ((document_age_days IS NULL) <> (document_age_bucket LIKE 'UNCLASSIFIED%') OR (overdue_days IS NOT NULL) <> (due_status = 'PAST_DUE_OR_DUE_TODAY')
         OR (classification_status = 'CREDIT_OUTSTANDING') <> (drcr = 'Cr'))
$$;

-- ───────────────────────────── controlled functions ─────────────────────────────

-- the only way a control result is written; the layer pair decides who may write it and in which state the run must be
CREATE FUNCTION cred.record_control(p_run text, p_id text, p_dim text, p_left_layer text, p_left numeric, p_right_layer text, p_right numeric) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = cred, pg_temp AS
$$
DECLARE st text;
BEGIN
  SELECT recon_state INTO st FROM cred.run WHERE extraction_run_id = p_run;
  IF NOT FOUND THEN RAISE EXCEPTION 'run % does not exist', p_run; END IF;
  IF (p_left_layer, p_right_layer) IN (('source', 'extract'), ('extract', 'mart')) THEN
    IF NOT cred.caller_is('cred_loader') THEN RAISE EXCEPTION 'only the loader records source/extract/mart controls' USING ERRCODE = 'insufficient_privilege'; END IF;
    IF st <> 'loaded' THEN RAISE EXCEPTION 'run % is % : its load controls are closed', p_run, st; END IF;
  ELSIF (p_left_layer, p_right_layer) = ('mart', 'api') THEN
    IF NOT cred.caller_is('cred_verifier') THEN RAISE EXCEPTION 'only the verifier records API-layer controls' USING ERRCODE = 'insufficient_privilege'; END IF;
    IF st <> 'verified' THEN RAISE EXCEPTION 'run % must be verified before API controls (it is %)', p_run, st; END IF;
  ELSIF (p_left_layer, p_right_layer) = ('api', 'ui') THEN
    IF NOT cred.caller_is('cred_verifier') THEN RAISE EXCEPTION 'only the verifier records UI-layer controls' USING ERRCODE = 'insufficient_privilege'; END IF;
    IF st <> 'api_verified' THEN RAISE EXCEPTION 'run % must be api_verified before UI controls (it is %)', p_run, st; END IF;
  ELSE
    RAISE EXCEPTION 'unsupported layer pair % -> %', p_left_layer, p_right_layer;
  END IF;
  INSERT INTO cred.control_result (extraction_run_id, control_id, dimension, left_layer, left_value, right_layer, right_value)
  VALUES (p_run, p_id, p_dim, p_left_layer, p_left, p_right_layer, p_right);
END
$$;

CREATE FUNCTION cred.verify_run(p_run text) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = cred, pg_temp AS
$$
DECLARE st text; n_fail int; n_se int; n_em int; bad jsonb;
BEGIN
  IF NOT (cred.caller_is('cred_loader') OR cred.caller_is('cred_owner')) THEN RAISE EXCEPTION 'not allowed' USING ERRCODE = 'insufficient_privilege'; END IF;
  SELECT recon_state INTO st FROM cred.run WHERE extraction_run_id = p_run FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'run % does not exist', p_run; END IF;
  IF st <> 'loaded' THEN RAISE EXCEPTION 'run % is already %', p_run, st; END IF;
  SELECT count(*) FILTER (WHERE verdict <> 'PASS'), count(*) FILTER (WHERE left_layer = 'source' AND right_layer = 'extract'), count(*) FILTER (WHERE left_layer = 'extract' AND right_layer = 'mart')
    INTO n_fail, n_se, n_em FROM cred.control_result WHERE extraction_run_id = p_run;
  SELECT coalesce(jsonb_object_agg(check_id, violations) FILTER (WHERE violations <> 0), '{}'::jsonb) INTO bad FROM cred.mart_checks(p_run);
  PERFORM set_config('cred.maintenance', 'on', true);
  IF n_fail = 0 AND n_se > 0 AND n_em > 0 AND bad = '{}'::jsonb THEN
    UPDATE cred.run SET recon_state = 'verified' WHERE extraction_run_id = p_run;
    INSERT INTO cred.run_event (extraction_run_id, event, detail) VALUES (p_run, 'verified', jsonb_build_object('source_extract_controls', n_se, 'extract_mart_controls', n_em));
    PERFORM set_config('cred.maintenance', 'off', true);
    RETURN jsonb_build_object('ok', true, 'recon_state', 'verified');
  END IF;
  INSERT INTO cred.run_event (extraction_run_id, event, detail)
  VALUES (p_run, 'verify_failed', jsonb_build_object('failed_controls', n_fail, 'source_extract_controls', n_se, 'extract_mart_controls', n_em, 'structural', bad));
  PERFORM set_config('cred.maintenance', 'off', true);
  RETURN jsonb_build_object('ok', false, 'failed_controls', n_fail, 'source_extract_controls', n_se, 'extract_mart_controls', n_em, 'structural', bad);
END
$$;

CREATE FUNCTION cred.layer_verify(p_run text, p_from text, p_to text, p_left text, p_right text, p_ok_event text, p_fail_event text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = cred, pg_temp AS
$$
DECLARE st text; n_fail int; n int;
BEGIN
  IF NOT cred.caller_is('cred_verifier') THEN RAISE EXCEPTION 'only the verifier verifies layers' USING ERRCODE = 'insufficient_privilege'; END IF;
  SELECT recon_state INTO st FROM cred.run WHERE extraction_run_id = p_run FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'run % does not exist', p_run; END IF;
  IF st <> p_from THEN RAISE EXCEPTION 'run % is %, expected %', p_run, st, p_from; END IF;
  SELECT count(*), count(*) FILTER (WHERE verdict <> 'PASS') INTO n, n_fail FROM cred.control_result WHERE extraction_run_id = p_run AND left_layer = p_left AND right_layer = p_right;
  PERFORM set_config('cred.maintenance', 'on', true);
  IF n > 0 AND n_fail = 0 THEN
    UPDATE cred.run SET recon_state = p_to WHERE extraction_run_id = p_run;
    INSERT INTO cred.run_event (extraction_run_id, event, detail) VALUES (p_run, p_ok_event, jsonb_build_object('controls', n));
    PERFORM set_config('cred.maintenance', 'off', true);
    RETURN jsonb_build_object('ok', true, 'recon_state', p_to);
  END IF;
  INSERT INTO cred.run_event (extraction_run_id, event, detail) VALUES (p_run, p_fail_event, jsonb_build_object('controls', n, 'failed', n_fail));
  PERFORM set_config('cred.maintenance', 'off', true);
  RETURN jsonb_build_object('ok', false, 'controls', n, 'failed', n_fail);
END
$$;

CREATE FUNCTION cred.api_verify_run(p_run text) RETURNS jsonb LANGUAGE sql SECURITY DEFINER SET search_path = cred, pg_temp AS
$$ SELECT cred.layer_verify(p_run, 'verified', 'api_verified', 'mart', 'api', 'api_verified', 'api_verify_failed') $$;
CREATE FUNCTION cred.ui_verify_run(p_run text) RETURNS jsonb LANGUAGE sql SECURITY DEFINER SET search_path = cred, pg_temp AS
$$ SELECT cred.layer_verify(p_run, 'api_verified', 'ui_verified', 'api', 'ui', 'ui_verified', 'ui_verify_failed') $$;

CREATE FUNCTION cred.promote_run(p_run text, p_reason text) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = cred, pg_temp AS
$$
DECLARE r cred.run%ROWTYPE; pol cred.policy_change; prev text; prev_asof date; fails int; n bigint; need text;
BEGIN
  IF NOT cred.caller_is('cred_owner') THEN RAISE EXCEPTION 'only the owner/operator promotes runs' USING ERRCODE = 'insufficient_privilege'; END IF;
  SELECT * INTO r FROM cred.run WHERE extraction_run_id = p_run FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'run % does not exist', p_run; END IF;
  IF r.publication_state <> 'unpublished' THEN RAISE EXCEPTION 'run % is % and cannot be promoted here', p_run, r.publication_state; END IF;
  IF r.data_purged_at IS NOT NULL THEN RAISE EXCEPTION 'run % has been purged', p_run; END IF;
  pol := cred.current_policy();
  need := CASE WHEN pol.require_ui_layer THEN 'ui_verified' WHEN pol.require_api_layer THEN 'api_verified' ELSE 'verified' END;
  IF (CASE r.recon_state WHEN 'loaded' THEN 0 WHEN 'verified' THEN 1 WHEN 'api_verified' THEN 2 ELSE 3 END)
     < (CASE need WHEN 'verified' THEN 1 WHEN 'api_verified' THEN 2 ELSE 3 END) THEN
    RAISE EXCEPTION 'run % is % but policy requires %', p_run, r.recon_state, need;
  END IF;
  SELECT count(*) INTO fails FROM cred.control_result WHERE extraction_run_id = p_run AND verdict <> 'PASS';
  IF fails > 0 THEN RAISE EXCEPTION 'run %: % control(s) failed', p_run, fails; END IF;
  SELECT count(*) INTO n FROM cred.open_item WHERE extraction_run_id = p_run;
  IF n <> r.expected_rows THEN RAISE EXCEPTION 'run %: % rows loaded, % expected', p_run, n, r.expected_rows; END IF;
  SELECT l.extraction_run_id, x.as_of_date INTO prev, prev_asof FROM cred.live_run l JOIN cred.run x USING (extraction_run_id);
  IF prev IS NOT NULL AND r.as_of_date < prev_asof THEN RAISE EXCEPTION 'run % is older (as_of %) than the live run (as_of %): use demote_to', p_run, r.as_of_date, prev_asof; END IF;
  PERFORM set_config('cred.maintenance', 'on', true);
  INSERT INTO cred.live_run (extraction_run_id) VALUES (p_run)
    ON CONFLICT (singleton) DO UPDATE SET extraction_run_id = EXCLUDED.extraction_run_id, since = now();
  IF prev IS NOT NULL THEN
    UPDATE cred.run SET publication_state = 'superseded' WHERE extraction_run_id = prev;
    INSERT INTO cred.run_event (extraction_run_id, event, detail) VALUES (prev, 'superseded', jsonb_build_object('by', p_run));
  END IF;
  UPDATE cred.run SET publication_state = 'live' WHERE extraction_run_id = p_run;
  INSERT INTO cred.run_event (extraction_run_id, event, detail) VALUES (p_run, 'promoted', jsonb_build_object('previous', prev, 'reason', p_reason));
  INSERT INTO cred.promotion (action, extraction_run_id, previous_run_id, reason) VALUES ('promote', p_run, prev, p_reason);
  PERFORM set_config('cred.maintenance', 'off', true);
END
$$;

-- moves the live pointer back to an earlier run; nothing is deleted and the run being left keeps its reconciliation state
CREATE FUNCTION cred.demote_to(p_target text, p_reason text) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = cred, pg_temp AS
$$
DECLARE t cred.run%ROWTYPE; cur text;
BEGIN
  IF NOT cred.caller_is('cred_owner') THEN RAISE EXCEPTION 'only the owner/operator rolls back' USING ERRCODE = 'insufficient_privilege'; END IF;
  SELECT * INTO t FROM cred.run WHERE extraction_run_id = p_target FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'run % does not exist', p_target; END IF;
  IF t.publication_state <> 'superseded' THEN RAISE EXCEPTION 'run % is % : only a previously live (superseded) run can be reinstated', p_target, t.publication_state; END IF;
  IF t.data_purged_at IS NOT NULL THEN RAISE EXCEPTION 'run % has been purged and cannot be reinstated', p_target; END IF;
  SELECT extraction_run_id INTO cur FROM cred.live_run;
  IF cur IS NULL THEN RAISE EXCEPTION 'there is no live run to roll back from'; END IF;
  PERFORM set_config('cred.maintenance', 'on', true);
  UPDATE cred.live_run SET extraction_run_id = p_target, since = now() WHERE singleton;
  UPDATE cred.run SET publication_state = 'withdrawn' WHERE extraction_run_id = cur;
  UPDATE cred.run SET publication_state = 'live' WHERE extraction_run_id = p_target;
  INSERT INTO cred.run_event (extraction_run_id, event, detail) VALUES (cur, 'withdrawn', jsonb_build_object('rolled_back_to', p_target, 'reason', p_reason));
  INSERT INTO cred.run_event (extraction_run_id, event, detail) VALUES (p_target, 'reinstated', jsonb_build_object('replaces', cur, 'reason', p_reason));
  INSERT INTO cred.promotion (action, extraction_run_id, previous_run_id, reason) VALUES ('demote', p_target, cur, p_reason);
  PERFORM set_config('cred.maintenance', 'off', true);
END
$$;

-- retention: removes the fact snapshots of ONE run; run metadata, control results, events and promotion history stay.
-- It refuses the live run and the rollback target, and logs every outcome.
CREATE FUNCTION cred.purge_run(p_run text, p_reason text) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = cred, pg_temp AS
$$
DECLARE r cred.run%ROWTYPE; target text; n_items bigint; n_vendors bigint; n_ident bigint;
BEGIN
  IF NOT cred.caller_is('cred_owner') THEN RAISE EXCEPTION 'only the owner/operator purges' USING ERRCODE = 'insufficient_privilege'; END IF;
  IF p_reason IS NULL OR length(p_reason) = 0 THEN RAISE EXCEPTION 'a reason is required'; END IF;
  SELECT * INTO r FROM cred.run WHERE extraction_run_id = p_run FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'run % does not exist', p_run; END IF;
  SELECT previous_run_id INTO target FROM cred.promotion WHERE action = 'promote' ORDER BY promotion_id DESC LIMIT 1;
  PERFORM set_config('cred.maintenance', 'on', true);
  IF r.publication_state = 'live' OR EXISTS (SELECT 1 FROM cred.live_run WHERE extraction_run_id = p_run) THEN
    INSERT INTO cred.run_event (extraction_run_id, event, detail) VALUES (p_run, 'purge_refused', jsonb_build_object('why', 'live run', 'reason', p_reason));
    PERFORM set_config('cred.maintenance', 'off', true);
    RETURN jsonb_build_object('purged', false, 'why', 'live run');
  END IF;
  IF target = p_run THEN
    INSERT INTO cred.run_event (extraction_run_id, event, detail) VALUES (p_run, 'purge_refused', jsonb_build_object('why', 'rollback target', 'reason', p_reason));
    PERFORM set_config('cred.maintenance', 'off', true);
    RETURN jsonb_build_object('purged', false, 'why', 'rollback target');
  END IF;
  IF r.data_purged_at IS NOT NULL THEN
    PERFORM set_config('cred.maintenance', 'off', true);
    RETURN jsonb_build_object('purged', false, 'why', 'already purged');
  END IF;
  DELETE FROM cred.open_item WHERE extraction_run_id = p_run;          GET DIAGNOSTICS n_items = ROW_COUNT;
  DELETE FROM cred.vendor_snapshot WHERE extraction_run_id = p_run;    GET DIAGNOSTICS n_vendors = ROW_COUNT;
  DELETE FROM cred.identity_snapshot WHERE extraction_run_id = p_run;  GET DIAGNOSTICS n_ident = ROW_COUNT;
  UPDATE cred.run SET data_purged_at = now(), data_purged_by = cred.caller_role() WHERE extraction_run_id = p_run;
  INSERT INTO cred.run_event (extraction_run_id, event, detail)
  VALUES (p_run, 'data_purged', jsonb_build_object('items', n_items, 'vendors', n_vendors, 'identity_rows', n_ident, 'reason', p_reason));
  PERFORM set_config('cred.maintenance', 'off', true);
  RETURN jsonb_build_object('purged', true, 'items', n_items, 'vendors', n_vendors, 'identity_rows', n_ident);
END
$$;

CREATE FUNCTION cred.set_policy(p_require_api boolean, p_require_ui boolean, p_reason text) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = cred, pg_temp AS
$$
BEGIN
  IF NOT cred.caller_is('cred_owner') THEN RAISE EXCEPTION 'only the owner changes policy' USING ERRCODE = 'insufficient_privilege'; END IF;
  INSERT INTO cred.policy_change (require_api_layer, require_ui_layer, reason) VALUES (p_require_api, p_require_ui, p_reason);
END
$$;

-- ───────────────────────────── views (every live view reads through live_run) ─────────────────────────────

-- masked: no vendor name, no vendor/document codes; a pseudonymous vendor_ref and an item_ref only
CREATE VIEW cred.v_open_item_any_run AS
SELECT i.extraction_run_id, i.source_row_key AS item_ref, v.vendor_ref, i.as_of_date, i.ledger_code, i.ledger_name, i.drcr,
       i.amount, i.adjusted, i.pending, i.document_type, i.due_date_basis, i.document_date, i.due_date, i.entry_date,
       i.document_age_days, i.document_age_bucket, i.overdue_days, i.due_status, i.date_quality_status, i.classification_status,
       v.party_class, v.party_class_type
FROM cred.open_item i JOIN cred.vendor_snapshot v USING (extraction_run_id, sub_ledger_code);

CREATE VIEW cred.v_exposure_summary_any_run AS
SELECT extraction_run_id, ledger_code, ledger_name, drcr, document_age_bucket, due_status, party_class,
       count(*) AS item_rows,
       coalesce(sum(abs(pending)) FILTER (WHERE drcr = 'Cr'), 0) AS credit_outstanding,
       coalesce(sum(abs(pending)) FILTER (WHERE drcr = 'Dr'), 0) AS creditor_debit_balance,
       sum(pending) AS signed_net
FROM cred.v_open_item_any_run GROUP BY extraction_run_id, ledger_code, ledger_name, drcr, document_age_bucket, due_status, party_class;

CREATE VIEW cred.v_vendor_counts_any_run AS
SELECT extraction_run_id, GROUPING(ledger_code) AS g_ledger, GROUPING(drcr) AS g_drcr, ledger_code, drcr, count(DISTINCT vendor_ref) AS vendors
FROM cred.v_open_item_any_run GROUP BY extraction_run_id, GROUPING SETS ((extraction_run_id), (extraction_run_id, ledger_code), (extraction_run_id, drcr), (extraction_run_id, ledger_code, drcr));

CREATE VIEW cred.v_control_result_any_run AS
SELECT extraction_run_id, control_id, dimension, left_layer, left_value, right_layer, right_value, variance, verdict FROM cred.control_result;

-- finance only: everything, including vendor name and the real codes
CREATE VIEW cred.v_open_item_named_any_run AS
SELECT i.*, v.vendor_ref, v.slid, v.vendor_name, v.party_class, v.party_class_type, v.credit_days, v.vendor_extinct
FROM cred.open_item i JOIN cred.vendor_snapshot v USING (extraction_run_id, sub_ledger_code);

CREATE VIEW cred.v_live_run AS
SELECT r.extraction_run_id, r.as_of_date, r.contract_version, r.rules_version, r.expected_rows, r.recon_state, r.publication_state, l.since AS live_since
FROM cred.run r JOIN cred.live_run l USING (extraction_run_id);
CREATE VIEW cred.v_open_item AS SELECT v.* FROM cred.v_open_item_any_run v JOIN cred.live_run l USING (extraction_run_id);
CREATE VIEW cred.v_exposure_summary AS SELECT v.* FROM cred.v_exposure_summary_any_run v JOIN cred.live_run l USING (extraction_run_id);
CREATE VIEW cred.v_vendor_counts AS SELECT v.* FROM cred.v_vendor_counts_any_run v JOIN cred.live_run l USING (extraction_run_id);
CREATE VIEW cred.v_live_controls AS SELECT v.* FROM cred.v_control_result_any_run v JOIN cred.live_run l USING (extraction_run_id);
CREATE VIEW cred.v_open_item_named AS SELECT v.* FROM cred.v_open_item_named_any_run v JOIN cred.live_run l USING (extraction_run_id);

-- ───────────────────────────── indexes ─────────────────────────────

CREATE INDEX ON cred.open_item (extraction_run_id, ledger_code, drcr);
CREATE INDEX ON cred.open_item (extraction_run_id, document_age_bucket, drcr);
CREATE INDEX ON cred.open_item (extraction_run_id, due_status, drcr);
CREATE INDEX ON cred.open_item (extraction_run_id, sub_ledger_code);
CREATE INDEX ON cred.vendor_snapshot (extraction_run_id, party_class);
CREATE INDEX ON cred.control_result (extraction_run_id) WHERE verdict <> 'PASS';
CREATE INDEX ON cred.run_event (extraction_run_id, at);
CREATE INDEX ON cred.promotion (extraction_run_id, at DESC);

-- ───────────────────────────── grants ─────────────────────────────

REVOKE ALL ON ALL TABLES IN SCHEMA cred FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA cred FROM PUBLIC;

GRANT USAGE ON SCHEMA cred TO cred_loader, cred_verifier, cred_api_reader, cred_finance_reader;

-- loader: bulk insert of one run; reads what it needs to compute its own controls; cannot update, delete, promote or change schema
GRANT INSERT ON cred.run, cred.vendor_snapshot, cred.open_item, cred.identity_snapshot, cred.load_rejection TO cred_loader;
GRANT SELECT ON cred.run, cred.vendor_snapshot, cred.open_item, cred.identity_snapshot, cred.control_result TO cred_loader;
GRANT USAGE ON SEQUENCE cred.load_rejection_rejection_id_seq TO cred_loader;
GRANT EXECUTE ON FUNCTION cred.record_control(text, text, text, text, numeric, text, numeric), cred.verify_run(text), cred.mart_checks(text) TO cred_loader;

-- verifier: masked candidate data and results; writes only through controlled functions
GRANT SELECT ON cred.v_open_item_any_run, cred.v_exposure_summary_any_run, cred.v_vendor_counts_any_run, cred.v_control_result_any_run, cred.v_live_run TO cred_verifier;
GRANT EXECUTE ON FUNCTION cred.record_control(text, text, text, text, numeric, text, numeric), cred.api_verify_run(text), cred.ui_verify_run(text) TO cred_verifier;

-- API: approved masked views of the LIVE run only
GRANT SELECT ON cred.v_live_run, cred.v_open_item, cred.v_exposure_summary, cred.v_vendor_counts, cred.v_live_controls TO cred_api_reader;

-- Finance / CFO (and an Admin application role mapped here): the same plus the named view
GRANT SELECT ON cred.v_live_run, cred.v_open_item, cred.v_exposure_summary, cred.v_vendor_counts, cred.v_live_controls, cred.v_open_item_named TO cred_finance_reader;

-- operator functions: the owner only
GRANT EXECUTE ON FUNCTION cred.promote_run(text, text), cred.demote_to(text, text), cred.purge_run(text, text), cred.set_policy(boolean, boolean, text),
                           cred.verify_run(text), cred.mart_checks(text) TO cred_owner;
-- harmless read-only helpers used inside the guard triggers, which run with the caller's rights
GRANT EXECUTE ON FUNCTION cred.caller_role(), cred.caller_is(name), cred.maintenance_on() TO PUBLIC;

RESET ROLE;
