-- fpa_app 002: Adjustments and Provisions (governed management amounts that change Store and Corporate EBITDA).
-- Not corrections (no amount, net zero) and not exceptions (workflow only). Vocabulary follows the management engine: entity SUBCO | HOLDCO | CONSOLIDATED,
-- location type STORES | DC | HO, management line = the engine's line key (for example employee_cost).
-- Sign: profit_effect_rupees carries the sign of its effect on profit (a cost provision is negative), as in the register today.
-- State changes go ONLY through INSERT into adjustment_event: the trigger validates the transition, the maker-checker rule and the period lock, then moves the
-- status. The app login has no UPDATE right on the status columns.

CREATE TABLE fpa_app.app_setting (
    key         text PRIMARY KEY,
    value       text NOT NULL,
    note        text,
    updated_at  timestamptz NOT NULL DEFAULT now(),
    updated_by  uuid REFERENCES fpa_app.app_user (user_id)
);
-- single_user_mode on: one FP&A Manager may both create and approve (the events stay separate). Turn off when roles are in force.
INSERT INTO fpa_app.app_setting (key, value, note) VALUES
    ('single_user_mode', 'on', 'on: creator may approve their own adjustment or correction; off: maker-checker enforced by the database');
GRANT UPDATE (value, updated_at, updated_by) ON fpa_app.app_setting TO fpa_workflow_app;

CREATE TABLE fpa_app.adjustment_transition (
    from_status text NOT NULL,
    to_status   text NOT NULL,
    event_type  text NOT NULL,
    PRIMARY KEY (from_status, to_status, event_type)
);
INSERT INTO fpa_app.adjustment_transition VALUES
    ('DRAFT', 'REVIEW', 'SUBMITTED'), ('DRAFT', 'WITHDRAWN', 'WITHDRAWN'),
    ('REVIEW', 'APPROVED', 'APPROVED'), ('REVIEW', 'REJECTED', 'REJECTED'), ('REVIEW', 'WITHDRAWN', 'WITHDRAWN'),
    ('APPROVED', 'ACTIVE', 'ACTIVATED'),
    ('ACTIVE', 'REVERSAL_REQUESTED', 'REVERSAL_REQUESTED'),
    ('REVERSAL_REQUESTED', 'REVERSED', 'REVERSAL_APPROVED'), ('REVERSAL_REQUESTED', 'ACTIVE', 'REVERSAL_REJECTED');

CREATE TABLE fpa_app.adjustment_template (
    template_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name                 text NOT NULL,
    entity               text NOT NULL CHECK (entity IN ('SUBCO', 'HOLDCO', 'CONSOLIDATED')),
    management_line      text NOT NULL,
    location_type        text NOT NULL CHECK (location_type IN ('STORES', 'DC', 'HO')),
    location_code        text,
    adjustment_type      text NOT NULL CHECK (adjustment_type IN ('PROVISION', 'MANAGEMENT_JOURNAL', 'INCOME_ADJUSTMENT', 'ONE_TIME', 'INTERCOMPANY_ELIMINATION', 'COGS_MANAGEMENT_CORRECTION')),
    basis_type           text NOT NULL CHECK (basis_type IN ('FIXED', 'RATE')),
    fixed_amount_rupees  numeric(20, 4),
    rate                 numeric(12, 8),
    rate_metric          text,
    start_month          date NOT NULL CHECK (start_month = date_trunc('month', start_month)::date),
    end_month            date CHECK (end_month IS NULL OR (end_month = date_trunc('month', end_month)::date AND end_month >= start_month)),
    linked_policy        text,
    owner_user_id        uuid NOT NULL REFERENCES fpa_app.app_user (user_id),
    status               text NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT', 'ACTIVE', 'PAUSED', 'RETIRED')),
    last_generated_month date,
    created_by           uuid NOT NULL REFERENCES fpa_app.app_user (user_id),
    created_at           timestamptz NOT NULL DEFAULT now(),
    approved_by          uuid REFERENCES fpa_app.app_user (user_id),
    approved_at          timestamptz,
    CHECK ((basis_type = 'FIXED' AND fixed_amount_rupees IS NOT NULL AND rate IS NULL) OR (basis_type = 'RATE' AND rate IS NOT NULL AND rate_metric IS NOT NULL AND fixed_amount_rupees IS NULL))
);
CREATE TRIGGER adjustment_template_freeze BEFORE UPDATE ON fpa_app.adjustment_template FOR EACH ROW EXECUTE FUNCTION fpa_app.freeze_columns(
    'template_id', 'entity', 'management_line', 'location_type', 'location_code', 'adjustment_type', 'basis_type', 'start_month', 'created_by', 'created_at');
