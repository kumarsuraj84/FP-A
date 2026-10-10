-- fpa_app 011: a new source fix candidate always starts OPEN and unvalidated, whatever the insert says; its identity columns never change.
CREATE OR REPLACE FUNCTION fpa_app.source_fix_candidate_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        NEW.status := 'OPEN'; NEW.post_fix_validation := 'NOT_VALIDATED'; NEW.source_fix_date := NULL;
        RETURN NEW;
    END IF;
    IF NEW.candidate_id <> OLD.candidate_id OR NEW.pattern_key <> OLD.pattern_key OR NEW.issue_type <> OLD.issue_type OR NEW.subject_key <> OLD.subject_key OR NEW.created_at <> OLD.created_at
       OR NEW.entity IS DISTINCT FROM OLD.entity OR NEW.from_value IS DISTINCT FROM OLD.from_value OR NEW.to_value IS DISTINCT FROM OLD.to_value THEN
        RAISE EXCEPTION 'identity columns of a source fix candidate are immutable' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER source_fix_candidate_guard BEFORE INSERT OR UPDATE ON fpa_app.source_fix_candidate FOR EACH ROW EXECUTE FUNCTION fpa_app.source_fix_candidate_guard();
CREATE TRIGGER source_fix_candidate_no_delete BEFORE DELETE ON fpa_app.source_fix_candidate FOR EACH ROW EXECUTE FUNCTION fpa_app.forbid_mutation();
