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
    #: pilot packages: control_pre | extract | identity | control_post (empty for discovery / probe packages)
    role: str = ""


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

# ───────────── payables_probe_02: how much creditor exposure is affected by missing due dates? ─────────────
# Scoped to the four Sundry Creditors control ledgers (the agreed creditor family). Open rows only. TDS Payable, Sundry
# Debtors and Inter-Company are deliberately outside this scope.
CREDITOR_LEDGERS = (1000000026, 1000000024, 1000000092, 1000000025)  # Apparels, for Expenses, GM, Non Trading
_LEDGER_IN = ", ".join(str(c) for c in CREDITOR_LEDGERS)

_DUE_INNER = (
    "SELECT l.glname AS ledger_name, s.sl_class AS party_class, o.drcr AS drcr, "
    "CASE WHEN s.credit_days IS NULL THEN 'credit_days_null' WHEN s.credit_days = 0 THEN 'credit_days_zero' ELSE 'credit_days_positive' END AS credit_days_state, "
    "CASE WHEN o.due_date IS NULL THEN 'due_missing' WHEN o.due_date > o.report_date THEN 'due_present_not_yet_due' ELSE 'due_present_due_or_past' END AS due_state, "
    "o.pending AS pending "
    f"FROM {_T} o LEFT JOIN {_G} l ON l.glcode = o.ledger_code LEFT JOIN {_S} s ON s.slcode = o.sub_ledger_code "
    f"WHERE {_BO} AND o.pending <> 0 AND o.ledger_code IN ({_LEDGER_IN})"
)

PAYABLES_PROBE_02: tuple[Dataset, ...] = (
    Dataset(
        "r1_creditor_due_by_ledger",
        "extract",
        "Open creditor rows by ledger, Dr/Cr, credit-days state and due-date state: row count, absolute and signed pending.",
        sql=(
            "SELECT ledger_name, drcr, credit_days_state, due_state, COUNT(*) AS open_rows, SUM(ABS(pending)) AS abs_pending, "
            f"SUM(pending) AS signed_pending FROM ({_DUE_INNER}) GROUP BY ledger_name, drcr, credit_days_state, due_state "
            "ORDER BY ledger_name, drcr, credit_days_state, due_state FETCH FIRST 500 ROWS ONLY"
        ),
    ),
    Dataset(
        "r2_creditor_due_by_party_class",
        "extract",
        "The same exposure split by party class (no party names or codes), to see which classes carry the missing due dates.",
        sql=(
            "SELECT party_class, drcr, credit_days_state, due_state, COUNT(*) AS open_rows, SUM(ABS(pending)) AS abs_pending, "
            f"SUM(pending) AS signed_pending FROM ({_DUE_INNER}) GROUP BY party_class, drcr, credit_days_state, due_state "
            "ORDER BY party_class, drcr, credit_days_state, due_state FETCH FIRST 500 ROWS ONLY"
        ),
    ),
)

# ───────────── payables_probe_03: is there a stable, unique source-row identity? ─────────────
# Aggregate-only duplicate counting for candidate identity keys on the four creditor ledgers, for open rows and for all rows
# (a settled item must keep its identity, so settled rows are in scope for the test). No value, code or name leaves Oracle.
# Mutable accounting state (PENDING, ADJUSTED) and free text (NARRATION) are never part of a candidate key.
_SCOPES = {"open": f"{_BO} AND o.ledger_code IN ({_LEDGER_IN}) AND o.pending <> 0", "all": f"{_BO} AND o.ledger_code IN ({_LEDGER_IN})"}


def _key(*cols: str) -> str:
    return " || '|' || ".join(f"NVL(TO_CHAR(o.{c}), '~')" for c in cols)


