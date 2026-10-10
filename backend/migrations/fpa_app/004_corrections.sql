-- fpa_app 004: Corrections (reclassification overlay on immutable finance lines).
-- A correction changes only HOW an existing source line is grouped (management group) and WHICH month it is reported in (expense month). There is no amount
-- column a client can write: the rupee amount stays in gold_fpa and the engine reads it from there; source_amount_snapshot is an audit copy made by the API.
-- Net zero is therefore structural. Source key = (gold entity, cost_tag_key) with gold entity RETAIL | VENTURES (RETAIL = SubCo, VENTURES = HoldCo).
-- States move only by INSERT into correction_event (transition table, maker-checker, period lock, conflict detection), as for adjustments.

CREATE TABLE fpa_app.correction_transition (
    from_status text NOT NULL,
    to_status   text NOT NULL,
    event_type  text NOT NULL,
    PRIMARY KEY (from_status, to_status, event_type)
);
INSERT INTO fpa_app.correction_transition VALUES
    ('DRAFT', 'SUBMITTED', 'SUBMITTED'), ('DRAFT', 'WITHDRAWN', 'WITHDRAWN'),
    ('SUBMITTED', 'APPROVED', 'APPROVED'), ('SUBMITTED', 'REJECTED', 'REJECTED'), ('SUBMITTED', 'WITHDRAWN', 'WITHDRAWN'),
    ('APPROVED', 'ACTIVE', 'ACTIVATED'), ('APPROVED', 'WITHDRAWN', 'VOIDED'),
    ('ACTIVE', 'REVERSAL_REQUESTED', 'REVERSAL_REQUESTED'),
    ('REVERSAL_REQUESTED', 'REVERSED', 'REVERSAL_APPROVED'), ('REVERSAL_REQUESTED', 'ACTIVE', 'REVERSAL_REJECTED'),
    ('ACTIVE', 'SOURCE_REVIEW_REQUIRED', 'SOURCE_CHANGED'), ('ACTIVE', 'SUPERSEDED_BY_SOURCE', 'SOURCE_NOW_MATCHES'),
    ('SOURCE_REVIEW_REQUIRED', 'ACTIVE', 'SOURCE_RECONFIRMED'), ('SOURCE_REVIEW_REQUIRED', 'REVERSED', 'REVERSAL_APPROVED'),
    ('SOURCE_REVIEW_REQUIRED', 'SUPERSEDED_BY_SOURCE', 'SOURCE_NOW_MATCHES');

CREATE TABLE fpa_app.correction_request (
    request_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    scope_type          text NOT NULL CHECK (scope_type IN ('LINE', 'VOUCHER', 'BULK')),
    correction_type     text NOT NULL CHECK (correction_type IN ('GROUP', 'EXPENSE_MONTH', 'BOTH')),
    source_entity       text NOT NULL CHECK (source_entity IN ('RETAIL', 'VENTURES')),
    status              text NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT', 'SUBMITTED', 'APPROVED', 'ACTIVE', 'REJECTED', 'WITHDRAWN', 'REVERSAL_REQUESTED', 'REVERSED',
                                                                        'SOURCE_REVIEW_REQUIRED', 'SUPERSEDED_BY_SOURCE')),
    reason_code         text NOT NULL CHECK (reason_code IN ('WRONG_CLASSIFICATION', 'WRONG_MONTH', 'LATE_INVOICE_TIMING', 'WRONG_SOURCE_MAPPING', 'MANAGEMENT_RECLASSIFICATION', 'OTHER')),
    reason_text         text NOT NULL CHECK (length(btrim(reason_text)) >= 10),
    evidence_reference  text NOT NULL CHECK (length(btrim(evidence_reference)) >= 3),
    requested_by        uuid NOT NULL REFERENCES fpa_app.app_user (user_id),
    requested_at        timestamptz NOT NULL DEFAULT now(),
    submitted_at        timestamptz,
    approved_by         uuid REFERENCES fpa_app.app_user (user_id),
    approved_at         timestamptz,
    activated_at        timestamptz,
    reversal_of_id      uuid REFERENCES fpa_app.correction_request (request_id),
    created_by          uuid NOT NULL REFERENCES fpa_app.app_user (user_id),
    created_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX correction_request_status_ix ON fpa_app.correction_request (status, requested_at);

