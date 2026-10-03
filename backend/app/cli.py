"""Controlled discovery CLI.  python -m app.cli <command> --help

Commands (all Oracle access is SELECT-only; outputs labelled CONFIRMED / UNVERIFIED / BLOCKED,
never contain credentials):
  registry-status                      merged seed + local overlay, with physical resolution state
  oracle-check                         connectivity test (SELECT 1 FROM dual)
  discover-cube-registry               OLAP_DATACUBE_LIST -> columns, finance rows, hint existence checks
  discover-object SOURCE [--copy ID] [--object OWNER.NAME]
                                       metadata only (columns + stats estimate), no table scan
  profile-source SOURCE --copy ID --mode light|deep [--date-col C --debit-col C --credit-col C ...]
  discover-definitions [--pattern P ...]   P&L-related view/table definitions (metadata only)
  discover-keys SOURCE [--copy ID]      PK/unique constraint + unique index candidates (metadata only, no row scan)
  profile-group SOURCE --copy ID --group-col C [--debit-col C --credit-col C]   one aggregate scan, ONE dimension, max 100 groups
  registry-add --source-type T --logical-cube N --copy-id ID --date-from D --date-to D   local UNVERIFIED entry (e.g. OUTSTANDING)
  discovery-run-01 [--gate 1..5 ...]    gated orchestrator: runs ONE gate, then stops (see docs/DATA_DISCOVERY.md)
  registry-confirm SOURCE --copy ID --object OWNER.NAME --evidence-file F --evidence-row N
                   [--access-mode separate|shared  (shared needs --discriminator-column and --discriminator-value)]
                   evidence-file = a cube_registry_discovery.json produced by discover-cube-registry;
                   evidence-row  = 0-based index into its list.rows. Result is MACHINE_VERIFIED or OPERATOR_CONFIRMED.
"""
import argparse
import json
from datetime import datetime, timezone
import re
import sys
from pathlib import Path

from app.config import Settings
from app.redact import redact
from app.registry.models import SEPARATE_OBJECT, SHARED_DISCRIMINATOR
from app.registry.resolver import (apply_overlay, find, format_status, load_local_entries, load_seed,
                                   validate_no_double_coverage)

ROOT = Path(__file__).resolve().parents[2]
SEED = ROOT / "config" / "source_registry_seed.csv"
OUT_DIR = ROOT / "reports" / "generated"          # git-ignored
OVERLAY = OUT_DIR / "registry_overlay.json"


def _registry():
    entries = apply_overlay(load_seed(SEED) + load_local_entries(OUT_DIR / "local_entries.json"), OVERLAY)
    validate_no_double_coverage(entries)
    return entries


def _ora(settings: Settings, factory=None):
    if factory:
        return factory()
    if not settings.oracle_configured:
        print("BLOCKED: no Oracle connection configured (set ORACLE_ODBC_DSN, or ORACLE_DSN/ORACLE_USER/ORACLE_PASSWORD; use a SELECT-only account)")
        return None
    from app.oracle.client import OracleReadOnly
    return OracleReadOnly(settings)