_K1 = ("document_code", "ledger_code", "sub_ledger_code", "drcr")
_K2 = _K1 + ("ref_no",)
_K3 = _K2 + ("document_date",)
_K4 = _K3 + ("amount",)
KEY_CANDIDATES: dict[str, tuple[str, ...]] = {
    "K1": _K1,
    "K2": _K2,
    "K3": _K3,  # K2 + DOCUMENT_DATE
    "K4": _K4,  # K3 + AMOUNT
    "K2A": _K2 + ("amount",),  # K2 + AMOUNT without the date, to see which field resolves the ties
    "K5": _K4 + ("document_no", "document_type", "document_initial", "entry_date", "created_by_site"),
}
KEY_COMPONENTS = tuple(dict.fromkeys(c for cols in KEY_CANDIDATES.values() for c in cols))


def _key_test(scope: str, name: str, cols: tuple[str, ...]) -> str:
    k = _key(*cols)
    return (
        f"SELECT '{scope}' AS scope_name, '{name}' AS key_name, SUM(c) AS total_rows, COUNT(*) AS distinct_keys, SUM(c) - COUNT(*) AS surplus_rows, "
        "NVL(SUM(CASE WHEN c > 1 THEN c END), 0) AS rows_in_dup_groups, NVL(SUM(CASE WHEN c > 1 THEN 1 END), 0) AS dup_groups, MAX(c) AS max_group_size "
        f"FROM (SELECT COUNT(*) AS c FROM {_T} o WHERE {_SCOPES[scope]} GROUP BY {k})"
    )


def _null_counts(scope: str) -> str:
    cols = ", ".join(f"SUM(CASE WHEN o.{c} IS NULL THEN 1 ELSE 0 END) AS n_{c}" for c in KEY_COMPONENTS)
    return f"SELECT '{scope}' AS scope_name, COUNT(*) AS total_rows, {cols} FROM {_T} o WHERE {_SCOPES[scope]}"


_STRUCTURE = {
    # pattern name -> (group by, having)
    "doc_code_many_rows": ("o.document_code", "COUNT(*) > 1"),
    "doc_code_sub_ledger_many_rows": ("o.document_code, o.sub_ledger_code", "COUNT(*) > 1"),
    "doc_code_ledger_both_drcr": ("o.document_code, o.ledger_code", "COUNT(DISTINCT o.drcr) > 1"),
    "doc_code_many_sub_ledgers": ("o.document_code", "COUNT(DISTINCT o.sub_ledger_code) > 1"),
}


def _structure(scope: str, pattern: str) -> str:
    group, having = _STRUCTURE[pattern]
    return (
        f"SELECT '{scope}' AS scope_name, '{pattern}' AS pattern_name, COUNT(*) AS groups, NVL(SUM(c), 0) AS rows_in_groups, MAX(c) AS max_group_size "
        f"FROM (SELECT COUNT(*) AS c FROM {_T} o WHERE {_SCOPES[scope]} GROUP BY {group} HAVING {having})"
    )


def _union(parts: list[str], columns: str, order: str, cap: int) -> str:
    return f"SELECT {columns} FROM ({' UNION ALL '.join(parts)}) ORDER BY {order} FETCH FIRST {cap} ROWS ONLY"


PAYABLES_PROBE_03: tuple[Dataset, ...] = (
    Dataset(
        "s1_key_uniqueness",
        "extract",
        "Duplicate counts for each candidate identity key, open rows and all rows of the four creditor ledgers (scalars only).",
        sql=_union([_key_test(sc, n, c) for sc in _SCOPES for n, c in KEY_CANDIDATES.items()], "scope_name, key_name, total_rows, distinct_keys, surplus_rows, rows_in_dup_groups, dup_groups, max_group_size", "scope_name, key_name", 40),
    ),
    Dataset(
        "s2_key_component_nulls",
        "extract",
        "Null counts of every key component, open rows and all rows.",
        sql=_union([_null_counts(sc) for sc in _SCOPES], "scope_name, total_rows, " + ", ".join(f"n_{c}" for c in KEY_COMPONENTS), "scope_name", 5),
    ),
    Dataset(
        "s3_duplicate_structure",
        "extract",
        "How duplicate document codes are structured: line splits within a sub-ledger, both sides of a ledger, or several sub-ledgers (counts only).",
        sql=_union([_structure(sc, pt) for sc in _SCOPES for pt in _STRUCTURE], "scope_name, pattern_name, groups, rows_in_groups, max_group_size", "scope_name, pattern_name", 20),
    ),
)

