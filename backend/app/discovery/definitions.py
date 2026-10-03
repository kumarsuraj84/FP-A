"""Metadata-only extraction of existing finance reporting objects and view definitions
(approved-P&L evidence). Never reads fact rows."""
from app.discovery.profiler import table_metadata, Target

DEFAULT_PATTERNS = ("V_FINANCE_P_AND_L_%", "T_FINANCE_P_AND_L_%", "T_FINANCE_RAJEEV_%")


def discover_definitions(ora, patterns=DEFAULT_PATTERNS, with_columns: bool = True) -> list[dict]:
    out = []
    for pat in patterns:
        objs = ora.query("SELECT owner, object_name, object_type, last_ddl_time FROM all_objects "
                         "WHERE object_name LIKE :p AND object_type IN ('VIEW','TABLE','MATERIALIZED VIEW') "
                         "ORDER BY owner, object_name", {"p": pat})
        for o in objs:
            rec = {"pattern": pat, **o, "label": "UNVERIFIED (definition text is evidence, not an approved rule)"}
            if o["OBJECT_TYPE"] == "VIEW":
                v = ora.query("SELECT text FROM all_views WHERE owner = :o AND view_name = :n",
                              {"o": o["OWNER"], "n": o["OBJECT_NAME"]})
                rec["view_sql"] = v[0]["TEXT"] if v else None
            if with_columns:
                rec["columns"] = table_metadata(ora, Target(o["OWNER"], o["OBJECT_NAME"]))["columns"]
            out.append(rec)
    return out
