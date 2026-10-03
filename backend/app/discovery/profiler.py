"""Low-impact profiler. Read-only. Emits JSON with NO credentials.

LIGHT (default) per object:  1 metadata query (columns) + 1 stats query (ALL_TABLES.NUM_ROWS,
  no scan) + at most 1 aggregate scan (only if the caller asked for row count / date range /
  sums / distincts, all folded into ONE statement) + 1 bounded sample.
DEEP (explicit): LIGHT + null counts for all columns in ceil(ncols/chunk) aggregate scans
  (never one scan per column).

Physical objects come from the registry (CONFIRMED) or are passed explicitly by the
operator; names are never derived from patterns here."""
import math
from dataclasses import dataclass
from datetime import datetime, timezone

from app.identifiers import ident, quote
from app.registry.models import PhysicalObject, SEPARATE_OBJECT

DEEP_NULL_CHUNK = 100   # columns per null-count aggregate pass


@dataclass(frozen=True)
class Target:
    owner: str
    name: str
    discriminator: tuple[str, str] | None = None   # (column, value) for shared-object architecture

    @classmethod
    def from_physical(cls, p: PhysicalObject) -> "Target":
        d = (p.discriminator_column, p.discriminator_value) if p.access_mode != SEPARATE_OBJECT else None
        return cls(p.owner, p.object_name, d)

    @property
    def qualified(self) -> str:
        return f"{quote(self.owner)}.{quote(self.name)}"

    def where(self) -> tuple[str, dict]:
        if not self.discriminator:
            return "", {}
        return f" WHERE {quote(self.discriminator[0])} = :disc", {"disc": self.discriminator[1]}


def table_metadata(ora, t: Target) -> dict:
    cols = ora.query(
        "SELECT column_name, data_type, data_length, data_precision, data_scale, nullable "
        "FROM all_tab_columns WHERE owner = :o AND table_name = :t ORDER BY column_id",
        {"o": t.owner, "t": t.name})
    stats = ora.query(
        "SELECT num_rows, last_analyzed FROM all_tables WHERE owner = :o AND table_name = :t",
        {"o": t.owner, "t": t.name})
    return {"object": f"{t.owner}.{t.name}", "columns": cols,
            "estimated_rows": stats[0]["NUM_ROWS"] if stats else None,
            "stats_last_analyzed": stats[0]["LAST_ANALYZED"] if stats else None,
            "estimate_source": "ALL_TABLES.NUM_ROWS (optimizer stats; may be stale/absent for views)"}


def profile_light(ora, t: Target, *, date_col: str | None = None, debit_col: str | None = None,
                  credit_col: str | None = None, distinct_cols: tuple[str, ...] = (),
                  exact_count: bool = False, sample: int = 5, sample_order_by: str | None = None) -> dict:
    meta = table_metadata(ora, t)
    where, binds = t.where()
    sels = []
    if exact_count or date_col or debit_col or credit_col or distinct_cols:
        sels.append("COUNT(*) AS n")
    if date_col:
        sels += [f"MIN({quote(date_col)}) AS dmin", f"MAX({quote(date_col)}) AS dmax"]
    if debit_col:
        sels.append(f"SUM({quote(debit_col)}) AS debit")
    if credit_col:
        sels.append(f"SUM({quote(credit_col)}) AS credit")
    for i, g in enumerate(distinct_cols):
        sels.append(f"COUNT(DISTINCT {quote(g)}) AS d{i}")
    agg = None
    if sels:   # ONE scan for everything requested
        agg = ora.query(f"SELECT {', '.join(sels)} FROM {t.qualified}{where}", binds)[0]
        for i, g in enumerate(distinct_cols):
            agg[f"DISTINCT_{ident(g).upper()}"] = agg.pop(f"D{i}")
    order = f" ORDER BY {quote(sample_order_by)}" if sample_order_by else ""
    rows = ora.query(f"SELECT * FROM {t.qualified}{where}{order} FETCH FIRST {int(sample)} ROWS ONLY", binds)
    meta.update({"mode": "light", "aggregates": agg, "sample_rows": rows,
                 "sample_deterministic": bool(sample_order_by),
                 "profiled_at": datetime.now(timezone.utc).isoformat()})
    return meta


def profile_deep(ora, t: Target, *, chunk: int = DEEP_NULL_CHUNK, **light_kwargs) -> dict:
    prof = profile_light(ora, t, **light_kwargs)
    names = [c["COLUMN_NAME"] for c in prof["columns"]]
    where, binds = t.where()
    counts: dict[str, int] = {}
    total = None
    for start in range(0, len(names), chunk):
        part = names[start:start + chunk]
        sel = ", ".join(f"COUNT({quote(c)}) AS c{i}" for i, c in enumerate(part))
        r = ora.query(f"SELECT COUNT(*) AS n, {sel} FROM {t.qualified}{where}", binds)[0]
        total = r["N"]
        for i, c in enumerate(part):
            counts[c] = r[f"C{i}"]
    prof["mode"] = "deep"
    prof["exact_rows"] = total
    prof["null_rate"] = {c: ((total - n) / total if total else None) for c, n in counts.items()}
    prof["null_passes"] = math.ceil(len(names) / chunk) if names else 0
    return prof


MAX_GROUPS = 100


def profile_group(ora, t: Target, group_col: str, *, debit_col: str | None = None, credit_col: str | None = None,
                  max_groups: int = MAX_GROUPS) -> dict:
    """ONE aggregate scan: count (+ optional debit/credit sums) per value of ONE column. Bounded to
    max_groups rows (fetches max_groups+1 to detect truncation). Group values are returned verbatim, so
    only use low-cardinality code columns (e.g. release status), never narration/party columns."""
    if not isinstance(group_col, str):
        raise ValueError("exactly one group column is supported at this stage")
    try:
        g = quote(group_col)
    except ValueError:
        raise ValueError("exactly one safe group column name is supported at this stage")
    where, binds = t.where()
    sels = [f"{g} AS grp", "COUNT(*) AS n"]
    if debit_col: sels.append(f"SUM({quote(debit_col)}) AS debit")
    if credit_col: sels.append(f"SUM({quote(credit_col)}) AS credit")
    limit = int(max_groups) + 1
    rows = ora.query(f"SELECT {', '.join(sels)} FROM {t.qualified}{where} GROUP BY {g} "
                     f"ORDER BY COUNT(*) DESC FETCH FIRST {limit} ROWS ONLY", binds)
    truncated = len(rows) > max_groups
    return {"object": f"{t.owner}.{t.name}", "group_column": group_col.upper(), "groups": rows[:max_groups],
            "truncated": truncated, "profiled_at": datetime.now(timezone.utc).isoformat()}
