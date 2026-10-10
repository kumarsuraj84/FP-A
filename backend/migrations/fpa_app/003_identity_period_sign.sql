-- fpa_app 003: changes agreed with ChatGPT after steps 1 and 2.
--  * identity: password_changed_at, session idle expiry (last_seen_at, idle_expires_at); lockout and session policy live in the API, recorded in audit_event.
--  * reporting periods are keyed by (entity, month): close state can differ between SubCo and HoldCo; CONSOLIDATED is writable only when both are.
--  * the adjustment amount is stored in the management engine's line sign (which IS profit-effect sign: costs negative, income positive), so Book + Reclass +
--    Adjustment = Total holds line by line; the column is renamed adjustment_amount_rupees and a calculation timestamp joins the frozen basis snapshot.
-- The period tables are empty at this point (no period has been closed yet), so they are recreated rather than altered.

ALTER TABLE fpa_app.app_user ADD COLUMN password_changed_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE fpa_app.app_session ADD COLUMN last_seen_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE fpa_app.app_session ADD COLUMN idle_expires_at timestamptz;
GRANT UPDATE (last_seen_at, idle_expires_at) ON fpa_app.app_session TO fpa_workflow_app;
GRANT UPDATE (password_changed_at) ON fpa_app.app_user TO fpa_workflow_app;

DROP TABLE fpa_app.reporting_period_event;
DROP TABLE fpa_app.reporting_period_status;
DROP FUNCTION fpa_app.period_is_writable(date);

CREATE TABLE fpa_app.reporting_period_status (
    entity      text NOT NULL CHECK (entity IN ('SUBCO', 'HOLDCO')),
    period      date NOT NULL CHECK (period = date_trunc('month', period)::date),
    status      text NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'SOFT_CLOSED', 'MANAGEMENT_CLOSED', 'FINAL_CLOSED', 'REOPENED')),
    changed_at  timestamptz NOT NULL DEFAULT now(),
    changed_by  uuid REFERENCES fpa_app.app_user (user_id),
    PRIMARY KEY (entity, period)
);
CREATE TRIGGER reporting_period_freeze BEFORE UPDATE ON fpa_app.reporting_period_status FOR EACH ROW EXECUTE FUNCTION fpa_app.freeze_columns('entity', 'period');

CREATE TABLE fpa_app.reporting_period_event (
    event_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    entity        text NOT NULL,
    period        date NOT NULL,
    from_status   text NOT NULL,
    to_status     text NOT NULL,
    actor_user_id uuid NOT NULL REFERENCES fpa_app.app_user (user_id),
    reason        text NOT NULL,
    at            timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (entity, period) REFERENCES fpa_app.reporting_period_status (entity, period),
    CHECK (to_status <> 'REOPENED' OR length(btrim(reason)) >= 10)
);
CREATE TRIGGER reporting_period_event_append_only BEFORE UPDATE OR DELETE ON fpa_app.reporting_period_event FOR EACH ROW EXECUTE FUNCTION fpa_app.forbid_mutation();
GRANT UPDATE ON fpa_app.reporting_period_status TO fpa_workflow_app;

-- A month without a row is OPEN. CONSOLIDATED is writable only when SUBCO and HOLDCO both are.
CREATE OR REPLACE FUNCTION fpa_app.period_is_writable(p_entity text, p date) RETURNS boolean LANGUAGE sql STABLE AS $$
    SELECT CASE WHEN p_entity = 'CONSOLIDATED' THEN fpa_app.period_is_writable('SUBCO', p) AND fpa_app.period_is_writable('HOLDCO', p)
                ELSE coalesce((SELECT status IN ('OPEN', 'SOFT_CLOSED', 'REOPENED') FROM fpa_app.reporting_period_status
                               WHERE entity = p_entity AND period = date_trunc('month', p)::date), true) END
$$;

-- adjustment: rename the amount, add the calculation timestamp, point the triggers at the new period function
ALTER TABLE fpa_app.adjustment RENAME COLUMN profit_effect_rupees TO adjustment_amount_rupees;
ALTER TABLE fpa_app.adjustment ADD COLUMN calculated_at timestamptz;
GRANT UPDATE (calculated_at) ON fpa_app.adjustment TO fpa_workflow_app;
COMMENT ON COLUMN fpa_app.adjustment.adjustment_amount_rupees IS
    'Rupees in the management engine line sign (profit-effect sign: a cost provision is negative, income positive). Book + Reclass + Adjustment = Total per line. RATE rows derive it from rate x metric snapshot; FIXED and MANUAL copy the entered amount.';

