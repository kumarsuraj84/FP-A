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

PACKAGES: dict[str, tuple[Dataset, ...]] = {"discovery_01": DISCOVERY_01}
