-- Accounting-entry layer, schema `entry` (migration 005). Applied by the database administrator, objects owned by entry_owner.
-- ONE canonical structure for every drill: entries identified by (site, entry type, entry number), all lines of every extracted entry, and three
-- source bridges that land on it (creditor bill link, Cash Drawer lines, bank ledger lines). Same discipline as `cred` and `cash`: immutable run-versioned
-- snapshots, controlled state functions, no UPDATE or DELETE, reconciliation state separate from publication state.
--
-- SENSITIVE TEXT. Narration, references, cheque fields, preparer / releaser names, raw sub-ledger codes and the entry number live ONLY in
-- entry.entry_identity and entry.entry_line_text. entry_api_reader has no privilege on them, directly or through any view; only entry_finance_reader can read them.

DO $pre$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'entry_owner') THEN RAISE EXCEPTION 'run 000_roles.sql first'; END IF;
  IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'entry') THEN RAISE EXCEPTION 'schema entry already exists: migrations are not re-runnable'; END IF;
  IF to_regclass('cash.run') IS NULL OR to_regclass('cred.run') IS NULL OR to_regclass('core.v_domain_run') IS NULL THEN RAISE EXCEPTION 'apply migrations 001 to 004 first'; END IF;
  EXECUTE format('GRANT CONNECT, CREATE ON DATABASE %I TO entry_owner', current_database());
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO entry_loader, entry_verifier, entry_promoter, entry_api_reader, entry_finance_reader', current_database());
END
$pre$;

-- the owner's cross-domain control function reads the domain runs it must agree with (keys and amounts only; no vendor names)
GRANT USAGE ON SCHEMA cred, cash TO entry_owner;
GRANT SELECT ON cred.run, cred.open_item TO entry_owner;
GRANT SELECT ON cash.run, cash.bank_ledger, cash.store_till TO entry_owner;

SET ROLE entry_owner;
CREATE SCHEMA entry;
REVOKE ALL ON SCHEMA entry FROM PUBLIC;

-- ───────────────────────────── tables ─────────────────────────────

CREATE TABLE entry.run (
  entry_run_id           text PRIMARY KEY CHECK (entry_run_id ~ '^run_[0-9]{8}_[0-9]{3}$'),
  register_report_date   date NOT NULL,                      -- the site register snapshot every entry comes from
  creditors_run_id       text NOT NULL,                      -- the creditors run whose bills are linked
  cash_run_id            text NOT NULL,                      -- the cash run whose bank ledgers and till days are drilled
  till_balance_date      date NOT NULL,
  coverage_from          date NOT NULL,                      -- earliest date the all-years register covers
  package                text NOT NULL,
  contract_version       text NOT NULL,
  rules                  jsonb NOT NULL,
  manifest_sha256        char(64) NOT NULL UNIQUE CHECK (manifest_sha256 ~ '^[0-9a-f]{64}$'),
  staging_report_sha256  char(64) NOT NULL CHECK (staging_report_sha256 ~ '^[0-9a-f]{64}$'),
  extract_started_at     timestamptz NOT NULL,
  extract_finished_at    timestamptz NOT NULL,
  expected_headers       integer NOT NULL CHECK (expected_headers > 0),
  expected_lines         integer NOT NULL CHECK (expected_lines > 0),
  expected_links         integer NOT NULL CHECK (expected_links > 0),
  expected_till_days     integer NOT NULL CHECK (expected_till_days > 0),
  loaded_at              timestamptz NOT NULL DEFAULT now(),
  loaded_by              text NOT NULL DEFAULT current_user,
  recon_state            text NOT NULL DEFAULT 'loaded' CHECK (recon_state IN ('loaded', 'verified', 'api_verified')),
  publication_state      text NOT NULL DEFAULT 'unpublished' CHECK (publication_state IN ('unpublished', 'live', 'superseded', 'withdrawn')),
  CHECK (extract_finished_at >= extract_started_at),
  CHECK (till_balance_date <= register_report_date)
);

-- masked-safe header: no entry number
CREATE TABLE entry.entry_header (
  entry_run_id     text NOT NULL REFERENCES entry.run,
  entry_ref        char(32) NOT NULL CHECK (entry_ref ~ '^[0-9a-f]{32}$'),   -- sha256('v1|site|type|number') prefix: opaque, stable
  site_code        text NOT NULL,
  entry_type_short text NOT NULL,
  entry_type_long  text,
  entry_date       date NOT NULL,
  release_status   text NOT NULL CHECK (release_status IN ('Posted', 'Unposted', 'Mixed')),
  line_count       integer NOT NULL CHECK (line_count > 0),
  total_dr         numeric(30,4) NOT NULL,
  total_cr         numeric(30,4) NOT NULL,
  selections       text[] NOT NULL,                          -- which drills reach this entry: creditors, bank, till
  PRIMARY KEY (entry_run_id, entry_ref)
);