CREATE TABLE fpa_app.correction_line (
    line_id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id            uuid NOT NULL REFERENCES fpa_app.correction_request (request_id),
    source_entity         text NOT NULL CHECK (source_entity IN ('RETAIL', 'VENTURES')),
    source_line_key       text NOT NULL,                       -- gold_fpa.voucher_lines.cost_tag_key (unique with entity)
    source_run_id         text,
    fingerprint           text NOT NULL CHECK (fingerprint ~ '^[0-9a-fA-F]{64}$'),   -- computed by the API from the immutable finance-line fields
    fingerprint_version   text NOT NULL DEFAULT 'v1',
    source_amount_snapshot numeric(20, 4) NOT NULL,            -- audit copy of the finance amount, made by the API; never read by the engine
    voucher_key           text NOT NULL,
    ledger_key            text NOT NULL,
    site_code             text,
    original_group        text NOT NULL,
    corrected_group       text,
    original_month        date NOT NULL CHECK (original_month = date_trunc('month', original_month)::date),
    corrected_month       date CHECK (corrected_month IS NULL OR corrected_month = date_trunc('month', corrected_month)::date),
    source_state          text NOT NULL DEFAULT 'UNCHANGED' CHECK (source_state IN ('UNCHANGED', 'NOW_MATCHES', 'CHANGED_DIFFERENTLY', 'ORPHANED')),
    group_active          boolean NOT NULL DEFAULT false,      -- maintained by the event trigger: this line's group overlay is in force
    month_active          boolean NOT NULL DEFAULT false,
    created_at            timestamptz NOT NULL DEFAULT now(),
    CHECK ((corrected_group IS NOT NULL AND corrected_group <> original_group) OR (corrected_month IS NOT NULL AND corrected_month <> original_month)),
    CHECK (corrected_group IS NULL OR corrected_group <> original_group),
    CHECK (corrected_month IS NULL OR corrected_month <> original_month)
);
CREATE INDEX correction_line_request_ix ON fpa_app.correction_line (request_id);
-- one ACTIVE correction per source line and attribute
CREATE UNIQUE INDEX correction_line_group_active_uq ON fpa_app.correction_line (source_entity, source_line_key) WHERE group_active;
CREATE UNIQUE INDEX correction_line_month_active_uq ON fpa_app.correction_line (source_entity, source_line_key) WHERE month_active;

-- Lines belong to one request and may be added or changed only while it is DRAFT; afterwards only source_state moves (the source checks).
CREATE OR REPLACE FUNCTION fpa_app.correction_line_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE st text; r fpa_app.correction_request%ROWTYPE;
BEGIN
    SELECT * INTO r FROM fpa_app.correction_request WHERE request_id = NEW.request_id;
    IF TG_OP = 'INSERT' THEN
        IF r.status <> 'DRAFT' THEN RAISE EXCEPTION 'lines can only be added to a DRAFT correction' USING ERRCODE = 'check_violation'; END IF;
        IF NEW.source_entity <> r.source_entity THEN RAISE EXCEPTION 'every line of a request must come from the request entity' USING ERRCODE = 'check_violation'; END IF;
        IF r.correction_type = 'GROUP' AND NEW.corrected_month IS NOT NULL THEN RAISE EXCEPTION 'a GROUP correction cannot change the month' USING ERRCODE = 'check_violation'; END IF;
        IF r.correction_type = 'EXPENSE_MONTH' AND NEW.corrected_group IS NOT NULL THEN RAISE EXCEPTION 'an EXPENSE_MONTH correction cannot change the group' USING ERRCODE = 'check_violation'; END IF;
        NEW.group_active := false; NEW.month_active := false; NEW.source_state := 'UNCHANGED';
        RETURN NEW;
    END IF;
    -- UPDATE: the flags belong to the event trigger (definer); everything that defines the correction is frozen once the request is no longer DRAFT
    IF r.status <> 'DRAFT' AND current_user = 'fpa_workflow_app' THEN
        IF ROW(NEW.request_id, NEW.source_entity, NEW.source_line_key, NEW.source_run_id, NEW.fingerprint, NEW.fingerprint_version, NEW.source_amount_snapshot, NEW.voucher_key, NEW.ledger_key, NEW.site_code,
               NEW.original_group, NEW.corrected_group, NEW.original_month, NEW.corrected_month)
           IS DISTINCT FROM
           ROW(OLD.request_id, OLD.source_entity, OLD.source_line_key, OLD.source_run_id, OLD.fingerprint, OLD.fingerprint_version, OLD.source_amount_snapshot, OLD.voucher_key, OLD.ledger_key, OLD.site_code,
               OLD.original_group, OLD.corrected_group, OLD.original_month, OLD.corrected_month) THEN
            RAISE EXCEPTION 'a submitted correction line cannot be changed; withdraw or reverse and create a new request' USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    IF NEW.line_id <> OLD.line_id OR NEW.created_at <> OLD.created_at THEN RAISE EXCEPTION 'line identity is immutable' USING ERRCODE = 'check_violation'; END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER correction_line_guard BEFORE INSERT OR UPDATE ON fpa_app.correction_line FOR EACH ROW EXECUTE FUNCTION fpa_app.correction_line_guard();
