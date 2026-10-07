-- Store P&L actuals mart, schema `pnl` (migration 008). Applied by the database administrator, objects owned by pnl_owner.
-- Same discipline as the creditors, cash and entry marts: immutable, run-versioned snapshots; reconciliation state and publication state are separate;
-- every change of state goes through a controlled function. A run holds:
--   gl_site_month    : the books. P&L-ledger lines by site, month, ledger, entry type and posting status (debit, credit), each in a P&L section (REVENUE, COGS_BOOKS, STORE_OPEX,
--                      OTHER_INCOME, FINANCE_COST) or UNMAPPED (a ledger the finance mapping does not know: kept and shown, never guessed into a section).
--   cogs_site_month  : the COGS table (T_CUSTOM_COGS) by site and month: sales value (incl. GST), tax, COGS, quantity.
--   sales_tieout     : per site and month, books sales (ledger "Sales - POS") against the COGS table's sales ex-GST, with the difference and a tied flag.
--   site, group_section: the site master (region, cluster, state, status) and the section each finance group belongs to.
-- Budget is NOT held: it is not available for FY26-27 and is shown as blank.

DO $pre$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pnl_owner') THEN RAISE EXCEPTION 'run 000_roles.sql first'; END IF;
  IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'pnl') THEN RAISE EXCEPTION 'schema pnl already exists: migrations are not re-runnable'; END IF;
  IF to_regclass('core.v_domain_run') IS NULL OR to_regclass('entry.run') IS NULL THEN RAISE EXCEPTION 'apply migrations 001 to 007 first'; END IF;
  EXECUTE format('GRANT CONNECT, CREATE ON DATABASE %I TO pnl_owner', current_database());
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO pnl_loader, pnl_verifier, pnl_promoter, pnl_api_reader', current_database());
END
$pre$;

SET ROLE pnl_owner;
CREATE SCHEMA pnl;
REVOKE ALL ON SCHEMA pnl FROM PUBLIC;

-- ───────────────────────────── tables ─────────────────────────────

CREATE TABLE pnl.run (
  run_id                 text PRIMARY KEY CHECK (run_id ~ '^run_[0-9]{8}_[0-9]{3}$'),
  as_of_date             date NOT NULL,                       -- the register report date: the cut-off of the books
  cogs_run_id            text NOT NULL,                       -- the COGS-table scan this run was built with
  cogs_last_bill_date    date NOT NULL,                       -- newest bill date in the COGS table
  package                text NOT NULL,
  contract_version       text NOT NULL,
  rules                  jsonb NOT NULL,
  manifest_sha256        char(64) NOT NULL UNIQUE CHECK (manifest_sha256 ~ '^[0-9a-f]{64}$'),
  cogs_manifest_sha256   char(64) NOT NULL CHECK (cogs_manifest_sha256 ~ '^[0-9a-f]{64}$'),
  staging_report_sha256  char(64) NOT NULL CHECK (staging_report_sha256 ~ '^[0-9a-f]{64}$'),
  extract_started_at     timestamptz NOT NULL,
  extract_finished_at    timestamptz NOT NULL,
  expected_gl_rows       integer NOT NULL CHECK (expected_gl_rows > 0),
  expected_cogs_rows     integer NOT NULL CHECK (expected_cogs_rows > 0),
  expected_sites         integer NOT NULL CHECK (expected_sites > 0),
  tolerance_rupees       numeric(30,4) NOT NULL,
  loaded_at              timestamptz NOT NULL DEFAULT now(),
  loaded_by              text NOT NULL DEFAULT current_user,
  recon_state            text NOT NULL DEFAULT 'loaded' CHECK (recon_state IN ('loaded', 'verified', 'api_verified')),
  publication_state      text NOT NULL DEFAULT 'unpublished' CHECK (publication_state IN ('unpublished', 'live', 'superseded', 'withdrawn')),
  CHECK (extract_finished_at >= extract_started_at)
);

CREATE TABLE pnl.site (
  run_id               text NOT NULL REFERENCES pnl.run,
  site_code            text NOT NULL,
  store_name           text,
  opening_date         date,
  store_status         text,
  store_current_status text,
  cluster_type         text,
  region_type          text,
  state                text,
  store_type           text,
  last_bill_date       date,
  PRIMARY KEY (run_id, site_code)
);

