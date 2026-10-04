-- Cash and working capital mart, schema `cash` (migration 004). Applied by the database administrator, objects owned by cash_owner.
-- Same discipline as the creditors mart: immutable, run-versioned snapshots; reconciliation state and publication state are separate;
-- every change of state goes through a controlled function. Creditor figures are NOT stored here: the API reads them from the creditors mart
-- (one source of truth) and states which creditors run it used.
--
-- What a run holds:
--   store_till   : one row per store: till cash (cumulative balance) on the position date, month-to-date and year-to-date Dr/Cr.
--   bank_ledger  : one row per bank/cash ledger per source (site register, GL register, prior-year closing): opening, posted, unposted and
--                  future-dated debits/credits, last posted and last entry dates. These are LEDGER BOOK figures, not bank-reconciled.

DO $pre$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cash_owner') THEN RAISE EXCEPTION 'run 000_roles.sql first'; END IF;
  IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'cash') THEN RAISE EXCEPTION 'schema cash already exists: migrations are not re-runnable'; END IF;
  IF to_regclass('core.v_domain_run') IS NULL THEN RAISE EXCEPTION 'apply migration 003 (shared run model) first'; END IF;
  EXECUTE format('GRANT CONNECT, CREATE ON DATABASE %I TO cash_owner', current_database());
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO cash_loader, cash_verifier, cash_promoter, cash_api_reader', current_database());
END
$pre$;

SET ROLE cash_owner;
CREATE SCHEMA cash;
REVOKE ALL ON SCHEMA cash FROM PUBLIC;

-- ───────────────────────────── tables ─────────────────────────────

CREATE TABLE cash.run (
  run_id                 text PRIMARY KEY CHECK (run_id ~ '^run_[0-9]{8}_[0-9]{3}$'),
  as_of_date             date NOT NULL,                       -- the register report date: the position cut-off
  till_balance_date      date NOT NULL,                       -- the date the store till balances are read on
  package                text NOT NULL,
  contract_version       text NOT NULL,
  rules                  jsonb NOT NULL,
  manifest_sha256        char(64) NOT NULL UNIQUE CHECK (manifest_sha256 ~ '^[0-9a-f]{64}$'),
  staging_report_sha256  char(64) NOT NULL CHECK (staging_report_sha256 ~ '^[0-9a-f]{64}$'),
  extract_started_at     timestamptz NOT NULL,
  extract_finished_at    timestamptz NOT NULL,
  expected_store_rows    integer NOT NULL CHECK (expected_store_rows > 0),
  expected_bank_rows     integer NOT NULL CHECK (expected_bank_rows > 0),
  loaded_at              timestamptz NOT NULL DEFAULT now(),
  loaded_by              text NOT NULL DEFAULT current_user,
  recon_state            text NOT NULL DEFAULT 'loaded' CHECK (recon_state IN ('loaded', 'verified', 'api_verified')),
  publication_state      text NOT NULL DEFAULT 'unpublished' CHECK (publication_state IN ('unpublished', 'live', 'superseded', 'withdrawn')),
  CHECK (extract_finished_at >= extract_started_at),
  CHECK (till_balance_date <= as_of_date)
);

CREATE TABLE cash.store_till (
  run_id              text NOT NULL REFERENCES cash.run,
  site_code           text NOT NULL,
  store_name          text,
  cumulative_balance  numeric(30,4) NOT NULL,
  mtd_debit           numeric(30,4) NOT NULL,
  mtd_credit          numeric(30,4) NOT NULL,
  fytd_debit          numeric(30,4) NOT NULL,
  fytd_credit         numeric(30,4) NOT NULL,
  last_activity_date  date,
  PRIMARY KEY (run_id, site_code)
);

