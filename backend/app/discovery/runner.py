"""Gated live-discovery orchestrator (discovery-run-01). Each invocation runs EXACTLY ONE gate and stops.
It never auto-confirms a registry mapping, never runs DEEP profiling, never ingests.

 Gate 1  registry-status + oracle-check (+ privilege inspection)
 Gate 2  cube-registry discovery + finance reporting object definitions        -> operator reviews, runs registry-confirm
 Gate 3  (SITE_REG confirmed) object metadata + key metadata                    -> operator picks column roles
 Gate 4  (roles supplied)     ONE light profile of SITE_REG                     -> sample goes to LOCAL_ONLY file
 Gate 5  release-status group + OUTSTANDING mapping/metadata/keys               -> may need registry-add/confirm, then re-run
After every gate the sanitized LIVE_DISCOVERY_01_SUMMARY.json is regenerated."""
import json
import re
import time
from pathlib import Path

from app.discovery import cube_registry as cr
from app.discovery import definitions, environment, keys, profiler, summary
from app.redact import redact
from app.registry.models import PhysicalUnresolvedError, SourceEntry
from app.registry.resolver import format_status

STATE = "discovery_run_01_state.json"
LARGE_ROWS = 20_000_000
LOCAL_WARNING = "DO NOT SHARE / DO NOT COMMIT - MAY CONTAIN FINANCIAL TRANSACTION DATA"
_META = re.compile(r"\b(?:FROM|JOIN)\s+(?:(?:ALL|DBA|USER)_\w+|V\$\w+|SESSION_\w+|DUAL)\b", re.I)
_FROM = re.compile(r"\b(?:FROM|JOIN)\s+([\w\"$#.]+)", re.I)