def _emit(name: str, data) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    p = OUT_DIR / f"{name}.json"
    p.write_text(json.dumps(data, indent=2, default=str))
    try:
        shown = p.relative_to(ROOT)
    except ValueError:
        shown = p
    print(f"wrote {shown} (git-ignored; do not commit)")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="fpa", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("registry-status"); sub.add_parser("oracle-check"); sub.add_parser("discover-cube-registry")
    d = sub.add_parser("discover-object"); d.add_argument("source"); d.add_argument("--copy"); d.add_argument("--object")
    p = sub.add_parser("profile-source"); p.add_argument("source"); p.add_argument("--copy", required=True)
    p.add_argument("--mode", choices=["light", "deep"], default="light")
    p.add_argument("--date-col"); p.add_argument("--debit-col"); p.add_argument("--credit-col")
    p.add_argument("--distinct-col", action="append", default=[]); p.add_argument("--exact-count", action="store_true")
    p.add_argument("--sample", type=int, default=5); p.add_argument("--sample-order-by")
    f = sub.add_parser("discover-definitions"); f.add_argument("--pattern", action="append")
    c = sub.add_parser("registry-confirm"); c.add_argument("source"); c.add_argument("--copy", required=True)
    c.add_argument("--object", required=True); c.add_argument("--evidence-file", required=True)
    c.add_argument("--evidence-row", type=int, required=True)
    c.add_argument("--access-mode", choices=["separate", "shared"], default="separate")
    c.add_argument("--discriminator-column"); c.add_argument("--discriminator-value")
    c.add_argument("--confirmed-by", default="operator")
    k = sub.add_parser("discover-keys"); k.add_argument("source"); k.add_argument("--copy"); k.add_argument("--object")
    g = sub.add_parser("profile-group"); g.add_argument("source"); g.add_argument("--copy", required=True)
    g.add_argument("--group-col", required=True); g.add_argument("--debit-col"); g.add_argument("--credit-col")
    a = sub.add_parser("registry-add"); a.add_argument("--source-type", required=True); a.add_argument("--logical-cube", required=True)
    a.add_argument("--copy-id", required=True); a.add_argument("--date-from", required=True); a.add_argument("--date-to", required=True)
    a.add_argument("--financial-year"); a.add_argument("--current", action="store_true")
    r = sub.add_parser("discovery-run-01"); r.add_argument("--gate", type=int, choices=[1, 2, 3, 4, 5])
    r.add_argument("--site-copy")
    for opt in ("date", "debit", "credit", "site", "gl", "sl", "release"): r.add_argument(f"--{opt}-col")
    r.add_argument("--sample", type=int, default=5); r.add_argument("--allow-large", action="store_true")
    return ap