-- masked-safe lines: ledger names and amounts, a pseudonymous sub-ledger reference, never the raw sub-ledger code
CREATE TABLE entry.entry_line (
  entry_run_id    text NOT NULL,
  entry_ref       char(32) NOT NULL,
  line_no         integer NOT NULL CHECK (line_no > 0),
  source_seq      text NOT NULL,
  ledger_code     text NOT NULL,
  ledger_name     text NOT NULL,
  ledger_nature   text,
  sub_ledger_ref  text,
  debit           numeric(30,4) NOT NULL CHECK (debit >= 0),
  credit          numeric(30,4) NOT NULL CHECK (credit >= 0),
  release_status  text NOT NULL CHECK (release_status IN ('Posted', 'Unposted')),
  cube_name       text,
  PRIMARY KEY (entry_run_id, entry_ref, line_no),
  FOREIGN KEY (entry_run_id, entry_ref) REFERENCES entry.entry_header
);

-- RESTRICTED (Finance only): the entry number and the free-text / source-identifying fields
CREATE TABLE entry.entry_identity (
  entry_run_id     text NOT NULL,
  entry_ref        char(32) NOT NULL,
  site_code        text NOT NULL,
  entry_type_short text NOT NULL,
  entry_no         text NOT NULL,
  created_by_site  text,
  PRIMARY KEY (entry_run_id, entry_ref),
  UNIQUE (entry_run_id, site_code, entry_type_short, entry_no),
  FOREIGN KEY (entry_run_id, entry_ref) REFERENCES entry.entry_header
);

CREATE TABLE entry.entry_line_text (
  entry_run_id   text NOT NULL,
  entry_ref      char(32) NOT NULL,
  line_no        integer NOT NULL,
  sub_ledger_code text,
  narration      text,
  reference_no   text,
  reference_date text,
  cheque_no      text,
  cheque_date    text,
  counter_ledgers text,
  prepared_by    text,
  prepared_on    text,
  modified_by    text,
  modified_on    text,
  released_by    text,
  released_on    text,
  PRIMARY KEY (entry_run_id, entry_ref, line_no),
  FOREIGN KEY (entry_run_id, entry_ref, line_no) REFERENCES entry.entry_line
);

-- bridge 1: creditor bill -> entry. Materialised, never resolved at request time. An ambiguous or unlinked bill never carries an entry.
CREATE TABLE entry.creditor_bill_link (
  entry_run_id      text NOT NULL REFERENCES entry.run,
  creditors_run_id  text NOT NULL,
  source_row_key    char(64) NOT NULL CHECK (source_row_key ~ '^[0-9a-f]{64}$'),
  ledger_code       text NOT NULL,
  bill_amount       numeric(30,4) NOT NULL,
  link_status       text NOT NULL CHECK (link_status IN ('EXACT', 'STRONG', 'AMBIGUOUS', 'NOT_LINKED')),
  not_linked_reason text CHECK (not_linked_reason IN ('NO_MATCH', 'REGISTER_COVERAGE_UNAVAILABLE')),
  key_used          text NOT NULL,
  matched_entries   integer NOT NULL CHECK (matched_entries >= 0),
  entry_ref         char(32),
  entry_net_amount  numeric(30,4),
  amount_agrees     boolean,
  coverage          text NOT NULL CHECK (coverage IN ('CURRENT_FY', 'PRIOR_YEARS_IN_COVERAGE', 'BEFORE_COVERAGE')),
  PRIMARY KEY (entry_run_id, source_row_key),
  FOREIGN KEY (entry_run_id, entry_ref) REFERENCES entry.entry_header,
  CHECK ((link_status IN ('EXACT', 'STRONG')) = (entry_ref IS NOT NULL)),
  CHECK ((link_status = 'EXACT') = (matched_entries = 1 AND amount_agrees IS TRUE)),
  CHECK ((link_status = 'STRONG') = (matched_entries = 1 AND amount_agrees IS NOT TRUE)),
  CHECK ((link_status = 'AMBIGUOUS') = (matched_entries > 1)),
  CHECK ((link_status = 'NOT_LINKED') = (matched_entries = 0)),
  CHECK ((link_status = 'NOT_LINKED') = (not_linked_reason IS NOT NULL)),
  CHECK (not_linked_reason IS DISTINCT FROM 'REGISTER_COVERAGE_UNAVAILABLE' OR coverage = 'BEFORE_COVERAGE')
);

