-- fpa_app 013: moving the adjustment register from the spreadsheet (CSV) to the app, and recording every cut-over.
--  * adjustment.source: 'app' or 'legacy_csv_import'. The legacy rows are imported once, by an administrator, as ACTIVE (event IMPORTED) or REVIEW (a proposed row), never edited afterwards.
--  * cutover_record: an append-only record of each cut-over (adjustments register, mapping): the validation result the administrator saw, the first month the app is the source, who and when.

ALTER TABLE fpa_app.adjustment ADD COLUMN source text NOT NULL DEFAULT 'app' CHECK (source IN ('app', 'legacy_csv_import'));
GRANT UPDATE (source) ON fpa_app.adjustment TO fpa_workflow_app;
INSERT INTO fpa_app.adjustment_transition VALUES ('DRAFT', 'ACTIVE', 'IMPORTED'), ('DRAFT', 'REVIEW', 'IMPORTED_PROPOSED');

CREATE OR REPLACE FUNCTION fpa_app.adjustment_freeze() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE c text;
BEGIN
    IF OLD.status <> 'DRAFT' THEN
        FOREACH c IN ARRAY ARRAY['reporting_month', 'entity', 'management_line', 'location_type', 'location_code', 'adjustment_type', 'basis_type', 'entered_amount_rupees', 'rate',
                                 'rate_metric', 'metric_snapshot', 'adjustment_amount_rupees', 'calculation_version', 'calculated_at', 'supporting_reference', 'narrative',
                                 'linked_policy', 'owner_user_id', 'template_id', 'source'] LOOP
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
    -- a legacy import brings history in as it was: the period lock applies to what people enter, not to the baseline
    IF NEW.source = 'app' AND NOT fpa_app.period_is_writable(NEW.entity, NEW.reporting_month) THEN
        RAISE EXCEPTION 'the reporting month % is closed for %; a controller must reopen it first', NEW.reporting_month, NEW.entity USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION fpa_app.adjustment_event_check() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE a fpa_app.adjustment%ROWTYPE; single boolean; arole text;
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
    IF NEW.event_type IN ('IMPORTED', 'IMPORTED_PROPOSED') THEN
        SELECT role INTO arole FROM fpa_app.app_user WHERE user_id = NEW.actor_user_id AND active;
        IF a.source <> 'legacy_csv_import' OR arole IS DISTINCT FROM 'admin' THEN
            RAISE EXCEPTION 'only an administrator imports the legacy register' USING ERRCODE = 'insufficient_privilege';
        END IF;
        RETURN NEW;
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

CREATE OR REPLACE FUNCTION fpa_app.adjustment_event_apply() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = fpa_app, pg_temp AS $$
BEGIN
    UPDATE fpa_app.adjustment SET status = NEW.to_status,
        submitted_at = CASE WHEN NEW.event_type IN ('SUBMITTED', 'IMPORTED_PROPOSED') THEN NEW.at ELSE submitted_at END,
        approved_by  = CASE WHEN NEW.event_type = 'APPROVED' THEN NEW.actor_user_id ELSE approved_by END,
        approved_at  = CASE WHEN NEW.event_type = 'APPROVED' THEN NEW.at ELSE approved_at END,
        activated_at = CASE WHEN NEW.event_type IN ('ACTIVATED', 'IMPORTED') THEN NEW.at ELSE activated_at END
    WHERE adjustment_id = NEW.adjustment_id;
    RETURN NULL;
END $$;

CREATE TABLE fpa_app.cutover_record (
    cutover_id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    domain        text NOT NULL CHECK (domain IN ('ADJUSTMENTS', 'MAPPING')),
    first_month   date NOT NULL CHECK (first_month = date_trunc('month', first_month)::date),
    validation    jsonb NOT NULL,                 -- what the validation reported when the administrator decided
    identical     boolean NOT NULL,
    comment       text NOT NULL CHECK (length(btrim(comment)) >= 10),
    actor_user_id uuid NOT NULL REFERENCES fpa_app.app_user (user_id),
    at            timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER cutover_record_append_only BEFORE UPDATE OR DELETE ON fpa_app.cutover_record FOR EACH ROW EXECUTE FUNCTION fpa_app.forbid_mutation();
CREATE OR REPLACE FUNCTION fpa_app.cutover_record_check() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = fpa_app, pg_temp AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM fpa_app.app_user WHERE user_id = NEW.actor_user_id AND active AND role = 'admin') THEN
        RAISE EXCEPTION 'only an administrator records a cut-over' USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER cutover_record_check BEFORE INSERT ON fpa_app.cutover_record FOR EACH ROW EXECUTE FUNCTION fpa_app.cutover_record_check();
