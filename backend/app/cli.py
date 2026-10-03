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
from app.registry.models import SEPARATE_OBJECT, SHARED_DISCRIMINATOR
from app.registry.resolver import apply_overlay, find, load_seed, validate_no_double_coverage

ROOT = Path(__file__).resolve().parents[2]
SEED = ROOT / "config" / "source_registry_seed.csv"
OUT_DIR = ROOT / "reports" / "generated"          # git-ignored
OVERLAY = OUT_DIR / "registry_overlay.json"


def redact(text: str, settings: Settings | None = None) -> str:
    s = settings or Settings()
    for secret in sorted(s.secret_values(), key=len, reverse=True):
        text = text.replace(secret, "***")
    return re.sub(r"(?i)\b(password|pwd|uid)\s*=\s*[^;\s]+", r"\1=***", text)


def _registry():
    entries = apply_overlay(load_seed(SEED), OVERLAY)
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
        for e in entries:
            phys = e.physical.display_name if e.physical else "-"
            print(f"{e.status:10} {e.registry_key:34} {e.financial_year or '-':8} physical={phys} "
                  f"hint={e.physical_hint or '-'} authoritative={e.authoritative}")
        print("NOTE: UNVERIFIED rows carry no physical object; nothing may query them until CONFIRMED.")
        return 0
    ora = _ora(settings, ora_factory)
    if ora is None:
        return 2
    if args.cmd == "oracle-check":
        print(f"driver={ora.driver if hasattr(ora, 'driver') else '?'}")
        print(ora.query("SELECT 1 AS ok FROM dual"))
        for label, q in (("user", "SELECT USER AS v FROM dual"),
                         ("version", "SELECT banner AS v FROM v$version WHERE ROWNUM = 1"),
                         ("utc_now", "SELECT TO_CHAR(SYS_EXTRACT_UTC(SYSTIMESTAMP), 'YYYY-MM-DD HH24:MI:SS') AS v FROM dual")):
            try:
                print(f"{label}: {ora.query(q)[0]['V']}")
            except Exception as e:   # v$version may not be granted; not an error
                print(f"{label}: unavailable ({type(e).__name__})")
        return 0
    from app.discovery import cube_registry as cr, definitions, profiler
    if args.cmd == "discover-cube-registry":
        loc = cr.locate_list(ora)
        out = {"located": loc, "label": "UNVERIFIED", "discovered_at": datetime.now(timezone.utc).isoformat()}
        if not loc:
            print("BLOCKED: OLAP_DATACUBE_LIST not visible to this account"); _emit("cube_registry_discovery", out); return 2
        first = loc[0]
        owner, name = (first["OWNER"], first["OBJECT_NAME"]) if first["kind"] == "object" else (first["TABLE_OWNER"], first["TABLE_NAME"])
        out["list"] = cr.inspect_list(ora, owner, name)
        out["hint_checks"] = cr.check_hints(ora, entries)
        _emit("cube_registry_discovery", out)
        print(f"UNVERIFIED: {len(out['list']['rows'])} list rows captured; review then run registry-confirm per copy")
        return 0
    if args.cmd == "discover-definitions":
        _emit("pnl_definitions", definitions.discover_definitions(ora, tuple(args.pattern) if args.pattern else definitions.DEFAULT_PATTERNS))
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