GRANT INSERT ON fpa_app.adjustment_template TO fpa_workflow_app;
GRANT UPDATE (name, fixed_amount_rupees, rate, rate_metric, end_month, linked_policy, owner_user_id, status, last_generated_month, approved_by, approved_at)
    ON fpa_app.adjustment_template TO fpa_workflow_app;

CREATE TABLE fpa_app.adjustment (
    adjustment_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    template_id           uuid REFERENCES fpa_app.adjustment_template (template_id),
    reporting_month       date NOT NULL CHECK (reporting_month = date_trunc('month', reporting_month)::date),
    entity                text NOT NULL CHECK (entity IN ('SUBCO', 'HOLDCO', 'CONSOLIDATED')),
    management_line       text NOT NULL,
    location_type         text NOT NULL CHECK (location_type IN ('STORES', 'DC', 'HO')),
    location_code         text,
    adjustment_type       text NOT NULL CHECK (adjustment_type IN ('PROVISION', 'MANAGEMENT_JOURNAL', 'INCOME_ADJUSTMENT', 'ONE_TIME', 'INTERCOMPANY_ELIMINATION', 'COGS_MANAGEMENT_CORRECTION')),
    basis_type            text NOT NULL CHECK (basis_type IN ('FIXED', 'RATE', 'MANUAL')),
    entered_amount_rupees numeric(20, 4),
    rate                  numeric(12, 8),
    rate_metric           text,
    metric_snapshot       jsonb,
    profit_effect_rupees  numeric(20, 4) NOT NULL,
    calculation_version   text NOT NULL DEFAULT 'v1',
    supporting_reference  text NOT NULL CHECK (length(btrim(supporting_reference)) >= 3),
    narrative             text NOT NULL CHECK (length(btrim(narrative)) >= 10),
    linked_policy         text,
    owner_user_id         uuid NOT NULL REFERENCES fpa_app.app_user (user_id),
    status                text NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT', 'REVIEW', 'APPROVED', 'ACTIVE', 'REJECTED', 'WITHDRAWN', 'REVERSAL_REQUESTED', 'REVERSED')),
    reversal_of_id        uuid REFERENCES fpa_app.adjustment (adjustment_id),
    created_by            uuid NOT NULL REFERENCES fpa_app.app_user (user_id),
    created_at            timestamptz NOT NULL DEFAULT now(),
    submitted_at          timestamptz,
    approved_by           uuid REFERENCES fpa_app.app_user (user_id),
    approved_at           timestamptz,
    activated_at          timestamptz,
    CHECK ((basis_type IN ('FIXED', 'MANUAL') AND entered_amount_rupees IS NOT NULL AND rate IS NULL AND profit_effect_rupees = entered_amount_rupees)
        OR (basis_type = 'RATE' AND rate IS NOT NULL AND rate_metric IS NOT NULL AND metric_snapshot IS NOT NULL AND entered_amount_rupees IS NULL)),
    CHECK (entity <> 'CONSOLIDATED' OR adjustment_type = 'INTERCOMPANY_ELIMINATION')
);
-- one live row per template and month (rejected, withdrawn and reversed rows do not count)
CREATE UNIQUE INDEX adjustment_template_month_uq ON fpa_app.adjustment (template_id, reporting_month)
    WHERE template_id IS NOT NULL AND status NOT IN ('REJECTED', 'WITHDRAWN', 'REVERSED');
CREATE INDEX adjustment_month_ix ON fpa_app.adjustment (reporting_month, status);

-- Draft rows may be edited; from SUBMITTED on, the financial meaning is frozen (reverse, then create a new row). The status and stamp columns move only by the event trigger.
CREATE OR REPLACE FUNCTION fpa_app.adjustment_freeze() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE c text;
BEGIN
    IF OLD.status <> 'DRAFT' THEN
        FOREACH c IN ARRAY ARRAY['reporting_month', 'entity', 'management_line', 'location_type', 'location_code', 'adjustment_type', 'basis_type', 'entered_amount_rupees', 'rate',
                                 'rate_metric', 'metric_snapshot', 'profit_effect_rupees', 'calculation_version', 'supporting_reference', 'narrative', 'linked_policy', 'owner_user_id', 'template_id'] LOOP
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
CREATE TRIGGER adjustment_freeze BEFORE UPDATE ON fpa_app.adjustment FOR EACH ROW EXECUTE FUNCTION fpa_app.adjustment_freeze();