CREATE TABLE cash.bank_ledger (
  run_id              text NOT NULL REFERENCES cash.run,
  source              text NOT NULL CHECK (source IN ('site_register', 'gl_register', 'prior_year_closing')),
  ledger_code         text NOT NULL,
  ledger_name         text NOT NULL,
  gl_type             text,
  nature              text,
  extinct             text,
  has_movement        boolean NOT NULL,
  opening_dr          numeric(30,4) NOT NULL,
  opening_cr          numeric(30,4) NOT NULL,
  posted_dr           numeric(30,4) NOT NULL,
  posted_cr           numeric(30,4) NOT NULL,
  unposted_dr         numeric(30,4) NOT NULL,
  unposted_cr         numeric(30,4) NOT NULL,
  future_net          numeric(30,4) NOT NULL,                -- future-dated entries, posted and unposted, net Dr - Cr: shown, never in a position
  contra_posted_dr    numeric(30,4) NOT NULL,
  contra_posted_cr    numeric(30,4) NOT NULL,
  opening_rows        integer NOT NULL,
  posted_rows         integer NOT NULL,
  unposted_rows       integer NOT NULL,
  future_rows         integer NOT NULL,
  last_posted_date    date,
  last_entry_date     date,
  register_report_date date,
  sites               integer,
  -- derived in the mart from the stored figures so the arithmetic is one definition
  opening_balance     numeric(30,4) GENERATED ALWAYS AS (opening_dr - opening_cr) STORED,
  posted_closing      numeric(30,4) GENERATED ALWAYS AS (opening_dr - opening_cr + posted_dr - posted_cr) STORED,
  unposted_movement   numeric(30,4) GENERATED ALWAYS AS (unposted_dr - unposted_cr) STORED,
  including_unposted  numeric(30,4) GENERATED ALWAYS AS (opening_dr - opening_cr + posted_dr - posted_cr + unposted_dr - unposted_cr) STORED,
  PRIMARY KEY (run_id, source, ledger_code)
);

CREATE TABLE cash.control_result (
  run_id            text NOT NULL REFERENCES cash.run,
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
  PRIMARY KEY (run_id, control_id, dimension, left_layer, right_layer),
  CHECK ((left_layer, right_layer) IN (('source', 'extract'), ('extract', 'mart'), ('mart', 'api')))
);

CREATE TABLE cash.run_event (
  event_id   bigserial PRIMARY KEY,
  run_id     text NOT NULL REFERENCES cash.run,
  event      text NOT NULL CHECK (event IN ('loaded', 'verified', 'verify_failed', 'api_verified', 'api_verify_failed', 'promoted', 'superseded', 'withdrawn', 'reinstated')),
  detail     jsonb,
  at         timestamptz NOT NULL DEFAULT now(),
  by         text NOT NULL DEFAULT current_user
);

CREATE TABLE cash.load_rejection (
  rejection_id    bigserial PRIMARY KEY,
  run_id          text NOT NULL,
  manifest_sha256 char(64),
  stage           text NOT NULL CHECK (stage IN ('precheck', 'staging_report', 'load', 'mart_controls', 'promotion')),
  reason          text NOT NULL,
  failed_controls jsonb,
  attempted_at    timestamptz NOT NULL DEFAULT now(),
  attempted_by    text NOT NULL DEFAULT current_user
);

