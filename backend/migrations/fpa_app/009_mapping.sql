-- fpa_app 009: Mapping Governance. The rules that classify finance data for management reporting become versioned, effective-dated and approved:
--   LEDGER_GROUP   ledger name -> management group           (attrs: major_group, category, location_rule, note)
--   SITE_LOCATION  site code   -> location type STORES | DC | HO (attrs: note)
-- A standing rule is NOT a correction: a correction fixes one historical line; a mapping changes the rule from an effective month. No in-place edit of an ACTIVE rule: a change is a
-- new version that supersedes the old one (the old one ends the month before). The engine resolves a rule by month, so history stays reproducible.
-- Lifecycle DRAFT -> SUBMITTED -> APPROVED -> ACTIVE -> RETIRED (REJECTED, WITHDRAWN). The one-time baseline from the legacy CSV files is imported as ACTIVE version 1 (event IMPORTED,
-- administrator only, source legacy_csv_import).

CREATE TABLE fpa_app.mapping_transition (
    from_status text NOT NULL,
    to_status   text NOT NULL,
    event_type  text NOT NULL,
    PRIMARY KEY (from_status, to_status, event_type)
);
INSERT INTO fpa_app.mapping_transition VALUES
    ('DRAFT', 'SUBMITTED', 'SUBMITTED'), ('DRAFT', 'WITHDRAWN', 'WITHDRAWN'),
    ('SUBMITTED', 'APPROVED', 'APPROVED'), ('SUBMITTED', 'REJECTED', 'REJECTED'), ('SUBMITTED', 'WITHDRAWN', 'WITHDRAWN'),
    ('APPROVED', 'ACTIVE', 'ACTIVATED'), ('APPROVED', 'WITHDRAWN', 'VOIDED'),
    ('DRAFT', 'ACTIVE', 'IMPORTED'),
    ('ACTIVE', 'RETIRED', 'RETIRED');

CREATE TABLE fpa_app.mapping_rule (
    mapping_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    domain          text NOT NULL CHECK (domain IN ('LEDGER_GROUP', 'SITE_LOCATION')),
    source_key      text NOT NULL CHECK (length(btrim(source_key)) > 0),
    mapped_value    text NOT NULL CHECK (length(btrim(mapped_value)) > 0),
    attrs           jsonb NOT NULL DEFAULT '{}'::jsonb,
    effective_from  date NOT NULL CHECK (effective_from = date_trunc('month', effective_from)::date),
    effective_to    date CHECK (effective_to IS NULL OR (effective_to = date_trunc('month', effective_to)::date AND effective_to >= effective_from)),
    version         integer NOT NULL DEFAULT 1 CHECK (version >= 1),
    supersedes_id   uuid REFERENCES fpa_app.mapping_rule (mapping_id),
    status          text NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT', 'SUBMITTED', 'APPROVED', 'ACTIVE', 'REJECTED', 'WITHDRAWN', 'RETIRED')),
    source          text NOT NULL DEFAULT 'app' CHECK (source IN ('app', 'legacy_csv_import')),
    reason          text NOT NULL CHECK (length(btrim(reason)) >= 10),
    evidence_ref    text,
    requested_by    uuid NOT NULL REFERENCES fpa_app.app_user (user_id),
    requested_at    timestamptz NOT NULL DEFAULT now(),
    approved_by     uuid REFERENCES fpa_app.app_user (user_id),
    approved_at     timestamptz,
    activated_at    timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now(),
    CHECK (domain <> 'SITE_LOCATION' OR mapped_value IN ('STORES', 'DC', 'HO'))
);
CREATE INDEX mapping_rule_lookup_ix ON fpa_app.mapping_rule (domain, source_key, effective_from) WHERE status IN ('ACTIVE', 'RETIRED');
CREATE UNIQUE INDEX mapping_rule_version_uq ON fpa_app.mapping_rule (domain, source_key, version) WHERE status NOT IN ('REJECTED', 'WITHDRAWN');
-- one pending proposal per key at a time
CREATE UNIQUE INDEX mapping_rule_pending_uq ON fpa_app.mapping_rule (domain, source_key) WHERE status IN ('DRAFT', 'SUBMITTED', 'APPROVED');