-- bridge 2 (right-hand side of the till's cumulative-day control): the till view per store per day
CREATE TABLE entry.till_day (
  entry_run_id       text NOT NULL REFERENCES entry.run,
  cash_run_id        text NOT NULL,
  site_code          text NOT NULL,
  day                date NOT NULL,
  debit              numeric(30,4) NOT NULL,
  credit             numeric(30,4) NOT NULL,
  cumulative_balance numeric(30,4) NOT NULL,
  PRIMARY KEY (entry_run_id, site_code, day)
);

CREATE TABLE entry.control_result (
  entry_run_id text NOT NULL REFERENCES entry.run,
  control_id   text NOT NULL,
  dimension    text NOT NULL,
  left_layer   text NOT NULL,
  left_value   numeric(30,4) NOT NULL,
  right_layer  text NOT NULL,
  right_value  numeric(30,4) NOT NULL,
  variance     numeric(30,4) GENERATED ALWAYS AS (right_value - left_value) STORED,
  verdict      text GENERATED ALWAYS AS (CASE WHEN right_value = left_value THEN 'PASS' ELSE 'FAIL' END) STORED,
  recorded_at  timestamptz NOT NULL DEFAULT now(),
  recorded_by  text NOT NULL DEFAULT current_user,
  PRIMARY KEY (entry_run_id, control_id, dimension, left_layer, right_layer),
  CHECK ((left_layer, right_layer) IN (('source', 'extract'), ('extract', 'mart'), ('mart', 'api')))
);

CREATE TABLE entry.run_event (
  event_id bigserial PRIMARY KEY,
  entry_run_id text NOT NULL REFERENCES entry.run,
  event text NOT NULL CHECK (event IN ('loaded', 'verified', 'verify_failed', 'api_verified', 'api_verify_failed', 'promoted', 'superseded', 'withdrawn', 'reinstated')),
  detail jsonb,                                              -- counts and control ids only: never row values, never text
  at timestamptz NOT NULL DEFAULT now(),
  by text NOT NULL DEFAULT current_user
);

CREATE TABLE entry.load_rejection (
  rejection_id bigserial PRIMARY KEY,
  entry_run_id text NOT NULL,
  manifest_sha256 char(64),
  stage text NOT NULL CHECK (stage IN ('precheck', 'staging_report', 'load', 'mart_controls', 'promotion')),
  reason text NOT NULL,
  failed_controls jsonb,
  attempted_at timestamptz NOT NULL DEFAULT now(),
  attempted_by text NOT NULL DEFAULT current_user
);

CREATE TABLE entry.live_run (singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton), entry_run_id text NOT NULL REFERENCES entry.run, since timestamptz NOT NULL DEFAULT now());
CREATE TABLE entry.promotion (
  promotion_id bigserial PRIMARY KEY, action text NOT NULL CHECK (action IN ('promote', 'demote')), entry_run_id text NOT NULL REFERENCES entry.run,
  previous_run_id text REFERENCES entry.run, reason text NOT NULL CHECK (length(reason) > 0), at timestamptz NOT NULL DEFAULT now(), by text NOT NULL DEFAULT current_user
);

-- ───────────────────────────── helpers and guards ─────────────────────────────

CREATE FUNCTION entry.caller_role() RETURNS name LANGUAGE sql STABLE AS $$ SELECT CASE WHEN current_setting('role') <> 'none' THEN current_setting('role')::name ELSE session_user END $$;
CREATE FUNCTION entry.caller_is(p_role name) RETURNS boolean LANGUAGE sql STABLE AS $$ SELECT pg_has_role(entry.caller_role(), p_role, 'MEMBER') $$;
CREATE FUNCTION entry.maintenance_on() RETURNS boolean LANGUAGE sql STABLE AS $$ SELECT coalesce(current_setting('entry.maintenance', true), 'off') = 'on' $$;

CREATE FUNCTION entry.deny_mutation() RETURNS trigger LANGUAGE plpgsql AS
$$ BEGIN RAISE EXCEPTION '% on entry.% is not allowed: runs are immutable (use the controlled functions)', TG_OP, TG_TABLE_NAME USING ERRCODE = 'insufficient_privilege'; END $$;
DO $t$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['entry_header', 'entry_line', 'entry_identity', 'entry_line_text', 'creditor_bill_link', 'till_day', 'control_result', 'run_event', 'load_rejection', 'promotion'] LOOP
    EXECUTE format('CREATE TRIGGER no_mutation BEFORE UPDATE OR DELETE ON entry.%I FOR EACH ROW EXECUTE FUNCTION entry.deny_mutation()', t);
  END LOOP;
END
$t$;
CREATE TRIGGER no_delete BEFORE DELETE ON entry.run FOR EACH ROW EXECUTE FUNCTION entry.deny_mutation();

CREATE FUNCTION entry.guard_run_insert() RETURNS trigger LANGUAGE plpgsql AS
$$ BEGIN IF NEW.recon_state <> 'loaded' OR NEW.publication_state <> 'unpublished' THEN RAISE EXCEPTION 'a run must start as loaded / unpublished' USING ERRCODE = 'check_violation'; END IF; RETURN NEW; END $$;
CREATE TRIGGER run_insert BEFORE INSERT ON entry.run FOR EACH ROW EXECUTE FUNCTION entry.guard_run_insert();
CREATE FUNCTION entry.guard_run_update() RETURNS trigger LANGUAGE plpgsql AS
$$ BEGIN
  IF NOT entry.maintenance_on() THEN RAISE EXCEPTION 'entry.run can only change through the controlled functions' USING ERRCODE = 'insufficient_privilege'; END IF;
  IF (to_jsonb(NEW) - 'recon_state' - 'publication_state') IS DISTINCT FROM (to_jsonb(OLD) - 'recon_state' - 'publication_state') THEN RAISE EXCEPTION 'only the state columns of a run may change' USING ERRCODE = 'check_violation'; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER run_update BEFORE UPDATE ON entry.run FOR EACH ROW EXECUTE FUNCTION entry.guard_run_update();

CREATE FUNCTION entry.guard_open_run() RETURNS trigger LANGUAGE plpgsql AS
$$ DECLARE st text; pub text;
BEGIN
  SELECT recon_state, publication_state INTO st, pub FROM entry.run WHERE entry_run_id = NEW.entry_run_id;
  IF NOT FOUND THEN RAISE EXCEPTION 'run % does not exist', NEW.entry_run_id USING ERRCODE = 'foreign_key_violation'; END IF;
  IF st <> 'loaded' OR pub <> 'unpublished' THEN RAISE EXCEPTION 'run % is closed (% / %): no rows can be added', NEW.entry_run_id, st, pub USING ERRCODE = 'insufficient_privilege'; END IF;
  RETURN NEW;
