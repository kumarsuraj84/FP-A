-- fpa_app 005: Exception Inbox (workflow around evidence; never changes reporting, never holds a finance fact).
-- A case is one detected issue with an owner, due date, next action and status. The evidence column is a snapshot of what triggered the case (observed value,
-- reference value, source run, drill link): it is evidence, not a financial record. State, owner, due date and scores change only by INSERT into exception_event;
-- a SECURITY DEFINER trigger applies the event to the case. The app login has no UPDATE right on exception_case at all.
-- Recurrence: a re-detection of an OPEN case is a SYSTEM_RECURRED event on that case; a re-detection after the case was CLOSED creates a NEW case linked to the
-- old one (recurrence_of_case_id, recurrence_no). REOPENED is for a closure that was itself premature or invalid.

CREATE TABLE fpa_app.exception_case (
    case_id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    dedupe_key            text NOT NULL,                      -- hash(exception_type, entity, site, metric_id, period, subject_key), computed by the API
    exception_type        text NOT NULL,
    domain                text NOT NULL CHECK (domain IN ('EXPENSE', 'REVENUE', 'CREDITORS', 'CASH', 'CONTROLS', 'RELATED_PARTY', 'MAPPING', 'CLOSE')),
    entity                text CHECK (entity IN ('SUBCO', 'HOLDCO', 'CONSOLIDATED')),
    site_code             text,
    metric_id             text,
    period                date CHECK (period IS NULL OR period = date_trunc('month', period)::date),
    subject_key           text,                               -- vendor, ledger, related-party pair, voucher or control the case is about
    title                 text NOT NULL,
    recurrence_of_case_id uuid REFERENCES fpa_app.exception_case (case_id),
    recurrence_no         integer NOT NULL DEFAULT 1 CHECK (recurrence_no >= 1),
    severity_score        numeric(5, 2) NOT NULL CHECK (severity_score BETWEEN 0 AND 100),
    materiality_score     numeric(5, 2) NOT NULL CHECK (materiality_score BETWEEN 0 AND 100),
    recency_score         numeric(5, 2) NOT NULL CHECK (recency_score BETWEEN 0 AND 100),
    actionability_score   numeric(5, 2) NOT NULL CHECK (actionability_score BETWEEN 0 AND 100),
    persistence_multiplier numeric(4, 2) NOT NULL DEFAULT 1.00 CHECK (persistence_multiplier BETWEEN 1.00 AND 1.25),
    escalated             boolean NOT NULL DEFAULT false,     -- reconciliation failures and close blockers override the score
    final_score           numeric(5, 2) NOT NULL CHECK (final_score BETWEEN 0 AND 100),
    band                  text GENERATED ALWAYS AS (CASE WHEN escalated OR final_score >= 80 THEN 'CRITICAL' WHEN final_score >= 60 THEN 'HIGH' WHEN final_score >= 40 THEN 'MEDIUM' ELSE 'LOW' END) STORED,
    evidence              jsonb NOT NULL DEFAULT '{}'::jsonb,
    drill_link            text,
    status                text NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'ACKNOWLEDGED', 'RESOLVED', 'CLOSED')),
    owner_user_id         uuid REFERENCES fpa_app.app_user (user_id),
    due_date              date,
    next_action           text,
    closure_reason        text,
    source_run_id         text,
    first_detected_at     timestamptz NOT NULL DEFAULT now(),
    last_detected_at      timestamptz NOT NULL DEFAULT now(),
    detection_count       integer NOT NULL DEFAULT 1,
    closed_at             timestamptz,
    created_at            timestamptz NOT NULL DEFAULT now()
);
-- at most one live (not CLOSED) case per dedupe key
CREATE UNIQUE INDEX exception_case_live_uq ON fpa_app.exception_case (dedupe_key) WHERE status <> 'CLOSED';
CREATE INDEX exception_case_rank_ix ON fpa_app.exception_case (status, final_score DESC);
CREATE INDEX exception_case_owner_ix ON fpa_app.exception_case (owner_user_id, status);

CREATE OR REPLACE FUNCTION fpa_app.exception_case_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        NEW.status := 'OPEN'; NEW.closed_at := NULL; NEW.closure_reason := NULL; NEW.detection_count := 1; NEW.first_detected_at := now(); NEW.last_detected_at := now();
        RETURN NEW;
    END IF;
    IF NEW.case_id <> OLD.case_id OR NEW.dedupe_key <> OLD.dedupe_key OR NEW.exception_type <> OLD.exception_type OR NEW.domain <> OLD.domain
       OR NEW.entity IS DISTINCT FROM OLD.entity OR NEW.site_code IS DISTINCT FROM OLD.site_code OR NEW.metric_id IS DISTINCT FROM OLD.metric_id
       OR NEW.period IS DISTINCT FROM OLD.period OR NEW.subject_key IS DISTINCT FROM OLD.subject_key OR NEW.recurrence_of_case_id IS DISTINCT FROM OLD.recurrence_of_case_id
       OR NEW.first_detected_at <> OLD.first_detected_at OR NEW.created_at <> OLD.created_at THEN
        RAISE EXCEPTION 'identity columns of an exception case are immutable' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER exception_case_guard BEFORE INSERT OR UPDATE ON fpa_app.exception_case FOR EACH ROW EXECUTE FUNCTION fpa_app.exception_case_guard();