def main(argv: list[str], ora_factory=None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings()
    try:
        return _run(args, settings, ora_factory)
    except Exception as e:   # never leak connection strings
        print(f"ERROR: {type(e).__name__}: {redact(str(e), settings)}"); return 1


def _run(args, settings, ora_factory) -> int:
    entries = _registry()
    if args.cmd == "registry-status":
        for line in format_status(entries): print(line)
        print("NOTE: UNVERIFIED rows carry no physical object; nothing may query them until CONFIRMED.")
        return 0
    if args.cmd == "registry-add":
        p = OUT_DIR / "local_entries.json"; OUT_DIR.mkdir(parents=True, exist_ok=True)
        cur = json.loads(p.read_text()) if p.exists() else []
        rec = {"source_type": args.source_type.upper(), "logical_cube_name": args.logical_cube.upper(), "copy_id": args.copy_id,
               "financial_year": args.financial_year, "date_from": args.date_from, "date_to": args.date_to, "is_current": args.current}
        cur.append(rec); p.write_text(json.dumps(cur, indent=2))
        try:
            _registry()
        except Exception:
            p.write_text(json.dumps(cur[:-1], indent=2)); raise     # roll back an entry that overlaps existing coverage
        print(f"added UNVERIFIED local entry {rec['source_type']}|{rec['logical_cube_name']}|{rec['copy_id']} (git-ignored)"); return 0
    ora = _ora(settings, ora_factory)
    if ora is None:
        return 2
    if args.cmd == "oracle-check":
        from app.discovery.environment import check_environment
        env = check_environment(ora)
        print(f"driver={env['driver']} user={env['user']} version={env['version']} utc={env['utc_now']}")
        p = env["privileges"]; print(f"privileges: {p['status']} {p.get('flagged_system_privileges') or ''}")
        return 0
    from app.discovery import cube_registry as cr, definitions, profiler
    if args.cmd == "discovery-run-01":
        from app.discovery import runner
        gate = args.gate or runner.next_gate(OUT_DIR)
        opts = {k: getattr(args, k) for k in ("site_copy", "date_col", "debit_col", "credit_col", "site_col", "gl_col", "sl_col",
                                              "release_col", "sample", "allow_large")}
        return runner.run_gate(gate, ora=ora, out=OUT_DIR, load_entries=_registry, args=opts, settings=settings)
    if args.cmd == "discover-cube-registry":
        out, ok = cr.discover_cube_registry(ora, entries)
        _emit("cube_registry_discovery", out)
        if not ok:
            print("BLOCKED: OLAP_DATACUBE_LIST not visible to this account"); return 2
        print(f"UNVERIFIED: {len(out['list']['rows'])} list rows captured; review then run registry-confirm per copy")
        return 0
    if args.cmd == "discover-definitions":
        _emit("pnl_definitions", definitions.discover_definitions(ora, tuple(args.pattern) if args.pattern else definitions.DEFAULT_PATTERNS + definitions.CONTEXT_OBJECTS))
        return 0
    entry = find(entries, args.source, getattr(args, "copy", None))
    if args.cmd == "discover-object":
        if args.object:
            owner, _, name = args.object.partition(".")
            t = profiler.Target(owner.upper(), name.upper()); lab = "UNVERIFIED (operator-supplied object)"
        else:
            t = profiler.Target.from_physical(entry.require_physical()); lab = "CONFIRMED mapping"
        _emit(f"object_{t.name}", {"label": lab, **profiler.table_metadata(ora, t)}); return 0
    if args.cmd == "profile-source":
        t = profiler.Target.from_physical(entry.require_physical())   # BLOCKED via PhysicalUnresolvedError if unresolved
        kw = dict(date_col=args.date_col, debit_col=args.debit_col, credit_col=args.credit_col,
                  distinct_cols=tuple(args.distinct_col), exact_count=args.exact_count,
                  sample=args.sample, sample_order_by=args.sample_order_by)
        prof = (profiler.profile_deep if args.mode == "deep" else profiler.profile_light)(ora, t, **kw)
        _emit(f"profile_{args.mode}_{t.name}", {"registry_key": entry.registry_key, **prof}); return 0
    if args.cmd == "discover-keys":
        if args.object:
            owner, _, name = args.object.partition("."); t = profiler.Target(owner.upper(), name.upper()); lab = "UNVERIFIED (operator-supplied object)"
        else:
            t = profiler.Target.from_physical(entry.require_physical()); lab = "CONFIRMED mapping"
        from app.discovery.keys import discover_keys
        res = discover_keys(ora, t.owner, t.name, discriminator_column=t.discriminator[0] if t.discriminator else None)
        _emit(f"keys_{t.name}", {"label": lab, **res}); print(f"{res['recommendation']}: {res['note']}"); return 0
    if args.cmd == "profile-group":
        t = profiler.Target.from_physical(entry.require_physical())
        res = profiler.profile_group(ora, t, args.group_col, debit_col=args.debit_col, credit_col=args.credit_col)
        _emit(f"group_{t.name}_{args.group_col}", {"registry_key": entry.registry_key, **res}); return 0
    if args.cmd == "registry-confirm":
        owner, _, name = args.object.partition(".")
        mode = SHARED_DISCRIMINATOR if args.access_mode == "shared" else SEPARATE_OBJECT
        rec = cr.confirm_mapping(ora, entry, owner.upper(), name.upper(), access_mode=mode,
                                 discriminator_column=args.discriminator_column.upper() if args.discriminator_column else None,
                                 discriminator_value=args.discriminator_value,
                                 evidence_file=args.evidence_file, evidence_row=args.evidence_row, confirmed_by=args.confirmed_by)
        ov = json.loads(OVERLAY.read_text()) if OVERLAY.exists() else {}
        cr.assert_not_already_mapped(ov, entry.registry_key, rec["physical"])
        ov[entry.registry_key] = rec; _emit("registry_overlay", ov)
        print(f"CONFIRMED ({rec['evidence']['verification']}) {entry.registry_key} -> {owner.upper()}.{name.upper()} [{mode}]")
        for n in rec["evidence"]["notes"]:
            print(f"  note: {n}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
