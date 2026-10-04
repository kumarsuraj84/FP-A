"""
Extraction packages. Each dataset is ONE guarded, capped query against MISRETAIL (the MIS data warehouse) only.
SSRK is live production and out of scope; the guard rejects it. Discovery comes first and is metadata-only:
no transaction data, no COUNT(*) on finance objects (row estimates come from ALL_TABLES statistics).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

OWNER = "MISRETAIL"

# Finance-like object names. Deliberately name-based: the registry is UNVERIFIED, so this only decides which
# objects get their metadata pulled, never what they mean.
_NAME_RE = (
    "(FIN|LEDGER|VOUCHER|CREDITOR|PAYABLE|VENDOR|SUPPLIER|PURCHASE|GRC|PAYMENT|SETTLE|CASH|BANK|COGS|OLAP|CUBE|"
    "OUTSTAND|BILLCOLL|MOP)|(^|[_$])(GL|SL|PO)([_$]|$)"
)
_SCOPE = f"owner = '{OWNER}'"
FIN_OBJECTS = (
    f"SELECT owner, object_name FROM all_objects WHERE {_SCOPE} AND object_type IN ('TABLE', 'VIEW', 'MATERIALIZED VIEW') "
    f"AND REGEXP_LIKE(object_name, '{_NAME_RE}', 'i')"
)
FIN_TABLES = (
    f"SELECT owner, object_name FROM all_objects WHERE {_SCOPE} AND object_type = 'TABLE' "
    f"AND REGEXP_LIKE(object_name, '{_NAME_RE}', 'i')"
)
FIN_VIEWS = (
    f"SELECT owner, object_name FROM all_objects WHERE {_SCOPE} AND object_type IN ('VIEW', 'MATERIALIZED VIEW') "
    f"AND REGEXP_LIKE(object_name, '{_NAME_RE}', 'i')"
)

# Cube copy tables are named T$<CUBE>_<cube code>. These cube families carry the finance structures we care about.
CUBE_FAMILIES = ("FINREGSITE", "FINOTSD", "BILLCOLL", "FINREGSL", "FINREG", "BANKREG", "GRCCHGITEM", "PURCHASE")
HEADER_COLUMNS = ("CUBE_CODE", "CUBENAME", "START_DATE", "END_DATE", "REPORT_DATE")
MAX_HEADER_TABLES = 80


@dataclass(frozen=True)
class Dataset:
    name: str
    kind: str  # metadata | sample | extract
    description: str
    sql: str | None = None
    #: for datasets that depend on an earlier result (receives {dataset_name: list of row dicts})
    build: Callable[[dict], str] | None = None
    depends_on: tuple[str, ...] = ()
    #: columns that hold dates in the output, used to fill min_date / max_date in the manifest
    date_columns: tuple[str, ...] = ()
    notes: tuple[str, ...] = field(default_factory=tuple)


def cube_copy_tables(prev: dict) -> list[str]:
    """Cube copy tables that exist AND expose all header columns, so the one-row probe is valid SQL."""
    pat = re.compile(rf"^T\$({'|'.join(CUBE_FAMILIES)})_\d+$")
    have: dict[str, set[str]] = {}
    for r in prev.get("d04_columns", []):
        have.setdefault(r["TABLE_NAME"], set()).add(r["COLUMN_NAME"])
    tables = [
        r["OBJECT_NAME"]
        for r in prev.get("d01_finance_objects", [])
        if r.get("OBJECT_TYPE") == "TABLE" and r.get("OWNER") == OWNER and pat.match(str(r["OBJECT_NAME"]))
    ]
    ok = sorted(t for t in tables if set(HEADER_COLUMNS) <= have.get(t, set()))
    return ok[:MAX_HEADER_TABLES]


def _cube_header_sql(prev: dict) -> str:
    """One row per cube copy: which cube code / name / date range / refresh date it holds. A copy that returns no
    row is empty (or mid-refresh): this is the existence probe that settles the 'statistics say 0 rows' question."""
    tables = cube_copy_tables(prev)
    if not tables:
        raise LookupError("no cube copy tables with header columns were found")
    cols = ", ".join(c.lower() for c in HEADER_COLUMNS)
    branches = [
        f"SELECT * FROM (SELECT '{t}' AS source_table, {cols} FROM {OWNER}.\"{t}\" FETCH FIRST 1 ROWS ONLY)" for t in tables
    ]
    return f"SELECT * FROM ({' UNION ALL '.join(branches)}) FETCH FIRST 500 ROWS ONLY"


DISCOVERY_01: tuple[Dataset, ...] = (
    Dataset(
        "d01_finance_objects",
        "metadata",
        "Finance-like tables and views in MISRETAIL, matched by name only.",
        sql=(
            "SELECT owner, object_name, object_type, status, created, last_ddl_time FROM all_objects "
            f"WHERE {_SCOPE} AND object_type IN ('TABLE', 'VIEW', 'MATERIALIZED VIEW') "
            f"AND REGEXP_LIKE(object_name, '{_NAME_RE}', 'i') ORDER BY object_type, object_name FETCH FIRST 20000 ROWS ONLY"
        ),
        date_columns=("CREATED", "LAST_DDL_TIME"),
    ),
    Dataset(
        "d02_table_stats",
        "metadata",
        "Optimizer statistics (NUM_ROWS, blocks, last analysed) for the finance-like tables. No COUNT(*).",
        sql=(
            "SELECT owner, table_name, num_rows, blocks, avg_row_len, last_analyzed, partitioned, temporary, iot_type "
            f"FROM all_tables WHERE (owner, table_name) IN ({FIN_TABLES}) ORDER BY num_rows DESC NULLS LAST "
            "FETCH FIRST 20000 ROWS ONLY"
        ),
        date_columns=("LAST_ANALYZED",),
    ),
    Dataset(
        "d03_view_meta",
        "metadata",
        "Finance-like views: owner, name, text length. The view text itself is not pulled (LONG column).",
        sql=(
            "SELECT owner, view_name, text_length, read_only FROM all_views "
            f"WHERE (owner, view_name) IN ({FIN_VIEWS}) ORDER BY view_name FETCH FIRST 20000 ROWS ONLY"
        ),
    ),
    Dataset(
        "d04_columns",
        "metadata",
        "Every column of every finance-like table/view: type, length, precision, nullability, distinct/null stats.",
        sql=(
            "SELECT owner, table_name, column_id, column_name, data_type, data_length, data_precision, data_scale, "
            "nullable, num_distinct, num_nulls, last_analyzed FROM all_tab_columns "
            f"WHERE (owner, table_name) IN ({FIN_OBJECTS}) ORDER BY owner, table_name, column_id FETCH FIRST 300000 ROWS ONLY"
        ),
        date_columns=("LAST_ANALYZED",),
    ),
    Dataset(
        "d05_table_comments",
        "metadata",
        "Table / view comments (business descriptions, where someone wrote them).",
        sql=(
            "SELECT owner, table_name, table_type, comments FROM all_tab_comments "
            f"WHERE comments IS NOT NULL AND (owner, table_name) IN ({FIN_OBJECTS}) FETCH FIRST 20000 ROWS ONLY"
        ),
    ),
    Dataset(
        "d06_column_comments",
        "metadata",
        "Column comments for the finance-like objects.",
        sql=(
            "SELECT owner, table_name, column_name, comments FROM all_col_comments "
            f"WHERE comments IS NOT NULL AND (owner, table_name) IN ({FIN_OBJECTS}) FETCH FIRST 300000 ROWS ONLY"
        ),
    ),
    Dataset(
        "d07_constraints",
        "metadata",
        "Primary / unique / foreign-key constraints on the finance-like tables.",
        sql=(
            "SELECT owner, constraint_name, constraint_type, table_name, r_owner, r_constraint_name, status, validated "
            f"FROM all_constraints WHERE constraint_type IN ('P', 'U', 'R') AND (owner, table_name) IN ({FIN_TABLES}) "
            "FETCH FIRST 100000 ROWS ONLY"
        ),
    ),
    Dataset(
        "d08_constraint_columns",
        "metadata",
        "Columns behind each constraint, in order, so candidate row keys can be read off.",
        sql=(
            "SELECT cc.owner, cc.constraint_name, cc.table_name, cc.column_name, cc.position, c.constraint_type "
            "FROM all_cons_columns cc JOIN all_constraints c ON c.owner = cc.owner AND c.constraint_name = cc.constraint_name "
            f"WHERE c.constraint_type IN ('P', 'U', 'R') AND (cc.owner, cc.table_name) IN ({FIN_TABLES}) "
            "FETCH FIRST 300000 ROWS ONLY"
        ),
    ),
    Dataset(
        "d09_indexes",
        "metadata",
        "Indexes on the finance-like tables (what the database can read cheaply).",
        sql=(
            "SELECT owner, index_name, table_owner, table_name, uniqueness, index_type, status, distinct_keys, num_rows, "
            f"last_analyzed, partitioned FROM all_indexes WHERE (table_owner, table_name) IN ({FIN_TABLES}) "
            "FETCH FIRST 100000 ROWS ONLY"
        ),
        date_columns=("LAST_ANALYZED",),
    ),
    Dataset(
        "d10_index_columns",
        "metadata",
        "Columns of each index, in order.",
        sql=(
            "SELECT index_owner, index_name, table_owner, table_name, column_name, column_position FROM all_ind_columns "
            f"WHERE (table_owner, table_name) IN ({FIN_TABLES}) FETCH FIRST 300000 ROWS ONLY"
        ),
    ),
    Dataset(
        "d11_view_dependencies",
        "metadata",
        "What each finance-like view reads from (lineage). Names only; nothing outside MISRETAIL is ever read.",
        sql=(
            "SELECT owner, name, type, referenced_owner, referenced_name, referenced_type, dependency_type "
            f"FROM all_dependencies WHERE (owner, name) IN ({FIN_VIEWS}) FETCH FIRST 300000 ROWS ONLY"
        ),
    ),
    Dataset(
        "d12_cube_copy_headers",
        "sample",
        "One row from each MISRETAIL cube copy table: cube code, cube name, date range, refresh date. Maps copy IDs to "
        "fiscal years from the warehouse's own tables, and shows which copies are empty.",
        build=_cube_header_sql,
        depends_on=("d01_finance_objects", "d04_columns"),
        date_columns=("START_DATE", "END_DATE", "REPORT_DATE"),
        notes=("one-row probe per copy: cheap, and an empty copy returns no row",),
    ),
)


# ───────────── ageing_probe_01: let the data answer the creditor ageing-basis question ─────────────
# Everything reads MISRETAIL."T$FINOTSD_533" (the OUTSTANDING cube, refreshed daily, ~211K rows) or the two small
# masters. Aggregates and one tiny sample only: no wide SELECT *, no personal / contact columns. Nothing here decides
# the ageing rule; it collects evidence.
_T = f'{OWNER}."T$FINOTSD_533"'
_B = "report_date >= DATE '2026-01-01'"  # the current snapshot: bounds every probe to a date range
_DAYS = "no_of_days_base_on_{}"


def _sums(day_col: str, as_on: str) -> str:
    """16 counts over {2 day-count columns} x {2 as-on dates} x {4 candidate dates}. Aliases stay <= 30 chars (Oracle 12.1)."""
    short = {"no_of_days_base_on_entry_date": "ent", "no_of_days_base_on_ref_date": "ref", "report_date": "rep", "end_date": "end",
             "entry_date": "ent", "ref_date": "ref", "document_date": "doc", "due_date": "due"}
    return ", ".join(
        f"SUM(CASE WHEN {day_col} = TRUNC({as_on}) - TRUNC({d}) THEN 1 ELSE 0 END) AS d_{short[day_col]}_{short[as_on]}_{short[d]}"
        for d in ("entry_date", "ref_date", "document_date", "due_date")
    )


AGEING_PROBE_01: tuple[Dataset, ...] = (
    Dataset(
        "p01_report_date_distribution",
        "extract",
        "How many rows per REPORT_DATE snapshot, with the document / due date ranges. Shows whether 533 is one snapshot.",
        sql=(
            "SELECT report_date, COUNT(*) AS row_count, MIN(document_date) AS min_document_date, MAX(document_date) AS max_document_date, "
            f"MIN(due_date) AS min_due_date, MAX(due_date) AS max_due_date FROM {_T} WHERE {_B} "
            "GROUP BY report_date ORDER BY report_date DESC FETCH FIRST 400 ROWS ONLY"
        ),
        date_columns=("REPORT_DATE",),
    ),
    Dataset(
        "p02_due_date_basis",
        "extract",
        "What DUE_DATE_BASIS contains: values and counts, with how often each value has a due date and a document date.",
        sql=(
            "SELECT due_date_basis, COUNT(*) AS row_count, COUNT(due_date) AS due_date_filled, COUNT(document_date) AS document_date_filled "
            f"FROM {_T} WHERE {_B} GROUP BY due_date_basis ORDER BY COUNT(*) DESC FETCH FIRST 200 ROWS ONLY"
        ),
    ),
    Dataset(
        "p03_null_counts_and_ranges",
        "extract",
        "Which date and day-count columns are populated, their ranges, and basic sanity counts (single row).",
        sql=(
            "SELECT COUNT(*) AS total_rows, COUNT(document_date) AS document_date_filled, COUNT(due_date) AS due_date_filled, "
            "COUNT(ref_date) AS ref_date_filled, COUNT(entry_date) AS entry_date_filled, "
            "COUNT(no_of_days_base_on_entry_date) AS days_entry_filled, COUNT(no_of_days_base_on_ref_date) AS days_ref_filled, "
            "SUM(CASE WHEN document_date IS NULL AND due_date IS NULL THEN 1 ELSE 0 END) AS neither_document_nor_due_date, "
            "SUM(CASE WHEN document_date IS NULL AND due_date IS NULL AND ref_date IS NULL AND entry_date IS NULL THEN 1 ELSE 0 END) AS no_date_at_all, "
            "SUM(CASE WHEN due_date < document_date THEN 1 ELSE 0 END) AS due_before_document, "
            "MIN(document_date) AS min_document_date, MAX(document_date) AS max_document_date, MIN(due_date) AS min_due_date, MAX(due_date) AS max_due_date, "
            "MIN(ref_date) AS min_ref_date, MAX(ref_date) AS max_ref_date, MIN(entry_date) AS min_entry_date, MAX(entry_date) AS max_entry_date, "
            "MIN(no_of_days_base_on_entry_date) AS min_days_entry, MAX(no_of_days_base_on_entry_date) AS max_days_entry, "
            "MIN(no_of_days_base_on_ref_date) AS min_days_ref, MAX(no_of_days_base_on_ref_date) AS max_days_ref, "
            "COUNT(pending) AS pending_filled, SUM(CASE WHEN pending = 0 THEN 1 ELSE 0 END) AS pending_zero, "
            "SUM(CASE WHEN pending < 0 THEN 1 ELSE 0 END) AS pending_negative, MIN(pending) AS min_pending, MAX(pending) AS max_pending "
            f"FROM {_T} WHERE {_B} FETCH FIRST 2 ROWS ONLY"
        ),
    ),
    Dataset(
        "p04_drcr_distribution",
        "extract",
        "Distinct DRCR values with counts and amount / pending / adjusted ranges, to read what Dr/Cr means in this cube.",
        sql=(
            "SELECT drcr, COUNT(*) AS row_count, MIN(amount) AS min_amount, MAX(amount) AS max_amount, MIN(pending) AS min_pending, "
            "MAX(pending) AS max_pending, MIN(adjusted) AS min_adjusted, MAX(adjusted) AS max_adjusted "
            f"FROM {_T} WHERE {_B} GROUP BY drcr ORDER BY COUNT(*) DESC FETCH FIRST 50 ROWS ONLY"
        ),
    ),
    Dataset(
        "p05_day_count_consistency",
        "extract",
        "For each stored day-count column: on how many rows does it equal (as-on date minus date X)? Shows which date and "
        "which as-on date each day-count is really computed from (single row).",
        sql=(
            "SELECT COUNT(*) AS total_rows, "
            + ", ".join(
                _sums(f"no_of_days_base_on_{b}_date", a) for b in ("entry", "ref") for a in ("report_date", "end_date")
            )
            + f" FROM {_T} WHERE {_B} FETCH FIRST 2 ROWS ONLY"
        ),
    ),
    Dataset(
        "p06_due_minus_date_days",
        "extract",
        "Distribution of (due date minus document / reference / entry date) in days: does due date encode a credit period?",
        sql=(
            "SELECT basis, days, row_count FROM ("
            f"SELECT 'due_minus_document' AS basis, TRUNC(due_date) - TRUNC(document_date) AS days, COUNT(*) AS row_count FROM {_T} "
            f"WHERE {_B} AND due_date IS NOT NULL AND document_date IS NOT NULL GROUP BY TRUNC(due_date) - TRUNC(document_date) "
            "UNION ALL "
            f"SELECT 'due_minus_ref', TRUNC(due_date) - TRUNC(ref_date), COUNT(*) FROM {_T} "
            f"WHERE {_B} AND due_date IS NOT NULL AND ref_date IS NOT NULL GROUP BY TRUNC(due_date) - TRUNC(ref_date) "
            "UNION ALL "
            f"SELECT 'due_minus_entry', TRUNC(due_date) - TRUNC(entry_date), COUNT(*) FROM {_T} "
            f"WHERE {_B} AND due_date IS NOT NULL AND entry_date IS NOT NULL GROUP BY TRUNC(due_date) - TRUNC(entry_date)"
            ") ORDER BY basis, row_count DESC FETCH FIRST 600 ROWS ONLY"
        ),
    ),
    Dataset(
        "p07_vendor_due_terms",
        "extract",
        "Per sub-ledger (vendor) code and DUE_DATE_BASIS: the due-minus-document days and how many rows. Compared with "
        "SUB_LEDGER_MV.CREDIT_DAYS to see whether due date follows the vendor's credit terms.",
        sql=(
            "SELECT sub_ledger_code, due_date_basis, TRUNC(due_date) - TRUNC(document_date) AS due_minus_document_days, COUNT(*) AS row_count "
            f"FROM {_T} WHERE {_B} AND due_date IS NOT NULL AND document_date IS NOT NULL "
            "GROUP BY sub_ledger_code, due_date_basis, TRUNC(due_date) - TRUNC(document_date) FETCH FIRST 50000 ROWS ONLY"
        ),
    ),
    Dataset(
        "p08_sample_50",
        "sample",
        "A very small row sample (at most 50) with only the ageing-relevant columns, to eyeball the fields side by side.",
        sql=(
            "SELECT document_date, due_date, ref_date, entry_date, due_date_basis, no_of_days_base_on_entry_date, "
            "no_of_days_base_on_ref_date, amount, adjusted, pending, drcr, ledger_code, sub_ledger_code "
            f"FROM {_T} SAMPLE (0.1) FETCH FIRST 50 ROWS ONLY"
        ),
    ),
    Dataset(
        "m01_ledger_mv",
        "master",
        "GL master (code, name, group, type, nature). Contact columns are deliberately not selected.",
        sql=f"SELECT glcode, glname, grpcode, type, nature, extinct FROM {OWNER}.LEDGER_MV FETCH FIRST 100000 ROWS ONLY",
    ),
    Dataset(
        "m02_sub_ledger_mv",
        "master",
        "Sub-ledger (vendor / party) master: SLCODE, SLID, name, class, credit terms. Address, phone, e-mail, PAN, contacts are not selected.",
        sql=(
            "SELECT glcode, slcode, slid, sl_name, sl_alias, sl_class, sl_class_type, credit_days, credit_limit, "
            f"cash_disc_app, cash_disc_percent, cash_disc_period, is_extinct FROM {OWNER}.SUB_LEDGER_MV FETCH FIRST 100000 ROWS ONLY"
        ),
    ),
)

# ───────────── payables_probe_01: which rows are open payables, and can a missing due date be derived? ─────────────
# Still evidence-gathering: grouped aggregates over MISRETAIL."T$FINOTSD_533" joined (inside MISRETAIL) to the two masters.
# No row-level extract, no derived due dates are written anywhere, no rule is decided.
_S = f"{OWNER}.SUB_LEDGER_MV"
_G = f"{OWNER}.LEDGER_MV"
_BO = "o.report_date >= DATE '2026-01-01'"

PAYABLES_PROBE_01: tuple[Dataset, ...] = (
    Dataset(
        "q1_due_date_derivation",
        "extract",
        "OPEN rows only (PENDING <> 0): does the stored DUE_DATE equal document_date + CREDIT_DAYS, or entry_date + CREDIT_DAYS? "
        "Counts by DUE_DATE_BASIS, party class, credit-days state, Dr/Cr and due-date state. Nothing is derived or written.",
        sql=(
            "SELECT due_date_basis, sl_class_type, sl_class, drcr, credit_days_state, due_state, master_state, COUNT(*) AS open_rows, "
            "SUM(comparable) AS comparable_rows, SUM(eq_document) AS eq_document_plus_credit, SUM(eq_entry) AS eq_entry_plus_credit FROM ("
            "SELECT o.due_date_basis AS due_date_basis, s.sl_class_type AS sl_class_type, s.sl_class AS sl_class, o.drcr AS drcr, "
            "CASE WHEN s.slcode IS NULL THEN 'no_master_row' ELSE 'in_master' END AS master_state, "
            "CASE WHEN s.credit_days IS NULL THEN 'credit_days_null' WHEN s.credit_days = 0 THEN 'credit_days_zero' ELSE 'credit_days_positive' END AS credit_days_state, "
            "CASE WHEN o.due_date IS NULL THEN 'due_null' ELSE 'due_filled' END AS due_state, "
            "CASE WHEN o.due_date IS NOT NULL AND s.credit_days IS NOT NULL THEN 1 ELSE 0 END AS comparable, "
            "CASE WHEN o.due_date IS NOT NULL AND s.credit_days IS NOT NULL AND TRUNC(o.due_date) = TRUNC(o.document_date) + s.credit_days THEN 1 ELSE 0 END AS eq_document, "
            "CASE WHEN o.due_date IS NOT NULL AND s.credit_days IS NOT NULL AND TRUNC(o.due_date) = TRUNC(o.entry_date) + s.credit_days THEN 1 ELSE 0 END AS eq_entry "
            f"FROM {_T} o LEFT JOIN {_S} s ON s.slcode = o.sub_ledger_code WHERE {_BO} AND o.pending <> 0) "
            "GROUP BY due_date_basis, sl_class_type, sl_class, drcr, credit_days_state, due_state, master_state "
            "ORDER BY COUNT(*) DESC FETCH FIRST 5000 ROWS ONLY"
        ),
    ),
    Dataset(
        "q2_date_quality_by_exposure",
        "extract",
        "Date problems (pre-2000, after the report date, null) split by settled / open and Dr / Cr, with row counts AND the "
        "absolute pending exposure they carry. Invalid dates are flagged, never discarded.",
        sql=(
            "SELECT pending_state, drcr, COUNT(*) AS total_rows, SUM(abs_pending) AS abs_pending, "
            "SUM(f_doc_pre2000) AS doc_pre2000_rows, SUM(f_doc_pre2000 * abs_pending) AS doc_pre2000_abs, "
            "SUM(f_doc_after_report) AS doc_after_report_rows, SUM(f_doc_after_report * abs_pending) AS doc_after_report_abs, "
            "SUM(f_due_after_report) AS due_after_report_rows, SUM(f_due_after_report * abs_pending) AS due_after_report_abs, "
            "SUM(f_doc_null) AS doc_null_rows, SUM(f_doc_null * abs_pending) AS doc_null_abs, "
            "SUM(f_due_null) AS due_null_rows, SUM(f_due_null * abs_pending) AS due_null_abs, "
            "SUM(f_credit_null) AS credit_null_rows, SUM(f_credit_null * abs_pending) AS credit_null_abs, "
            "SUM(f_entry_pre2000) AS entry_pre2000_rows, SUM(f_entry_after_report) AS entry_after_report_rows FROM ("
            "SELECT CASE WHEN o.pending = 0 THEN 'settled' ELSE 'open' END AS pending_state, o.drcr AS drcr, ABS(o.pending) AS abs_pending, "
            "CASE WHEN o.document_date < DATE '2000-01-01' THEN 1 ELSE 0 END AS f_doc_pre2000, "
            "CASE WHEN o.document_date > o.report_date THEN 1 ELSE 0 END AS f_doc_after_report, "
            "CASE WHEN o.due_date > o.report_date THEN 1 ELSE 0 END AS f_due_after_report, "
            "CASE WHEN o.document_date IS NULL THEN 1 ELSE 0 END AS f_doc_null, "
            "CASE WHEN o.due_date IS NULL THEN 1 ELSE 0 END AS f_due_null, "
            "CASE WHEN s.credit_days IS NULL THEN 1 ELSE 0 END AS f_credit_null, "
            "CASE WHEN o.entry_date < DATE '2000-01-01' THEN 1 ELSE 0 END AS f_entry_pre2000, "
            "CASE WHEN o.entry_date > o.report_date THEN 1 ELSE 0 END AS f_entry_after_report "
            f"FROM {_T} o LEFT JOIN {_S} s ON s.slcode = o.sub_ledger_code WHERE {_BO}) "
            "GROUP BY pending_state, drcr ORDER BY pending_state, drcr FETCH FIRST 20 ROWS ONLY"
        ),
    ),
    Dataset(
        "q3_payable_population",
        "extract",
        "The ledger / party-class population: per ledger code, name, type, Dr/Cr and party class, the row count, open-row "
        "count, signed and absolute pending, and distinct open sub-ledgers. Shows which ledgers really carry creditor balances.",
        sql=(
            "SELECT o.ledger_code AS ledger_code, l.glname AS ledger_name, l.type AS ledger_type, l.nature AS ledger_nature, o.drcr AS drcr, "
            "s.sl_class_type AS party_class_type, s.sl_class AS party_class, COUNT(*) AS row_count, "
            "SUM(CASE WHEN o.pending <> 0 THEN 1 ELSE 0 END) AS open_rows, SUM(o.pending) AS signed_sum_pending, "
            "SUM(ABS(o.pending)) AS abs_sum_pending, COUNT(DISTINCT CASE WHEN o.pending <> 0 THEN o.sub_ledger_code END) AS open_sub_ledgers "
            f"FROM {_T} o LEFT JOIN {_G} l ON l.glcode = o.ledger_code LEFT JOIN {_S} s ON s.slcode = o.sub_ledger_code "
            f"WHERE {_BO} GROUP BY o.ledger_code, l.glname, l.type, l.nature, o.drcr, s.sl_class_type, s.sl_class "
            "ORDER BY SUM(ABS(o.pending)) DESC FETCH FIRST 20000 ROWS ONLY"
        ),
    ),
    Dataset(
        "q4_amount_adjusted_pending",
        "extract",
        "How AMOUNT, ADJUSTED and PENDING reconcile, by Dr/Cr and settled/open: which formula holds and what sign ADJUSTED carries.",
        sql=(
            "SELECT drcr, pending_state, COUNT(*) AS total_rows, "
            "SUM(CASE WHEN adjusted IS NULL THEN 1 ELSE 0 END) AS adjusted_null, SUM(CASE WHEN adjusted = 0 THEN 1 ELSE 0 END) AS adjusted_zero, "
            "SUM(CASE WHEN adjusted > 0 THEN 1 ELSE 0 END) AS adjusted_positive, SUM(CASE WHEN adjusted < 0 THEN 1 ELSE 0 END) AS adjusted_negative, "
            "SUM(CASE WHEN ABS(pending - (amount - NVL(adjusted, 0))) <= 0.01 THEN 1 ELSE 0 END) AS p_eq_amount_minus_adj, "
            "SUM(CASE WHEN ABS(pending - (amount + NVL(adjusted, 0))) <= 0.01 THEN 1 ELSE 0 END) AS p_eq_amount_plus_adj, "
            "SUM(CASE WHEN ABS(pending - SIGN(amount) * (ABS(amount) - ABS(NVL(adjusted, 0)))) <= 0.01 THEN 1 ELSE 0 END) AS p_eq_abs_difference, "
            "SUM(CASE WHEN ABS(pending - amount) <= 0.01 THEN 1 ELSE 0 END) AS p_eq_amount, "
            "SUM(CASE WHEN ABS(adjusted) > ABS(amount) THEN 1 ELSE 0 END) AS adj_exceeds_amount, "
            "SUM(CASE WHEN ABS(pending) > ABS(amount) THEN 1 ELSE 0 END) AS pending_exceeds_amount FROM ("
            "SELECT o.drcr AS drcr, CASE WHEN o.pending = 0 THEN 'settled' ELSE 'open' END AS pending_state, "
            f"o.amount AS amount, o.adjusted AS adjusted, o.pending AS pending FROM {_T} o WHERE {_BO}) "
            "GROUP BY drcr, pending_state ORDER BY drcr, pending_state FETCH FIRST 20 ROWS ONLY"
        ),
    ),
)

PACKAGES: dict[str, tuple[Dataset, ...]] = {"discovery_01": DISCOVERY_01, "ageing_probe_01": AGEING_PROBE_01, "payables_probe_01": PAYABLES_PROBE_01}