CREATE TABLE cash.live_run (
  singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
  run_id    text NOT NULL REFERENCES cash.run,
  since     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE cash.promotion (
  promotion_id bigserial PRIMARY KEY,
  action       text NOT NULL CHECK (action IN ('promote', 'demote')),
  run_id       text NOT NULL REFERENCES cash.run,
  previous_run_id text REFERENCES cash.run,
  reason       text NOT NULL CHECK (length(reason) > 0),
  at           timestamptz NOT NULL DEFAULT now(),
  by           text NOT NULL DEFAULT current_user
);

-- ───────────────────────────── helpers and guards ─────────────────────────────

CREATE FUNCTION cash.caller_role() RETURNS name LANGUAGE sql STABLE AS
$$ SELECT CASE WHEN current_setting('role') <> 'none' THEN current_setting('role')::name ELSE session_user END $$;
CREATE FUNCTION cash.caller_is(p_role name) RETURNS boolean LANGUAGE sql STABLE AS
$$ SELECT pg_has_role(cash.caller_role(), p_role, 'MEMBER') $$;
CREATE FUNCTION cash.maintenance_on() RETURNS boolean LANGUAGE sql STABLE AS
$$ SELECT coalesce(current_setting('cash.maintenance', true), 'off') = 'on' $$;

CREATE FUNCTION cash.deny_mutation() RETURNS trigger LANGUAGE plpgsql AS
$$
BEGIN
  RAISE EXCEPTION '% on cash.% is not allowed: runs are immutable (use the controlled functions)', TG_OP, TG_TABLE_NAME USING ERRCODE = 'insufficient_privilege';
END
$$;
CREATE TRIGGER no_mutation BEFORE UPDATE OR DELETE ON cash.store_till     FOR EACH ROW EXECUTE FUNCTION cash.deny_mutation();
CREATE TRIGGER no_mutation BEFORE UPDATE OR DELETE ON cash.bank_ledger    FOR EACH ROW EXECUTE FUNCTION cash.deny_mutation();
CREATE TRIGGER no_mutation BEFORE UPDATE OR DELETE ON cash.control_result FOR EACH ROW EXECUTE FUNCTION cash.deny_mutation();
CREATE TRIGGER no_mutation BEFORE UPDATE OR DELETE ON cash.run_event      FOR EACH ROW EXECUTE FUNCTION cash.deny_mutation();
CREATE TRIGGER no_mutation BEFORE UPDATE OR DELETE ON cash.load_rejection FOR EACH ROW EXECUTE FUNCTION cash.deny_mutation();
CREATE TRIGGER no_mutation BEFORE UPDATE OR DELETE ON cash.promotion      FOR EACH ROW EXECUTE FUNCTION cash.deny_mutation();
CREATE TRIGGER no_delete   BEFORE DELETE ON cash.run                      FOR EACH ROW EXECUTE FUNCTION cash.deny_mutation();

CREATE FUNCTION cash.guard_run_insert() RETURNS trigger LANGUAGE plpgsql AS
$$
BEGIN
  IF NEW.recon_state <> 'loaded' OR NEW.publication_state <> 'unpublished' THEN RAISE EXCEPTION 'a run must start as loaded / unpublished' USING ERRCODE = 'check_violation'; END IF;
  RETURN NEW;
END
$$;
CREATE TRIGGER run_insert BEFORE INSERT ON cash.run FOR EACH ROW EXECUTE FUNCTION cash.guard_run_insert();

CREATE FUNCTION cash.guard_run_update() RETURNS trigger LANGUAGE plpgsql AS
$$
BEGIN
  IF NOT cash.maintenance_on() THEN RAISE EXCEPTION 'cash.run can only change through the controlled functions' USING ERRCODE = 'insufficient_privilege'; END IF;
  IF (to_jsonb(NEW) - 'recon_state' - 'publication_state') IS DISTINCT FROM (to_jsonb(OLD) - 'recon_state' - 'publication_state') THEN
    RAISE EXCEPTION 'only the state columns of a run may change' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END
$$;
CREATE TRIGGER run_update BEFORE UPDATE ON cash.run FOR EACH ROW EXECUTE FUNCTION cash.guard_run_update();

CREATE FUNCTION cash.guard_open_run() RETURNS trigger LANGUAGE plpgsql AS
$$
DECLARE st text; pub text;
BEGIN
  SELECT recon_state, publication_state INTO st, pub FROM cash.run WHERE run_id = NEW.run_id;
  IF NOT FOUND THEN RAISE EXCEPTION 'run % does not exist', NEW.run_id USING ERRCODE = 'foreign_key_violation'; END IF;
  IF st <> 'loaded' OR pub <> 'unpublished' THEN RAISE EXCEPTION 'run % is closed (% / %): no rows can be added', NEW.run_id, st, pub USING ERRCODE = 'insufficient_privilege'; END IF;
  RETURN NEW;
END
$$;
CREATE TRIGGER run_open BEFORE INSERT ON cash.store_till  FOR EACH ROW EXECUTE FUNCTION cash.guard_open_run();
CREATE TRIGGER run_open BEFORE INSERT ON cash.bank_ledger FOR EACH ROW EXECUTE FUNCTION cash.guard_open_run();

-- ───────────────────────────── structural checks (zero violations expected) ─────────────────────────────

CREATE FUNCTION cash.mart_checks(p_run text) RETURNS TABLE (check_id text, violations bigint) LANGUAGE sql STABLE SECURITY DEFINER SET search_path = cash, pg_temp AS
$$
  SELECT 'M1_store_rows', abs((SELECT count(*) FROM cash.store_till WHERE run_id = p_run) - (SELECT expected_store_rows FROM cash.run WHERE run_id = p_run))::bigint
  UNION ALL SELECT 'M2_bank_rows', abs((SELECT count(*) FROM cash.bank_ledger WHERE run_id = p_run) - (SELECT expected_bank_rows FROM cash.run WHERE run_id = p_run))::bigint
  UNION ALL SELECT 'M3_negative_amounts', count(*) FROM cash.bank_ledger WHERE run_id = p_run
       AND (opening_dr < 0 OR opening_cr < 0 OR posted_dr < 0 OR posted_cr < 0 OR unposted_dr < 0 OR unposted_cr < 0 OR contra_posted_dr < 0 OR contra_posted_cr < 0)
  UNION ALL SELECT 'M4_register_date_vs_run', count(*) FROM cash.bank_ledger b JOIN cash.run r USING (run_id)
       WHERE b.run_id = p_run AND b.source = 'site_register' AND b.register_report_date IS DISTINCT FROM r.as_of_date
  UNION ALL SELECT 'M5_same_ledgers_in_every_current_source', count(*) FROM (
       SELECT ledger_code FROM cash.bank_ledger WHERE run_id = p_run AND source IN ('site_register', 'gl_register') GROUP BY ledger_code HAVING count(*) <> 2) x
  UNION ALL SELECT 'M6_till_dates', count(*) FROM cash.run WHERE run_id = p_run AND till_balance_date > as_of_date
  UNION ALL SELECT 'M7_movement_flag_consistent', count(*) FROM cash.bank_ledger WHERE run_id = p_run
       AND has_movement <> (opening_rows + posted_rows + unposted_rows + future_rows > 0)
$$;

-- ───────────────────────────── controlled functions ─────────────────────────────

CREATE FUNCTION cash.record_control(p_run text, p_id text, p_dim text, p_left_layer text, p_left numeric, p_right_layer text, p_right numeric) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = cash, pg_temp AS
$$
DECLARE st text;
BEGIN
  SELECT recon_state INTO st FROM cash.run WHERE run_id = p_run;
  IF NOT FOUND THEN RAISE EXCEPTION 'run % does not exist', p_run; END IF;
  IF (p_left_layer, p_right_layer) IN (('source', 'extract'), ('extract', 'mart')) THEN
    IF NOT cash.caller_is('cash_loader') THEN RAISE EXCEPTION 'only the loader records source/extract/mart controls' USING ERRCODE = 'insufficient_privilege'; END IF;
    IF st <> 'loaded' THEN RAISE EXCEPTION 'run % is % : its load controls are closed', p_run, st; END IF;
  ELSIF (p_left_layer, p_right_layer) = ('mart', 'api') THEN
    IF NOT cash.caller_is('cash_verifier') THEN RAISE EXCEPTION 'only the verifier records API-layer controls' USING ERRCODE = 'insufficient_privilege'; END IF;
    IF st <> 'verified' THEN RAISE EXCEPTION 'run % must be verified before API controls (it is %)', p_run, st; END IF;
  ELSE
    RAISE EXCEPTION 'unsupported layer pair % -> %', p_left_layer, p_right_layer;
  END IF;
  INSERT INTO cash.control_result (run_id, control_id, dimension, left_layer, left_value, right_layer, right_value) VALUES (p_run, p_id, p_dim, p_left_layer, p_left, p_right_layer, p_right);
END
$$;

CREATE FUNCTION cash.verify_run(p_run text) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = cash, pg_temp AS
$$
DECLARE st text; n_fail int; n_se int; n_em int; bad jsonb;
BEGIN
  IF NOT (cash.caller_is('cash_loader') OR cash.caller_is('cash_owner')) THEN RAISE EXCEPTION 'not allowed' USING ERRCODE = 'insufficient_privilege'; END IF;
  SELECT recon_state INTO st FROM cash.run WHERE run_id = p_run FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'run % does not exist', p_run; END IF;
  IF st <> 'loaded' THEN RAISE EXCEPTION 'run % is already %', p_run, st; END IF;
  SELECT count(*) FILTER (WHERE verdict <> 'PASS'), count(*) FILTER (WHERE left_layer = 'source' AND right_layer = 'extract'), count(*) FILTER (WHERE left_layer = 'extract' AND right_layer = 'mart')
    INTO n_fail, n_se, n_em FROM cash.control_result WHERE run_id = p_run;
  SELECT coalesce(jsonb_object_agg(check_id, violations) FILTER (WHERE violations <> 0), '{}'::jsonb) INTO bad FROM cash.mart_checks(p_run);
  PERFORM set_config('cash.maintenance', 'on', true);
  IF n_fail = 0 AND n_se > 0 AND n_em > 0 AND bad = '{}'::jsonb THEN
    UPDATE cash.run SET recon_state = 'verified' WHERE run_id = p_run;
    INSERT INTO cash.run_event (run_id, event, detail) VALUES (p_run, 'verified', jsonb_build_object('source_extract_controls', n_se, 'extract_mart_controls', n_em));
    PERFORM set_config('cash.maintenance', 'off', true);
    RETURN jsonb_build_object('ok', true, 'recon_state', 'verified');
  END IF;
  INSERT INTO cash.run_event (run_id, event, detail) VALUES (p_run, 'verify_failed', jsonb_build_object('failed_controls', n_fail, 'source_extract_controls', n_se, 'extract_mart_controls', n_em, 'structural', bad));
  PERFORM set_config('cash.maintenance', 'off', true);
  RETURN jsonb_build_object('ok', false, 'failed_controls', n_fail, 'source_extract_controls', n_se, 'extract_mart_controls', n_em, 'structural', bad);
END
$$;

CREATE FUNCTION cash.api_verify_run(p_run text) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = cash, pg_temp AS
$$
DECLARE st text; n_fail int; n int;
BEGIN
  IF NOT cash.caller_is('cash_verifier') THEN RAISE EXCEPTION 'only the verifier verifies layers' USING ERRCODE = 'insufficient_privilege'; END IF;
  SELECT recon_state INTO st FROM cash.run WHERE run_id = p_run FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'run % does not exist', p_run; END IF;
  IF st <> 'verified' THEN RAISE EXCEPTION 'run % is %, expected verified', p_run, st; END IF;
  SELECT count(*), count(*) FILTER (WHERE verdict <> 'PASS') INTO n, n_fail FROM cash.control_result WHERE run_id = p_run AND left_layer = 'mart' AND right_layer = 'api';
  PERFORM set_config('cash.maintenance', 'on', true);
  IF n > 0 AND n_fail = 0 THEN
    UPDATE cash.run SET recon_state = 'api_verified' WHERE run_id = p_run;
    INSERT INTO cash.run_event (run_id, event, detail) VALUES (p_run, 'api_verified', jsonb_build_object('controls', n));
    PERFORM set_config('cash.maintenance', 'off', true);
    RETURN jsonb_build_object('ok', true, 'recon_state', 'api_verified');
  END IF;
  INSERT INTO cash.run_event (run_id, event, detail) VALUES (p_run, 'api_verify_failed', jsonb_build_object('controls', n, 'failed', n_fail));
  PERFORM set_config('cash.maintenance', 'off', true);
  RETURN jsonb_build_object('ok', false, 'controls', n, 'failed', n_fail);
END
$$;

CREATE FUNCTION cash.promote_run(p_run text, p_reason text) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = cash, pg_temp AS
$$
DECLARE r cash.run%ROWTYPE; prev text; prev_asof date; fails int; n bigint;
BEGIN
  IF NOT cash.caller_is('cash_promoter') THEN RAISE EXCEPTION 'only the promoter publishes runs' USING ERRCODE = 'insufficient_privilege'; END IF;
  SELECT * INTO r FROM cash.run WHERE run_id = p_run FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'run % does not exist', p_run; END IF;
  IF r.publication_state <> 'unpublished' THEN RAISE EXCEPTION 'run % is % and cannot be promoted here', p_run, r.publication_state; END IF;
  IF r.recon_state <> 'api_verified' THEN RAISE EXCEPTION 'run % is % but promotion requires api_verified', p_run, r.recon_state; END IF;
  SELECT count(*) INTO fails FROM cash.control_result WHERE run_id = p_run AND verdict <> 'PASS';
  IF fails > 0 THEN RAISE EXCEPTION 'run %: % control(s) failed', p_run, fails; END IF;
  SELECT count(*) INTO n FROM cash.store_till WHERE run_id = p_run;
  IF n <> r.expected_store_rows THEN RAISE EXCEPTION 'run %: % store rows loaded, % expected', p_run, n, r.expected_store_rows; END IF;
  SELECT l.run_id, x.as_of_date INTO prev, prev_asof FROM cash.live_run l JOIN cash.run x USING (run_id);
  IF prev IS NOT NULL AND r.as_of_date < prev_asof THEN RAISE EXCEPTION 'run % is older (as_of %) than the live run (as_of %): use demote_to', p_run, r.as_of_date, prev_asof; END IF;
  PERFORM set_config('cash.maintenance', 'on', true);
  INSERT INTO cash.live_run (run_id) VALUES (p_run) ON CONFLICT (singleton) DO UPDATE SET run_id = EXCLUDED.run_id, since = now();
  IF prev IS NOT NULL THEN
    UPDATE cash.run SET publication_state = 'superseded' WHERE run_id = prev;
    INSERT INTO cash.run_event (run_id, event, detail) VALUES (prev, 'superseded', jsonb_build_object('by', p_run));
  END IF;
  UPDATE cash.run SET publication_state = 'live' WHERE run_id = p_run;
  INSERT INTO cash.run_event (run_id, event, detail) VALUES (p_run, 'promoted', jsonb_build_object('previous', prev, 'reason', p_reason));
  INSERT INTO cash.promotion (action, run_id, previous_run_id, reason) VALUES ('promote', p_run, prev, p_reason);
  PERFORM set_config('cash.maintenance', 'off', true);
END
$$;

CREATE FUNCTION cash.demote_to(p_target text, p_reason text) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = cash, pg_temp AS
$$
DECLARE t cash.run%ROWTYPE; cur text;
BEGIN
  IF NOT cash.caller_is('cash_promoter') THEN RAISE EXCEPTION 'only the promoter rolls back' USING ERRCODE = 'insufficient_privilege'; END IF;
  SELECT * INTO t FROM cash.run WHERE run_id = p_target FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'run % does not exist', p_target; END IF;
  IF t.publication_state <> 'superseded' THEN RAISE EXCEPTION 'run % is % : only a previously live (superseded) run can be reinstated', p_target, t.publication_state; END IF;
  SELECT run_id INTO cur FROM cash.live_run;
  IF cur IS NULL THEN RAISE EXCEPTION 'there is no live run to roll back from'; END IF;
  PERFORM set_config('cash.maintenance', 'on', true);
  UPDATE cash.live_run SET run_id = p_target, since = now() WHERE singleton;
  UPDATE cash.run SET publication_state = 'withdrawn' WHERE run_id = cur;
  UPDATE cash.run SET publication_state = 'live' WHERE run_id = p_target;
  INSERT INTO cash.run_event (run_id, event, detail) VALUES (cur, 'withdrawn', jsonb_build_object('rolled_back_to', p_target, 'reason', p_reason));
  INSERT INTO cash.run_event (run_id, event, detail) VALUES (p_target, 'reinstated', jsonb_build_object('replaces', cur, 'reason', p_reason));
  INSERT INTO cash.promotion (action, run_id, previous_run_id, reason) VALUES ('demote', p_target, cur, p_reason);
  PERFORM set_config('cash.maintenance', 'off', true);
END
$$;

-- ───────────────────────────── views ─────────────────────────────

-- a run that may be SERVED: reconciled at least to `verified` (candidate) or published (live). A merely `loaded` run is not served.
CREATE VIEW cash.v_serving_run AS
SELECT r.run_id, r.as_of_date, r.till_balance_date, r.recon_state, r.publication_state, r.contract_version, r.extract_finished_at, r.loaded_at, r.expected_store_rows, r.expected_bank_rows
FROM cash.run r WHERE r.recon_state IN ('verified', 'api_verified');

CREATE VIEW cash.v_store_till AS SELECT t.* FROM cash.store_till t JOIN cash.v_serving_run s USING (run_id);
CREATE VIEW cash.v_bank_ledger AS SELECT b.* FROM cash.bank_ledger b JOIN cash.v_serving_run s USING (run_id);
CREATE VIEW cash.v_control AS SELECT c.* FROM cash.control_result c JOIN cash.v_serving_run s USING (run_id);
CREATE VIEW cash.v_run_status AS SELECT run_id, as_of_date, recon_state, publication_state, loaded_at FROM cash.run;
CREATE VIEW cash.v_promotion_history AS SELECT promotion_id, action, run_id, previous_run_id, reason, at, by FROM cash.promotion;

CREATE INDEX ON cash.control_result (run_id) WHERE verdict <> 'PASS';
CREATE INDEX ON cash.run_event (run_id, at);

-- ───────────────────────────── grants ─────────────────────────────

REVOKE ALL ON ALL TABLES IN SCHEMA cash FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA cash FROM PUBLIC;
GRANT USAGE ON SCHEMA cash TO cash_loader, cash_verifier, cash_promoter, cash_api_reader;

GRANT INSERT ON cash.run, cash.store_till, cash.bank_ledger, cash.load_rejection TO cash_loader;
GRANT SELECT ON cash.run, cash.store_till, cash.bank_ledger, cash.control_result TO cash_loader;
GRANT USAGE ON SEQUENCE cash.load_rejection_rejection_id_seq TO cash_loader;
GRANT EXECUTE ON FUNCTION cash.record_control(text, text, text, text, numeric, text, numeric), cash.verify_run(text), cash.mart_checks(text) TO cash_loader;

GRANT SELECT ON cash.v_serving_run, cash.v_store_till, cash.v_bank_ledger, cash.v_control TO cash_verifier, cash_api_reader;
GRANT EXECUTE ON FUNCTION cash.record_control(text, text, text, text, numeric, text, numeric), cash.api_verify_run(text) TO cash_verifier;

GRANT SELECT ON cash.v_run_status, cash.v_promotion_history, cash.v_control TO cash_promoter;
GRANT EXECUTE ON FUNCTION cash.promote_run(text, text), cash.demote_to(text, text) TO cash_promoter;
GRANT EXECUTE ON FUNCTION cash.verify_run(text), cash.mart_checks(text) TO cash_owner;
GRANT EXECUTE ON FUNCTION cash.caller_role(), cash.caller_is(name), cash.maintenance_on() TO PUBLIC;

RESET ROLE;

-- the shared run model learns about the Cash domain (a view over each domain's own run table: nothing is copied)
CREATE OR REPLACE VIEW core.v_domain_run AS
SELECT 'creditors'::text AS domain, r.extraction_run_id AS run_id, r.as_of_date, 'validated'::text AS source_state,
       CASE r.recon_state WHEN 'loaded' THEN 'loaded' ELSE 'verified' END AS mart_state,
       CASE WHEN r.recon_state IN ('api_verified', 'ui_verified') THEN 'verified' ELSE 'pending' END AS api_state,
       r.publication_state, r.recon_state AS reconciliation_status, r.extract_finished_at AS source_updated_at, r.loaded_at, (r.publication_state = 'live') AS is_live
FROM cred.run r
UNION ALL
SELECT 'cash'::text, c.run_id, c.as_of_date, 'validated'::text,
       CASE c.recon_state WHEN 'loaded' THEN 'loaded' ELSE 'verified' END,
       CASE WHEN c.recon_state = 'api_verified' THEN 'verified' ELSE 'pending' END,
       c.publication_state, c.recon_state, c.extract_finished_at, c.loaded_at, (c.publication_state = 'live')
FROM cash.run c;

GRANT USAGE ON SCHEMA core TO cred_verifier, cred_api_reader, cred_finance_reader, cred_promoter, cash_verifier, cash_api_reader, cash_promoter;
GRANT SELECT ON core.v_domain_run TO cred_verifier, cred_api_reader, cred_finance_reader, cred_promoter, cash_verifier, cash_api_reader, cash_promoter;

INSERT INTO cred.schema_migration (version, description) VALUES
  ('004', 'cash schema: immutable runs of store till cash and bank ledger book figures, controlled functions, serving views, grants; core.v_domain_run learns cash');