# ───────────── creditors_pilot_01: the first controlled real extraction (contract creditors-pilot-1.0) ─────────────
# Oracle -> guarded broker -> Parquet + manifest -> offline staging validation (creditors_stage.py). Nothing is loaded anywhere else.
# Numbers and dates leave Oracle as exact text so no float or timestamp conversion can alter a value; every derived field
# (Document Age, Due Status, hashes) is computed offline, and an independent Oracle-side implementation of the Document Age
# and Due Status rules runs inside the source control so a rule bug cannot validate itself.
PILOT_RULES = {
    "contract_version": "creditors-pilot-1.0",
    "rules_version": "1",
    "hash_spec_version": "v1",
    # technical data-quality window for dates, NOT an accounting policy; configurable here and recorded in the manifest
    "valid_date_min": "2000-01-01",
    "valid_date_max": "2100-12-31",
    "age_buckets": [("D0_30", 30), ("D31_60", 60), ("D61_90", 90), ("D91_180", 180), ("D181_365", 365)],
}
PILOT_E1_CAP = 50_000
PILOT_E2_CAP = 500_000
_PL = f"{OWNER}.LEDGER_MV"
_PS = f"{OWNER}.SUB_LEDGER_MV"
_P_BOUND = "o.report_date >= DATE '2026-01-01'"
_P_LEDGERS = ", ".join(str(c) for c in CREDITOR_LEDGERS)
_P_ALL = f"{_P_BOUND} AND o.ledger_code IN ({_P_LEDGERS})"
_P_OPEN = f"{_P_ALL} AND o.pending <> 0"
_VMIN = f"DATE '{PILOT_RULES['valid_date_min']}'"
_VMAX = f"DATE '{PILOT_RULES['valid_date_max']}'"


def _age_case() -> str:
    days = "TRUNC(o.report_date) - TRUNC(o.document_date)"
    whens = " ".join(f"WHEN {days} <= {edge} THEN '{name}'" for name, edge in PILOT_RULES["age_buckets"])
    return (
        f"CASE WHEN o.document_date IS NULL THEN 'UNCLASSIFIED_MISSING' WHEN TRUNC(o.document_date) < {_VMIN} THEN 'UNCLASSIFIED_BEFORE_MIN' "
        f"WHEN TRUNC(o.document_date) > TRUNC(o.report_date) THEN 'UNCLASSIFIED_AFTER_AS_OF' {whens} ELSE 'D365_PLUS' END"
    )


def _due_case() -> str:
    return (
        "CASE WHEN o.due_date IS NULL THEN 'DUE_UNAVAILABLE' "
        f"WHEN TRUNC(o.due_date) < {_VMIN} OR TRUNC(o.due_date) > {_VMAX} OR TRUNC(o.due_date) < TRUNC(o.document_date) THEN 'DUE_INVALID' "
        "WHEN TRUNC(o.due_date) > TRUNC(o.report_date) THEN 'NOT_YET_DUE' ELSE 'PAST_DUE_OR_DUE_TODAY' END"
    )


_P_JOINS = f"FROM {_T} o LEFT JOIN {_PL} l ON l.glcode = o.ledger_code LEFT JOIN {_PS} s ON s.slcode = o.sub_ledger_code"

