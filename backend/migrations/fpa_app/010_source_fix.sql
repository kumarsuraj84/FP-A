-- fpa_app 010: Source Fix Candidate queue. Recurring corrections and recurring mapping changes are a signal that something upstream is wrong. The queue ranks them (recurrence x
-- materiality x breadth) for the extraction / data team. It is ADVISORY ONLY: nothing here can change a mapping, a correction or any finance data. The data team records that a
-- source fix was implemented, and the platform checks afterwards whether the pattern really stopped (post_fix_validation). The originating correction and mapping ids are kept.

CREATE TABLE fpa_app.source_fix_candidate (
    candidate_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    pattern_key         text NOT NULL,               -- hash of issue type, entity, subject and the from/to pair; one live candidate per pattern
    issue_type          text NOT NULL CHECK (issue_type IN ('RECURRING_GROUP_RECLASS', 'RECURRING_MONTH_SHIFT', 'RECURRING_MAPPING_CHANGE')),
    entity              text CHECK (entity IN ('RETAIL', 'VENTURES')),
    subject_key         text NOT NULL,               -- ledger code (reclass) or the mapping key
    subject_name        text,
    from_value          text,
    to_value            text,
    correction_count    integer NOT NULL DEFAULT 0,
    line_count          integer NOT NULL DEFAULT 0,
    site_count          integer NOT NULL DEFAULT 0,
    months_affected     integer NOT NULL DEFAULT 0,
    consecutive_months  integer NOT NULL DEFAULT 0,
    cumulative_amount_cr numeric(20, 4) NOT NULL DEFAULT 0,
    first_seen          date,
    last_seen           date,
    score               numeric(5, 2) NOT NULL DEFAULT 0 CHECK (score BETWEEN 0 AND 100),
    recommended_fix     text NOT NULL,
    origin_ids          jsonb NOT NULL DEFAULT '[]'::jsonb,
    threshold_version   text NOT NULL,
    status              text NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'ACKNOWLEDGED', 'FIX_IMPLEMENTED', 'VALIDATED', 'STILL_RECURRING', 'DISMISSED')),
    finance_owner       text,
    data_owner          text,
    source_fix_date     date,
    post_fix_validation text NOT NULL DEFAULT 'NOT_VALIDATED' CHECK (post_fix_validation IN ('NOT_VALIDATED', 'PENDING', 'PASSED', 'FAILED')),
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX source_fix_live_uq ON fpa_app.source_fix_candidate (pattern_key) WHERE status NOT IN ('VALIDATED', 'DISMISSED');
CREATE INDEX source_fix_rank_ix ON fpa_app.source_fix_candidate (status, score DESC);

CREATE TABLE fpa_app.source_fix_transition (
    from_status text NOT NULL,
    to_status   text NOT NULL,
    event_type  text NOT NULL,
    PRIMARY KEY (from_status, to_status, event_type)
);
INSERT INTO fpa_app.source_fix_transition VALUES
    ('OPEN', 'ACKNOWLEDGED', 'ACKNOWLEDGED'), ('OPEN', 'FIX_IMPLEMENTED', 'FIX_IMPLEMENTED'), ('ACKNOWLEDGED', 'FIX_IMPLEMENTED', 'FIX_IMPLEMENTED'), ('STILL_RECURRING', 'FIX_IMPLEMENTED', 'FIX_IMPLEMENTED'),
    ('FIX_IMPLEMENTED', 'VALIDATED', 'VALIDATED'), ('FIX_IMPLEMENTED', 'STILL_RECURRING', 'VALIDATION_FAILED'),
    ('OPEN', 'DISMISSED', 'DISMISSED'), ('ACKNOWLEDGED', 'DISMISSED', 'DISMISSED'), ('STILL_RECURRING', 'DISMISSED', 'DISMISSED');

CREATE TABLE fpa_app.source_fix_event (
    event_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    candidate_id  uuid NOT NULL REFERENCES fpa_app.source_fix_candidate (candidate_id),
    seq           integer NOT NULL,
    event_type    text NOT NULL,
    from_status   text,
    to_status     text NOT NULL,
    actor_user_id uuid REFERENCES fpa_app.app_user (user_id),
    actor_label   text,
    comment       text,
    fix_date      date,
    at            timestamptz NOT NULL DEFAULT now(),
    UNIQUE (candidate_id, seq),
    CHECK (actor_user_id IS NOT NULL OR actor_label = 'system')
);
CREATE TRIGGER source_fix_event_append_only BEFORE UPDATE OR DELETE ON fpa_app.source_fix_event FOR EACH ROW EXECUTE FUNCTION fpa_app.forbid_mutation();

