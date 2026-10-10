-- fpa_app 001: identity, audit trail, reporting period status. Run as fpa_app_migrator after SET ROLE fpa_app_owner.
-- Principles: append-only event tables (no UPDATE/DELETE, enforced by trigger); projection tables carry current state and may be UPDATEd only by the app login
-- through named actions; every write names an actor; nothing here copies finance amounts from gold_fpa.

CREATE OR REPLACE FUNCTION fpa_app.forbid_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% on %.% is not allowed: the table is append-only', TG_OP, TG_TABLE_SCHEMA, TG_TABLE_NAME USING ERRCODE = 'insufficient_privilege';
END $$;

-- Freezes columns on a projection table: trigger args are the immutable column names; any change to one of them is refused.
CREATE OR REPLACE FUNCTION fpa_app.freeze_columns() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE c text;
BEGIN
    FOREACH c IN ARRAY TG_ARGV LOOP
        IF to_jsonb(NEW) -> c IS DISTINCT FROM to_jsonb(OLD) -> c THEN
            RAISE EXCEPTION 'column % of %.% cannot be changed after creation; reverse and create a new record', c, TG_TABLE_SCHEMA, TG_TABLE_NAME USING ERRCODE = 'check_violation';
        END IF;
    END LOOP;
    RETURN NEW;
END $$;

CREATE TABLE fpa_app.schema_migration (
    version     text PRIMARY KEY,
    checksum    text NOT NULL,
    applied_at  timestamptz NOT NULL DEFAULT now()
);

-- Users: email + password, created and managed by an administrator only (no self sign-up). Password hash is argon2id or bcrypt, never the password.
CREATE TABLE fpa_app.app_user (
    user_id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email                text NOT NULL CHECK (email = lower(email) AND email LIKE '%_@_%'),
    display_name         text NOT NULL,
    role                 text NOT NULL CHECK (role IN ('viewer', 'fpa_manager', 'finance_reviewer', 'controller', 'admin')),
    password_hash        text NOT NULL,
    must_change_password boolean NOT NULL DEFAULT true,
    active               boolean NOT NULL DEFAULT true,
    failed_attempts      integer NOT NULL DEFAULT 0,
    locked_until         timestamptz,
    last_login_at        timestamptz,
    created_by           uuid REFERENCES fpa_app.app_user (user_id),
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX app_user_email_uq ON fpa_app.app_user (email);
CREATE TRIGGER app_user_freeze BEFORE UPDATE ON fpa_app.app_user FOR EACH ROW EXECUTE FUNCTION fpa_app.freeze_columns('user_id', 'email', 'created_by', 'created_at');

CREATE TABLE fpa_app.app_session (
    session_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      uuid NOT NULL REFERENCES fpa_app.app_user (user_id),
    token_hash   text NOT NULL,                 -- sha256 of the opaque cookie token; the token itself is never stored
    created_at   timestamptz NOT NULL DEFAULT now(),
    expires_at   timestamptz NOT NULL,
    revoked_at   timestamptz,
    client_ip    text
);
CREATE UNIQUE INDEX app_session_token_uq ON fpa_app.app_session (token_hash);
CREATE INDEX app_session_user_ix ON fpa_app.app_session (user_id) WHERE revoked_at IS NULL;
CREATE TRIGGER app_session_freeze BEFORE UPDATE ON fpa_app.app_session FOR EACH ROW EXECUTE FUNCTION fpa_app.freeze_columns('session_id', 'user_id', 'token_hash', 'created_at', 'expires_at');

-- One audit trail for everything the app does that matters: logins, user administration, every write on the three domains.
CREATE TABLE fpa_app.audit_event (
    event_id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    at             timestamptz NOT NULL DEFAULT now(),
    actor_user_id  uuid REFERENCES fpa_app.app_user (user_id),
    actor_email    text NOT NULL,               -- kept as text so the trail survives any later user change
    action         text NOT NULL,
    object_type    text NOT NULL,
    object_id      text NOT NULL,
    detail         jsonb NOT NULL DEFAULT '{}'::jsonb,
    client_ip      text
);
CREATE INDEX audit_event_object_ix ON fpa_app.audit_event (object_type, object_id, event_id);
CREATE INDEX audit_event_actor_ix ON fpa_app.audit_event (actor_user_id, at);
CREATE TRIGGER audit_event_append_only BEFORE UPDATE OR DELETE ON fpa_app.audit_event FOR EACH ROW EXECUTE FUNCTION fpa_app.forbid_mutation();

-- Reporting calendar. A month moves OPEN -> SOFT_CLOSED -> MANAGEMENT_CLOSED -> FINAL_CLOSED; REOPENED is entered only by a controller with an event and a reason.
CREATE TABLE fpa_app.reporting_period_status (
    period      date PRIMARY KEY CHECK (period = date_trunc('month', period)::date),
    status      text NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'SOFT_CLOSED', 'MANAGEMENT_CLOSED', 'FINAL_CLOSED', 'REOPENED')),
    changed_at  timestamptz NOT NULL DEFAULT now(),
    changed_by  uuid REFERENCES fpa_app.app_user (user_id)
);
CREATE TRIGGER reporting_period_freeze BEFORE UPDATE ON fpa_app.reporting_period_status FOR EACH ROW EXECUTE FUNCTION fpa_app.freeze_columns('period');

CREATE TABLE fpa_app.reporting_period_event (
    event_id     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    period       date NOT NULL REFERENCES fpa_app.reporting_period_status (period),
    from_status  text NOT NULL,
    to_status    text NOT NULL,
    actor_user_id uuid NOT NULL REFERENCES fpa_app.app_user (user_id),
    reason       text NOT NULL,
    at           timestamptz NOT NULL DEFAULT now(),
    CHECK (to_status <> 'REOPENED' OR length(btrim(reason)) >= 10)
);
CREATE TRIGGER reporting_period_event_append_only BEFORE UPDATE OR DELETE ON fpa_app.reporting_period_event FOR EACH ROW EXECUTE FUNCTION fpa_app.forbid_mutation();

-- A closed period refuses new money-moving records; used by the adjustment and correction triggers.
CREATE OR REPLACE FUNCTION fpa_app.period_is_writable(p date) RETURNS boolean LANGUAGE sql STABLE AS $$
    SELECT coalesce((SELECT status IN ('OPEN', 'SOFT_CLOSED', 'REOPENED') FROM fpa_app.reporting_period_status WHERE period = date_trunc('month', p)::date), true)
$$;

-- Projection tables the app login may UPDATE (event and audit tables stay INSERT / SELECT only).
GRANT UPDATE ON fpa_app.app_user, fpa_app.app_session, fpa_app.reporting_period_status TO fpa_workflow_app;