CREATE TRIGGER exception_case_no_delete BEFORE DELETE ON fpa_app.exception_case FOR EACH ROW EXECUTE FUNCTION fpa_app.forbid_mutation();

CREATE TABLE fpa_app.exception_transition (
    from_status text NOT NULL,
    to_status   text NOT NULL,
    event_type  text NOT NULL,
    PRIMARY KEY (from_status, to_status, event_type)
);
INSERT INTO fpa_app.exception_transition VALUES
    ('OPEN', 'ACKNOWLEDGED', 'ACKNOWLEDGED'),
    ('OPEN', 'RESOLVED', 'RESOLVED'), ('ACKNOWLEDGED', 'RESOLVED', 'RESOLVED'),
    ('RESOLVED', 'OPEN', 'RETURNED'),
    ('OPEN', 'CLOSED', 'CLOSED'), ('ACKNOWLEDGED', 'CLOSED', 'CLOSED'), ('RESOLVED', 'CLOSED', 'CLOSED'),
    ('CLOSED', 'OPEN', 'REOPENED');

CREATE TABLE fpa_app.exception_event (
    event_id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    case_id         uuid NOT NULL REFERENCES fpa_app.exception_case (case_id),
    seq             integer NOT NULL,
    event_type      text NOT NULL CHECK (event_type IN ('DETECTED', 'SYSTEM_RECURRED', 'ASSIGNED', 'REASSIGNED', 'ACKNOWLEDGED', 'ACTION_UPDATED', 'DUE_DATE_CHANGED', 'COMMENTED',
                                                         'RESOLVED', 'RETURNED', 'CLOSED', 'REOPENED')),
    from_status     text,
    to_status       text NOT NULL,
    actor_user_id   uuid REFERENCES fpa_app.app_user (user_id),
    actor_label     text,                                   -- 'system' for detections
    comment         text,
    closure_reason  text CHECK (closure_reason IN ('RESOLVED_FIXED', 'FALSE_POSITIVE', 'ACCEPTED_RISK', 'DUPLICATE', 'SOURCE_FIXED', 'OTHER')),
    new_owner_user_id uuid REFERENCES fpa_app.app_user (user_id),
    new_due_date    date,
    new_next_action text,
    new_evidence    jsonb,                                  -- SYSTEM_RECURRED: the refreshed evidence snapshot
    new_final_score numeric(5, 2) CHECK (new_final_score BETWEEN 0 AND 100),
    request_id      text,
    at              timestamptz NOT NULL DEFAULT now(),
    UNIQUE (case_id, seq),
    CHECK (actor_user_id IS NOT NULL OR (actor_label = 'system' AND event_type IN ('DETECTED', 'SYSTEM_RECURRED')))
);
CREATE TRIGGER exception_event_append_only BEFORE UPDATE OR DELETE ON fpa_app.exception_event FOR EACH ROW EXECUTE FUNCTION fpa_app.forbid_mutation();