END $$;
DO $t$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['entry_header', 'entry_line', 'entry_identity', 'entry_line_text', 'creditor_bill_link', 'till_day'] LOOP
    EXECUTE format('CREATE TRIGGER run_open BEFORE INSERT ON entry.%I FOR EACH ROW EXECUTE FUNCTION entry.guard_open_run()', t);
  END LOOP;
END
$t$;

-- ───────────────────────────── structural checks (zero violations expected) ─────────────────────────────
-- Every row of the output is a COUNT: no row value, no text can leave through a check.

CREATE FUNCTION entry.mart_checks(p_run text) RETURNS TABLE (check_id text, violations bigint) LANGUAGE sql STABLE SECURITY DEFINER SET search_path = entry, pg_temp AS
$$
  SELECT 'M01_header_rows', abs((SELECT count(*) FROM entry.entry_header WHERE entry_run_id = p_run) - (SELECT expected_headers FROM entry.run WHERE entry_run_id = p_run))::bigint
  UNION ALL SELECT 'M02_line_rows', abs((SELECT count(*) FROM entry.entry_line WHERE entry_run_id = p_run) - (SELECT expected_lines FROM entry.run WHERE entry_run_id = p_run))::bigint
  UNION ALL SELECT 'M03_link_rows', abs((SELECT count(*) FROM entry.creditor_bill_link WHERE entry_run_id = p_run) - (SELECT expected_links FROM entry.run WHERE entry_run_id = p_run))::bigint
  UNION ALL SELECT 'M04_till_day_rows', abs((SELECT count(*) FROM entry.till_day WHERE entry_run_id = p_run) - (SELECT expected_till_days FROM entry.run WHERE entry_run_id = p_run))::bigint
  -- E2: a voucher is stored complete: the header's line count equals the lines present
  UNION ALL SELECT 'M05_E2_line_count_matches_header', count(*) FROM entry.entry_header h WHERE h.entry_run_id = p_run
       AND h.line_count <> (SELECT count(*) FROM entry.entry_line l WHERE l.entry_run_id = h.entry_run_id AND l.entry_ref = h.entry_ref)
  UNION ALL SELECT 'M06_header_totals_match_lines', count(*) FROM entry.entry_header h
       LEFT JOIN (SELECT entry_ref, sum(debit) AS dr, sum(credit) AS cr FROM entry.entry_line WHERE entry_run_id = p_run GROUP BY entry_ref) l ON l.entry_ref = h.entry_ref
       WHERE h.entry_run_id = p_run AND (h.total_dr <> coalesce(l.dr, 0) OR h.total_cr <> coalesce(l.cr, 0))
  -- E3: every extracted entry balances
  UNION ALL SELECT 'M07_E3_entry_balances', count(*) FROM entry.entry_header WHERE entry_run_id = p_run AND total_dr <> total_cr
  -- E4: an EXACT link resolves to exactly one canonical identity that exists in the layer
  UNION ALL SELECT 'M08_E4_exact_resolves_to_one_entry', count(*) FROM entry.creditor_bill_link k WHERE k.entry_run_id = p_run AND k.link_status = 'EXACT'
       AND (k.matched_entries <> 1 OR NOT EXISTS (SELECT 1 FROM entry.entry_identity i WHERE i.entry_run_id = k.entry_run_id AND i.entry_ref = k.entry_ref))
  -- E5: nothing ambiguous or unlinked carries an entry
  UNION ALL SELECT 'M09_E5_no_auto_selection', count(*) FROM entry.creditor_bill_link WHERE entry_run_id = p_run AND link_status IN ('AMBIGUOUS', 'NOT_LINKED') AND entry_ref IS NOT NULL
  UNION ALL SELECT 'M10_identity_complete_and_unique', (SELECT count(*) FROM entry.entry_header h WHERE h.entry_run_id = p_run AND NOT EXISTS (SELECT 1 FROM entry.entry_identity i WHERE i.entry_run_id = h.entry_run_id AND i.entry_ref = h.entry_ref))
       + (SELECT count(*) FROM entry.entry_identity i WHERE i.entry_run_id = p_run AND NOT EXISTS (SELECT 1 FROM entry.entry_header h WHERE h.entry_run_id = i.entry_run_id AND h.entry_ref = i.entry_ref))
  UNION ALL SELECT 'M11_text_rows_match_lines', abs((SELECT count(*) FROM entry.entry_line_text WHERE entry_run_id = p_run) - (SELECT count(*) FROM entry.entry_line WHERE entry_run_id = p_run))::bigint
  -- E9: an EXACT link's entry nets (for that ledger and sub-ledger) to the bill amount
  UNION ALL SELECT 'M12_E9_exact_is_amount_corroborated', count(*) FROM entry.creditor_bill_link WHERE entry_run_id = p_run AND link_status = 'EXACT' AND (amount_agrees IS NOT TRUE OR abs(entry_net_amount) <> abs(bill_amount))
  -- E8: the cumulative-day reconciliation. For every store and day: the day's Dr and Cr equal the Cash Drawer lines of that day, and the till view's cumulative balance
  -- equals the running total of ALL Cash Drawer lines up to that day (the Opening line included)
  UNION ALL SELECT 'M13_E8_till_cumulative_and_day_totals', count(*) FROM (
       SELECT d.site_code, d.day, d.debit, d.credit, d.cumulative_balance, sum(d.debit - d.credit) OVER (PARTITION BY d.site_code ORDER BY d.day) AS running_balance,
              coalesce(l.dr, 0) AS line_dr, coalesce(l.cr, 0) AS line_cr
         FROM entry.till_day d
         LEFT JOIN (SELECT h.site_code, h.entry_date AS day, sum(e.debit) AS dr, sum(e.credit) AS cr FROM entry.entry_line e JOIN entry.entry_header h USING (entry_run_id, entry_ref)
                     WHERE e.entry_run_id = p_run AND e.ledger_name = 'Cash Drawer' GROUP BY h.site_code, h.entry_date) l ON l.site_code = d.site_code AND l.day = d.day
        WHERE d.entry_run_id = p_run) q
       WHERE q.cumulative_balance <> q.running_balance OR q.debit <> q.line_dr OR q.credit <> q.line_cr
  -- every Cash Drawer line belongs to a store/day that the till view lists
  UNION ALL SELECT 'M14_drawer_lines_without_a_till_day', count(*) FROM (
       SELECT DISTINCT h.site_code, h.entry_date FROM entry.entry_line e JOIN entry.entry_header h USING (entry_run_id, entry_ref)
        WHERE e.entry_run_id = p_run AND e.ledger_name = 'Cash Drawer' AND (e.debit <> 0 OR e.credit <> 0)) x
       WHERE NOT EXISTS (SELECT 1 FROM entry.till_day d WHERE d.entry_run_id = p_run AND d.site_code = x.site_code AND d.day = x.entry_date)
