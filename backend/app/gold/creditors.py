"""Creditors over gold_fpa.creditors_open_items. The API repository reads `FROM {relation}`, so each former cred.* view becomes a
parenthesised subselect with the same column names. The run is synthetic: one 'run' per gold as_of_date, always live and verified
(extraction rebuilds the table daily); it is verified here by recomputing extraction's control_totals."""
from __future__ import annotations

from .db import vendor_salt

RUN_ID = "GOLD-' || to_char(as_of_date, 'YYYYMMDD') || '"


def _salt() -> str:
    return vendor_salt().replace("'", "")


def items(finance: bool) -> str:
    named = ", slid, vendor_name, credit_days, vendor_extinct, document_code, document_no, NULL::text AS document_initial, NULL::text AS ref_no, ref_date, created_by_site" if finance else ""
    return f"""(SELECT 'GOLD-' || to_char(as_of_date, 'YYYYMMDD') AS extraction_run_id,
        postcode::text AS source_row_key, 'I' || postcode::text AS item_ref,
        'V' || substr(md5('{_salt()}' || sub_ledger_code::text), 1, 12) AS vendor_ref, sub_ledger_code,
        as_of_date, ledger_code::text AS ledger_code, ledger_name, drcr, amount, adjusted, pending, document_type, due_date_basis,
        document_date, due_date, entry_date, age_days AS document_age_days,
        CASE WHEN age_bucket = 'DATE_INVALID' THEN 'UNCLASSIFIED_DATE_INVALID' ELSE age_bucket END AS document_age_bucket,
        CASE WHEN due_status = 'PAST_DUE_OR_DUE_TODAY' THEN (as_of_date - due_date) END AS overdue_days,
        due_status, CASE WHEN age_bucket = 'DATE_INVALID' THEN 'DATE_INVALID' ELSE 'OK' END AS date_quality_status,
        CASE WHEN age_bucket = 'DATE_INVALID' THEN 'UNCLASSIFIED' ELSE 'CLASSIFIED' END AS classification_status,
        party_class, party_class AS party_class_type{named}
      FROM gold_fpa.creditors_open_items) AS items"""


# one verified run per as_of_date (the only one in the table)
RUN = """(SELECT 'GOLD-' || to_char(as_of_date, 'YYYYMMDD') AS extraction_run_id, as_of_date, 'verified' AS recon_state,
        'live' AS publication_state, 'gold_fpa-1' AS contract_version, 'extraction-gold-1' AS rules_version,
        count(*) AS expected_rows, count(*) AS expected_identity_rows, max(_loaded_at) AS loaded_at
      FROM gold_fpa.creditors_open_items GROUP BY as_of_date) AS run"""

# controls: extraction's control_totals (per ledger: rows, pending) against a live recomputation from the same table
CONTROLS = """(WITH a AS (SELECT 'GOLD-' || to_char(as_of_date, 'YYYYMMDD') AS rid, ledger_name, count(*)::numeric AS n, sum(pending) AS p
                         FROM gold_fpa.creditors_open_items GROUP BY as_of_date, ledger_name),
   c AS (SELECT group_key, row_count, sum_amount FROM gold_fpa.control_totals WHERE table_name = 'creditors_open_items')
 SELECT a.rid AS extraction_run_id, 'ROWS' AS control_id, a.ledger_name AS dimension, 'extract' AS left_layer, c.row_count AS left_value,
        'mart' AS right_layer, a.n AS right_value, c.row_count - a.n AS variance, CASE WHEN c.row_count = a.n THEN 'PASS' ELSE 'FAIL' END AS verdict
 FROM a JOIN c ON c.group_key = a.ledger_name
 UNION ALL
 SELECT a.rid, 'PENDING', a.ledger_name, 'extract', c.sum_amount::numeric, 'mart', a.p, c.sum_amount::numeric - a.p,
        CASE WHEN abs(c.sum_amount::numeric - a.p) < 0.005 THEN 'PASS' ELSE 'FAIL' END FROM a JOIN c ON c.group_key = a.ledger_name) AS controls"""
