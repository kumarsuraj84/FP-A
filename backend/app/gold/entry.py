"""Entry / voucher drill views over (SELECT * FROM gold_fpa.voucher_lines WHERE entity = 'RETAIL') (+ creditors_open_items, cash_drawer_store, dim_ledger, dim_site, control_totals).

Grain decisions (see docs/GOLD_SOURCE_GAPS_ENTRY.md):
  * entry (voucher)  = one `entcode`. Paired document types (PSC/PSD, PIC/PIM, CTC/CTM ...) share an entcode, so the header shows them together ('PSC/PSD').
  * entry_ref        = entcode as text (indexed; an opaque hash would force a scan of all 2.5M lines on every drill).
  * line             = one cost-tag row (cost_tag_key is unique); line_no = row_number() over (entcode order by cost_tag_key), the same expression in
                       v_entry_line and v_entry_line_text so the two always line up.
  * till day         = Cash Drawer (ledger 1000000008) debit / credit per store (tag_site_code) per day of the current financial year, plus a synthetic
                       opening day (last day of the previous FY) carrying cash_drawer_store.opening_balance, so the running total on the as-of day equals
                       Store Till Cash exactly.
  * creditor bill link = bill (creditors_open_items.postcode) -> voucher entcode = document_code. Never EXACT: voucher_lines carries no creditor-ledger
                       line, so the bill amount cannot be corroborated; a found voucher is STRONG, a missing one NOT_LINKED.
  * bank entries     = empty: gold_fpa has no bank-ledger master / bank lines yet.
Every view is self-contained (the db wrapper turns each into its own CTE). No percent sign may appear in the SQL (psycopg parameter style).
"""
from __future__ import annotations

from .db import vendor_salt

TILL_LEDGER = 1000000008
COVERAGE_FLOOR = "(SELECT min(entdt) FROM (SELECT * FROM gold_fpa.voucher_lines WHERE entity = 'RETAIL'))"
AS_OF = "(SELECT max(as_of_date) FROM gold_fpa.cash_drawer_store)"
RUN_ID = f"('ENTRY-' || to_char({AS_OF}, 'YYYYMMDD'))"
CASH_RUN = f"('CASH-' || to_char({AS_OF}, 'YYYYMMDD'))"
CRED_RUN = f"('GOLD-' || to_char({AS_OF}, 'YYYYMMDD'))"
FY_START = (f"(CASE WHEN extract(month FROM {AS_OF}) >= 4 THEN make_date(extract(year FROM {AS_OF})::int, 4, 1) "
            f"ELSE make_date(extract(year FROM {AS_OF})::int - 1, 4, 1) END)")


def _salt() -> str:
    return vendor_salt().replace("'", "")