$$;

-- the same entry layer measured against the two domain runs it serves (counts only)
CREATE FUNCTION entry.cross_checks(p_run text) RETURNS TABLE (check_id text, violations bigint) LANGUAGE sql STABLE SECURITY DEFINER SET search_path = entry, pg_temp AS
$$
  WITH r AS (SELECT * FROM entry.run WHERE entry_run_id = p_run)
  -- E11: one snapshot: the register date, the cash run's date and the creditors run's date agree
  SELECT 'X01_E11_as_of_lineage', (SELECT count(*) FROM r WHERE register_report_date IS DISTINCT FROM (SELECT as_of_date FROM cash.run c WHERE c.run_id = r.cash_run_id)
                                                             OR register_report_date IS DISTINCT FROM (SELECT as_of_date FROM cred.run c WHERE c.extraction_run_id = r.creditors_run_id)
                                                             OR till_balance_date IS DISTINCT FROM (SELECT till_balance_date FROM cash.run c WHERE c.run_id = r.cash_run_id))::bigint
  -- E6: every bill of the creditors run has exactly one link row, and no link row names a bill that is not in that run
  UNION ALL SELECT 'X02_E6_every_bill_has_a_link',
       (SELECT count(*) FROM cred.open_item o, r WHERE o.extraction_run_id = r.creditors_run_id AND NOT EXISTS (SELECT 1 FROM entry.creditor_bill_link k WHERE k.entry_run_id = p_run AND k.source_row_key = o.source_row_key))
     + (SELECT count(*) FROM entry.creditor_bill_link k, r WHERE k.entry_run_id = p_run AND NOT EXISTS (SELECT 1 FROM cred.open_item o WHERE o.extraction_run_id = r.creditors_run_id AND o.source_row_key = k.source_row_key))
  UNION ALL SELECT 'X03_link_amounts_equal_bill_amounts', count(*) FROM entry.creditor_bill_link k, r WHERE k.entry_run_id = p_run
       AND abs(k.bill_amount) <> (SELECT abs(o.amount) FROM cred.open_item o WHERE o.extraction_run_id = r.creditors_run_id AND o.source_row_key = k.source_row_key)
  -- E7: bank ledger lines sum back to the cash run's review figures, per ledger, exactly (posted and unposted, opening separate, future-dated excluded)
  UNION ALL SELECT 'X04_E7_bank_lines_equal_the_review_card', count(*) FROM (
       SELECT b.ledger_code,
              coalesce(sum(CASE WHEN trim(h.entry_type_long) = 'Opening' THEN e.debit END), 0) AS open_dr, coalesce(sum(CASE WHEN trim(h.entry_type_long) = 'Opening' THEN e.credit END), 0) AS open_cr,
              coalesce(sum(CASE WHEN trim(h.entry_type_long) <> 'Opening' AND e.release_status = 'Posted' AND h.entry_date <= r.register_report_date THEN e.debit END), 0) AS posted_dr,
              coalesce(sum(CASE WHEN trim(h.entry_type_long) <> 'Opening' AND e.release_status = 'Posted' AND h.entry_date <= r.register_report_date THEN e.credit END), 0) AS posted_cr,
              coalesce(sum(CASE WHEN trim(h.entry_type_long) <> 'Opening' AND e.release_status = 'Unposted' AND h.entry_date <= r.register_report_date THEN e.debit END), 0) AS unposted_dr,
              coalesce(sum(CASE WHEN trim(h.entry_type_long) <> 'Opening' AND e.release_status = 'Unposted' AND h.entry_date <= r.register_report_date THEN e.credit END), 0) AS unposted_cr,
              b.opening_dr AS c_open_dr, b.opening_cr AS c_open_cr, b.posted_dr AS c_posted_dr, b.posted_cr AS c_posted_cr, b.unposted_dr AS c_unposted_dr, b.unposted_cr AS c_unposted_cr
         FROM r JOIN cash.bank_ledger b ON b.run_id = r.cash_run_id AND b.source = 'site_register' AND b.has_movement
         LEFT JOIN entry.entry_line e ON e.entry_run_id = r.entry_run_id AND e.ledger_code = b.ledger_code
         LEFT JOIN entry.entry_header h ON h.entry_run_id = e.entry_run_id AND h.entry_ref = e.entry_ref
        GROUP BY b.ledger_code, b.opening_dr, b.opening_cr, b.posted_dr, b.posted_cr, b.unposted_dr, b.unposted_cr, r.register_report_date) q
       WHERE (q.open_dr, q.open_cr, q.posted_dr, q.posted_cr, q.unposted_dr, q.unposted_cr) IS DISTINCT FROM (q.c_open_dr, q.c_open_cr, q.c_posted_dr, q.c_posted_cr, q.c_unposted_dr, q.c_unposted_cr)
  -- E8: the till view's cumulative balance on the till date equals the cash run's Store Till Cash, store by store (and the store sets agree)
  UNION ALL SELECT 'X05_E8_till_equals_the_cash_card', (SELECT count(*) FROM r, cash.store_till s WHERE s.run_id = r.cash_run_id
          AND coalesce((SELECT d.cumulative_balance FROM entry.till_day d WHERE d.entry_run_id = r.entry_run_id AND d.site_code = s.site_code AND d.day = r.till_balance_date), 'NaN'::numeric) <> s.cumulative_balance)
       + (SELECT count(DISTINCT d.site_code) FROM entry.till_day d, r WHERE d.entry_run_id = r.entry_run_id AND NOT EXISTS (SELECT 1 FROM cash.store_till s WHERE s.run_id = r.cash_run_id AND s.site_code = d.site_code))
