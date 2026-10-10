-- fpa_app 007: a recurring template records whether its amount is a COST (reduces profit) or INCOME (raises profit). A FIXED amount is stored signed in the line sign
-- as before; a RATE template has no amount, so the effect is what gives its generated rows their sign.
ALTER TABLE fpa_app.adjustment_template ADD COLUMN effect text NOT NULL DEFAULT 'COST' CHECK (effect IN ('COST', 'INCOME'));
ALTER TABLE fpa_app.adjustment_template ADD CONSTRAINT adjustment_template_effect_sign CHECK (basis_type = 'RATE' OR (effect = 'COST') = (fixed_amount_rupees < 0));
CREATE OR REPLACE FUNCTION fpa_app.template_effect_freeze() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.effect <> OLD.effect THEN RAISE EXCEPTION 'the effect of a template cannot change' USING ERRCODE = 'check_violation'; END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER adjustment_template_effect_freeze BEFORE UPDATE ON fpa_app.adjustment_template FOR EACH ROW EXECUTE FUNCTION fpa_app.template_effect_freeze();