def _safe(n: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", n)


def classify(sql: str) -> str:
    objs = _FROM.findall(sql)
    meta = [o for o in objs if re.match(r"(?i)^(ALL|DBA|USER)_\w+$|^V\$\w+$|^SESSION_\w+$|^DUAL$", o)]
    if objs and len(meta) == len(objs):
        return "METADATA"
    return "DATA_SAMPLE" if re.search(r"(?i)FETCH FIRST \d+ ROWS ONLY", sql) and "GROUP BY" not in sql.upper() and "COUNT(" not in sql.upper() else "DATA_AGGREGATE"


class Recorder:
    """Wraps the Oracle client; logs SQL text (never bind values), kind, seconds, row count."""
    def __init__(self, ora, gate: int):
        self.ora, self.gate, self.log = ora, gate, []
        self.driver = getattr(ora, "driver", "?")

    def query(self, sql, params=None):
        t0 = time.perf_counter()
        rows = self.ora.query(sql, params)
        self.log.append({"gate": self.gate, "kind": classify(sql), "sql": " ".join(sql.split())[:400],
                         "seconds": round(time.perf_counter() - t0, 3), "rows_returned": len(rows)})
        return rows


def load_state(out: Path) -> dict:
    p = out / STATE
    return json.loads(p.read_text()) if p.exists() else {"completed_gates": [], "query_log": []}


def _save(out: Path, st: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / STATE).write_text(json.dumps(st, indent=2, default=str))


def _write(out: Path, name: str, data) -> None:
    (out / f"{name}.json").write_text(json.dumps(data, indent=2, default=str))


def _site_entry(entries: list[SourceEntry], source_type: str, copy: str | None) -> SourceEntry:
    c = [e for e in entries if e.source_type == source_type and (copy is None and e.is_current or e.copy_id == copy)]
    if not c:
        raise LookupError(f"no {source_type} registry entry (copy={copy or 'current'}); pass --{source_type.lower().replace('_', '-')}-copy or registry-add")
    if len(c) > 1:
        raise LookupError(f"{source_type}: several candidates {[e.copy_id for e in c]}; pass the copy id")
    return c[0]


def run_gate(gate: int, *, ora, out: Path, load_entries, args: dict, echo=print, settings=None) -> int:
    out.mkdir(parents=True, exist_ok=True)
    st = load_state(out)
    done = set(st["completed_gates"])
    if gate > 1 and (gate - 1) not in done and not (gate == 5 and 4 in done):
        echo(f"STOP: gate {gate} requires gate {gate - 1} to be completed first (completed: {sorted(done) or 'none'}).")
        return 2
    rec = Recorder(ora, gate)
    try:
        rc = _GATES[gate](rec, out, st, load_entries, args, echo)
    except PhysicalUnresolvedError as e:
        echo(f"BLOCKED: {redact(str(e), settings)}"); rc = 2
    except Exception as e:
        echo(f"STOP: {type(e).__name__}: {redact(str(e), settings)}"); rc = 1
    st["query_log"] = [q for q in st.get("query_log", []) if q.get("gate") != gate] + rec.log
    if rc == 0:
        st["completed_gates"] = sorted(set(st["completed_gates"]) | {gate})
    _save(out, st)
    p = summary.write_summary(out, settings)
    data_q = [q for q in st["query_log"] if q["kind"] != "METADATA"]
    echo(f"summary refreshed: {p.name} (safe to share; {len(data_q)} data-table queries so far, "
         f"{sum(q['seconds'] for q in st['query_log']):.1f}s total Oracle time)")
    return rc


def gate1(ora, out, st, load_entries, args, echo):
    for line in format_status(load_entries()): echo(line)
    env = environment.check_environment(ora)
    st["environment"] = env
    echo(f"connected via {env['driver']}; user={env['user']}; version={env['version']}; utc={env['utc_now']}")
    p = env["privileges"]
    echo(f"privilege inspection: {p['status']}" + (f" -> {p['flagged_system_privileges']}" if p.get("flagged_system_privileges") else ""))
    if p.get("flagged_system_privileges"):
        echo("WARNING: account holds write-capable privileges. Ask the DBA for a SELECT-only account before continuing.")
    echo("GATE 1 COMPLETE. Next: discovery-run-01 --gate 2")
    return 0


def gate2(ora, out, st, load_entries, args, echo):
    art, ok = cr.discover_cube_registry(ora, load_entries())
    _write(out, "cube_registry_discovery", art)
    if not ok:
        echo("STOP: OLAP_DATACUBE_LIST not visible to this account."); return 2
    defs = definitions.discover_definitions(ora, definitions.DEFAULT_PATTERNS + definitions.CONTEXT_OBJECTS)
    _write(out, "pnl_definitions", defs)
    echo(f"cube list: {len(art['list']['rows'])} rows, columns={[c['COLUMN_NAME'] for c in art['list']['metadata']['columns']]}")
    echo(f"finance reporting objects found: {len(defs)}")
    echo("GATE 2 COMPLETE. STOP and REVIEW reports/generated/cube_registry_discovery.json.")
    echo("Then confirm SITE_REG current copy yourself:  registry-confirm SITE_REG --copy <ID> --object OWNER.NAME "
         "--evidence-file <that json> --evidence-row N [--access-mode shared ...]   (never auto-confirmed)")
    echo("Then: discovery-run-01 --gate 3")
    return 0


def gate3(ora, out, st, load_entries, args, echo):
    e = _site_entry(load_entries(), "SITE_REG", args.get("site_copy"))
    p = e.require_physical()                       # BLOCKED if not CONFIRMED
    t = profiler.Target.from_physical(p)
    meta = {"label": "CONFIRMED mapping", **profiler.table_metadata(ora, t)}
    k = keys.discover_keys(ora, t.owner, t.name, discriminator_column=p.discriminator_column)
    nm = _safe(t.name)
    _write(out, f"object_{nm}", meta); _write(out, f"keys_{nm}", k)
    st["site_reg"] = {"registry_key": e.registry_key, "object": t.name, "access_mode": p.access_mode,
                      "discriminator_column": p.discriminator_column, "columns": [c["COLUMN_NAME"] for c in meta["columns"]]}
    echo(f"{e.registry_key} -> {p.display_name} [{p.access_mode}]; estimated rows={meta['estimated_rows']} analyzed={meta['stats_last_analyzed']}")
    for c in meta["columns"]: echo(f"  {c['COLUMN_NAME']:32} {c['DATA_TYPE']}")
    echo(f"key metadata: {k['recommendation']} ({len(k['candidates'])} candidates) - {k['note']}")
    echo("GATE 3 COMPLETE. STOP. Choose column roles from the list above, then run gate 4 with:")
    echo("  --date-col X --debit-col X --credit-col X --site-col X --gl-col X [--sl-col X] [--release-col X]")
    return 0


def _resolve_cols(st_cols: list[str], args: dict, required: tuple, optional: tuple) -> dict:
    by_up = {c.upper(): c for c in st_cols}
    roles, missing = {}, [r for r in required if not args.get(r)]
    if missing:
        raise ValueError("gate 4 needs explicit column roles: " + ", ".join("--" + m.replace("_", "-") for m in missing))
    for r in (*required, *optional):
        if args.get(r):
            c = by_up.get(args[r].upper())
            if not c: raise ValueError(f"--{r.replace('_', '-')} {args[r]!r} is not a column of the SITE_REG object")
            roles[r] = c
    return roles


def gate4(ora, out, st, load_entries, args, echo):
    info = st.get("site_reg")
    roles = _resolve_cols(info["columns"], args, ("date_col", "debit_col", "credit_col", "site_col", "gl_col"), ("sl_col", "release_col"))
    e = _site_entry(load_entries(), "SITE_REG", args.get("site_copy"))
    t = profiler.Target.from_physical(e.require_physical())
    nm = _safe(t.name)
    est = (json.loads((out / f"object_{nm}.json").read_text()).get("estimated_rows")) or 0
    if est > LARGE_ROWS and not args.get("allow_large"):
        echo(f"STOP: optimizer estimates {est:,} rows (> {LARGE_ROWS:,}). Review with the DBA/off-peak, then re-run with --allow-large."); return 2
    distinct = tuple(roles[r] for r in ("site_col", "gl_col", "sl_col") if r in roles)
    prof = profiler.profile_light(ora, t, date_col=roles["date_col"], debit_col=roles["debit_col"], credit_col=roles["credit_col"],
                                  distinct_cols=distinct, exact_count=True, sample=int(args.get("sample") or 5))
    sample = prof.pop("sample_rows")
    _write(out, f"LOCAL_ONLY_{nm}_sample", {"WARNING": LOCAL_WARNING, "object": t.name, "sample_rows": sample})
    _write(out, f"profile_light_{nm}", prof)
    st["site_reg"]["roles"] = roles
    a = prof["aggregates"]
    echo(f"rows={a['N']} date {a['DMIN']} .. {a['DMAX']} debit={a['DEBIT']} credit={a['CREDIT']}")
    for k_, v in a.items():
        if k_.startswith("DISTINCT_"): echo(f"  {k_.lower()}: {v}")
    echo(f"sample rows written to LOCAL_ONLY_{nm}_sample.json  ** {LOCAL_WARNING} **")
    echo("GATE 4 COMPLETE. STOP. Next: discovery-run-01 --gate 5")
    return 0


def gate5(ora, out, st, load_entries, args, echo):
    info = st["site_reg"]; roles = info["roles"]
    entries = load_entries()
    e = _site_entry(entries, "SITE_REG", args.get("site_copy"))
    t = profiler.Target.from_physical(e.require_physical()); nm = _safe(t.name)
    rel = roles.get("release_col")
    if rel and not st.get("release_group_done"):
        g = profiler.profile_group(ora, t, rel, debit_col=roles["debit_col"], credit_col=roles["credit_col"])
        _write(out, f"group_{nm}", g); st["release_group_done"] = True
        echo(f"release-status groups on {rel}: {len(g['groups'])}{' (TRUNCATED)' if g['truncated'] else ''}")
        for r in g["groups"]: echo(f"  {r['GRP']!s:20} n={r['N']} debit={r.get('DEBIT')} credit={r.get('CREDIT')}")
    elif not rel:
        echo("no --release-col chosen at gate 4: release-status aggregate skipped")
    outs = [x for x in entries if x.source_type == "OUTSTANDING"]
    conf = [x for x in outs if x.physical_resolved]
    if not conf:
        cube = json.loads((out / "cube_registry_discovery.json").read_text())
        cand = [{"row_index": i, "row": r} for i, r in enumerate(cube["list"]["rows"])
                if any("FINOTSD" in str(v).upper() for v in r.values() if v is not None)]
        st["outstanding_candidates"] = cand[:50]
        echo(f"OUTSTANDING has no CONFIRMED mapping. Candidate OLAP_DATACUBE_LIST rows mentioning FINOTSD: {len(cand)}")
        for c in cand[:20]: echo(f"  row {c['row_index']}: {c['row']}")
        echo("Add and confirm it yourself, then re-run gate 5:")
        echo("  registry-add --source-type OUTSTANDING --logical-cube CUBE$FINOTSD --copy-id <ID> --date-from YYYY-MM-DD --date-to YYYY-MM-DD")
        echo("  registry-confirm OUTSTANDING --copy <ID> --object OWNER.NAME --evidence-file ... --evidence-row N")
        echo("GATE 5 PARTIAL (SITE_REG release groups done). STOP."); return 3
    o = conf[0]; op = o.require_physical(); ot = profiler.Target.from_physical(op); on = _safe(ot.name)
    meta = {"label": "CONFIRMED mapping", **profiler.table_metadata(ora, ot)}
    k = keys.discover_keys(ora, ot.owner, ot.name, discriminator_column=op.discriminator_column)
    _write(out, f"object_{on}", meta); _write(out, f"keys_{on}", k)
    st["outstanding"] = {"registry_key": o.registry_key, "object": ot.name, "access_mode": op.access_mode,
                         "discriminator_column": op.discriminator_column, "columns": [c["COLUMN_NAME"] for c in meta["columns"]]}
    echo(f"OUTSTANDING {o.registry_key} -> {op.display_name}; estimated rows={meta['estimated_rows']}")
    for c in meta["columns"]: echo(f"  {c['COLUMN_NAME']:32} {c['DATA_TYPE']}")
    echo(f"key metadata: {k['recommendation']}")
    echo("GATE 5 COMPLETE. STOP. Share reports/generated/LIVE_DISCOVERY_01_SUMMARY.json only. No ageing logic has been built.")
    return 0


_GATES = {1: gate1, 2: gate2, 3: gate3, 4: gate4, 5: gate5}


def next_gate(out: Path) -> int:
    done = set(load_state(out)["completed_gates"])
    for g in (1, 2, 3, 4, 5):
        if g not in done: return g
    return 5