$$;

-- ───────────────────────────── controlled functions ─────────────────────────────

CREATE FUNCTION entry.record_control(p_run text, p_id text, p_dim text, p_left_layer text, p_left numeric, p_right_layer text, p_right numeric) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = entry, pg_temp AS
$$
DECLARE st text;
BEGIN
  SELECT recon_state INTO st FROM entry.run WHERE entry_run_id = p_run;
  IF NOT FOUND THEN RAISE EXCEPTION 'run % does not exist', p_run; END IF;
  IF (p_left_layer, p_right_layer) IN (('source', 'extract'), ('extract', 'mart')) THEN
    IF NOT entry.caller_is('entry_loader') THEN RAISE EXCEPTION 'only the loader records source/extract/mart controls' USING ERRCODE = 'insufficient_privilege'; END IF;
    IF st <> 'loaded' THEN RAISE EXCEPTION 'run % is % : its load controls are closed', p_run, st; END IF;
  ELSIF (p_left_layer, p_right_layer) = ('mart', 'api') THEN
    IF NOT entry.caller_is('entry_verifier') THEN RAISE EXCEPTION 'only the verifier records API-layer controls' USING ERRCODE = 'insufficient_privilege'; END IF;
    IF st <> 'verified' THEN RAISE EXCEPTION 'run % must be verified before API controls (it is %)', p_run, st; END IF;
  ELSE RAISE EXCEPTION 'unsupported layer pair % -> %', p_left_layer, p_right_layer; END IF;
  INSERT INTO entry.control_result (entry_run_id, control_id, dimension, left_layer, left_value, right_layer, right_value) VALUES (p_run, p_id, p_dim, p_left_layer, p_left, p_right_layer, p_right);
END
$$;

CREATE FUNCTION entry.verify_run(p_run text) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = entry, pg_temp AS
$$
DECLARE st text; n_fail int; n_se int; n_em int; bad jsonb; xbad jsonb;
BEGIN
  IF NOT (entry.caller_is('entry_loader') OR entry.caller_is('entry_owner')) THEN RAISE EXCEPTION 'not allowed' USING ERRCODE = 'insufficient_privilege'; END IF;
  SELECT recon_state INTO st FROM entry.run WHERE entry_run_id = p_run FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'run % does not exist', p_run; END IF;
  IF st <> 'loaded' THEN RAISE EXCEPTION 'run % is already %', p_run, st; END IF;
  SELECT count(*) FILTER (WHERE verdict <> 'PASS'), count(*) FILTER (WHERE left_layer = 'source'), count(*) FILTER (WHERE left_layer = 'extract') INTO n_fail, n_se, n_em FROM entry.control_result WHERE entry_run_id = p_run;
  SELECT coalesce(jsonb_object_agg(check_id, violations) FILTER (WHERE violations <> 0), '{}'::jsonb) INTO bad FROM entry.mart_checks(p_run);
  SELECT coalesce(jsonb_object_agg(check_id, violations) FILTER (WHERE violations <> 0), '{}'::jsonb) INTO xbad FROM entry.cross_checks(p_run);
  PERFORM set_config('entry.maintenance', 'on', true);
  IF n_fail = 0 AND n_se > 0 AND n_em > 0 AND bad = '{}'::jsonb AND xbad = '{}'::jsonb THEN
    UPDATE entry.run SET recon_state = 'verified' WHERE entry_run_id = p_run;
    INSERT INTO entry.run_event (entry_run_id, event, detail) VALUES (p_run, 'verified', jsonb_build_object('source_extract_controls', n_se, 'extract_mart_controls', n_em));
    PERFORM set_config('entry.maintenance', 'off', true);
    RETURN jsonb_build_object('ok', true, 'recon_state', 'verified');
  END IF;
  INSERT INTO entry.run_event (entry_run_id, event, detail) VALUES (p_run, 'verify_failed', jsonb_build_object('failed_controls', n_fail, 'structural', bad, 'cross', xbad));
  PERFORM set_config('entry.maintenance', 'off', true);
  RETURN jsonb_build_object('ok', false, 'failed_controls', n_fail, 'structural', bad, 'cross', xbad);