CREATE TRIGGER correction_line_no_delete BEFORE DELETE ON fpa_app.correction_line FOR EACH ROW EXECUTE FUNCTION fpa_app.forbid_mutation();

-- Request header: created as DRAFT, no direct status or stamp edits; reason, type and entity freeze at submission.
CREATE OR REPLACE FUNCTION fpa_app.correction_request_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        NEW.status := 'DRAFT'; NEW.submitted_at := NULL; NEW.approved_by := NULL; NEW.approved_at := NULL; NEW.activated_at := NULL;
        RETURN NEW;
    END IF;
    IF NEW.request_id <> OLD.request_id OR NEW.created_by <> OLD.created_by OR NEW.created_at <> OLD.created_at OR NEW.requested_by <> OLD.requested_by
       OR NEW.reversal_of_id IS DISTINCT FROM OLD.reversal_of_id THEN
        RAISE EXCEPTION 'identity columns of a correction request are immutable' USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.status <> 'DRAFT' AND (NEW.scope_type <> OLD.scope_type OR NEW.correction_type <> OLD.correction_type OR NEW.source_entity <> OLD.source_entity
                                  OR NEW.reason_code <> OLD.reason_code OR NEW.reason_text <> OLD.reason_text OR NEW.evidence_reference <> OLD.evidence_reference) THEN
        RAISE EXCEPTION 'a submitted correction request cannot be edited; withdraw it and create a new one' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER correction_request_guard BEFORE INSERT OR UPDATE ON fpa_app.correction_request FOR EACH ROW EXECUTE FUNCTION fpa_app.correction_request_guard();
CREATE TRIGGER correction_request_no_delete BEFORE DELETE ON fpa_app.correction_request FOR EACH ROW EXECUTE FUNCTION fpa_app.forbid_mutation();

CREATE TABLE fpa_app.correction_event (
    event_id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    request_id     uuid NOT NULL REFERENCES fpa_app.correction_request (request_id),
    seq            integer NOT NULL,
    event_type     text NOT NULL,
    from_status    text,
    to_status      text NOT NULL,
    actor_user_id  uuid NOT NULL REFERENCES fpa_app.app_user (user_id),
    comment        text,
    request_ref    text,
    at             timestamptz NOT NULL DEFAULT now(),
    UNIQUE (request_id, seq)
);
CREATE TRIGGER correction_event_append_only BEFORE UPDATE OR DELETE ON fpa_app.correction_event FOR EACH ROW EXECUTE FUNCTION fpa_app.forbid_mutation();

-- Gold entity -> period entity
CREATE OR REPLACE FUNCTION fpa_app.period_entity(p_source_entity text) RETURNS text LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE p_source_entity WHEN 'RETAIL' THEN 'SUBCO' WHEN 'VENTURES' THEN 'HOLDCO' END
$$;

