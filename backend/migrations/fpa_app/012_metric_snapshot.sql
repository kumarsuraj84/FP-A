-- fpa_app 012: metric snapshots. The finance tables hold only the current position (creditors, till cash), so a trend needs the platform to remember its own aggregates. Each detection run
-- stores small aggregates (never party names, never rows) once per domain, metric, subject and as-of date. Append-only: a day is recorded once and never rewritten.

CREATE TABLE fpa_app.metric_snapshot (
    snapshot_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    domain      text NOT NULL CHECK (domain IN ('CREDITORS', 'CASH', 'BANK')),
    metric      text NOT NULL,
    subject_key text NOT NULL DEFAULT 'all',
    as_of       date NOT NULL,
    value       jsonb NOT NULL,
    taken_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (domain, metric, subject_key, as_of)
);
CREATE INDEX metric_snapshot_ix ON fpa_app.metric_snapshot (domain, metric, subject_key, as_of DESC);
CREATE TRIGGER metric_snapshot_append_only BEFORE UPDATE OR DELETE ON fpa_app.metric_snapshot FOR EACH ROW EXECUTE FUNCTION fpa_app.forbid_mutation();