PILOT_E1_SQL = (
    "SELECT TO_CHAR(o.report_date, 'YYYY-MM-DD') AS as_of_date, o.document_code AS document_code, TO_CHAR(o.sub_ledger_code, 'TM9') AS sub_ledger_code, "
    "TO_CHAR(o.ledger_code, 'TM9') AS ledger_code, l.glname AS ledger_name, s.slid AS slid, s.sl_name AS vendor_name, s.sl_class AS party_class, "
    "s.sl_class_type AS party_class_type, TO_CHAR(s.credit_days, 'TM9') AS credit_days, s.is_extinct AS vendor_extinct, "
    "o.document_no AS document_no, o.document_type AS document_type, o.document_initial AS document_initial, "
    "TO_CHAR(o.document_date, 'YYYY-MM-DD') AS document_date, TO_CHAR(o.due_date, 'YYYY-MM-DD') AS due_date, o.due_date_basis AS due_date_basis, "
    "o.ref_no AS ref_no, TO_CHAR(o.ref_date, 'YYYY-MM-DD') AS ref_date, TO_CHAR(o.entry_date, 'YYYY-MM-DD') AS entry_date, o.drcr AS drcr, "
    "TO_CHAR(o.amount, 'TM9') AS amount, TO_CHAR(o.adjusted, 'TM9') AS adjusted, TO_CHAR(o.pending, 'TM9') AS pending, o.created_by_site AS created_by_site "
    f"{_P_JOINS} WHERE {_P_OPEN} ORDER BY o.document_code, o.sub_ledger_code FETCH FIRST {PILOT_E1_CAP} ROWS ONLY"
)
PILOT_E2_SQL = (
    "SELECT o.document_code AS document_code, TO_CHAR(o.sub_ledger_code, 'TM9') AS sub_ledger_code, TO_CHAR(o.ledger_code, 'TM9') AS ledger_code, o.drcr AS drcr, "
    "TO_CHAR(o.pending, 'TM9') AS pending, TO_CHAR(o.entry_date, 'YYYY-MM-DD') AS entry_date, TO_CHAR(o.report_date, 'YYYY-MM-DD') AS as_of_date "
    f"FROM {_T} o WHERE {_P_ALL} ORDER BY o.document_code, o.sub_ledger_code FETCH FIRST {PILOT_E2_CAP} ROWS ONLY"
)
PILOT_C1_SQL = (
    "SELECT TO_CHAR(ledger_code, 'TM9') AS ledger_code, drcr, doc_age_bucket, due_status, COUNT(*) AS item_rows, "
    "TO_CHAR(SUM(ABS(pending)), 'TM9') AS abs_pending, TO_CHAR(SUM(pending), 'TM9') AS signed_pending "
    f"FROM (SELECT o.ledger_code AS ledger_code, o.drcr AS drcr, o.pending AS pending, {_age_case()} AS doc_age_bucket, {_due_case()} AS due_status FROM {_T} o WHERE {_P_OPEN}) "
    "GROUP BY ledger_code, drcr, doc_age_bucket, due_status ORDER BY ledger_code, drcr, doc_age_bucket, due_status FETCH FIRST 1000 ROWS ONLY"
)
PILOT_C2_SQL = (
    "SELECT GROUPING(o.ledger_code) AS g_ledger, GROUPING(o.drcr) AS g_drcr, TO_CHAR(o.ledger_code, 'TM9') AS ledger_code, o.drcr AS drcr, "
    "COUNT(DISTINCT o.sub_ledger_code) AS vendors, COUNT(*) AS item_rows "
    f"FROM {_T} o WHERE {_P_OPEN} GROUP BY GROUPING SETS ((), (o.ledger_code), (o.drcr), (o.ledger_code, o.drcr)) "
    "ORDER BY g_ledger, g_drcr, ledger_code, drcr FETCH FIRST 100 ROWS ONLY"
)
PILOT_C3_SQL = (
    "SELECT COUNT(*) AS item_rows, COUNT(DISTINCT o.report_date) AS report_dates, TO_CHAR(MIN(o.report_date), 'YYYY-MM-DD') AS min_as_of, "
    "TO_CHAR(MAX(o.report_date), 'YYYY-MM-DD') AS max_as_of, "
    "COUNT(DISTINCT o.document_code || '|' || TO_CHAR(o.sub_ledger_code)) AS distinct_identity_keys, "
    "COUNT(DISTINCT o.document_code || '|' || TO_CHAR(o.ledger_code) || '|' || TO_CHAR(o.sub_ledger_code) || '|' || o.drcr) AS distinct_k1_keys, "
    "SUM(CASE WHEN o.document_code IS NULL OR o.sub_ledger_code IS NULL THEN 1 ELSE 0 END) AS null_identity_rows, "
    "SUM(CASE WHEN o.document_date IS NULL THEN 1 ELSE 0 END) AS null_document_date_rows, SUM(CASE WHEN o.due_date IS NULL THEN 1 ELSE 0 END) AS null_due_date_rows, "
    "SUM(CASE WHEN s.slcode IS NULL THEN 1 ELSE 0 END) AS rows_without_vendor_master, SUM(CASE WHEN l.glcode IS NULL THEN 1 ELSE 0 END) AS rows_without_ledger_master "
    f"{_P_JOINS} WHERE {_P_OPEN} FETCH FIRST 2 ROWS ONLY"
)

