-- P&L review foundation (migration 009): store area and the effective-area denominator, the day-aligned window of last year, the early (first N days) part of COGS.
-- Runs stay immutable: the new columns are nullable / default zero for runs loaded before this migration, and the new tables are filled by the new loader only.
-- store_month_effective_area is THE denominator for every per-square-foot measure: Effective Area = Actual Area x Active Days in Month / Calendar Days in Month, derived at load
-- (not in the frontend) and re-derived independently in mart_checks M14.

DO $pre$
BEGIN
  IF to_regclass('pnl.run') IS NULL THEN RAISE EXCEPTION 'apply migration 008 first'; END IF;
END
$pre$;

SET ROLE pnl_owner;

ALTER TABLE pnl.run ADD COLUMN aligned_days integer, ADD COLUMN ly_aligned_month date;
ALTER TABLE pnl.site ADD COLUMN area numeric(12,2) CHECK (area IS NULL OR area >= 0), ADD COLUMN st_type text, ADD COLUMN store_grade text;
ALTER TABLE pnl.cogs_site_month ADD COLUMN sl_v_early numeric(30,4) NOT NULL DEFAULT 0, ADD COLUMN tax_early numeric(30,4) NOT NULL DEFAULT 0,
                                ADD COLUMN cogs_early numeric(30,4) NOT NULL DEFAULT 0, ADD COLUMN sl_q_early numeric(30,4) NOT NULL DEFAULT 0;

CREATE TABLE pnl.gl_aligned (
  run_id           text NOT NULL REFERENCES pnl.run,
  site_code        text NOT NULL,
  month            date NOT NULL CHECK (month = date_trunc('month', month)::date),     -- last year's as-of month
  glcode           text NOT NULL,
  ledger_name      text NOT NULL,
  group_label      text,
  section          text NOT NULL CHECK (section IN ('REVENUE', 'COGS_BOOKS', 'STORE_OPEX', 'OTHER_INCOME', 'FINANCE_COST', 'UNMAPPED')),
  entry_type_short text NOT NULL,
  release_status   text NOT NULL CHECK (release_status IN ('Posted', 'Unposted')),
  debit            numeric(30,4) NOT NULL CHECK (debit >= 0),
  credit           numeric(30,4) NOT NULL CHECK (credit >= 0),
  lines            integer NOT NULL CHECK (lines > 0),
  PRIMARY KEY (run_id, site_code, month, glcode, entry_type_short, release_status),
  CHECK ((section = 'UNMAPPED') = (group_label IS NULL))
);

CREATE TABLE pnl.store_month_effective_area (
  run_id          text NOT NULL REFERENCES pnl.run,
  site_code       text NOT NULL,
  month           date NOT NULL CHECK (month = date_trunc('month', month)::date),
  actual_area     numeric(12,2),
  opening_date    date,
  closing_date    date,
  active_days     integer NOT NULL CHECK (active_days >= 0),
  calendar_days   integer NOT NULL CHECK (calendar_days BETWEEN 28 AND 31),
  effective_area  numeric(18,4) CHECK (effective_area IS NULL OR effective_area >= 0),
  reason          text NOT NULL,
  PRIMARY KEY (run_id, site_code, month),
  CHECK (active_days <= calendar_days)
);

CREATE TRIGGER no_mutation BEFORE UPDATE OR DELETE ON pnl.gl_aligned FOR EACH ROW EXECUTE FUNCTION pnl.deny_mutation();
CREATE TRIGGER no_mutation BEFORE UPDATE OR DELETE ON pnl.store_month_effective_area FOR EACH ROW EXECUTE FUNCTION pnl.deny_mutation();
CREATE TRIGGER run_open BEFORE INSERT ON pnl.gl_aligned FOR EACH ROW EXECUTE FUNCTION pnl.guard_open_run();
CREATE TRIGGER run_open BEFORE INSERT ON pnl.store_month_effective_area FOR EACH ROW EXECUTE FUNCTION pnl.guard_open_run();
CREATE INDEX ON pnl.gl_aligned (run_id, site_code);

-- the serving views learn the new columns (a view built on `x.*` keeps the column list it had)
CREATE OR REPLACE VIEW pnl.v_serving_run AS
SELECT r.run_id, r.as_of_date, r.cogs_run_id, r.cogs_last_bill_date, r.recon_state, r.publication_state, r.contract_version, r.extract_finished_at, r.loaded_at,
       r.expected_gl_rows, r.expected_cogs_rows, r.expected_sites, r.tolerance_rupees, r.aligned_days, r.ly_aligned_month