CREATE OR REPLACE FUNCTION fpa_app.mapping_rule_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        NEW.status := 'DRAFT'; NEW.approved_by := NULL; NEW.approved_at := NULL; NEW.activated_at := NULL; NEW.effective_to := NULL;
        RETURN NEW;
    END IF;
    IF NEW.mapping_id <> OLD.mapping_id OR NEW.domain <> OLD.domain OR NEW.source_key <> OLD.source_key OR NEW.requested_by <> OLD.requested_by OR NEW.created_at <> OLD.created_at
       OR NEW.supersedes_id IS DISTINCT FROM OLD.supersedes_id OR NEW.version <> OLD.version OR NEW.source <> OLD.source THEN
        RAISE EXCEPTION 'identity columns of a mapping rule are immutable' USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.status <> 'DRAFT' AND (NEW.mapped_value <> OLD.mapped_value OR NEW.effective_from <> OLD.effective_from OR NEW.attrs <> OLD.attrs OR NEW.reason <> OLD.reason) THEN
        RAISE EXCEPTION 'a submitted mapping cannot be edited: propose a new version' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER mapping_rule_guard BEFORE INSERT OR UPDATE ON fpa_app.mapping_rule FOR EACH ROW EXECUTE FUNCTION fpa_app.mapping_rule_guard();
CREATE TRIGGER mapping_rule_no_delete BEFORE DELETE ON fpa_app.mapping_rule FOR EACH ROW EXECUTE FUNCTION fpa_app.forbid_mutation();

CREATE TABLE fpa_app.mapping_event (
    event_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    mapping_id    uuid NOT NULL REFERENCES fpa_app.mapping_rule (mapping_id),
    seq           integer NOT NULL,
    event_type    text NOT NULL,
    from_status   text,
    to_status     text NOT NULL,
    actor_user_id uuid NOT NULL REFERENCES fpa_app.app_user (user_id),
    comment       text,
    at            timestamptz NOT NULL DEFAULT now(),
    UNIQUE (mapping_id, seq)
);
CREATE TRIGGER mapping_event_append_only BEFORE UPDATE OR DELETE ON fpa_app.mapping_event FOR EACH ROW EXECUTE FUNCTION fpa_app.forbid_mutation();

-- Validates the transition, maker-checker, reasons and (at activation) that the new rule does not overlap an ACTIVE one of the same key except the version it supersedes.
CREATE OR REPLACE FUNCTION fpa_app.mapping_event_check() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = fpa_app, pg_temp AS $$
DECLARE r fpa_app.mapping_rule%ROWTYPE; single boolean; arole text;
BEGIN
    SELECT * INTO r FROM fpa_app.mapping_rule WHERE mapping_id = NEW.mapping_id FOR UPDATE;
    SELECT role INTO arole FROM fpa_app.app_user WHERE user_id = NEW.actor_user_id AND active;
    SELECT coalesce((SELECT value = 'on' FROM fpa_app.app_setting WHERE key = 'single_user_mode'), false) INTO single;
    NEW.seq := coalesce((SELECT max(seq) FROM fpa_app.mapping_event WHERE mapping_id = NEW.mapping_id), 0) + 1;
    IF NEW.event_type = 'CREATED' THEN
        IF NEW.seq <> 1 OR NEW.to_status <> 'DRAFT' THEN RAISE EXCEPTION 'CREATED must be the first event and leave the rule in DRAFT'; END IF;
        RETURN NEW;
    END IF;
    IF NEW.event_type = 'COMMENTED' THEN
        NEW.from_status := r.status; NEW.to_status := r.status;
        RETURN NEW;
    END IF;
    NEW.from_status := r.status;
    IF NOT EXISTS (SELECT 1 FROM fpa_app.mapping_transition t WHERE t.from_status = r.status AND t.to_status = NEW.to_status AND t.event_type = NEW.event_type) THEN
        RAISE EXCEPTION 'mapping % cannot go from % to % by %', r.mapping_id, r.status, NEW.to_status, NEW.event_type USING ERRCODE = 'check_violation';
    END IF;
    IF arole IS NULL OR arole = 'viewer' THEN RAISE EXCEPTION 'the actor cannot change mappings' USING ERRCODE = 'insufficient_privilege'; END IF;
    IF NEW.event_type = 'IMPORTED' THEN
        IF r.source <> 'legacy_csv_import' OR arole <> 'admin' THEN RAISE EXCEPTION 'only an administrator imports the legacy baseline' USING ERRCODE = 'insufficient_privilege'; END IF;
    END IF;
    IF NEW.event_type IN ('REJECTED', 'VOIDED', 'RETIRED') AND length(btrim(coalesce(NEW.comment, ''))) < 10 THEN
        RAISE EXCEPTION '% needs a reason of at least 10 characters', NEW.event_type USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.event_type = 'APPROVED' THEN
        IF NOT (arole IN ('finance_reviewer', 'controller', 'admin') OR (single AND arole = 'fpa_manager')) THEN
            RAISE EXCEPTION 'only a finance reviewer or above approves a mapping' USING ERRCODE = 'insufficient_privilege';
        END IF;
        IF NEW.actor_user_id = r.requested_by AND NOT single THEN
            RAISE EXCEPTION 'the requester of a mapping cannot approve it (maker-checker)' USING ERRCODE = 'insufficient_privilege';
        END IF;
    END IF;
    IF NEW.event_type = 'ACTIVATED' THEN
        IF NOT (arole IN ('finance_reviewer', 'controller', 'admin') OR (single AND arole = 'fpa_manager')) THEN
            RAISE EXCEPTION 'only a finance reviewer or above activates a mapping' USING ERRCODE = 'insufficient_privilege';
        END IF;
        IF EXISTS (SELECT 1 FROM fpa_app.mapping_rule o WHERE o.domain = r.domain AND o.source_key = r.source_key AND o.status = 'ACTIVE' AND o.mapping_id <> r.mapping_id
                     AND o.mapping_id IS DISTINCT FROM r.supersedes_id AND (o.effective_to IS NULL OR o.effective_to >= r.effective_from)) THEN
            RAISE EXCEPTION 'an active mapping already covers this key from that month; propose it as a new version of that rule' USING ERRCODE = 'check_violation';
        END IF;
        IF r.supersedes_id IS NOT NULL AND r.effective_from <= (SELECT effective_from FROM fpa_app.mapping_rule WHERE mapping_id = r.supersedes_id) THEN
            RAISE EXCEPTION 'a new version must start after the version it supersedes' USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER mapping_event_check BEFORE INSERT ON fpa_app.mapping_event FOR EACH ROW EXECUTE FUNCTION fpa_app.mapping_event_check();