-- event_type: CREATED, SUBMITTED, APPROVED, ACTIVATED, REJECTED, WITHDRAWN, VOIDED, REVERSAL_REQUESTED, REVERSAL_APPROVED, REVERSAL_REJECTED, SOURCE_CHANGED,
--             SOURCE_NOW_MATCHES, SOURCE_RECONFIRMED, COMMENTED
CREATE OR REPLACE FUNCTION fpa_app.correction_event_check() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r fpa_app.correction_request%ROWTYPE; single boolean; n integer; actor_role text; pe text; soft boolean; closed boolean;
BEGIN
    SELECT * INTO r FROM fpa_app.correction_request WHERE request_id = NEW.request_id FOR UPDATE;
    SELECT coalesce((SELECT value = 'on' FROM fpa_app.app_setting WHERE key = 'single_user_mode'), false) INTO single;
    SELECT role INTO actor_role FROM fpa_app.app_user WHERE user_id = NEW.actor_user_id;
    NEW.seq := coalesce((SELECT max(seq) FROM fpa_app.correction_event WHERE request_id = NEW.request_id), 0) + 1;
    IF NEW.event_type = 'CREATED' THEN
        IF NEW.seq <> 1 OR NEW.to_status <> 'DRAFT' THEN RAISE EXCEPTION 'CREATED must be the first event and leave the request in DRAFT'; END IF;
        RETURN NEW;
    END IF;
    IF NEW.event_type = 'COMMENTED' THEN
        NEW.from_status := r.status; NEW.to_status := r.status;
        RETURN NEW;
    END IF;
    NEW.from_status := r.status;
    IF NOT EXISTS (SELECT 1 FROM fpa_app.correction_transition t WHERE t.from_status = r.status AND t.to_status = NEW.to_status AND t.event_type = NEW.event_type) THEN
        RAISE EXCEPTION 'correction % cannot go from % to % by %', r.request_id, r.status, NEW.to_status, NEW.event_type USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.event_type IN ('REJECTED', 'VOIDED', 'REVERSAL_REQUESTED', 'REVERSAL_REJECTED', 'SOURCE_RECONFIRMED') AND length(btrim(coalesce(NEW.comment, ''))) < 10 THEN
        RAISE EXCEPTION '% needs a reason of at least 10 characters', NEW.event_type USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.event_type = 'SUBMITTED' THEN
        SELECT count(*) INTO n FROM fpa_app.correction_line WHERE request_id = r.request_id;
        IF n = 0 THEN RAISE EXCEPTION 'a correction needs at least one line before it is submitted' USING ERRCODE = 'check_violation'; END IF;
        IF r.scope_type = 'LINE' AND n <> 1 THEN RAISE EXCEPTION 'a LINE correction has exactly one line' USING ERRCODE = 'check_violation'; END IF;
    END IF;
    IF NEW.event_type IN ('APPROVED', 'REVERSAL_APPROVED') AND NEW.actor_user_id = r.requested_by AND NOT single THEN
        RAISE EXCEPTION 'the requester of a correction cannot approve it (maker-checker)' USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF NEW.event_type IN ('APPROVED', 'ACTIVATED', 'REVERSAL_APPROVED') THEN
        pe := fpa_app.period_entity(r.source_entity);
        -- both the original and the corrected month must be writable; a SOFT_CLOSED month needs a controller or admin approver
        SELECT bool_or(NOT fpa_app.period_is_writable(pe, m)) INTO closed
        FROM (SELECT original_month AS m FROM fpa_app.correction_line WHERE request_id = r.request_id
              UNION SELECT corrected_month FROM fpa_app.correction_line WHERE request_id = r.request_id AND corrected_month IS NOT NULL) x;
        IF closed THEN RAISE EXCEPTION 'a month touched by this correction is closed for %; a controller must reopen it first', pe USING ERRCODE = 'check_violation'; END IF;
        SELECT EXISTS (SELECT 1 FROM fpa_app.reporting_period_status s
                       WHERE s.entity = pe AND s.status = 'SOFT_CLOSED' AND s.period IN (SELECT original_month FROM fpa_app.correction_line WHERE request_id = r.request_id
                                                                                          UNION SELECT corrected_month FROM fpa_app.correction_line WHERE request_id = r.request_id AND corrected_month IS NOT NULL)) INTO soft;
        IF soft AND NEW.event_type = 'APPROVED' AND coalesce(actor_role, '') NOT IN ('controller', 'admin') THEN
            RAISE EXCEPTION 'a month touched by this correction is soft-closed; a controller must approve it' USING ERRCODE = 'insufficient_privilege';
        END IF;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER correction_event_check BEFORE INSERT ON fpa_app.correction_event FOR EACH ROW EXECUTE FUNCTION fpa_app.correction_event_check();

