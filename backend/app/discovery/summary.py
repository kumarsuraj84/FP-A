"""Sanitized LIVE_DISCOVERY_01_SUMMARY.json - safe to share for review.

WHITELIST construction: only named structural/aggregate fields are copied; nothing is passed through
wholesale. Never included: sample rows, narrations, party/vendor names, voucher-level data, DSN,
credentials, Oracle username, local file paths. Aggregates (counts, date range, debit/credit totals,
distinct counts, release-status groups) are included by design."""
import json
import re
from pathlib import Path

from app.config import Settings
from app.redact import redact

SUMMARY_NAME = "LIVE_DISCOVERY_01_SUMMARY.json"
SENSITIVE_COL = re.compile(r"(USER|EMAIL|MAIL|PASSW|PWD|CREATED_BY|UPDATED_BY|MODIFIED_BY|AUTHOR)", re.I)
FINANCE_ROW = re.compile(r"(FIN|MOP|BILLCOLL|TDS|PTC|PETTY|BUDGET|SERINV|SERORD|SITE_REG|GL_REG|OTSD|OUTSTAND)", re.I)
MAX_LIST_ROWS = 300
MAX_VIEW_SQL = 20000


def _load(out: Path, name: str):
    p = out / name
    return json.loads(p.read_text()) if p.exists() else None


def _cols(meta: dict | None):
    if not meta: return None
    return [{"name": c["COLUMN_NAME"], "type": c["DATA_TYPE"], "length": c.get("DATA_LENGTH"), "precision": c.get("DATA_PRECISION"),
             "scale": c.get("DATA_SCALE"), "nullable": c.get("NULLABLE")} for c in meta.get("columns", [])]


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", name)


def build_summary(out: Path, settings: Settings | None = None) -> dict:
    settings = settings or Settings()
    st = _load(out, "discovery_run_01_state.json") or {}
    env = st.get("environment", {})
    s: dict = {"summary_version": 1, "label": "SANITIZED - structural/aggregate only; contains no transaction rows",
               "gates_completed": st.get("completed_gates", []),
               "environment": {k: env.get(k) for k in ("driver", "version", "utc_now", "privileges") if k in env}}

    cube = _load(out, "cube_registry_discovery.json")
    if cube:
        lst = cube.get("list", {})
        cols = [c["COLUMN_NAME"] for c in lst.get("metadata", {}).get("columns", [])]
        dropped = [c for c in cols if SENSITIVE_COL.search(c)]
        rows = [{k: v for k, v in r.items() if k not in dropped} for r in lst.get("rows", [])
                if any(FINANCE_ROW.search(str(v)) for v in r.values() if v is not None)]
        s["cube_registry"] = {"discovered_at": cube.get("discovered_at"), "located": cube.get("located"),
                              "list_object": lst.get("list_object"), "columns": _cols(lst.get("metadata")),
                              "estimated_rows": lst.get("metadata", {}).get("estimated_rows"), "row_scope": lst.get("row_scope"),
                              "total_rows_read": len(lst.get("rows", [])), "finance_related_rows": rows[:MAX_LIST_ROWS],
                              "redacted_columns": dropped, "hint_checks": cube.get("hint_checks")}
    defs = _load(out, "pnl_definitions.json")
    if defs is not None:
        s["finance_reporting_objects"] = [
            {"pattern": d.get("pattern"), "owner": d.get("OWNER"), "name": d.get("OBJECT_NAME"), "type": d.get("OBJECT_TYPE"),
             "last_ddl_time": d.get("LAST_DDL_TIME"), "columns": _cols({"columns": d.get("columns", [])}),
             "view_sql": (d.get("view_sql") or "")[:MAX_VIEW_SQL] or None, "depends_on": d.get("depends_on")} for d in defs]

    ov = _load(out, "registry_overlay.json") or {}
    s["confirmed_mappings"] = {k: {"status": v.get("status"), "physical": v.get("physical"),
        "verification": v.get("evidence", {}).get("verification"), "verification_notes": v.get("evidence", {}).get("notes"),
        "evidence_row_index": v.get("evidence", {}).get("evidence_row_index"),
        "artifact_sha256": v.get("evidence", {}).get("artifact_sha256"),
        "confirmed_at": v.get("evidence", {}).get("confirmed_at")} for k, v in ov.items()}

    for tag, key in (("site_reg", "site_reg"), ("outstanding", "outstanding")):
        info = st.get(key)
        if not info:
            continue
        nm = _safe(info["object"])
        sec = {"registry_key": info["registry_key"], "object": info["object"], "access_mode": info.get("access_mode"),
               "discriminator_column": info.get("discriminator_column")}
        obj = _load(out, f"object_{nm}.json")
        if obj:
            sec.update(columns=_cols(obj), estimated_rows=obj.get("estimated_rows"), stats_last_analyzed=obj.get("stats_last_analyzed"))
        keys = _load(out, f"keys_{nm}.json")
        if keys:
            sec["key_candidates"] = keys
        prof = _load(out, f"profile_light_{nm}.json")
        if prof:
            sec["light_profile"] = {k: prof.get(k) for k in ("aggregates", "profiled_at", "sample_deterministic")}
            sec["roles"] = info.get("roles")
        grp = _load(out, f"group_{nm}.json")
        if grp:
            sec["release_status_groups"] = {k: grp.get(k) for k in ("group_column", "groups", "truncated", "profiled_at")}
        s[tag] = sec
    s["outstanding_candidates_in_cube_list"] = [
        {"row_index": c["row_index"], "row": {k: v for k, v in c["row"].items() if not SENSITIVE_COL.search(k)}}
        for c in st.get("outstanding_candidates") or []]
    s["query_log"] = st.get("query_log", [])
    s["data_queries_executed"] = [q for q in s["query_log"] if q.get("kind") != "METADATA"]

    text = json.dumps(s, indent=2, default=str)
    clean = redact(text, settings)
    if clean != text:
        s = json.loads(clean); s["redactions_applied"] = True
    return s


def write_summary(out: Path, settings: Settings | None = None) -> Path:
    path = out / SUMMARY_NAME
    path.write_text(json.dumps(build_summary(out, settings), indent=2, default=str))
    return path