CREATE OR REPLACE FUNCTION fpa_app.mapping_event_apply() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = fpa_app, pg_temp AS $$
DECLARE r fpa_app.mapping_rule%ROWTYPE;
BEGIN
    UPDATE fpa_app.mapping_rule SET status = NEW.to_status,
        approved_by = CASE WHEN NEW.event_type = 'APPROVED' THEN NEW.actor_user_id ELSE approved_by END,
        approved_at = CASE WHEN NEW.event_type = 'APPROVED' THEN NEW.at ELSE approved_at END,
        activated_at = CASE WHEN NEW.event_type IN ('ACTIVATED', 'IMPORTED') THEN NEW.at ELSE activated_at END,
        effective_to = CASE WHEN NEW.event_type = 'RETIRED' AND effective_to IS NULL THEN date_trunc('month', NEW.at)::date ELSE effective_to END
    WHERE mapping_id = NEW.mapping_id RETURNING * INTO r;
    -- activating a new version ends the version it supersedes the month before
    IF NEW.event_type = 'ACTIVATED' AND r.supersedes_id IS NOT NULL THEN
        UPDATE fpa_app.mapping_rule SET effective_to = (r.effective_from - interval '1 month')::date WHERE mapping_id = r.supersedes_id;
        INSERT INTO fpa_app.mapping_event (mapping_id, event_type, to_status, actor_user_id, comment)
            VALUES (r.supersedes_id, 'RETIRED', 'RETIRED', NEW.actor_user_id, 'Superseded by version ' || r.version || ' from ' || to_char(r.effective_from, 'YYYY-MM') || '.')
        ;
    END IF;
    RETURN NULL;
END $$;
CREATE TRIGGER mapping_event_apply AFTER INSERT ON fpa_app.mapping_event FOR EACH ROW WHEN (NEW.event_type NOT IN ('CREATED', 'COMMENTED')) EXECUTE FUNCTION fpa_app.mapping_event_apply();

GRANT INSERT ON fpa_app.mapping_rule TO fpa_workflow_app;
GRANT UPDATE (mapped_value, attrs, effective_from, reason, evidence_ref) ON fpa_app.mapping_rule TO fpa_workflow_app;