CREDITORS_PILOT_01: tuple[Dataset, ...] = (
    Dataset("c1_source_control_pre", "extract", "Source control before the extract: ledger x Dr/Cr x Document Age x Due Status, computed in Oracle.", sql=PILOT_C1_SQL, role="control_pre"),
    Dataset("c2_vendor_control_pre", "extract", "Source control before the extract: distinct vendors in total, per ledger, per Dr/Cr.", sql=PILOT_C2_SQL, role="control_pre"),
    Dataset("c3_snapshot_control_pre", "extract", "Source control before the extract: rows, report dates, key uniqueness, nulls, join coverage.", sql=PILOT_C3_SQL, role="control_pre"),
    Dataset("e1_open_items", "extract", "The extract: one row per open source item of the four creditor ledgers (PENDING <> 0).", sql=PILOT_E1_SQL, role="extract"),
    Dataset("e2_identity_all_rows", "extract", "Identity and PENDING of every row in the four ledgers, open or settled (identity-stability evidence only).", sql=PILOT_E2_SQL, role="identity"),
    Dataset("c1_source_control_post", "extract", "The same source control again after the extract.", sql=PILOT_C1_SQL, role="control_post"),
    Dataset("c2_vendor_control_post", "extract", "The same vendor control again after the extract.", sql=PILOT_C2_SQL, role="control_post"),
    Dataset("c3_snapshot_control_post", "extract", "The same snapshot control again after the extract.", sql=PILOT_C3_SQL, role="control_post"),
)

#: manifest-level facts for packages that carry a contract; a failed dataset halts the run (never extract after a failed control)
PACKAGE_META: dict[str, dict] = {
    "creditors_pilot_01": {
        "halt_on_failure": True,
        "contract": {
            **PILOT_RULES,
            "scope": {"source_object": _T, "ledger_codes": list(CREDITOR_LEDGERS), "open_predicate": "PENDING <> 0", "as_of_source": "REPORT_DATE"},
            "identity": "sha256('v1|' + DOCUMENT_CODE + '|' + SUB_LEDGER_CODE)",
            "caps": {"e1_open_items": PILOT_E1_CAP, "e2_identity_all_rows": PILOT_E2_CAP},
        },
    }
}

# ───────────── profit_cash_probe_01: source discovery for Store Profitability and Cash (evidence only, aggregates and small masters) ─────────────
# The finance team's own P&L model lives in MISRETAIL: T_FINANCE_P_AND_L_BASE_1_STORE (ledger entries tagged with SK_GRP / SK_MAJ_GRP and a location),
# T_FINANCE_P_AND_L_BUDGET, the store map and the ledger->group map. Discovery asks: how complete and how consistent are they, do they tie to the
# site-wise GL register, what are the sales / COGS / cash candidates. No row-level transaction data leaves Oracle; sums leave as exact text.
# Nothing here decides a definition: it produces evidence for the Profitability and Cash contracts.
_PB = f"{OWNER}.T_FINANCE_P_AND_L_BASE_1_STORE"
_PBUD = f"{OWNER}.T_FINANCE_P_AND_L_BUDGET"
_SITEREG = f'{OWNER}."T$FINREGSITE_844"'  # SITE_REG_26-27, report date = current snapshot
_TM9 = lambda e, a: f"TO_CHAR({e}, 'TM9') AS {a}"  # noqa: E731  exact numeric text