DROP VIEW fpa_app.v_adjustment_active;
CREATE VIEW fpa_app.v_adjustment_active AS
    SELECT adjustment_id, template_id, reporting_month, entity, management_line, location_type, location_code, adjustment_type, basis_type, adjustment_amount_rupees,
           supporting_reference, narrative, linked_policy, owner_user_id, created_by, approved_by, approved_at, activated_at
    FROM fpa_app.adjustment WHERE status IN ('ACTIVE', 'REVERSAL_REQUESTED');
GRANT SELECT ON fpa_app.v_adjustment_active TO fpa_workflow_app;

CREATE OR REPLACE FUNCTION fpa_app.adjustment_freeze() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE c text;
BEGIN
    IF OLD.status <> 'DRAFT' THEN
        FOREACH c IN ARRAY ARRAY['reporting_month', 'entity', 'management_line', 'location_type', 'location_code', 'adjustment_type', 'basis_type', 'entered_amount_rupees', 'rate',
                                 'rate_metric', 'metric_snapshot', 'adjustment_amount_rupees', 'calculation_version', 'calculated_at', 'supporting_reference', 'narrative',
                                 'linked_policy', 'owner_user_id', 'template_id'] LOOP
            IF to_jsonb(NEW) -> c IS DISTINCT FROM to_jsonb(OLD) -> c THEN
                RAISE EXCEPTION 'column % of an adjustment cannot be changed after it was submitted; reverse it and create a new one', c USING ERRCODE = 'check_violation';
            END IF;
        END LOOP;
    END IF;
    FOREACH c IN ARRAY ARRAY['adjustment_id', 'created_by', 'created_at', 'reversal_of_id'] LOOP
        IF to_jsonb(NEW) -> c IS DISTINCT FROM to_jsonb(OLD) -> c THEN
            RAISE EXCEPTION 'column % of an adjustment is immutable', c USING ERRCODE = 'check_violation';
        END IF;
    END LOOP;
    RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION fpa_app.adjustment_force_draft() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.status := 'DRAFT'; NEW.submitted_at := NULL; NEW.approved_by := NULL; NEW.approved_at := NULL; NEW.activated_at := NULL;
    IF NEW.basis_type = 'RATE' AND NEW.calculated_at IS NULL THEN
        RAISE EXCEPTION 'a rate-based adjustment needs the calculation timestamp of its basis snapshot' USING ERRCODE = 'check_violation';
    END IF;
    IF NOT fpa_app.period_is_writable(NEW.entity, NEW.reporting_month) THEN
        RAISE EXCEPTION 'the reporting month % is closed for %; a controller must reopen it first', NEW.reporting_month, NEW.entity USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION fpa_app.adjustment_event_check() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE a fpa_app.adjustment%ROWTYPE; single boolean;
BEGIN
    SELECT * INTO a FROM fpa_app.adjustment WHERE adjustment_id = NEW.adjustment_id FOR UPDATE;
    SELECT coalesce((SELECT value = 'on' FROM fpa_app.app_setting WHERE key = 'single_user_mode'), false) INTO single;
    NEW.seq := coalesce((SELECT max(seq) FROM fpa_app.adjustment_event WHERE adjustment_id = NEW.adjustment_id), 0) + 1;
    IF NEW.event_type = 'CREATED' THEN
        IF NEW.seq <> 1 OR NEW.to_status <> 'DRAFT' THEN
            RAISE EXCEPTION 'CREATED must be the first event and leave the adjustment in DRAFT';
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.event_type = 'COMMENTED' THEN
        NEW.from_status := a.status;
        NEW.to_status := a.status;
        RETURN NEW;
    END IF;
    NEW.from_status := a.status;
    IF NOT EXISTS (SELECT 1 FROM fpa_app.adjustment_transition t WHERE t.from_status = a.status AND t.to_status = NEW.to_status AND t.event_type = NEW.event_type) THEN
        RAISE EXCEPTION 'adjustment % cannot go from % to % by %', a.adjustment_id, a.status, NEW.to_status, NEW.event_type USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.event_type IN ('REJECTED', 'REVERSAL_REQUESTED', 'REVERSAL_REJECTED') AND length(btrim(coalesce(NEW.comment, ''))) < 10 THEN
        RAISE EXCEPTION '% needs a reason of at least 10 characters', NEW.event_type USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.event_type IN ('APPROVED', 'REVERSAL_APPROVED') AND NEW.actor_user_id = a.created_by AND NOT single THEN
        RAISE EXCEPTION 'the creator of an adjustment cannot approve it (maker-checker)' USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF NEW.event_type IN ('APPROVED', 'ACTIVATED') AND NOT fpa_app.period_is_writable(a.entity, a.reporting_month) THEN
        RAISE EXCEPTION 'the reporting month % is closed for %; a controller must reopen it first', a.reporting_month, a.entity USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;