-- Who may do what. viewer: nothing. The owner of the work cannot close it (unless single_user_mode is on, the one-manager phase). Closing and reopening are reviewer actions.
CREATE OR REPLACE FUNCTION fpa_app.exception_event_check() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE c fpa_app.exception_case%ROWTYPE; single boolean; arole text;
BEGIN
    SELECT * INTO c FROM fpa_app.exception_case WHERE case_id = NEW.case_id FOR UPDATE;
    SELECT coalesce((SELECT value = 'on' FROM fpa_app.app_setting WHERE key = 'single_user_mode'), false) INTO single;
    NEW.seq := coalesce((SELECT max(seq) FROM fpa_app.exception_event WHERE case_id = NEW.case_id), 0) + 1;
    IF NEW.event_type = 'DETECTED' THEN
        IF NEW.seq <> 1 OR NEW.to_status <> 'OPEN' THEN RAISE EXCEPTION 'DETECTED must be the first event and leave the case OPEN'; END IF;
        RETURN NEW;
    END IF;
    NEW.from_status := c.status;
    IF NEW.actor_user_id IS NOT NULL THEN
        SELECT role INTO arole FROM fpa_app.app_user WHERE user_id = NEW.actor_user_id AND active;
        IF arole IS NULL THEN RAISE EXCEPTION 'the actor is not an active user' USING ERRCODE = 'insufficient_privilege'; END IF;
        IF arole = 'viewer' AND NEW.event_type <> 'COMMENTED' THEN RAISE EXCEPTION 'a viewer cannot change an exception' USING ERRCODE = 'insufficient_privilege'; END IF;
    END IF;
    IF c.status = 'CLOSED' AND NEW.event_type NOT IN ('REOPENED', 'COMMENTED') THEN
        RAISE EXCEPTION 'a CLOSED case accepts only REOPENED or a comment; a new detection opens a new linked case' USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.event_type IN ('SYSTEM_RECURRED', 'ASSIGNED', 'REASSIGNED', 'ACTION_UPDATED', 'DUE_DATE_CHANGED', 'COMMENTED') THEN
        NEW.to_status := c.status;
        IF NEW.event_type IN ('ASSIGNED', 'REASSIGNED') AND NEW.new_owner_user_id IS NULL THEN RAISE EXCEPTION '% needs the new owner', NEW.event_type USING ERRCODE = 'check_violation'; END IF;
        IF NEW.event_type = 'DUE_DATE_CHANGED' AND NEW.new_due_date IS NULL THEN RAISE EXCEPTION 'DUE_DATE_CHANGED needs the new due date' USING ERRCODE = 'check_violation'; END IF;
        IF NEW.event_type IN ('ASSIGNED', 'REASSIGNED', 'DUE_DATE_CHANGED') AND NEW.actor_user_id IS NOT NULL AND arole NOT IN ('fpa_manager', 'finance_reviewer', 'controller', 'admin') THEN
            RAISE EXCEPTION 'only a manager or reviewer assigns or reschedules' USING ERRCODE = 'insufficient_privilege';
        END IF;
        RETURN NEW;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM fpa_app.exception_transition t WHERE t.from_status = c.status AND t.to_status = NEW.to_status AND t.event_type = NEW.event_type) THEN
        RAISE EXCEPTION 'exception % cannot go from % to % by %', c.case_id, c.status, NEW.to_status, NEW.event_type USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.event_type IN ('RETURNED', 'CLOSED', 'REOPENED') AND length(btrim(coalesce(NEW.comment, ''))) < 10 THEN
        RAISE EXCEPTION '% needs a reason of at least 10 characters', NEW.event_type USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.event_type = 'CLOSED' AND NEW.closure_reason IS NULL THEN RAISE EXCEPTION 'CLOSED needs a closure reason' USING ERRCODE = 'check_violation'; END IF;
    IF NEW.event_type IN ('CLOSED', 'RETURNED', 'REOPENED') THEN
        IF NOT (arole IN ('finance_reviewer', 'controller', 'admin') OR (single AND arole = 'fpa_manager')) THEN
            RAISE EXCEPTION 'only a finance reviewer can close, return or reopen an exception' USING ERRCODE = 'insufficient_privilege';
        END IF;
        IF NEW.event_type = 'CLOSED' AND NEW.actor_user_id = c.owner_user_id AND NOT single THEN
            RAISE EXCEPTION 'the owner of the work cannot close it; a reviewer closes' USING ERRCODE = 'insufficient_privilege';
        END IF;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER exception_event_check BEFORE INSERT ON fpa_app.exception_event FOR EACH ROW EXECUTE FUNCTION fpa_app.exception_event_check();

CREATE OR REPLACE FUNCTION fpa_app.exception_event_apply() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = fpa_app, pg_temp AS $$
BEGIN
    UPDATE fpa_app.exception_case SET
        status = NEW.to_status,
        owner_user_id = CASE WHEN NEW.event_type IN ('ASSIGNED', 'REASSIGNED') THEN NEW.new_owner_user_id ELSE owner_user_id END,
        due_date = CASE WHEN NEW.new_due_date IS NOT NULL THEN NEW.new_due_date ELSE due_date END,
        next_action = CASE WHEN NEW.new_next_action IS NOT NULL THEN NEW.new_next_action ELSE next_action END,
        evidence = CASE WHEN NEW.event_type = 'SYSTEM_RECURRED' AND NEW.new_evidence IS NOT NULL THEN NEW.new_evidence ELSE evidence END,
        final_score = CASE WHEN NEW.event_type = 'SYSTEM_RECURRED' AND NEW.new_final_score IS NOT NULL THEN NEW.new_final_score ELSE final_score END,
        detection_count = CASE WHEN NEW.event_type = 'SYSTEM_RECURRED' THEN detection_count + 1 ELSE detection_count END,
        last_detected_at = CASE WHEN NEW.event_type = 'SYSTEM_RECURRED' THEN NEW.at ELSE last_detected_at END,
        closure_reason = CASE WHEN NEW.event_type = 'CLOSED' THEN NEW.closure_reason WHEN NEW.event_type = 'REOPENED' THEN NULL ELSE closure_reason END,
        closed_at = CASE WHEN NEW.event_type = 'CLOSED' THEN NEW.at WHEN NEW.event_type = 'REOPENED' THEN NULL ELSE closed_at END
    WHERE case_id = NEW.case_id;
    RETURN NULL;
END $$;
CREATE TRIGGER exception_event_apply AFTER INSERT ON fpa_app.exception_event FOR EACH ROW
    WHEN (NEW.event_type NOT IN ('DETECTED', 'COMMENTED')) EXECUTE FUNCTION fpa_app.exception_event_apply();

GRANT INSERT ON fpa_app.exception_case TO fpa_workflow_app;