-- Moves the projection and switches the line overlay flags on at ACTIVE and off when the overlay stops applying. SECURITY DEFINER with a pinned search path.
-- A second ACTIVE correction on the same line and attribute fails here on the partial unique indexes: conflicts are detected at activation, not later.
CREATE OR REPLACE FUNCTION fpa_app.correction_event_apply() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = fpa_app, pg_temp AS $$
BEGIN
    UPDATE fpa_app.correction_request SET status = NEW.to_status,
        submitted_at = CASE WHEN NEW.event_type = 'SUBMITTED' THEN NEW.at ELSE submitted_at END,
        approved_by  = CASE WHEN NEW.event_type = 'APPROVED' THEN NEW.actor_user_id ELSE approved_by END,
        approved_at  = CASE WHEN NEW.event_type = 'APPROVED' THEN NEW.at ELSE approved_at END,
        activated_at = CASE WHEN NEW.event_type = 'ACTIVATED' THEN NEW.at ELSE activated_at END
    WHERE request_id = NEW.request_id;
    IF NEW.to_status = 'ACTIVE' AND NEW.event_type IN ('ACTIVATED', 'SOURCE_RECONFIRMED') THEN
        UPDATE fpa_app.correction_line SET group_active = (corrected_group IS NOT NULL), month_active = (corrected_month IS NOT NULL) WHERE request_id = NEW.request_id;
    ELSIF NEW.to_status IN ('REVERSED', 'SUPERSEDED_BY_SOURCE', 'SOURCE_REVIEW_REQUIRED', 'REJECTED', 'WITHDRAWN') THEN
        UPDATE fpa_app.correction_line SET group_active = false, month_active = false WHERE request_id = NEW.request_id;
    END IF;
    RETURN NULL;
END $$;
CREATE TRIGGER correction_event_apply AFTER INSERT ON fpa_app.correction_event FOR EACH ROW
    WHEN (NEW.event_type NOT IN ('CREATED', 'COMMENTED')) EXECUTE FUNCTION fpa_app.correction_event_apply();

-- What the engine reads: line key plus the corrected group and month, nothing else. No amount leaves the app schema; the engine takes the amount from gold_fpa.
CREATE VIEW fpa_app.v_correction_overlay AS
    SELECT l.source_entity, l.source_line_key, CASE WHEN l.group_active THEN l.corrected_group END AS corrected_group, CASE WHEN l.month_active THEN l.corrected_month END AS corrected_month,
           l.request_id, l.line_id, r.activated_at, l.fingerprint, l.fingerprint_version
    FROM fpa_app.correction_line l JOIN fpa_app.correction_request r USING (request_id)
    WHERE r.status IN ('ACTIVE', 'REVERSAL_REQUESTED') AND (l.group_active OR l.month_active);

GRANT INSERT ON fpa_app.correction_request, fpa_app.correction_line TO fpa_workflow_app;
GRANT UPDATE (reason_code, reason_text, evidence_reference, scope_type, correction_type) ON fpa_app.correction_request TO fpa_workflow_app;
GRANT UPDATE (source_state) ON fpa_app.correction_line TO fpa_workflow_app;
GRANT SELECT ON fpa_app.v_correction_overlay TO fpa_workflow_app;
