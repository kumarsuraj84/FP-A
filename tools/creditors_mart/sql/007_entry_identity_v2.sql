-- Entry identity v2 (migration 007). The first real entry staging run showed the register reusing (site, entry type, entry number) across creating warehouses and over
-- time (the identity is now site + type + number + creating site + entry date, entry_ref = sha256('v2|...')), so the old UNIQUE (run, site, type, number) on
-- entry.entry_identity would reject real entries. Uniqueness of an entry is carried by entry_ref (primary key, a hash of the full five-part identity).

DO $pre$
BEGIN
  IF to_regclass('entry.entry_identity') IS NULL THEN RAISE EXCEPTION 'apply migration 005 first'; END IF;
END
$pre$;

SET ROLE entry_owner;
DO $drop$
DECLARE c text;
BEGIN
  FOR c IN SELECT conname FROM pg_constraint
            WHERE conrelid = 'entry.entry_identity'::regclass AND contype = 'u'
              AND (SELECT array_agg(a.attname::text ORDER BY a.attname) FROM pg_attribute a WHERE a.attrelid = conrelid AND a.attnum = ANY (conkey))
                  = ARRAY['entry_no', 'entry_run_id', 'entry_type_short', 'site_code']
  LOOP
    EXECUTE format('ALTER TABLE entry.entry_identity DROP CONSTRAINT %I', c);
  END LOOP;
END
$drop$;
COMMENT ON COLUMN entry.entry_header.entry_ref IS 'sha256(''v2|site|type|number|creating site or <none>|entry date'') prefix: opaque, stable';
RESET ROLE;

INSERT INTO cred.schema_migration (version, description) VALUES
  ('007', 'entry identity v2: (site, type, number, creating site, date); the (site, type, number) uniqueness constraint is removed');
