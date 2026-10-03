"""Live discovery profiler. Read-only. Emits a JSON profile with NO credentials.

Cube-style objects hold many logical cubes in one table, discriminated by a code
column; the discriminator column name is UNVERIFIED and is passed in by the caller."""
import json
import re
from datetime import datetime, timezone

from app.oracle.client import OracleReadOnly

_IDENT = re.compile(r"^[A-Za-z][A-Za-z0-9_$#]{0,127}$")


def _ident(name: str) -> str:
    if not _IDENT.match(name):
        raise ValueError(f"unsafe identifier: {name!r}")
    return name.upper()


def profile_object(ora: OracleReadOnly, owner: str, obj: str, *, date_col: str | None = None,
                   debit_col: str | None = None, credit_col: str | None = None,
                   group_cols: tuple[str, ...] = (), cube_col: str | None = None,
                   cube_code: str | None = None, sample: int = 5) -> dict:
    owner, obj = _ident(owner), _ident(obj)
    cols = ora.query(
        "SELECT column_name, data_type, data_length, nullable FROM all_tab_columns "
        "WHERE owner = :o AND table_name = :t ORDER BY column_id", {"o": owner, "t": obj})
    where, binds = "", {}
    if cube_col and cube_code is not None:
        where, binds = f" WHERE {_ident(cube_col)} = :cc", {"cc": cube_code}
    fq = f'{owner}."{obj}"'
    sels = ["COUNT(*) AS n"]
    if date_col:
        sels += [f"MIN({_ident(date_col)}) AS dmin", f"MAX({_ident(date_col)}) AS dmax"]
    if debit_col:
        sels.append(f"SUM({_ident(debit_col)}) AS debit")
    if credit_col:
        sels.append(f"SUM({_ident(credit_col)}) AS credit")
    for g in group_cols:
        sels.append(f"COUNT(DISTINCT {_ident(g)}) AS distinct_{_ident(g).lower()}")
    agg = ora.query(f"SELECT {', '.join(sels)} FROM {fq}{where}", binds)[0]
    nulls = {}
    for c in cols:
        cn = c["COLUMN_NAME"]
        r = ora.query(f'SELECT COUNT(*) - COUNT("{cn}") AS nn FROM {fq}{where}', binds)[0]
        nulls[cn] = (r["NN"] / agg["N"]) if agg["N"] else None
    rows = ora.query(f"SELECT * FROM {fq}{where} FETCH FIRST {int(sample)} ROWS ONLY", binds)
    return {"object": f"{owner}.{obj}", "cube_code": cube_code, "columns": cols, "aggregates": agg,
            "null_rate": nulls, "sample_rows": rows,
            "profiled_at": datetime.now(timezone.utc).isoformat()}


def dump(profile: dict, path: str) -> None:
    with open(path, "w") as f:
        json.dump(profile, f, indent=2, default=str)