CREATE TABLE pnl.group_section (
  run_id      text NOT NULL REFERENCES pnl.run,
  group_label text NOT NULL,
  section     text NOT NULL CHECK (section IN ('REVENUE', 'COGS_BOOKS', 'STORE_OPEX', 'OTHER_INCOME', 'FINANCE_COST')),
  PRIMARY KEY (run_id, group_label)
);

CREATE TABLE pnl.gl_site_month (
  run_id           text NOT NULL REFERENCES pnl.run,
  site_code        text NOT NULL,
  month            date NOT NULL CHECK (month = date_trunc('month', month)::date),
  glcode           text NOT NULL,
  ledger_name      text NOT NULL,
  group_label      text,
  section          text NOT NULL CHECK (section IN ('REVENUE', 'COGS_BOOKS', 'STORE_OPEX', 'OTHER_INCOME', 'FINANCE_COST', 'UNMAPPED')),
  entry_type_short text NOT NULL,
  release_status   text NOT NULL CHECK (release_status IN ('Posted', 'Unposted')),
  debit            numeric(30,4) NOT NULL CHECK (debit >= 0),
  credit           numeric(30,4) NOT NULL CHECK (credit >= 0),
  lines            integer NOT NULL CHECK (lines > 0),
  PRIMARY KEY (run_id, site_code, month, glcode, entry_type_short, release_status),
  CHECK ((section = 'UNMAPPED') = (group_label IS NULL))
);

CREATE TABLE pnl.cogs_site_month (
  run_id     text NOT NULL REFERENCES pnl.run,
  site_code  text NOT NULL,
  month      date NOT NULL CHECK (month = date_trunc('month', month)::date),
  sl_v       numeric(30,4) NOT NULL,                          -- sales value INCLUDING GST (POS basis)
  tax_amt    numeric(30,4) NOT NULL,
  cogs_v     numeric(30,4) NOT NULL,
  sl_q       numeric(30,4) NOT NULL,
  rows_n     integer NOT NULL,
  bill_days  integer NOT NULL,
  first_bill date,
  last_bill  date,
  PRIMARY KEY (run_id, site_code, month)
);

CREATE TABLE pnl.sales_tieout (
  run_id                  text NOT NULL REFERENCES pnl.run,
  site_code               text NOT NULL,
  month                   date NOT NULL,
  books_sales             numeric(30,4) NOT NULL,             -- GL "Sales - POS": credit less debit, ex-GST
  cogs_table_sales_ex_gst numeric(30,4) NOT NULL,             -- COGS table SL_V less TAXAMT
  difference              numeric(30,4) NOT NULL,
  tied                    boolean NOT NULL,
  PRIMARY KEY (run_id, site_code, month),
  CHECK (difference = books_sales - cogs_table_sales_ex_gst)
);

