-- fpa_app 008: month-end close. The reporting period moves ONLY by INSERT into reporting_period_event (transition table, role rules, reason); a definer trigger applies it to
-- reporting_period_status, which the app login can no longer write directly. Close sign-offs (manual checklist items and reviewer overrides) are an append-only table.
--   OPEN -> SOFT_CLOSED -> MANAGEMENT_CLOSED -> FINAL_CLOSED; any closed state -> REOPENED (controller or admin, with a reason); REOPENED -> SOFT_CLOSED.
--   soft close: manager or above; management close: reviewer, controller, admin (the one FP&A manager only while single_user_mode is on); final close and reopen: controller, admin.

CREATE TABLE fpa_app.period_transition (
    from_status text NOT NULL,
    to_status   text NOT NULL,
    PRIMARY KEY (from_status, to_status)
);
INSERT INTO fpa_app.period_transition VALUES
    ('OPEN', 'SOFT_CLOSED'), ('REOPENED', 'SOFT_CLOSED'), ('SOFT_CLOSED', 'MANAGEMENT_CLOSED'), ('MANAGEMENT_CLOSED', 'FINAL_CLOSED'),
    ('SOFT_CLOSED', 'REOPENED'), ('MANAGEMENT_CLOSED', 'REOPENED'), ('FINAL_CLOSED', 'REOPENED');

ALTER TABLE fpa_app.reporting_period_event ALTER COLUMN from_status DROP NOT NULL;

CREATE OR REPLACE FUNCTION fpa_app.period_event_check() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = fpa_app, pg_temp AS $$
DECLARE cur text; arole text; single boolean;
BEGIN
    INSERT INTO fpa_app.reporting_period_status (entity, period, status) VALUES (NEW.entity, NEW.period, 'OPEN') ON CONFLICT DO NOTHING;
    SELECT status INTO cur FROM fpa_app.reporting_period_status WHERE entity = NEW.entity AND period = NEW.period FOR UPDATE;
    SELECT role INTO arole FROM fpa_app.app_user WHERE user_id = NEW.actor_user_id AND active;
    SELECT coalesce((SELECT value = 'on' FROM fpa_app.app_setting WHERE key = 'single_user_mode'), false) INTO single;
    NEW.from_status := cur;
    IF NOT EXISTS (SELECT 1 FROM fpa_app.period_transition t WHERE t.from_status = cur AND t.to_status = NEW.to_status) THEN
        RAISE EXCEPTION 'the period % of % cannot go from % to %', NEW.period, NEW.entity, cur, NEW.to_status USING ERRCODE = 'check_violation';
    END IF;
    IF arole IS NULL OR arole = 'viewer' THEN
        RAISE EXCEPTION 'the actor cannot change a reporting period' USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF NEW.to_status = 'SOFT_CLOSED' AND arole NOT IN ('fpa_manager', 'finance_reviewer', 'controller', 'admin') THEN
        RAISE EXCEPTION 'only a manager or above soft-closes a period' USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF NEW.to_status = 'MANAGEMENT_CLOSED' AND NOT (arole IN ('finance_reviewer', 'controller', 'admin') OR (single AND arole = 'fpa_manager')) THEN
        RAISE EXCEPTION 'only a finance reviewer or above management-closes a period' USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF NEW.to_status IN ('FINAL_CLOSED', 'REOPENED') AND arole NOT IN ('controller', 'admin') THEN
        RAISE EXCEPTION 'only a controller or administrator makes the final close or reopens a period' USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF length(btrim(coalesce(NEW.reason, ''))) < 10 THEN
        RAISE EXCEPTION 'a period change needs a reason of at least 10 characters' USING ERRCODE = 'check_violation';
    END IF;
    UPDATE fpa_app.reporting_period_status SET status = NEW.to_status, changed_at = now(), changed_by = NEW.actor_user_id WHERE entity = NEW.entity AND period = NEW.period;
    RETURN NEW;
END $$;
CREATE TRIGGER reporting_period_event_check BEFORE INSERT ON fpa_app.reporting_period_event FOR EACH ROW EXECUTE FUNCTION fpa_app.period_event_check();
-- the event table references the status row, which the trigger creates on first use: drop the foreign key that would fire before it
ALTER TABLE fpa_app.reporting_period_event DROP CONSTRAINT reporting_period_event_entity_period_fkey;

-- the status table is now written only by the definer trigger above
REVOKE INSERT, UPDATE ON fpa_app.reporting_period_status FROM fpa_workflow_app;

CREATE TABLE fpa_app.close_signoff (
    signoff_id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    entity        text NOT NULL CHECK (entity IN ('SUBCO', 'HOLDCO')),
    period        date NOT NULL CHECK (period = date_trunc('month', period)::date),
    check_key     text NOT NULL,
    decision      text NOT NULL CHECK (decision IN ('SIGNED_OFF', 'OVERRIDDEN', 'WITHDRAWN')),
    evidence_sig  text NOT NULL,          -- fingerprint of the evidence the person saw; a changed signature makes the sign-off stale
    comment       text NOT NULL CHECK (length(btrim(comment)) >= 10),
    actor_user_id uuid NOT NULL REFERENCES fpa_app.app_user (user_id),
    at            timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX close_signoff_ix ON fpa_app.close_signoff (entity, period, check_key, signoff_id DESC);
CREATE TRIGGER close_signoff_append_only BEFORE UPDATE OR DELETE ON fpa_app.close_signoff FOR EACH ROW EXECUTE FUNCTION fpa_app.forbid_mutation();

CREATE OR REPLACE FUNCTION fpa_app.close_signoff_check() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = fpa_app, pg_temp AS $$
DECLARE arole text; single boolean;
BEGIN
    SELECT role INTO arole FROM fpa_app.app_user WHERE user_id = NEW.actor_user_id AND active;
    SELECT coalesce((SELECT value = 'on' FROM fpa_app.app_setting WHERE key = 'single_user_mode'), false) INTO single;
    IF NEW.check_key = 'pnl_certification' THEN
        IF arole NOT IN ('controller', 'admin') THEN
            RAISE EXCEPTION 'only a controller or administrator certifies the management P&L' USING ERRCODE = 'insufficient_privilege';
        END IF;
    ELSIF NOT (arole IN ('finance_reviewer', 'controller', 'admin') OR (single AND arole = 'fpa_manager')) THEN
        RAISE EXCEPTION 'only a finance reviewer or above signs off a close item' USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER close_signoff_check BEFORE INSERT ON fpa_app.close_signoff FOR EACH ROW EXECUTE FUNCTION fpa_app.close_signoff_check();