END
$$;

CREATE FUNCTION entry.api_verify_run(p_run text) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = entry, pg_temp AS
$$
DECLARE st text; n_fail int; n int;
BEGIN
  IF NOT entry.caller_is('entry_verifier') THEN RAISE EXCEPTION 'only the verifier verifies layers' USING ERRCODE = 'insufficient_privilege'; END IF;
  SELECT recon_state INTO st FROM entry.run WHERE entry_run_id = p_run FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'run % does not exist', p_run; END IF;
  IF st <> 'verified' THEN RAISE EXCEPTION 'run % is %, expected verified', p_run, st; END IF;
  SELECT count(*), count(*) FILTER (WHERE verdict <> 'PASS') INTO n, n_fail FROM entry.control_result WHERE entry_run_id = p_run AND left_layer = 'mart' AND right_layer = 'api';
  PERFORM set_config('entry.maintenance', 'on', true);
  IF n > 0 AND n_fail = 0 THEN
    UPDATE entry.run SET recon_state = 'api_verified' WHERE entry_run_id = p_run;
    INSERT INTO entry.run_event (entry_run_id, event, detail) VALUES (p_run, 'api_verified', jsonb_build_object('controls', n));
    PERFORM set_config('entry.maintenance', 'off', true);
    RETURN jsonb_build_object('ok', true, 'recon_state', 'api_verified');
  END IF;
  INSERT INTO entry.run_event (entry_run_id, event, detail) VALUES (p_run, 'api_verify_failed', jsonb_build_object('controls', n, 'failed', n_fail));
  PERFORM set_config('entry.maintenance', 'off', true);
  RETURN jsonb_build_object('ok', false, 'controls', n, 'failed', n_fail);
END
$$;

CREATE FUNCTION entry.promote_run(p_run text, p_reason text) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = entry, pg_temp AS
$$
DECLARE r entry.run%ROWTYPE; prev text; fails int;
BEGIN
  IF NOT entry.caller_is('entry_promoter') THEN RAISE EXCEPTION 'only the promoter publishes runs' USING ERRCODE = 'insufficient_privilege'; END IF;
  SELECT * INTO r FROM entry.run WHERE entry_run_id = p_run FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'run % does not exist', p_run; END IF;
  IF r.publication_state <> 'unpublished' THEN RAISE EXCEPTION 'run % is % and cannot be promoted here', p_run, r.publication_state; END IF;
  IF r.recon_state <> 'api_verified' THEN RAISE EXCEPTION 'run % is % but promotion requires api_verified', p_run, r.recon_state; END IF;
  SELECT count(*) INTO fails FROM entry.control_result WHERE entry_run_id = p_run AND verdict <> 'PASS';
  IF fails > 0 THEN RAISE EXCEPTION 'run %: % control(s) failed', p_run, fails; END IF;
  SELECT entry_run_id INTO prev FROM entry.live_run;
  PERFORM set_config('entry.maintenance', 'on', true);
  INSERT INTO entry.live_run (entry_run_id) VALUES (p_run) ON CONFLICT (singleton) DO UPDATE SET entry_run_id = EXCLUDED.entry_run_id, since = now();
  IF prev IS NOT NULL THEN UPDATE entry.run SET publication_state = 'superseded' WHERE entry_run_id = prev; INSERT INTO entry.run_event (entry_run_id, event, detail) VALUES (prev, 'superseded', jsonb_build_object('by', p_run)); END IF;
  UPDATE entry.run SET publication_state = 'live' WHERE entry_run_id = p_run;
  INSERT INTO entry.run_event (entry_run_id, event, detail) VALUES (p_run, 'promoted', jsonb_build_object('previous', prev, 'reason', p_reason));
  INSERT INTO entry.promotion (action, entry_run_id, previous_run_id, reason) VALUES ('promote', p_run, prev, p_reason);
  PERFORM set_config('entry.maintenance', 'off', true);
END
$$;

-- ───────────────────────────── views ─────────────────────────────

CREATE VIEW entry.v_serving_run AS
SELECT entry_run_id, register_report_date, creditors_run_id, cash_run_id, till_balance_date, coverage_from, recon_state, publication_state, contract_version, extract_finished_at, loaded_at
FROM entry.run WHERE recon_state IN ('verified', 'api_verified');

