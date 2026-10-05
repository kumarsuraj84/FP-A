-- Till drill ends at the store-day (migration 006). The ~500k POS Cash Drawer lines are no longer extracted or stored, so the two checks that compared them with the till view
-- (M13 day totals vs lines, M14 lines without a day) are replaced by the one check that needs only the till view: its cumulative balance is the running total of its own days.
-- The Cash Drawer entry view is removed (it could only ever be empty). Nothing else changes; the function keeps its owner and grants.

DO $pre$
BEGIN
  IF to_regclass('entry.run') IS NULL THEN RAISE EXCEPTION 'apply migration 005 first'; END IF;
END
$pre$;

SET ROLE entry_owner;
DROP VIEW IF EXISTS entry.v_cash_drawer_entry;
CREATE OR REPLACE FUNCTION entry.mart_checks(p_run text) RETURNS TABLE (check_id text, violations bigint) LANGUAGE sql STABLE SECURITY DEFINER SET search_path = entry, pg_temp AS
$$
  SELECT 'M01_header_rows', abs((SELECT count(*) FROM entry.entry_header WHERE entry_run_id = p_run) - (SELECT expected_headers FROM entry.run WHERE entry_run_id = p_run))::bigint
  UNION ALL SELECT 'M02_line_rows', abs((SELECT count(*) FROM entry.entry_line WHERE entry_run_id = p_run) - (SELECT expected_lines FROM entry.run WHERE entry_run_id = p_run))::bigint
  UNION ALL SELECT 'M03_link_rows', abs((SELECT count(*) FROM entry.creditor_bill_link WHERE entry_run_id = p_run) - (SELECT expected_links FROM entry.run WHERE entry_run_id = p_run))::bigint
  UNION ALL SELECT 'M04_till_day_rows', abs((SELECT count(*) FROM entry.till_day WHERE entry_run_id = p_run) - (SELECT expected_till_days FROM entry.run WHERE entry_run_id = p_run))::bigint
  -- E2: a voucher is stored complete: the header's line count equals the lines present
  UNION ALL SELECT 'M05_E2_line_count_matches_header', count(*) FROM entry.entry_header h WHERE h.entry_run_id = p_run
       AND h.line_count <> (SELECT count(*) FROM entry.entry_line l WHERE l.entry_run_id = h.entry_run_id AND l.entry_ref = h.entry_ref)
  UNION ALL SELECT 'M06_header_totals_match_lines', count(*) FROM entry.entry_header h
       LEFT JOIN (SELECT entry_ref, sum(debit) AS dr, sum(credit) AS cr FROM entry.entry_line WHERE entry_run_id = p_run GROUP BY entry_ref) l ON l.entry_ref = h.entry_ref
       WHERE h.entry_run_id = p_run AND (h.total_dr <> coalesce(l.dr, 0) OR h.total_cr <> coalesce(l.cr, 0))
  -- E3: every extracted entry balances
  UNION ALL SELECT 'M07_E3_entry_balances', count(*) FROM entry.entry_header WHERE entry_run_id = p_run AND total_dr <> total_cr
  -- E4: an EXACT link resolves to exactly one canonical identity that exists in the layer
  UNION ALL SELECT 'M08_E4_exact_resolves_to_one_entry', count(*) FROM entry.creditor_bill_link k WHERE k.entry_run_id = p_run AND k.link_status = 'EXACT'
       AND (k.matched_entries <> 1 OR NOT EXISTS (SELECT 1 FROM entry.entry_identity i WHERE i.entry_run_id = k.entry_run_id AND i.entry_ref = k.entry_ref))
  -- E5: nothing ambiguous or unlinked carries an entry
  UNION ALL SELECT 'M09_E5_no_auto_selection', count(*) FROM entry.creditor_bill_link WHERE entry_run_id = p_run AND link_status IN ('AMBIGUOUS', 'NOT_LINKED') AND entry_ref IS NOT NULL
  UNION ALL SELECT 'M10_identity_complete_and_unique', (SELECT count(*) FROM entry.entry_header h WHERE h.entry_run_id = p_run AND NOT EXISTS (SELECT 1 FROM entry.entry_identity i WHERE i.entry_run_id = h.entry_run_id AND i.entry_ref = h.entry_ref))
       + (SELECT count(*) FROM entry.entry_identity i WHERE i.entry_run_id = p_run AND NOT EXISTS (SELECT 1 FROM entry.entry_header h WHERE h.entry_run_id = i.entry_run_id AND h.entry_ref = i.entry_ref))
  UNION ALL SELECT 'M11_text_rows_match_lines', abs((SELECT count(*) FROM entry.entry_line_text WHERE entry_run_id = p_run) - (SELECT count(*) FROM entry.entry_line WHERE entry_run_id = p_run))::bigint
  -- E9: an EXACT link's entry nets (for that ledger and sub-ledger) to the bill amount
  UNION ALL SELECT 'M12_E9_exact_is_amount_corroborated', count(*) FROM entry.creditor_bill_link WHERE entry_run_id = p_run AND link_status = 'EXACT' AND (amount_agrees IS NOT TRUE OR abs(entry_net_amount) <> abs(bill_amount))
  -- E8 (till-day level): the till view's cumulative balance is the running total of the store's daily Dr - Cr, day by day. The till drill ends at the store-day;
  -- the individual POS Cash Drawer lines are not part of the entry layer.
  UNION ALL SELECT 'M13_E8_till_cumulative_running_balance', count(*) FROM (
       SELECT d.cumulative_balance, sum(d.debit - d.credit) OVER (PARTITION BY d.site_code ORDER BY d.day) AS running_balance
         FROM entry.till_day d WHERE d.entry_run_id = p_run) q
       WHERE q.cumulative_balance <> q.running_balance
$$;
RESET ROLE;

INSERT INTO cred.schema_migration (version, description) VALUES
  ('006', 'entry layer: the till drill ends at the store-day; Cash Drawer line view removed; M13 is the till running-balance check, M14 retired');