CREATE OR REPLACE FUNCTION fpa_app.source_fix_event_check() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = fpa_app, pg_temp AS $$
DECLARE c fpa_app.source_fix_candidate%ROWTYPE; arole text;
BEGIN
    SELECT * INTO c FROM fpa_app.source_fix_candidate WHERE candidate_id = NEW.candidate_id FOR UPDATE;
    NEW.seq := coalesce((SELECT max(seq) FROM fpa_app.source_fix_event WHERE candidate_id = NEW.candidate_id), 0) + 1;
    IF NEW.event_type = 'DETECTED' THEN
        IF NEW.seq <> 1 OR NEW.to_status <> 'OPEN' THEN RAISE EXCEPTION 'DETECTED must be the first event and leave the candidate OPEN'; END IF;
        RETURN NEW;
    END IF;
    IF NEW.event_type IN ('COMMENTED', 'REFRESHED') THEN
        NEW.from_status := c.status; NEW.to_status := c.status;
        RETURN NEW;
    END IF;
    NEW.from_status := c.status;
    IF NOT EXISTS (SELECT 1 FROM fpa_app.source_fix_transition t WHERE t.from_status = c.status AND t.to_status = NEW.to_status AND t.event_type = NEW.event_type) THEN
        RAISE EXCEPTION 'candidate % cannot go from % to % by %', c.candidate_id, c.status, NEW.to_status, NEW.event_type USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.actor_user_id IS NOT NULL THEN
        SELECT role INTO arole FROM fpa_app.app_user WHERE user_id = NEW.actor_user_id AND active;
        IF arole IS NULL OR arole = 'viewer' THEN RAISE EXCEPTION 'the actor cannot change a source fix candidate' USING ERRCODE = 'insufficient_privilege'; END IF;
    ELSIF NEW.event_type NOT IN ('VALIDATED', 'VALIDATION_FAILED') THEN
        RAISE EXCEPTION 'only the validation check may act as the system' USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF NEW.event_type = 'FIX_IMPLEMENTED' AND NEW.fix_date IS NULL THEN RAISE EXCEPTION 'FIX_IMPLEMENTED needs the date of the source fix' USING ERRCODE = 'check_violation'; END IF;
    IF NEW.event_type = 'DISMISSED' AND length(btrim(coalesce(NEW.comment, ''))) < 10 THEN RAISE EXCEPTION 'DISMISSED needs a reason of at least 10 characters' USING ERRCODE = 'check_violation'; END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER source_fix_event_check BEFORE INSERT ON fpa_app.source_fix_event FOR EACH ROW EXECUTE FUNCTION fpa_app.source_fix_event_check();

CREATE OR REPLACE FUNCTION fpa_app.source_fix_event_apply() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = fpa_app, pg_temp AS $$
BEGIN
    UPDATE fpa_app.source_fix_candidate SET status = NEW.to_status, updated_at = now(),
        source_fix_date = CASE WHEN NEW.event_type = 'FIX_IMPLEMENTED' THEN NEW.fix_date ELSE source_fix_date END,
        post_fix_validation = CASE NEW.event_type WHEN 'FIX_IMPLEMENTED' THEN 'PENDING' WHEN 'VALIDATED' THEN 'PASSED' WHEN 'VALIDATION_FAILED' THEN 'FAILED' ELSE post_fix_validation END
    WHERE candidate_id = NEW.candidate_id;
    RETURN NULL;
END $$;
CREATE TRIGGER source_fix_event_apply AFTER INSERT ON fpa_app.source_fix_event FOR EACH ROW
    WHEN (NEW.event_type NOT IN ('DETECTED', 'COMMENTED', 'REFRESHED')) EXECUTE FUNCTION fpa_app.source_fix_event_apply();

-- the measures of a candidate and its owners may be refreshed; its identity, origin ids and status may not be written directly
GRANT INSERT ON fpa_app.source_fix_candidate TO fpa_workflow_app;
GRANT UPDATE (subject_name, correction_count, line_count, site_count, months_affected, consecutive_months, cumulative_amount_cr, first_seen, last_seen, score, recommended_fix, origin_ids,
              threshold_version, finance_owner, data_owner, updated_at) ON fpa_app.source_fix_candidate TO fpa_workflow_app;