def _relations() -> dict[str, str]:
    salt = _salt()
    status = "CASE WHEN {c} = 'P' THEN 'Posted' ELSE 'Unposted' END"

    serving_run = f"""SELECT {RUN_ID} AS entry_run_id, {AS_OF} AS register_report_date, {CRED_RUN} AS creditors_run_id, {CASH_RUN} AS cash_run_id,
        {AS_OF} AS till_balance_date, {COVERAGE_FLOOR} AS coverage_from, 'verified' AS recon_state, 'live' AS publication_state,
        'gold_fpa-1' AS contract_version, (SELECT max(_loaded_at) FROM gold_fpa.cash_drawer_store) AS extract_finished_at,
        (SELECT max(_loaded_at) FROM gold_fpa.cash_drawer_store) AS loaded_at"""

    entry_header = f"""SELECT {RUN_ID} AS entry_run_id, h.entcode AS entry_ref, h.site_code, h.entry_type_short, h.entry_type_long, h.entry_date,
        h.release_status, h.line_count, h.total_dr, h.total_cr,
        array_remove(ARRAY[CASE WHEN h.has_till THEN 'till' END, CASE WHEN h.entcode IN (SELECT document_code FROM gold_fpa.creditors_open_items) THEN 'creditors' END], NULL)::text[] AS selections
      FROM (SELECT entcode, coalesce(min(created_by_site_code), min(tag_site_code))::text AS site_code,
                   string_agg(DISTINCT enttype, '/' ORDER BY enttype) AS entry_type_short, string_agg(DISTINCT entry_type, ' / ' ORDER BY entry_type) AS entry_type_long,
                   min(entdt) AS entry_date,
                   CASE WHEN bool_and(release_status = 'P') THEN 'Posted' WHEN bool_and(release_status <> 'P') THEN 'Unposted' ELSE 'Mixed' END AS release_status,
                   count(*)::integer AS line_count, sum(coalesce(damount, 0)) AS total_dr, sum(coalesce(camount, 0)) AS total_cr, bool_or(glcode = {TILL_LEDGER}) AS has_till
            FROM (SELECT * FROM gold_fpa.voucher_lines WHERE entity = 'RETAIL') GROUP BY entcode) h"""

    entry_line = f"""SELECT {RUN_ID} AS entry_run_id, entcode AS entry_ref, (row_number() OVER (PARTITION BY entcode ORDER BY cost_tag_key))::integer AS line_no,
        cost_tag_key::text AS source_seq, glcode::text AS ledger_code, glname AS ledger_name, ledger_type AS ledger_nature,
        CASE WHEN slcode IS NOT NULL THEN 'V' || substr(md5('{salt}' || slcode::text), 1, 12) END AS sub_ledger_ref,
        coalesce(damount, 0) AS debit, coalesce(camount, 0) AS credit, {status.format(c='release_status')} AS release_status, NULL::text AS cube_name
      FROM (SELECT * FROM gold_fpa.voucher_lines WHERE entity = 'RETAIL')"""

    entry_line_text = f"""SELECT {RUN_ID} AS entry_run_id, entcode AS entry_ref, (row_number() OVER (PARTITION BY entcode ORDER BY cost_tag_key))::integer AS line_no,
        slcode::text AS sub_ledger_code, narration, coalesce(docno, scheme_docno) AS reference_no, doc_date::text AS reference_date,
        NULL::text AS cheque_no, NULL::text AS cheque_date, NULL::text AS counter_ledgers, NULL::text AS prepared_by, NULL::text AS prepared_on,
        NULL::text AS modified_by, NULL::text AS modified_on, NULL::text AS released_by, NULL::text AS released_on
      FROM (SELECT * FROM gold_fpa.voucher_lines WHERE entity = 'RETAIL')"""

    entry_identity = f"""SELECT {RUN_ID} AS entry_run_id, h.entcode AS entry_ref, h.site_code, h.entry_type_short, h.entry_no,
        coalesce(s.store_name, h.created_by_site_code) AS created_by_site
      FROM (SELECT entcode, coalesce(min(created_by_site_code), min(tag_site_code))::text AS site_code, string_agg(DISTINCT enttype, '/' ORDER BY enttype) AS entry_type_short,
                   coalesce(min(entno), min(scheme_docno), min(docno), entcode) AS entry_no, min(created_by_site_code)::text AS created_by_site_code,
                   min(created_by_site_code) AS created_by_site_int
            FROM (SELECT * FROM gold_fpa.voucher_lines WHERE entity = 'RETAIL') GROUP BY entcode) h
      LEFT JOIN gold_fpa.dim_site s ON s.site_code = h.created_by_site_int"""

    # one row per store per active day of the current FY, an opening day (FY start - 1) and a closing row on the as-of day
    till_day = f"""SELECT {RUN_ID} AS entry_run_id, {CASH_RUN} AS cash_run_id, site_code, day, debit, credit,
        sum(debit - credit) OVER (PARTITION BY site_code ORDER BY day) AS cumulative_balance
      FROM (
        SELECT c.site_code, {FY_START} - 1 AS day, greatest(c.opening_balance, 0) AS debit, greatest(-c.opening_balance, 0) AS credit
          FROM gold_fpa.cash_drawer_store c WHERE c.opening_balance <> 0
        UNION ALL
        SELECT v.tag_site_code, v.entdt, sum(coalesce(v.damount, 0)), sum(coalesce(v.camount, 0))
          FROM (SELECT * FROM gold_fpa.voucher_lines WHERE entity = 'RETAIL') v WHERE v.glcode = {TILL_LEDGER} AND (v.entdt >= {FY_START} OR v.release_status = 'U') AND v.entdt <= {AS_OF}
           AND v.tag_site_code IN (SELECT site_code FROM gold_fpa.cash_drawer_store) GROUP BY v.tag_site_code, v.entdt
        UNION ALL
        SELECT c.site_code, {AS_OF}, 0, 0 FROM gold_fpa.cash_drawer_store c
         WHERE NOT EXISTS (SELECT 1 FROM (SELECT * FROM gold_fpa.voucher_lines WHERE entity = 'RETAIL') v WHERE v.glcode = {TILL_LEDGER} AND v.tag_site_code = c.site_code AND v.entdt = {AS_OF})
      ) d"""

    bill_link = f"""SELECT {RUN_ID} AS entry_run_id, {CRED_RUN} AS creditors_run_id, o.postcode::text AS source_row_key, o.ledger_code::text AS ledger_code,
        o.amount AS bill_amount,
        CASE WHEN m.entcode IS NOT NULL THEN 'STRONG' ELSE 'NOT_LINKED' END AS link_status,
        CASE WHEN m.entcode IS NOT NULL THEN NULL WHEN o.document_date < {COVERAGE_FLOOR} THEN 'REGISTER_COVERAGE_UNAVAILABLE' ELSE 'NO_MATCH' END AS not_linked_reason,
        'DOCUMENT_CODE' AS key_used, CASE WHEN m.entcode IS NOT NULL THEN 1 ELSE 0 END AS matched_entries, m.entcode AS entry_ref,
        NULL::numeric AS entry_net_amount, NULL::boolean AS amount_agrees,
        CASE WHEN o.document_date < {COVERAGE_FLOOR} THEN 'BEFORE_COVERAGE' WHEN o.document_date < {FY_START} THEN 'PRIOR_YEARS_IN_COVERAGE' ELSE 'CURRENT_FY' END AS coverage
      FROM gold_fpa.creditors_open_items o
      LEFT JOIN (SELECT DISTINCT entcode FROM (SELECT * FROM gold_fpa.voucher_lines WHERE entity = 'RETAIL')) m ON m.entcode = o.document_code"""

    bank_entry = """SELECT NULL::text AS entry_run_id, NULL::text AS ledger_code, NULL::text AS ledger_name, NULL::date AS entry_date, NULL::text AS entry_ref,
        NULL::text AS entry_type_short, NULL::text AS entry_type_long, NULL::integer AS line_no, NULL::numeric AS debit, NULL::numeric AS credit,
        NULL::text AS release_status WHERE false"""

    # extraction's control_totals (per month and ledger type) against a recompute from voucher_lines, plus the till and bill-link figures
    control = f"""WITH a AS (SELECT date_trunc('month', entdt)::date AS period, ledger_type AS group_key, count(*)::numeric AS n, sum(coalesce(damount, 0)) AS dr, sum(coalesce(camount, 0)) AS cr
                      FROM (SELECT * FROM gold_fpa.voucher_lines WHERE entity = 'RETAIL') GROUP BY 1, 2),
             c AS (SELECT period, group_key, row_count, sum_debit, sum_credit FROM gold_fpa.control_totals WHERE table_name = 'voucher_lines'),
             k AS (SELECT a.period, a.group_key, a.n, a.dr, a.cr, c.row_count, c.sum_debit, c.sum_credit FROM a JOIN c USING (period, group_key)),
             r AS (SELECT {RUN_ID} AS rid)
        SELECT r.rid AS entry_run_id, 'LINE_ROWS' AS control_id, to_char(k.period, 'YYYY-MM') || ' ' || k.group_key AS dimension, 'extract' AS left_layer,
               k.row_count AS left_value, 'mart' AS right_layer, k.n AS right_value, k.n - k.row_count AS variance,
               CASE WHEN k.n = k.row_count THEN 'PASS' ELSE 'FAIL' END AS verdict FROM k, r
        UNION ALL
        SELECT r.rid, 'LINE_DEBIT', to_char(k.period, 'YYYY-MM') || ' ' || k.group_key, 'extract', k.sum_debit, 'mart', k.dr, k.dr - k.sum_debit,
               CASE WHEN abs(k.dr - k.sum_debit) < 0.005 THEN 'PASS' ELSE 'FAIL' END FROM k, r
        UNION ALL
        SELECT r.rid, 'LINE_CREDIT', to_char(k.period, 'YYYY-MM') || ' ' || k.group_key, 'extract', k.sum_credit, 'mart', k.cr, k.cr - k.sum_credit,
               CASE WHEN abs(k.cr - k.sum_credit) < 0.005 THEN 'PASS' ELSE 'FAIL' END FROM k, r
        UNION ALL
        SELECT r.rid, 'TILL_CUMULATIVE', 'all stores', 'mart', (SELECT sum(cumulative_balance) FROM gold_fpa.cash_drawer_store), 'api',
               (SELECT sum(t.debit - t.credit) FROM (SELECT debit, credit FROM ({till_day}) x) t),
               (SELECT sum(t.debit - t.credit) FROM (SELECT debit, credit FROM ({till_day}) x) t) - (SELECT sum(cumulative_balance) FROM gold_fpa.cash_drawer_store),
               CASE WHEN abs((SELECT sum(t.debit - t.credit) FROM (SELECT debit, credit FROM ({till_day}) x) t) - (SELECT sum(cumulative_balance) FROM gold_fpa.cash_drawer_store)) < 0.005
                    THEN 'PASS' ELSE 'FAIL' END FROM r
        UNION ALL
        SELECT r.rid, 'BILL_LINK_ROWS', 'all bills', 'extract', (SELECT count(*) FROM gold_fpa.creditors_open_items)::numeric, 'mart',
               (SELECT count(*) FROM ({bill_link}) y)::numeric, 0,
               CASE WHEN (SELECT count(*) FROM gold_fpa.creditors_open_items) = (SELECT count(*) FROM ({bill_link}) y) THEN 'PASS' ELSE 'FAIL' END FROM r"""

    return {
        "entry.v_serving_run": serving_run, "entry.v_entry_header": entry_header, "entry.v_entry_line": entry_line,
        "entry.v_entry_line_text": entry_line_text, "entry.v_entry_identity": entry_identity, "entry.v_till_day": till_day,
        "entry.v_creditor_bill_link": bill_link, "entry.v_bank_entry": bank_entry, "entry.v_control": control,
    }


RELATIONS = _relations()

# HoldCo (gold entity VENTURES) copies of the voucher relations, named <relation>_vn, for the single-voucher lookup of a Citykart Ventures voucher (/entry?entity=VENTURES).
# Kept apart from RELATIONS (the old-mart contract, RETAIL only); gold/db.py registers EXTRA_RELATIONS too. The pseudonymous party reference uses a different salt.
EXTRA_RELATIONS = {
    _n + "_vn": RELATIONS[_n].replace("entity = 'RETAIL'", "entity = 'VENTURES'").replace(f"md5('{_salt()}'", f"md5('{_salt()}VENTURES'")
    for _n in ("entry.v_entry_header", "entry.v_entry_line", "entry.v_entry_line_text", "entry.v_entry_identity")
}