PROFIT_CASH_PROBE_01: tuple[Dataset, ...] = (
    Dataset("m1_store_map", "master", "Store map: site code, name, state, status, same-store flag (143 expected).",
            sql=f"SELECT site_code, store_name, state, store_status, same_store_filter FROM {OWNER}.T_FINANCE_P_AND_L_STORE_MAP FETCH FIRST 1000 ROWS ONLY"),
    Dataset("m2_group_map", "master", "SK_GRP -> SK_MAJ_GRP grouping used by the finance P&L.",
            sql=f"SELECT sk_grp, sk_maj_grp FROM {OWNER}.T_FINANCE_RAJEEV_GROUPING FETCH FIRST 1000 ROWS ONLY"),
    Dataset("m3_ledger_to_group", "master", "Ledger -> SK_GRP mapping used by the finance P&L.",
            sql=f"SELECT ledger, sk_grp FROM {OWNER}.T_FINANCE_RAJEEV_P_N_L FETCH FIRST 1000 ROWS ONLY"),
    Dataset("m4_location_map", "master", "Location code -> location -> location filter (hierarchy candidate).",
            sql=f"SELECT new_code, location, location_filter FROM {OWNER}.T_FINANCE_RAJEEV_LOCATION_DATA FETCH FIRST 1000 ROWS ONLY"),
    Dataset("m5_gl_master", "master", "GL master (code, name, group, type, nature): no address or contact columns.",
            sql=f'SELECT glcode, glname, grpcode, type, nature, extinct FROM {OWNER}."MAS$FINGL" FETCH FIRST 5000 ROWS ONLY'),
    Dataset("e1_pnl_by_group_month", "extract", "Finance P&L base (store level): row count and exact sums by FY, month, major group, group and Dr/Cr.",
            sql=("SELECT fy_year, TO_CHAR(exp_mth, 'YYYY-MM-DD') AS exp_mth, sk_maj_grp, sk_grp, dr_cr, COUNT(*) AS entry_rows, COUNT(DISTINCT location) AS locations, "
                 f"{_TM9('SUM(balance)', 'sum_balance')}, {_TM9('SUM(val_in_lacs)', 'sum_val_in_lacs')} FROM {_PB} WHERE exp_mth >= DATE '2025-04-01' "
                 "GROUP BY fy_year, exp_mth, sk_maj_grp, sk_grp, dr_cr FETCH FIRST 60000 ROWS ONLY")),
    Dataset("e2_pnl_coverage", "extract", "Finance P&L base: what the FILTER / LOCATION_FILTER / SOURCE_SHORT_NAME columns separate, per FY.",
            sql=("SELECT fy_year, filter, location_filter, source_short_name, COUNT(*) AS entry_rows, COUNT(DISTINCT location) AS locations, "
                 f"TO_CHAR(MIN(exp_mth), 'YYYY-MM-DD') AS first_month, TO_CHAR(MAX(exp_mth), 'YYYY-MM-DD') AS last_month, {_TM9('SUM(balance)', 'sum_balance')} "
                 f"FROM {_PB} WHERE exp_mth >= DATE '2025-04-01' GROUP BY fy_year, filter, location_filter, source_short_name FETCH FIRST 5000 ROWS ONLY")),
    Dataset("e3_pnl_amount_semantics", "extract", "Finance P&L base: do BALANCE, BALANCE_SUM and VAL_IN_LACS agree (VAL_IN_LACS x 100000 vs BALANCE), nulls and Dr/Cr signs, per FY.",
            sql=("SELECT fy_year, dr_cr, COUNT(*) AS entry_rows, COUNT(balance) AS n_balance, COUNT(balance_sum) AS n_balance_sum, COUNT(val_in_lacs) AS n_val_in_lacs, "
                 f"{_TM9('SUM(balance)', 'sum_balance')}, {_TM9('SUM(balance_sum)', 'sum_balance_sum')}, {_TM9('SUM(val_in_lacs) * 100000', 'sum_lacs_x_1e5')}, "
                 f"{_TM9('SUM(ABS(balance))', 'sum_abs_balance')}, COUNT(CASE WHEN balance < 0 THEN 1 END) AS negative_rows "
                 f"FROM {_PB} WHERE exp_mth >= DATE '2025-04-01' GROUP BY fy_year, dr_cr FETCH FIRST 200 ROWS ONLY")),
    Dataset("e4_budget_by_group_month", "extract", "Budget table: exact sums and store counts by FY, month, AOP group, major group and group.",
            sql=("SELECT fy, TO_CHAR(month, 'YYYY-MM-DD') AS budget_month, aop_group, maj_grp, sk_grp, COUNT(*) AS budget_rows, COUNT(DISTINCT store_nm) AS stores, "
                 f"{_TM9('SUM(budget_amt)', 'sum_budget')} FROM {_PBUD} WHERE month >= DATE '2025-04-01' GROUP BY fy, month, aop_group, maj_grp, sk_grp FETCH FIRST 60000 ROWS ONLY")),
    Dataset("e5_cogs_by_month", "extract", "Finance COGS view: exact cost by bill month and store count.",
            sql=(f"SELECT TO_CHAR(billmonth, 'YYYY-MM-DD') AS bill_month, COUNT(*) AS rows_in_month, COUNT(DISTINCT store_name) AS stores, {_TM9('SUM(costamount)', 'sum_cost')} "
                 f"FROM {OWNER}.V_FINANCE_P_AND_L_COGS_DATA WHERE billmonth >= DATE '2025-04-01' GROUP BY billmonth FETCH FIRST 100 ROWS ONLY")),
    Dataset("e6_sales_dashboard_by_month", "extract", "CFO dashboard sales view: sales value, tax, COGS, bills and store counts by bill month.",
            sql=(f"SELECT TO_CHAR(TRUNC(billdate, 'MM'), 'YYYY-MM-DD') AS bill_month, COUNT(*) AS rows_in_month, COUNT(DISTINCT admsite_code) AS stores, {_TM9('SUM(bill_count)', 'bills')}, "
                 f"{_TM9('SUM(sl_v)', 'sum_sales_value')}, {_TM9('SUM(tax_v)', 'sum_tax_value')}, {_TM9('SUM(cogs_v)', 'sum_cogs_value')}, {_TM9('SUM(sl_q)', 'sum_sales_qty')} "
                 f"FROM {OWNER}.V_CFO_DASHBOARD_SL_V WHERE billdate >= DATE '2025-04-01' GROUP BY TRUNC(billdate, 'MM') FETCH FIRST 100 ROWS ONLY")),
    Dataset("e7_site_register_by_gl_month", "extract", "Site-wise GL register (current FY): exact Dr/Cr by GL code, month and release status, with distinct site counts (ties the finance P&L to the books).",
            sql=("SELECT entry_glcode, TO_CHAR(TRUNC(entry_date, 'MM'), 'YYYY-MM-DD') AS entry_month, release_status, COUNT(*) AS entry_rows, COUNT(DISTINCT sitecode) AS sites, "
                 f"{_TM9('SUM(debit)', 'sum_debit')}, {_TM9('SUM(credit)', 'sum_credit')} FROM {_SITEREG} WHERE entry_date >= DATE '2026-04-01' "
                 "GROUP BY entry_glcode, TRUNC(entry_date, 'MM'), release_status FETCH FIRST 60000 ROWS ONLY")),
    Dataset("e8_site_register_snapshot", "extract", "Site-wise GL register: row count, report date, entry date range, distinct sites and GL codes (scalars).",
            sql=("SELECT COUNT(*) AS entry_rows, TO_CHAR(MIN(report_date), 'YYYY-MM-DD') AS report_date_min, TO_CHAR(MAX(report_date), 'YYYY-MM-DD') AS report_date_max, "
                 "TO_CHAR(MIN(entry_date), 'YYYY-MM-DD') AS entry_date_min, TO_CHAR(MAX(entry_date), 'YYYY-MM-DD') AS entry_date_max, COUNT(DISTINCT sitecode) AS sites, "
                 f"COUNT(DISTINCT entry_glcode) AS gl_codes FROM {_SITEREG} WHERE entry_date >= DATE '2026-04-01' FETCH FIRST 1 ROWS ONLY")),
    Dataset("e9_store_cash_by_month", "extract", "Store cash balance view: Dr/Cr by month and store count; the last cumulative balance date.",
            sql=(f"SELECT TO_CHAR(TRUNC(bill_date, 'MM'), 'YYYY-MM-DD') AS bill_month, COUNT(*) AS rows_in_month, COUNT(DISTINCT site_code) AS stores, {_TM9('SUM(debit)', 'sum_debit')}, "
                 f"{_TM9('SUM(credit)', 'sum_credit')}, TO_CHAR(MAX(bill_date), 'YYYY-MM-DD') AS last_date FROM {OWNER}.V_FINANCE_CASH_CUMLATIVE_BLNC WHERE bill_date >= DATE '2025-04-01' "
                 "GROUP BY TRUNC(bill_date, 'MM') FETCH FIRST 100 ROWS ONLY")),
    Dataset("e10_cash_flow_by_cube_month", "extract", "Finance cash-flow view: Dr/Cr by cube and month (bank / cash register candidate).",
            sql=(f"SELECT cubename, TO_CHAR(TRUNC(entry_date, 'MM'), 'YYYY-MM-DD') AS entry_month, COUNT(*) AS entry_rows, COUNT(DISTINCT ledger) AS ledgers, {_TM9('SUM(debit)', 'sum_debit')}, "
                 f"{_TM9('SUM(credit)', 'sum_credit')} FROM {OWNER}.V_FINANCE_CASH_FLOW WHERE entry_date >= DATE '2025-04-01' GROUP BY cubename, TRUNC(entry_date, 'MM') FETCH FIRST 2000 ROWS ONLY")),
    Dataset("e11_budget_cube_by_month", "extract", "Budget analysis cube (system budget vs actual): month, entries, exact budget and actual totals.",
            sql=(f"SELECT TO_CHAR(TRUNC(budget_date, 'MM'), 'YYYY-MM-DD') AS budget_month, COUNT(*) AS rows_in_month, COUNT(DISTINCT admsite_code) AS sites, COUNT(DISTINCT glcode) AS gl_codes, "
                 f"{_TM9('SUM(budgeted_total)', 'sum_budget')}, {_TM9('SUM(actual_total)', 'sum_actual')} FROM {OWNER}.CUBE$BUDGETANALYSIS WHERE budget_date >= DATE '2025-04-01' "
                 "GROUP BY TRUNC(budget_date, 'MM') FETCH FIRST 100 ROWS ONLY")),
)

PACKAGES: dict[str, tuple[Dataset, ...]] = {"discovery_01": DISCOVERY_01, "ageing_probe_01": AGEING_PROBE_01, "payables_probe_01": PAYABLES_PROBE_01, "payables_probe_02": PAYABLES_PROBE_02, "payables_probe_03": PAYABLES_PROBE_03, "creditors_pilot_01": CREDITORS_PILOT_01, "profit_cash_probe_01": PROFIT_CASH_PROBE_01}