-- MASKED views (entry_api_reader and entry_finance_reader): no entry number, no text, no raw sub-ledger code
CREATE VIEW entry.v_entry_header AS SELECT h.* FROM entry.entry_header h JOIN entry.v_serving_run s USING (entry_run_id);
CREATE VIEW entry.v_entry_line AS SELECT l.* FROM entry.entry_line l JOIN entry.v_serving_run s USING (entry_run_id);
CREATE VIEW entry.v_creditor_bill_link AS SELECT k.* FROM entry.creditor_bill_link k JOIN entry.v_serving_run s USING (entry_run_id);
CREATE VIEW entry.v_till_day AS SELECT d.* FROM entry.till_day d JOIN entry.v_serving_run s USING (entry_run_id);
CREATE VIEW entry.v_control AS SELECT c.* FROM entry.control_result c JOIN entry.v_serving_run s USING (entry_run_id);
-- the two drill sources are views over the one line table: no second copy of any line
CREATE VIEW entry.v_cash_drawer_entry AS
SELECT l.entry_run_id, h.site_code, h.entry_date AS day, l.entry_ref, h.entry_type_short, h.entry_type_long, l.line_no, l.debit, l.credit, l.release_status
FROM entry.v_entry_line l JOIN entry.v_entry_header h USING (entry_run_id, entry_ref) WHERE l.ledger_name = 'Cash Drawer';
CREATE VIEW entry.v_bank_entry AS
SELECT l.entry_run_id, l.ledger_code, l.ledger_name, h.entry_date, l.entry_ref, h.entry_type_short, h.entry_type_long, l.line_no, l.debit, l.credit, l.release_status
FROM entry.v_entry_line l JOIN entry.v_entry_header h USING (entry_run_id, entry_ref) WHERE l.ledger_nature IN ('Bank', 'Cash');
-- FINANCE-ONLY views
CREATE VIEW entry.v_entry_identity AS SELECT i.* FROM entry.entry_identity i JOIN entry.v_serving_run s USING (entry_run_id);
CREATE VIEW entry.v_entry_line_text AS SELECT t.* FROM entry.entry_line_text t JOIN entry.v_serving_run s USING (entry_run_id);
CREATE VIEW entry.v_run_status AS SELECT entry_run_id, register_report_date, recon_state, publication_state, loaded_at FROM entry.run;
CREATE VIEW entry.v_promotion_history AS SELECT promotion_id, action, entry_run_id, previous_run_id, reason, at, by FROM entry.promotion;

CREATE INDEX ON entry.entry_header (entry_run_id, site_code, entry_date);
CREATE INDEX ON entry.entry_line (entry_run_id, ledger_code);
CREATE INDEX ON entry.entry_line (entry_run_id, ledger_name);
CREATE INDEX ON entry.creditor_bill_link (entry_run_id, link_status);
CREATE INDEX ON entry.control_result (entry_run_id) WHERE verdict <> 'PASS';

-- ───────────────────────────── grants ─────────────────────────────

REVOKE ALL ON ALL TABLES IN SCHEMA entry FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA entry FROM PUBLIC;
GRANT USAGE ON SCHEMA entry TO entry_loader, entry_verifier, entry_promoter, entry_api_reader, entry_finance_reader;

GRANT INSERT ON entry.run, entry.entry_header, entry.entry_line, entry.entry_identity, entry.entry_line_text, entry.creditor_bill_link, entry.till_day, entry.load_rejection TO entry_loader;
GRANT SELECT ON entry.run, entry.control_result TO entry_loader;
GRANT USAGE ON SEQUENCE entry.load_rejection_rejection_id_seq TO entry_loader;
GRANT EXECUTE ON FUNCTION entry.record_control(text, text, text, text, numeric, text, numeric), entry.verify_run(text), entry.mart_checks(text), entry.cross_checks(text) TO entry_loader;

GRANT SELECT ON entry.v_serving_run, entry.v_entry_header, entry.v_entry_line, entry.v_creditor_bill_link, entry.v_till_day, entry.v_control, entry.v_cash_drawer_entry, entry.v_bank_entry TO entry_verifier, entry_api_reader, entry_finance_reader;
GRANT SELECT ON entry.v_entry_identity, entry.v_entry_line_text TO entry_finance_reader;
GRANT EXECUTE ON FUNCTION entry.record_control(text, text, text, text, numeric, text, numeric), entry.api_verify_run(text) TO entry_verifier;

GRANT SELECT ON entry.v_run_status, entry.v_promotion_history, entry.v_control TO entry_promoter;
GRANT EXECUTE ON FUNCTION entry.promote_run(text, text) TO entry_promoter;
GRANT EXECUTE ON FUNCTION entry.verify_run(text), entry.mart_checks(text), entry.cross_checks(text) TO entry_owner;
GRANT EXECUTE ON FUNCTION entry.caller_role(), entry.caller_is(name), entry.maintenance_on() TO PUBLIC;

RESET ROLE;

-- the shared run model learns about the entry layer
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
FROM entry.run e;

GRANT USAGE ON SCHEMA core TO entry_verifier, entry_promoter, entry_api_reader, entry_finance_reader;
GRANT SELECT ON core.v_domain_run TO entry_verifier, entry_promoter, entry_api_reader, entry_finance_reader;

INSERT INTO cred.schema_migration (version, description) VALUES
  ('005', 'entry schema: canonical accounting-entry layer (headers, all lines, restricted text), creditor bill links, till days, controlled functions, masked and finance views; core.v_domain_run learns entries');
