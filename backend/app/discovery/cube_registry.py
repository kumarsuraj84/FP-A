"""Metadata-only discovery of how logical cubes resolve to physical Oracle objects.

Flow: find OLAP_DATACUBE_LIST in Oracle metadata -> inspect its columns -> pull the
finance-related rows (bounded) -> check which registry hints / candidate objects exist in
ALL_OBJECTS. Output is evidence, labelled UNVERIFIED until an operator confirms a mapping
with `registry-confirm` (which re-checks ALL_OBJECTS)."""
from app.discovery.profiler import Target, table_metadata
from app.identifiers import quote
from app.registry.models import PhysicalObject, SourceEntry, SEPARATE_OBJECT

LIST_OBJECT = "OLAP_DATACUBE_LIST"
FINANCE_PATTERNS = ("%FIN%", "%MOP%", "%BILLCOLL%", "%TDS%", "%PTC%", "%BUDGET%", "%SER%INV%", "%SER%ORD%", "%SITE_REG%", "%GL_REG%")
MAX_ROWS = 5000
CHAR_TYPES = ("VARCHAR2", "CHAR", "NVARCHAR2", "NCHAR")


def locate_list(ora) -> list[dict]:
    objs = ora.query("SELECT owner, object_name, object_type FROM all_objects WHERE object_name = :n", {"n": LIST_OBJECT})
    syn = ora.query("SELECT owner, synonym_name, table_owner, table_name FROM all_synonyms WHERE synonym_name = :n", {"n": LIST_OBJECT})
    return [{"kind": "object", **o} for o in objs] + [{"kind": "synonym", **s} for s in syn]


def inspect_list(ora, owner: str, name: str = LIST_OBJECT) -> dict:
    t = Target(owner, name)
    meta = table_metadata(ora, t)
    char_cols = [c["COLUMN_NAME"] for c in meta["columns"] if c["DATA_TYPE"] in CHAR_TYPES]
    est = meta["estimated_rows"]
    if est is not None and est <= MAX_ROWS or not char_cols:
        sql, binds = f"SELECT * FROM {t.qualified} FETCH FIRST {MAX_ROWS} ROWS ONLY", {}
        scope = "all rows (small list)"
    else:
        conds, binds = [], {}
        for ci, c in enumerate(char_cols):
            for pi, p in enumerate(FINANCE_PATTERNS):
                k = f"p{ci}_{pi}"
                conds.append(f"UPPER({quote(c)}) LIKE :{k}")
                binds[k] = p
        sql = f"SELECT * FROM {t.qualified} WHERE {' OR '.join(conds)} FETCH FIRST {MAX_ROWS} ROWS ONLY"
        scope = "finance-pattern filtered rows"
    rows = ora.query(sql, binds)
    return {"list_object": f"{owner}.{name}", "metadata": meta, "row_scope": scope, "rows": rows,
            "label": "UNVERIFIED (columns/rows are evidence; mapping to registry needs confirmation)"}


def check_hints(ora, entries: list[SourceEntry]) -> list[dict]:
    """Existence check (ALL_OBJECTS only) for registry physical hints. A hint is a candidate,
    not a mapping."""
    out = []
    for e in entries:
        if not e.physical_hint:
            continue
        owner, _, name = e.physical_hint.partition(".")
        found = ora.query("SELECT object_type FROM all_objects WHERE owner = :o AND object_name = :n", {"o": owner, "n": name})
        out.append({"registry_key": e.registry_key, "hint": e.physical_hint,
                    "exists": bool(found), "object_types": [f["OBJECT_TYPE"] for f in found],
                    "label": "UNVERIFIED (exists != mapped to this cube copy)"})
    return out


def confirm_mapping(ora, entry: SourceEntry, owner: str, name: str, evidence: str) -> dict:
    """Operator-driven: re-checks the object exists, returns the overlay record. Does not
    prove cube->object linkage by itself; `evidence` must cite the OLAP_DATACUBE_LIST row."""
    found = ora.query("SELECT object_type FROM all_objects WHERE owner = :o AND object_name = :n", {"o": owner, "n": name})
    if not found:
        raise LookupError(f"{owner}.{name} not found in ALL_OBJECTS")
    if not evidence.strip():
        raise ValueError("evidence (OLAP_DATACUBE_LIST row reference) is required")
    phys = PhysicalObject(owner=owner, object_name=name, object_type=found[0]["OBJECT_TYPE"], access_mode=SEPARATE_OBJECT)
    return {"status": "CONFIRMED", "evidence": evidence,
            "physical": {"owner": phys.owner, "object_name": phys.object_name, "object_type": phys.object_type,
                         "access_mode": phys.access_mode}}