CREATE TABLE pnl.control_result (
  run_id            text NOT NULL REFERENCES pnl.run,
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

CREATE TABLE pnl.run_event (
  event_id   bigserial PRIMARY KEY,
  run_id     text NOT NULL REFERENCES pnl.run,
  event      text NOT NULL CHECK (event IN ('loaded', 'verified', 'verify_failed', 'api_verified', 'api_verify_failed', 'promoted', 'superseded', 'withdrawn', 'reinstated')),
  detail     jsonb,
  at         timestamptz NOT NULL DEFAULT now(),
  by         text NOT NULL DEFAULT current_user
);

CREATE TABLE pnl.load_rejection (
  rejection_id    bigserial PRIMARY KEY,
  run_id          text NOT NULL,
  manifest_sha256 char(64),
  stage           text NOT NULL CHECK (stage IN ('precheck', 'staging_report', 'load', 'mart_controls', 'promotion')),
  reason          text NOT NULL,
  failed_controls jsonb,
  attempted_at    timestamptz NOT NULL DEFAULT now(),
  attempted_by    text NOT NULL DEFAULT current_user
);

CREATE TABLE pnl.live_run (
  singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
  run_id    text NOT NULL REFERENCES pnl.run,
  since     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE pnl.promotion (
  promotion_id bigserial PRIMARY KEY,
  action       text NOT NULL CHECK (action IN ('promote', 'demote')),
  run_id       text NOT NULL REFERENCES pnl.run,
  previous_run_id text REFERENCES pnl.run,
  reason       text NOT NULL CHECK (length(reason) > 0),
  at           timestamptz NOT NULL DEFAULT now(),
  by           text NOT NULL DEFAULT current_user
);

-- ───────────────────────────── helpers and guards ─────────────────────────────

CREATE FUNCTION pnl.caller_role() RETURNS name LANGUAGE sql STABLE AS
$$ SELECT CASE WHEN current_setting('role') <> 'none' THEN current_setting('role')::name ELSE session_user END $$;
CREATE FUNCTION pnl.caller_is(p_role name) RETURNS boolean LANGUAGE sql STABLE AS
$$ SELECT pg_has_role(pnl.caller_role(), p_role, 'MEMBER') $$;
CREATE FUNCTION pnl.maintenance_on() RETURNS boolean LANGUAGE sql STABLE AS
$$ SELECT coalesce(current_setting('pnl.maintenance', true), 'off') = 'on' $$;

CREATE FUNCTION pnl.deny_mutation() RETURNS trigger LANGUAGE plpgsql AS
$$
BEGIN
  RAISE EXCEPTION '% on pnl.% is not allowed: runs are immutable (use the controlled functions)', TG_OP, TG_TABLE_NAME USING ERRCODE = 'insufficient_privilege';
END
$$;
CREATE TRIGGER no_delete   BEFORE DELETE ON pnl.run                      FOR EACH ROW EXECUTE FUNCTION pnl.deny_mutation();

CREATE FUNCTION pnl.guard_run_insert() RETURNS trigger LANGUAGE plpgsql AS
$$
BEGIN
  IF NEW.recon_state <> 'loaded' OR NEW.publication_state <> 'unpublished' THEN RAISE EXCEPTION 'a run must start as loaded / unpublished' USING ERRCODE = 'check_violation'; END IF;
  RETURN NEW;
END
$$;
CREATE TRIGGER run_insert BEFORE INSERT ON pnl.run FOR EACH ROW EXECUTE FUNCTION pnl.guard_run_insert();

CREATE FUNCTION pnl.guard_run_update() RETURNS trigger LANGUAGE plpgsql AS
$$
BEGIN
  IF NOT pnl.maintenance_on() THEN RAISE EXCEPTION 'pnl.run can only change through the controlled functions' USING ERRCODE = 'insufficient_privilege'; END IF;
  IF (to_jsonb(NEW) - 'recon_state' - 'publication_state') IS DISTINCT FROM (to_jsonb(OLD) - 'recon_state' - 'publication_state') THEN
    RAISE EXCEPTION 'only the state columns of a run may change' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END
$$;
CREATE TRIGGER run_update BEFORE UPDATE ON pnl.run FOR EACH ROW EXECUTE FUNCTION pnl.guard_run_update();

CREATE FUNCTION pnl.guard_open_run() RETURNS trigger LANGUAGE plpgsql AS
$$
DECLARE st text; pub text;
BEGIN
  SELECT recon_state, publication_state INTO st, pub FROM pnl.run WHERE run_id = NEW.run_id;
  IF NOT FOUND THEN RAISE EXCEPTION 'run % does not exist', NEW.run_id USING ERRCODE = 'foreign_key_violation'; END IF;
  IF st <> 'loaded' OR pub <> 'unpublished' THEN RAISE EXCEPTION 'run % is closed (% / %): no rows can be added', NEW.run_id, st, pub USING ERRCODE = 'insufficient_privilege'; END IF;
  RETURN NEW;
END
$$;


DO $t$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['site', 'group_section', 'gl_site_month', 'cogs_site_month', 'sales_tieout', 'control_result', 'run_event', 'load_rejection', 'promotion'] LOOP
    EXECUTE format('CREATE TRIGGER no_mutation BEFORE UPDATE OR DELETE ON pnl.%I FOR EACH ROW EXECUTE FUNCTION pnl.deny_mutation()', t);
  END LOOP;
  FOREACH t IN ARRAY ARRAY['site', 'group_section', 'gl_site_month', 'cogs_site_month', 'sales_tieout'] LOOP
    EXECUTE format('CREATE TRIGGER run_open BEFORE INSERT ON pnl.%I FOR EACH ROW EXECUTE FUNCTION pnl.guard_open_run()', t);
  END LOOP;
END
$t$;

-- ───────────────────────────── structural checks (zero violations expected) ─────────────────────────────
-- Every row of the output is a COUNT.

CREATE FUNCTION pnl.mart_checks(p_run text) RETURNS TABLE (check_id text, violations bigint) LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pnl, pg_temp AS
$$
  SELECT 'M01_gl_rows', abs((SELECT count(*) FROM pnl.gl_site_month WHERE run_id = p_run) - (SELECT expected_gl_rows FROM pnl.run WHERE run_id = p_run))::bigint
  UNION ALL SELECT 'M02_cogs_rows', abs((SELECT count(*) FROM pnl.cogs_site_month WHERE run_id = p_run) - (SELECT expected_cogs_rows FROM pnl.run WHERE run_id = p_run))::bigint
  UNION ALL SELECT 'M03_site_rows', abs((SELECT count(*) FROM pnl.site WHERE run_id = p_run) - (SELECT expected_sites FROM pnl.run WHERE run_id = p_run))::bigint
  -- no book row after the as-of month; no COGS row after it either
  UNION ALL SELECT 'M04_no_month_after_as_of', (SELECT count(*) FROM pnl.gl_site_month g JOIN pnl.run r USING (run_id) WHERE g.run_id = p_run AND g.month > date_trunc('month', r.as_of_date)::date)
       + (SELECT count(*) FROM pnl.cogs_site_month g JOIN pnl.run r USING (run_id) WHERE g.run_id = p_run AND g.month > date_trunc('month', r.as_of_date)::date)
  -- the tie-out table is exactly the books sales and the COGS-table sales, recomputed here from the stored rows
  UNION ALL SELECT 'M05_tieout_books_sales_recomputed', count(*) FROM (
       SELECT t.site_code, t.month, t.books_sales, coalesce(b.v, 0) AS v FROM pnl.sales_tieout t
         LEFT JOIN (SELECT site_code, month, sum(credit - debit) AS v FROM pnl.gl_site_month WHERE run_id = p_run AND ledger_name = 'Sales - POS' GROUP BY 1, 2) b USING (site_code, month)
        WHERE t.run_id = p_run) x WHERE x.books_sales <> x.v
  UNION ALL SELECT 'M06_tieout_table_sales_recomputed', count(*) FROM (
       SELECT t.cogs_table_sales_ex_gst, coalesce(c.sl_v - c.tax_amt, 0) AS v FROM pnl.sales_tieout t
         LEFT JOIN pnl.cogs_site_month c ON c.run_id = t.run_id AND c.site_code = t.site_code AND c.month = t.month WHERE t.run_id = p_run) x WHERE x.cogs_table_sales_ex_gst <> x.v
  UNION ALL SELECT 'M07_tied_flag_matches_tolerance', count(*) FROM pnl.sales_tieout t JOIN pnl.run r USING (run_id) WHERE t.run_id = p_run AND t.tied <> (abs(t.difference) <= r.tolerance_rupees)
  -- every site-month with books sales or table sales has a tie-out row
  UNION ALL SELECT 'M08_tieout_covers_every_site_month', (SELECT count(*) FROM (
          SELECT DISTINCT site_code, month FROM pnl.gl_site_month WHERE run_id = p_run AND ledger_name = 'Sales - POS'
          UNION SELECT site_code, month FROM pnl.cogs_site_month WHERE run_id = p_run) k
        WHERE NOT EXISTS (SELECT 1 FROM pnl.sales_tieout t WHERE t.run_id = p_run AND t.site_code = k.site_code AND t.month = k.month))
  -- every mapped group has a section row, and the section agrees
  UNION ALL SELECT 'M09_group_has_a_section', count(*) FROM pnl.gl_site_month g WHERE g.run_id = p_run AND g.group_label IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM pnl.group_section s WHERE s.run_id = p_run AND s.group_label = g.group_label AND s.section = g.section)
  -- one ledger is in one group and one section only
  UNION ALL SELECT 'M10_ledger_in_one_section', count(*) FROM (SELECT glcode FROM pnl.gl_site_month WHERE run_id = p_run GROUP BY glcode HAVING count(DISTINCT section) > 1) x
  -- the COGS table's sales and tax are non-negative in total and its bill days fit the month
  UNION ALL SELECT 'M11_cogs_rows_sane', count(*) FROM pnl.cogs_site_month WHERE run_id = p_run AND (bill_days < 1 OR bill_days > 31 OR rows_n < 1)
$$;

-- ───────────────────────────── controlled functions ─────────────────────────────

CREATE FUNCTION pnl.record_control(p_run text, p_id text, p_dim text, p_left_layer text, p_left numeric, p_right_layer text, p_right numeric) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pnl, pg_temp AS
$$
DECLARE st text;
BEGIN
  SELECT recon_state INTO st FROM pnl.run WHERE run_id = p_run;
  IF NOT FOUND THEN RAISE EXCEPTION 'run % does not exist', p_run; END IF;
  IF (p_left_layer, p_right_layer) IN (('source', 'extract'), ('extract', 'mart')) THEN
    IF NOT pnl.caller_is('pnl_loader') THEN RAISE EXCEPTION 'only the loader records source/extract/mart controls' USING ERRCODE = 'insufficient_privilege'; END IF;
    IF st <> 'loaded' THEN RAISE EXCEPTION 'run % is % : its load controls are closed', p_run, st; END IF;
  ELSIF (p_left_layer, p_right_layer) = ('mart', 'api') THEN
    IF NOT pnl.caller_is('pnl_verifier') THEN RAISE EXCEPTION 'only the verifier records API-layer controls' USING ERRCODE = 'insufficient_privilege'; END IF;
    IF st <> 'verified' THEN RAISE EXCEPTION 'run % must be verified before API controls (it is %)', p_run, st; END IF;
  ELSE
    RAISE EXCEPTION 'unsupported layer pair % -> %', p_left_layer, p_right_layer;
  END IF;
  INSERT INTO pnl.control_result (run_id, control_id, dimension, left_layer, left_value, right_layer, right_value) VALUES (p_run, p_id, p_dim, p_left_layer, p_left, p_right_layer, p_right);
END
$$;

CREATE FUNCTION pnl.verify_run(p_run text) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pnl, pg_temp AS
$$
DECLARE st text; n_fail int; n_se int; n_em int; bad jsonb;
BEGIN
  IF NOT (pnl.caller_is('pnl_loader') OR pnl.caller_is('pnl_owner')) THEN RAISE EXCEPTION 'not allowed' USING ERRCODE = 'insufficient_privilege'; END IF;
  SELECT recon_state INTO st FROM pnl.run WHERE run_id = p_run FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'run % does not exist', p_run; END IF;
  IF st <> 'loaded' THEN RAISE EXCEPTION 'run % is already %', p_run, st; END IF;
  SELECT count(*) FILTER (WHERE verdict <> 'PASS'), count(*) FILTER (WHERE left_layer = 'source' AND right_layer = 'extract'), count(*) FILTER (WHERE left_layer = 'extract' AND right_layer = 'mart')
    INTO n_fail, n_se, n_em FROM pnl.control_result WHERE run_id = p_run;
  SELECT coalesce(jsonb_object_agg(check_id, violations) FILTER (WHERE violations <> 0), '{}'::jsonb) INTO bad FROM pnl.mart_checks(p_run);
  PERFORM set_config('pnl.maintenance', 'on', true);
  IF n_fail = 0 AND n_se > 0 AND n_em > 0 AND bad = '{}'::jsonb THEN
    UPDATE pnl.run SET recon_state = 'verified' WHERE run_id = p_run;
    INSERT INTO pnl.run_event (run_id, event, detail) VALUES (p_run, 'verified', jsonb_build_object('source_extract_controls', n_se, 'extract_mart_controls', n_em));
    PERFORM set_config('pnl.maintenance', 'off', true);
    RETURN jsonb_build_object('ok', true, 'recon_state', 'verified');
  END IF;
  INSERT INTO pnl.run_event (run_id, event, detail) VALUES (p_run, 'verify_failed', jsonb_build_object('failed_controls', n_fail, 'source_extract_controls', n_se, 'extract_mart_controls', n_em, 'structural', bad));
  PERFORM set_config('pnl.maintenance', 'off', true);
  RETURN jsonb_build_object('ok', false, 'failed_controls', n_fail, 'source_extract_controls', n_se, 'extract_mart_controls', n_em, 'structural', bad);
END
$$;

CREATE FUNCTION pnl.api_verify_run(p_run text) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pnl, pg_temp AS
$$
DECLARE st text; n_fail int; n int;
BEGIN
  IF NOT pnl.caller_is('pnl_verifier') THEN RAISE EXCEPTION 'only the verifier verifies layers' USING ERRCODE = 'insufficient_privilege'; END IF;
  SELECT recon_state INTO st FROM pnl.run WHERE run_id = p_run FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'run % does not exist', p_run; END IF;
  IF st <> 'verified' THEN RAISE EXCEPTION 'run % is %, expected verified', p_run, st; END IF;
  SELECT count(*), count(*) FILTER (WHERE verdict <> 'PASS') INTO n, n_fail FROM pnl.control_result WHERE run_id = p_run AND left_layer = 'mart' AND right_layer = 'api';
  PERFORM set_config('pnl.maintenance', 'on', true);
  IF n > 0 AND n_fail = 0 THEN
    UPDATE pnl.run SET recon_state = 'api_verified' WHERE run_id = p_run;
    INSERT INTO pnl.run_event (run_id, event, detail) VALUES (p_run, 'api_verified', jsonb_build_object('controls', n));
    PERFORM set_config('pnl.maintenance', 'off', true);
    RETURN jsonb_build_object('ok', true, 'recon_state', 'api_verified');
  END IF;
  INSERT INTO pnl.run_event (run_id, event, detail) VALUES (p_run, 'api_verify_failed', jsonb_build_object('controls', n, 'failed', n_fail));
  PERFORM set_config('pnl.maintenance', 'off', true);
  RETURN jsonb_build_object('ok', false, 'controls', n, 'failed', n_fail);
END
$$;

CREATE FUNCTION pnl.promote_run(p_run text, p_reason text) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pnl, pg_temp AS
$$
DECLARE r pnl.run%ROWTYPE; prev text; prev_asof date; fails int; n bigint;
BEGIN
  IF NOT pnl.caller_is('pnl_promoter') THEN RAISE EXCEPTION 'only the promoter publishes runs' USING ERRCODE = 'insufficient_privilege'; END IF;
  SELECT * INTO r FROM pnl.run WHERE run_id = p_run FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'run % does not exist', p_run; END IF;
  IF r.publication_state <> 'unpublished' THEN RAISE EXCEPTION 'run % is % and cannot be promoted here', p_run, r.publication_state; END IF;
  IF r.recon_state <> 'api_verified' THEN RAISE EXCEPTION 'run % is % but promotion requires api_verified', p_run, r.recon_state; END IF;
  SELECT count(*) INTO fails FROM pnl.control_result WHERE run_id = p_run AND verdict <> 'PASS';
  IF fails > 0 THEN RAISE EXCEPTION 'run %: % control(s) failed', p_run, fails; END IF;
  SELECT count(*) INTO n FROM pnl.gl_site_month WHERE run_id = p_run;
  IF n <> r.expected_gl_rows THEN RAISE EXCEPTION 'run %: % book rows loaded, % expected', p_run, n, r.expected_gl_rows; END IF;
  SELECT l.run_id, x.as_of_date INTO prev, prev_asof FROM pnl.live_run l JOIN pnl.run x USING (run_id);
  IF prev IS NOT NULL AND r.as_of_date < prev_asof THEN RAISE EXCEPTION 'run % is older (as_of %) than the live run (as_of %): use demote_to', p_run, r.as_of_date, prev_asof; END IF;
  PERFORM set_config('pnl.maintenance', 'on', true);
  INSERT INTO pnl.live_run (run_id) VALUES (p_run) ON CONFLICT (singleton) DO UPDATE SET run_id = EXCLUDED.run_id, since = now();
  IF prev IS NOT NULL THEN
    UPDATE pnl.run SET publication_state = 'superseded' WHERE run_id = prev;
    INSERT INTO pnl.run_event (run_id, event, detail) VALUES (prev, 'superseded', jsonb_build_object('by', p_run));
  END IF;
  UPDATE pnl.run SET publication_state = 'live' WHERE run_id = p_run;
  INSERT INTO pnl.run_event (run_id, event, detail) VALUES (p_run, 'promoted', jsonb_build_object('previous', prev, 'reason', p_reason));
  INSERT INTO pnl.promotion (action, run_id, previous_run_id, reason) VALUES ('promote', p_run, prev, p_reason);
  PERFORM set_config('pnl.maintenance', 'off', true);
END
$$;

CREATE FUNCTION pnl.demote_to(p_target text, p_reason text) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pnl, pg_temp AS
$$
DECLARE t pnl.run%ROWTYPE; cur text;
BEGIN
  IF NOT pnl.caller_is('pnl_promoter') THEN RAISE EXCEPTION 'only the promoter rolls back' USING ERRCODE = 'insufficient_privilege'; END IF;
  SELECT * INTO t FROM pnl.run WHERE run_id = p_target FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'run % does not exist', p_target; END IF;
  IF t.publication_state <> 'superseded' THEN RAISE EXCEPTION 'run % is % : only a previously live (superseded) run can be reinstated', p_target, t.publication_state; END IF;
  SELECT run_id INTO cur FROM pnl.live_run;
  IF cur IS NULL THEN RAISE EXCEPTION 'there is no live run to roll back from'; END IF;
  PERFORM set_config('pnl.maintenance', 'on', true);
  UPDATE pnl.live_run SET run_id = p_target, since = now() WHERE singleton;
  UPDATE pnl.run SET publication_state = 'withdrawn' WHERE run_id = cur;
  UPDATE pnl.run SET publication_state = 'live' WHERE run_id = p_target;
  INSERT INTO pnl.run_event (run_id, event, detail) VALUES (cur, 'withdrawn', jsonb_build_object('rolled_back_to', p_target, 'reason', p_reason));
  INSERT INTO pnl.run_event (run_id, event, detail) VALUES (p_target, 'reinstated', jsonb_build_object('replaces', cur, 'reason', p_reason));
  INSERT INTO pnl.promotion (action, run_id, previous_run_id, reason) VALUES ('demote', p_target, cur, p_reason);
  PERFORM set_config('pnl.maintenance', 'off', true);
END
$$;

-- ───────────────────────────── views ─────────────────────────────

-- a run that may be SERVED: reconciled at least to `verified` (candidate) or published (live). A merely `loaded` run is not served.
CREATE VIEW pnl.v_serving_run AS
SELECT r.run_id, r.as_of_date, r.cogs_run_id, r.cogs_last_bill_date, r.recon_state, r.publication_state, r.contract_version, r.extract_finished_at, r.loaded_at,
       r.expected_gl_rows, r.expected_cogs_rows, r.expected_sites, r.tolerance_rupees
FROM pnl.run r WHERE r.recon_state IN ('verified', 'api_verified');

CREATE VIEW pnl.v_site AS SELECT x.* FROM pnl.site x JOIN pnl.v_serving_run s USING (run_id);
CREATE VIEW pnl.v_group_section AS SELECT x.* FROM pnl.group_section x JOIN pnl.v_serving_run s USING (run_id);
CREATE VIEW pnl.v_gl_site_month AS SELECT x.* FROM pnl.gl_site_month x JOIN pnl.v_serving_run s USING (run_id);
CREATE VIEW pnl.v_cogs_site_month AS SELECT x.* FROM pnl.cogs_site_month x JOIN pnl.v_serving_run s USING (run_id);
CREATE VIEW pnl.v_sales_tieout AS SELECT x.* FROM pnl.sales_tieout x JOIN pnl.v_serving_run s USING (run_id);
CREATE VIEW pnl.v_control AS SELECT c.* FROM pnl.control_result c JOIN pnl.v_serving_run s USING (run_id);
CREATE VIEW pnl.v_run_status AS SELECT run_id, as_of_date, recon_state, publication_state, loaded_at FROM pnl.run;
CREATE VIEW pnl.v_promotion_history AS SELECT promotion_id, action, run_id, previous_run_id, reason, at, by FROM pnl.promotion;

CREATE INDEX ON pnl.gl_site_month (run_id, section, month);
CREATE INDEX ON pnl.gl_site_month (run_id, site_code, month);
CREATE INDEX ON pnl.control_result (run_id) WHERE verdict <> 'PASS';
CREATE INDEX ON pnl.run_event (run_id, at);

-- ───────────────────────────── grants ─────────────────────────────

REVOKE ALL ON ALL TABLES IN SCHEMA pnl FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA pnl FROM PUBLIC;
GRANT USAGE ON SCHEMA pnl TO pnl_loader, pnl_verifier, pnl_promoter, pnl_api_reader;

GRANT INSERT ON pnl.run, pnl.site, pnl.group_section, pnl.gl_site_month, pnl.cogs_site_month, pnl.sales_tieout, pnl.load_rejection TO pnl_loader;
GRANT SELECT ON pnl.run, pnl.site, pnl.group_section, pnl.gl_site_month, pnl.cogs_site_month, pnl.sales_tieout, pnl.control_result TO pnl_loader;
GRANT USAGE ON SEQUENCE pnl.load_rejection_rejection_id_seq TO pnl_loader;
GRANT EXECUTE ON FUNCTION pnl.record_control(text, text, text, text, numeric, text, numeric), pnl.verify_run(text), pnl.mart_checks(text) TO pnl_loader;

GRANT SELECT ON pnl.v_serving_run, pnl.v_site, pnl.v_group_section, pnl.v_gl_site_month, pnl.v_cogs_site_month, pnl.v_sales_tieout, pnl.v_control TO pnl_verifier, pnl_api_reader;
GRANT EXECUTE ON FUNCTION pnl.record_control(text, text, text, text, numeric, text, numeric), pnl.api_verify_run(text) TO pnl_verifier;

GRANT SELECT ON pnl.v_run_status, pnl.v_promotion_history, pnl.v_control TO pnl_promoter;
GRANT EXECUTE ON FUNCTION pnl.promote_run(text, text), pnl.demote_to(text, text) TO pnl_promoter;
GRANT EXECUTE ON FUNCTION pnl.verify_run(text), pnl.mart_checks(text) TO pnl_owner;
GRANT EXECUTE ON FUNCTION pnl.caller_role(), pnl.caller_is(name), pnl.maintenance_on() TO PUBLIC;

RESET ROLE;

-- the shared run model learns about the P&L domain (a view over each domain's own run table: nothing is copied)
CREATE OR REPLACE VIEW core.v_domain_run AS
SELECT 'creditors'::text AS domain, r.extraction_run_id AS run_id, r.as_of_date, 'validated'::text AS source_state,
       CASE r.recon_state WHEN 'loaded' THEN 'loaded' ELSE 'verified' END AS mart_state,
       CASE WHEN r.recon_state IN ('api_verified', 'ui_verified') THEN 'verified' ELSE 'pending' END AS api_state,
       r.publication_state, r.recon_state AS reconciliation_status, r.extract_finished_at AS source_updated_at, r.loaded_at, (r.publication_state = 'live') AS is_live
FROM cred.run r
UNION ALL
SELECT 'cash'::text, c.run_id, c.as_of_date, 'validated'::text, CASE c.recon_state WHEN 'loaded' THEN 'loaded' ELSE 'verified' END,
       CASE WHEN c.recon_state = 'api_verified' THEN 'verified' ELSE 'pending' END, c.publication_state, c.recon_state, c.extract_finished_at, c.loaded_at, (c.publication_state = 'live')
FROM cash.run c
UNION ALL
SELECT 'entries'::text, e.entry_run_id, e.register_report_date, 'validated'::text, CASE e.recon_state WHEN 'loaded' THEN 'loaded' ELSE 'verified' END,
       CASE WHEN e.recon_state = 'api_verified' THEN 'verified' ELSE 'pending' END, e.publication_state, e.recon_state, e.extract_finished_at, e.loaded_at, (e.publication_state = 'live')
FROM entry.run e
UNION ALL
SELECT 'pnl'::text, p.run_id, p.as_of_date, 'validated'::text, CASE p.recon_state WHEN 'loaded' THEN 'loaded' ELSE 'verified' END,
       CASE WHEN p.recon_state = 'api_verified' THEN 'verified' ELSE 'pending' END, p.publication_state, p.recon_state, p.extract_finished_at, p.loaded_at, (p.publication_state = 'live')
FROM pnl.run p;

GRANT USAGE ON SCHEMA core TO pnl_verifier, pnl_promoter, pnl_api_reader;
GRANT SELECT ON core.v_domain_run TO pnl_verifier, pnl_promoter, pnl_api_reader;

INSERT INTO cred.schema_migration (version, description) VALUES
  ('008', 'pnl schema: immutable runs of the store P&L actuals (books by site, month and ledger; COGS table by site and month; sales tie-out), controlled functions, serving views, grants; core.v_domain_run learns pnl');