CREATE OR REPLACE FUNCTION fpa_app.adjustment_force_draft() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.status := 'DRAFT'; NEW.submitted_at := NULL; NEW.approved_by := NULL; NEW.approved_at := NULL; NEW.activated_at := NULL;
    IF NOT fpa_app.period_is_writable(NEW.reporting_month) THEN
        RAISE EXCEPTION 'the reporting month % is closed; a controller must reopen it first', NEW.reporting_month USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER adjustment_force_draft BEFORE INSERT ON fpa_app.adjustment FOR EACH ROW EXECUTE FUNCTION fpa_app.adjustment_force_draft();

CREATE TABLE fpa_app.adjustment_event (
    event_id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    adjustment_id  uuid NOT NULL REFERENCES fpa_app.adjustment (adjustment_id),
    seq            integer NOT NULL,
    event_type     text NOT NULL,
    from_status    text,
    to_status      text NOT NULL,
    actor_user_id  uuid NOT NULL REFERENCES fpa_app.app_user (user_id),
    comment        text,
    request_id     text,
    at             timestamptz NOT NULL DEFAULT now(),
    UNIQUE (adjustment_id, seq)
);
CREATE TRIGGER adjustment_event_append_only BEFORE UPDATE OR DELETE ON fpa_app.adjustment_event FOR EACH ROW EXECUTE FUNCTION fpa_app.forbid_mutation();

-- event_type: CREATED, SUBMITTED, APPROVED, ACTIVATED, REJECTED, WITHDRAWN, REVERSAL_REQUESTED, REVERSAL_APPROVED, REVERSAL_REJECTED, COMMENTED
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
    IF NEW.event_type IN ('APPROVED', 'ACTIVATED') AND NOT fpa_app.period_is_writable(a.reporting_month) THEN
        RAISE EXCEPTION 'the reporting month % is closed; a controller must reopen it first', a.reporting_month USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER adjustment_event_check BEFORE INSERT ON fpa_app.adjustment_event FOR EACH ROW EXECUTE FUNCTION fpa_app.adjustment_event_check();

-- Moves the projection. SECURITY DEFINER so the app login needs no UPDATE right on the status columns; the search path is pinned.
CREATE OR REPLACE FUNCTION fpa_app.adjustment_event_apply() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = fpa_app, pg_temp AS $$
BEGIN
    UPDATE fpa_app.adjustment SET status = NEW.to_status,
        submitted_at = CASE WHEN NEW.event_type = 'SUBMITTED' THEN NEW.at ELSE submitted_at END,
        approved_by  = CASE WHEN NEW.event_type = 'APPROVED' THEN NEW.actor_user_id ELSE approved_by END,
        approved_at  = CASE WHEN NEW.event_type = 'APPROVED' THEN NEW.at ELSE approved_at END,
        activated_at = CASE WHEN NEW.event_type = 'ACTIVATED' THEN NEW.at ELSE activated_at END
    WHERE adjustment_id = NEW.adjustment_id;
    RETURN NULL;
END $$;
CREATE TRIGGER adjustment_event_apply AFTER INSERT ON fpa_app.adjustment_event FOR EACH ROW
    WHEN (NEW.event_type NOT IN ('CREATED', 'COMMENTED')) EXECUTE FUNCTION fpa_app.adjustment_event_apply();

-- App login: create rows and edit DRAFT meaning columns only (the freeze trigger blocks edits after submission); never the status columns.
GRANT INSERT ON fpa_app.adjustment TO fpa_workflow_app;
GRANT UPDATE (entered_amount_rupees, rate, rate_metric, metric_snapshot, profit_effect_rupees, supporting_reference, narrative, linked_policy, owner_user_id,
              management_line, location_type, location_code, reporting_month, entity, adjustment_type, basis_type) ON fpa_app.adjustment TO fpa_workflow_app;

-- Only ACTIVE rows (and ACTIVE rows with a reversal pending) feed official Management Reporting; the engine reads this view.
CREATE VIEW fpa_app.v_adjustment_active AS
    SELECT adjustment_id, template_id, reporting_month, entity, management_line, location_type, location_code, adjustment_type, basis_type, profit_effect_rupees,
           supporting_reference, narrative, linked_policy, owner_user_id, created_by, approved_by, approved_at, activated_at
    FROM fpa_app.adjustment WHERE status IN ('ACTIVE', 'REVERSAL_REQUESTED');
GRANT SELECT ON fpa_app.v_adjustment_active TO fpa_workflow_app;