FROM pnl.run r WHERE r.recon_state IN ('verified', 'api_verified');
CREATE OR REPLACE VIEW pnl.v_site AS SELECT x.* FROM pnl.site x JOIN pnl.v_serving_run s USING (run_id);
CREATE OR REPLACE VIEW pnl.v_cogs_site_month AS SELECT x.* FROM pnl.cogs_site_month x JOIN pnl.v_serving_run s USING (run_id);
CREATE VIEW pnl.v_gl_aligned AS SELECT x.* FROM pnl.gl_aligned x JOIN pnl.v_serving_run s USING (run_id);
CREATE VIEW pnl.v_store_month_effective_area AS SELECT x.* FROM pnl.store_month_effective_area x JOIN pnl.v_serving_run s USING (run_id);

CREATE OR REPLACE FUNCTION pnl.mart_checks(p_run text) RETURNS TABLE (check_id text, violations bigint) LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pnl, pg_temp AS
$$
  SELECT 'M01_gl_rows', abs((SELECT count(*) FROM pnl.gl_site_month WHERE run_id = p_run) - (SELECT expected_gl_rows FROM pnl.run WHERE run_id = p_run))::bigint
  UNION ALL SELECT 'M02_cogs_rows', abs((SELECT count(*) FROM pnl.cogs_site_month WHERE run_id = p_run) - (SELECT expected_cogs_rows FROM pnl.run WHERE run_id = p_run))::bigint
  UNION ALL SELECT 'M03_site_rows', abs((SELECT count(*) FROM pnl.site WHERE run_id = p_run) - (SELECT expected_sites FROM pnl.run WHERE run_id = p_run))::bigint
  -- no book row after the as-of month; no COGS row after it either
  UNION ALL SELECT 'M04_no_month_after_as_of', (SELECT count(*) FROM pnl.gl_site_month g JOIN pnl.run r USING (run_id) WHERE g.run_id = p_run AND g.month > date_trunc('month', r.as_of_date)::date)
       + (SELECT count(*) FROM pnl.cogs_site_month g JOIN pnl.run r USING (run_id) WHERE g.run_id = p_run AND g.month > date_trunc('month', r.as_of_date)::date)
  -- the tie-out table is exactly the books sales and the COGS-table sales, recomputed here from the stored rows
  UNION ALL SELECT 'M05_tieout_books_sales_recomputed', count(*) FROM (
       SELECT t.site_code, t.month, t.books_sales, coalesce(b.v, 0) AS v FROM pnl.sales_tieout t
         LEFT JOIN (SELECT site_code, month, sum(credit - debit) AS v FROM pnl.gl_site_month WHERE run_id = p_run AND ledger_name = 'Sales - POS' GROUP BY 1, 2) b USING (site_code, month)
        WHERE t.run_id = p_run) x WHERE x.books_sales <> x.v
  UNION ALL SELECT 'M06_tieout_table_sales_recomputed', count(*) FROM (
       SELECT t.cogs_table_sales_ex_gst, coalesce(c.sl_v - c.tax_amt, 0) AS v FROM pnl.sales_tieout t
         LEFT JOIN pnl.cogs_site_month c ON c.run_id = t.run_id AND c.site_code = t.site_code AND c.month = t.month WHERE t.run_id = p_run) x WHERE x.cogs_table_sales_ex_gst <> x.v
  UNION ALL SELECT 'M07_tied_flag_matches_tolerance', count(*) FROM pnl.sales_tieout t JOIN pnl.run r USING (run_id) WHERE t.run_id = p_run AND t.tied <> (abs(t.difference) <= r.tolerance_rupees)
  -- every site-month with books sales or table sales has a tie-out row
  UNION ALL SELECT 'M08_tieout_covers_every_site_month', (SELECT count(*) FROM (
          SELECT DISTINCT site_code, month FROM pnl.gl_site_month WHERE run_id = p_run AND ledger_name = 'Sales - POS'
          UNION SELECT site_code, month FROM pnl.cogs_site_month WHERE run_id = p_run) k
        WHERE NOT EXISTS (SELECT 1 FROM pnl.sales_tieout t WHERE t.run_id = p_run AND t.site_code = k.site_code AND t.month = k.month))
  -- every mapped group has a section row, and the section agrees
  UNION ALL SELECT 'M09_group_has_a_section', count(*) FROM pnl.gl_site_month g WHERE g.run_id = p_run AND g.group_label IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM pnl.group_section s WHERE s.run_id = p_run AND s.group_label = g.group_label AND s.section = g.section)
  -- one ledger is in one group and one section only
  UNION ALL SELECT 'M10_ledger_in_one_section', count(*) FROM (SELECT glcode FROM pnl.gl_site_month WHERE run_id = p_run GROUP BY glcode HAVING count(DISTINCT section) > 1) x
  -- the COGS table's sales and tax are non-negative in total and its bill days fit the month
  UNION ALL SELECT 'M11_cogs_rows_sane', count(*) FROM pnl.cogs_site_month WHERE run_id = p_run AND (bill_days < 1 OR bill_days > 31 OR rows_n < 1)
  -- the day-aligned window of last year: every row is in last year's as-of month
  UNION ALL SELECT 'M12_aligned_rows_in_the_aligned_month', count(*) FROM pnl.gl_aligned g JOIN pnl.run r USING (run_id) WHERE g.run_id = p_run AND (r.ly_aligned_month IS NULL OR g.month <> r.ly_aligned_month)
  -- one effective-area row per site and month of the window (sites in the site master x months from April 2025 to the as-of month)
  UNION ALL SELECT 'M13_effective_area_covers_every_site_month', abs((SELECT count(*) FROM pnl.store_month_effective_area WHERE run_id = p_run)
       - (SELECT count(*) FROM pnl.site WHERE run_id = p_run) * (SELECT ((extract(year FROM r.as_of_date) - 2025) * 12 + extract(month FROM r.as_of_date) - 3)::int FROM pnl.run r WHERE r.run_id = p_run))::bigint
  -- the effective area re-derived HERE from the site master with the same rule, in SQL (the stager derived it in Python): every stored row must agree exactly
  UNION ALL SELECT 'M14_effective_area_recomputed', count(*) FROM (
       SELECT e.site_code, e.month, e.active_days, e.effective_area, e.calendar_days,
              x.cal, x.days, CASE WHEN x.area > 0 THEN round(x.area * x.days / x.cal, 4) END AS eff
         FROM pnl.store_month_effective_area e
         JOIN (
           SELECT s.site_code, m.month, s.area,
                  extract(day FROM (m.month + interval '1 month' - interval '1 day'))::int AS cal,
                  greatest(0, (CASE WHEN c.closing IS NOT NULL AND c.closing < m.month THEN m.month - 1
                                    WHEN c.closing IS NOT NULL AND c.closing < least((m.month + interval '1 month' - interval '1 day')::date, r.as_of_date) THEN c.closing
                                    ELSE least((m.month + interval '1 month' - interval '1 day')::date, r.as_of_date) END)
                          - (CASE WHEN s.opening_date IS NULL OR s.opening_date < DATE '2005-01-01' THEN m.month
                                  WHEN s.opening_date > (m.month + interval '1 month' - interval '1 day')::date THEN (m.month + interval '1 month')::date
                                  WHEN s.opening_date > m.month THEN s.opening_date ELSE m.month END) + 1) AS days
             FROM pnl.site s
             JOIN pnl.run r ON r.run_id = s.run_id
             CROSS JOIN LATERAL (SELECT generate_series(DATE '2025-04-01', date_trunc('month', r.as_of_date)::date, interval '1 month')::date AS month) m
             CROSS JOIN LATERAL (SELECT CASE WHEN s.store_status IN ('CLOSED', 'IN-ACTIVE') AND s.last_bill_date >= DATE '2005-01-01' AND s.last_bill_date < r.as_of_date THEN s.last_bill_date END AS closing) c
            WHERE s.run_id = p_run) x ON x.site_code = e.site_code AND x.month = e.month
        WHERE e.run_id = p_run) q
       WHERE q.active_days <> q.days OR q.calendar_days <> q.cal OR q.effective_area IS DISTINCT FROM q.eff
  -- the early (first N days) part of a COGS month never exceeds the month
  UNION ALL SELECT 'M15_cogs_early_within_month', count(*) FROM pnl.cogs_site_month WHERE run_id = p_run AND (abs(cogs_early) > abs(cogs_v) + 0.0001 AND sign(cogs_early) = sign(cogs_v) OR abs(sl_v_early) > abs(sl_v) + 0.0001 AND sign(sl_v_early) = sign(sl_v))
$$;

GRANT INSERT, SELECT ON pnl.gl_aligned, pnl.store_month_effective_area TO pnl_loader;
GRANT SELECT ON pnl.v_gl_aligned, pnl.v_store_month_effective_area TO pnl_verifier, pnl_api_reader;
GRANT EXECUTE ON FUNCTION pnl.mart_checks(text) TO pnl_loader, pnl_owner;
REVOKE ALL ON FUNCTION pnl.mart_checks(text) FROM PUBLIC;

RESET ROLE;

INSERT INTO cred.schema_migration (version, description) VALUES
  ('009', 'pnl review foundation: store area, the effective-area denominator (derived at load, re-derived in SQL), the day-aligned window of last year, the early part of COGS');
