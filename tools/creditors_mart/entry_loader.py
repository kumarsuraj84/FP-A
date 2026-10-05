"""
Entry-layer loader: one validated, immutable run folder -> schema `entry`, in ONE transaction, never promoted.

    python tools/creditors_mart/entry_loader.py load   data/inbox/run_YYYYMMDD_NNN
    python tools/creditors_mart/entry_loader.py verify run_YYYYMMDD_NNN

Rules (each covered by tests/test_entry_mart.py):
  * PREFLIGHT touches no database: manifest and file hashes, the staging report (PASSED, hash chain), and a full re-derivation from the raw extract that must equal the
    derived Parquet exactly (a tampered derived file is refused even if the report hash was re-sealed).
  * It connects only through a login that is a member of entry_loader and of no other role; never a superuser, postgres or an owner.
  * Source -> extract controls come from the staging report; extract -> mart controls are computed in SQL and compared; then the structural checks and the cross-domain
    checks (bank lines = the cash review card, till = the cash card, bills = the creditors run, one snapshot) must all be clean, or EVERY row of the run is rolled back.
  * It never promotes.
  * TELEMETRY IS METADATA-ONLY. Narration, references, cheque fields, preparer / releaser names, sub-ledger codes and entry numbers are written to the restricted
    Finance table and nowhere else: not to logs, reports, control evidence, rejection records, exceptions or console output. Messages carry counts and control ids only.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "extraction_broker"))
sys.path.insert(0, str(HERE))
import entry_stage as es  # noqa: E402
import manifest as mf  # noqa: E402

log = logging.getLogger("entry_loader")
ZERO = Decimal(0)
RUN_ID = re.compile(r"^run_[0-9]{8}_[0-9]{3}$")
PROTECTED_DB = {"fpa", "postgres", "template0", "template1"}
FORBIDDEN_LOGINS = {"postgres", "entry_owner", "entry_promoter", "entry_verifier", "entry_api_reader", "entry_finance_reader", "cash_owner", "cred_owner", "fpa_app", "admin"}
OTHER_ROLES = ["entry_owner", "entry_promoter", "entry_verifier", "entry_api_reader", "entry_finance_reader", "cash_owner", "cash_loader", "cash_promoter", "cash_verifier", "cash_api_reader",
               "cred_owner", "cred_loader", "cred_promoter", "cred_verifier", "cred_api_reader", "cred_finance_reader"]
SECRET_FILE = HERE.parents[1] / ".secrets" / "entry_loader.env"
SELECTIONS = ("creditors_cur", "creditors_old", "bank")

HEADER_COLUMNS = ["entry_run_id", "entry_ref", "site_code", "entry_type_short", "entry_type_long", "entry_date", "release_status", "line_count", "total_dr", "total_cr", "selections"]
LINE_COLUMNS = ["entry_run_id", "entry_ref", "line_no", "source_seq", "ledger_code", "ledger_name", "ledger_nature", "sub_ledger_ref", "debit", "credit", "release_status", "cube_name"]
IDENTITY_COLUMNS = ["entry_run_id", "entry_ref", "site_code", "entry_type_short", "entry_no", "created_by_site"]
TEXT_COLUMNS = ["entry_run_id", "entry_ref", "line_no", "sub_ledger_code", "narration", "reference_no", "reference_date", "cheque_no", "cheque_date", "counter_ledgers", "prepared_by", "prepared_on",
                "modified_by", "modified_on", "released_by", "released_on"]
LINK_COLUMNS = ["entry_run_id", "creditors_run_id", "source_row_key", "ledger_code", "bill_amount", "link_status", "not_linked_reason", "key_used", "matched_entries", "entry_ref", "entry_net_amount", "amount_agrees", "coverage"]
TILL_COLUMNS = ["entry_run_id", "cash_run_id", "site_code", "day", "debit", "credit", "cumulative_balance"]


class LoadError(Exception):
    def __init__(self, stage: str, reason: str, failed: dict | None = None):
        super().__init__(f"{stage}: {reason}")
        self.stage, self.reason, self.failed = stage, reason, failed or {}


class AlreadyLoaded(Exception):
    pass


def _read_env_file(path: Path) -> dict:
    out = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return out


def loader_conninfo() -> str | None:
    from psycopg.conninfo import make_conninfo

    url = os.environ.get("FPA_ENTRY_LOADER_URL")
    if url:
        return url
    cfg = _read_env_file(Path(os.environ.get("FPA_ENTRY_LOADER_ENV", SECRET_FILE)))
    if cfg.get("password"):
        return make_conninfo(host=cfg.get("host", "localhost"), port=cfg.get("port", "5432"), dbname=cfg.get("dbname", "fpa_pilot"), user=cfg.get("user", ""), password=cfg["password"])
    if not sys.stdin.isatty():
        return None
    import getpass

    try:
        host = input("PostgreSQL host [localhost]: ").strip() or "localhost"
        port = input("Port [5432]: ").strip() or "5432"
        dbname = input("Database [fpa_pilot]: ").strip() or "fpa_pilot"
        user = input("Loader login (a member of entry_loader): ").strip()
        password = getpass.getpass("Password (hidden, not stored): ")
    except (EOFError, KeyboardInterrupt):
        return None
    return make_conninfo(host=host, port=port, dbname=dbname, user=user, password=password)


def sub_ledger_ref(salt: str, code: str | None) -> str | None:
    """The same pseudonym the creditors mart uses for a vendor, so a masked entry line and a masked vendor agree. Empty sub-ledger -> no reference."""
    if not code:
        return None
    import loader as cred_loader

    return cred_loader.vendor_ref(salt, str(code))


def salt_value() -> str:
    import loader as cred_loader

    try:
        return cred_loader.vendor_ref_salt()
    except cred_loader.LoadError as e:
        raise LoadError("precheck", e.reason) from None


def assert_loader_identity(conn) -> str:
    row = conn.execute(
        "SELECT current_user, (SELECT rolsuper FROM pg_roles WHERE rolname = current_user), pg_has_role(current_user, 'entry_loader', 'MEMBER'), "
        "ARRAY(SELECT r FROM unnest(%s::text[]) r WHERE pg_has_role(current_user, r, 'MEMBER'))", (OTHER_ROLES,)).fetchone()
    who, is_super, is_loader, others = row
    if who in FORBIDDEN_LOGINS or is_super:
        raise LoadError("precheck", f"refusing to load as '{who}' (superuser or privileged/other-application role)")
    if not is_loader:
        raise LoadError("precheck", f"'{who}' is not a member of entry_loader")
    if others:
        raise LoadError("precheck", f"'{who}' also holds other roles ({', '.join(others)}): the loader must hold entry_loader only")
    return who


@dataclass
class Plan:
    run_id: str
    run_dir: Path
    manifest_sha256: str
    report_sha256: str
    register_report_date: str
    till_balance_date: str
    creditors_run_id: str
    cash_run_id: str
    contract: dict
    extract_started_at: str
    extract_finished_at: str
    data: tuple
    source_controls: list
    expected: dict = field(default_factory=dict)


def _pq(path: Path) -> list[dict]:
    import pyarrow.parquet as pq

    return pq.read_table(path).to_pylist()


def preflight(run_dir: Path | str, creditors_run_id: str, cash_run_id: str, salt: str) -> Plan:
    run_dir = Path(run_dir)
    if not RUN_ID.match(run_dir.name):
        raise LoadError("precheck", "not a run folder name")
    v = mf.validate_manifest(run_dir)
    if not v.ok:
        raise LoadError("precheck", f"manifest invalid ({len(v.errors)} problems)")
    manifest_sha = mf.sha256_file(run_dir / "manifest.json")
    m = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    if m.get("package") != "entry_pilot_01":
        raise LoadError("precheck", "not an entry_pilot_01 run")
    rep_path = run_dir / "staging" / "validation_report.json"
    if not rep_path.exists():
        raise LoadError("staging_report", "no staging report: run entry_stage.py first")
    rep = json.loads(rep_path.read_text(encoding="utf-8"))
    if rep.get("verdict") != "PASSED" or rep.get("hard_failures"):
        raise LoadError("staging_report", f"staging verdict is {rep.get('verdict')}")
    if rep.get("manifest_sha256") != manifest_sha:
        raise LoadError("staging_report", "the staging report does not belong to this manifest")
    names = ["entry_header", "entry_line", "entry_identity", "entry_line_text", "creditor_bill_link", "till_day"]
    for n in names:
        p = run_dir / "staging" / f"{n}.parquet"
        if not p.exists() or mf.sha256_file(p) != rep["outputs"][n]:
            raise LoadError("staging_report", f"{n}.parquet does not match the staging report hash")
    try:                                                      # full re-derivation from the raw extract; it must equal the derived files exactly
        fresh = es.validate(run_dir, write=False)
    except es.StageError:
        raise LoadError("staging_report", "the raw extract can no longer be re-derived") from None
    if fresh["verdict"] != "PASSED" or fresh.get("derived") is None:
        raise LoadError("staging_report", "the raw extract no longer passes validation")
    derived = dict(zip(names, fresh["derived"]))
    key = {"entry_header": "entry_ref", "entry_line": ("entry_ref", "line_no"), "entry_identity": "entry_ref", "entry_line_text": ("entry_ref", "line_no"), "creditor_bill_link": "source_row_key", "till_day": ("site_code", "day")}
    data = []
    for n in names:
        k = key[n]
        kf = (lambda r: tuple(r[x] for x in k)) if isinstance(k, tuple) else (lambda r: r[k])
        got = {kf(r): r for r in _pq(run_dir / "staging" / f"{n}.parquet")}
        want = {kf(r): r for r in derived[n]}
        if got.keys() != want.keys() or any(got[x] != want[x] for x in got):
            raise LoadError("staging_report", f"the derived {n} rows differ from the raw extract")
        data.append(derived[n])
    agg = rep["aggregates"]
    expected = {("E_headers", "count"): Decimal(agg["entries"]), ("E_lines", "count"): Decimal(agg["lines"]), ("E_totals", "total_dr"): Decimal(agg["total_dr"]), ("E_totals", "total_cr"): Decimal(agg["total_cr"]),
                ("E_links", "count"): Decimal(agg["links"]), ("E_till_days", "count"): Decimal(agg["till_days"])}
    for sel, n in agg["lines_by_selection"].items():
        expected[("E_lines_by_selection", sel)] = Decimal(n)
    for status in ("EXACT", "STRONG", "AMBIGUOUS", "NOT_LINKED"):
        expected[("E_links_by_status", status)] = Decimal(agg["links_by_status"].get(status, 0))
    for cover in ("CURRENT_FY", "PRIOR_YEARS_IN_COVERAGE", "BEFORE_COVERAGE"):
        expected[("E_links_by_coverage", cover)] = Decimal(agg["links_by_coverage"].get(cover, 0))
    times = [d.get("extracted_at") for d in m["datasets"] if d.get("extracted_at")]
    return Plan(run_dir.name, run_dir, manifest_sha, mf.sha256_file(rep_path), agg["register_report_date"], agg["till_balance_date"], creditors_run_id, cash_run_id, m["contract"],
                min(times), max(times), tuple(data), rep["controls"], expected)


def dims_from_db(conn, run_id: str) -> dict:
    one = lambda q, *p: conn.execute(q, p).fetchone()  # noqa: E731
    out = {}
    h = one("SELECT count(*), coalesce(sum(total_dr), 0), coalesce(sum(total_cr), 0) FROM entry.entry_header WHERE entry_run_id = %s", run_id)
    out[("E_headers", "count")], out[("E_totals", "total_dr")], out[("E_totals", "total_cr")] = Decimal(h[0]), Decimal(h[1]), Decimal(h[2])
    out[("E_lines", "count")] = Decimal(one("SELECT count(*) FROM entry.entry_line WHERE entry_run_id = %s", run_id)[0])
    for sel in SELECTIONS:
        out[("E_lines_by_selection", sel)] = Decimal(one("SELECT count(*) FROM entry.entry_line l JOIN entry.entry_header h USING (entry_run_id, entry_ref) WHERE l.entry_run_id = %s AND %s = ANY(h.selections)", run_id, sel)[0])
    out[("E_links", "count")] = Decimal(one("SELECT count(*) FROM entry.creditor_bill_link WHERE entry_run_id = %s", run_id)[0])
    by = dict(conn.execute("SELECT link_status, count(*) FROM entry.creditor_bill_link WHERE entry_run_id = %s GROUP BY 1", (run_id,)).fetchall())
    for s in ("EXACT", "STRONG", "AMBIGUOUS", "NOT_LINKED"):
        out[("E_links_by_status", s)] = Decimal(by.get(s, 0))
    cv = dict(conn.execute("SELECT coverage, count(*) FROM entry.creditor_bill_link WHERE entry_run_id = %s GROUP BY 1", (run_id,)).fetchall())
    for c in ("CURRENT_FY", "PRIOR_YEARS_IN_COVERAGE", "BEFORE_COVERAGE"):
        out[("E_links_by_coverage", c)] = Decimal(cv.get(c, 0))
    out[("E_till_days", "count")] = Decimal(one("SELECT count(*) FROM entry.till_day WHERE entry_run_id = %s", run_id)[0])
    return out


def safe_reason(e: BaseException) -> str:
    """The error class, SQLSTATE, constraint and table name. Never the DETAIL or the value-bearing message (they carry row values, which here could include narration).
    Only access/syntax errors (SQLSTATE class 42) also give their message: it names an object and never contains a row value."""
    diag = getattr(e, "diag", None)
    parts = [type(e).__name__]
    if diag is not None:
        code = getattr(diag, "sqlstate", None)
        if code:
            parts.append(f"sqlstate {code}")
        for attr, label in (("constraint_name", "constraint"), ("table_name", "table")):
            v = getattr(diag, attr, None)
            if v:
                parts.append(f"{label} {v}")
        if code and str(code).startswith("42") and getattr(diag, "message_primary", None):
            parts.append(str(diag.message_primary)[:120])
    return " ".join(parts)


def record_rejection(conn, run_id: str, manifest_sha: str | None, stage: str, reason: str, failed: dict | None) -> None:
    try:
        conn.execute("INSERT INTO entry.load_rejection (entry_run_id, manifest_sha256, stage, reason, failed_controls) VALUES (%s,%s,%s,%s,%s)", (run_id, manifest_sha, stage, reason[:300], json.dumps(failed or {})))
    except Exception as e:  # noqa: BLE001
        log.warning("could not record the rejection (%s)", safe_reason(e))


def _copy(conn, table: str, columns: list[str], rows) -> int:
    n = 0
    with conn.cursor() as cur, cur.copy(f"COPY entry.{table} ({', '.join(columns)}) FROM STDIN") as cp:
        for r in rows:
            cp.write_row(r)
            n += 1
    return n


def load_run(conn, plan: Plan, salt: str) -> dict:
    who = assert_loader_identity(conn)
    t0 = time.monotonic()
    run_id = plan.run_id
    prior = conn.execute("SELECT entry_run_id, manifest_sha256 FROM entry.run WHERE entry_run_id = %s OR manifest_sha256 = %s", (run_id, plan.manifest_sha256)).fetchall()
    if prior:
        if len(prior) == 1 and prior[0][0] == run_id and prior[0][1] == plan.manifest_sha256:
            raise AlreadyLoaded(run_id)
        record_rejection(conn, run_id, plan.manifest_sha256, "precheck", "this run id or this manifest is already loaded with different content", None)
        raise LoadError("precheck", "this run id or this manifest is already loaded with different content")
    headers, lines, identity, texts, links, till = plan.data
    try:
        import psycopg

        with conn.transaction():
            c = plan.contract
            conn.execute(
                "INSERT INTO entry.run (entry_run_id, register_report_date, creditors_run_id, cash_run_id, till_balance_date, coverage_from, package, contract_version, rules, manifest_sha256, staging_report_sha256,"
                " extract_started_at, extract_finished_at, expected_headers, expected_lines, expected_links, expected_till_days) VALUES (%s,%s,%s,%s,%s,%s,'entry_pilot_01',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (run_id, plan.register_report_date, plan.creditors_run_id, plan.cash_run_id, plan.till_balance_date, c["coverage_from"], c["contract"], json.dumps({k: v for k, v in c.items() if k != "caps"}),
                 plan.manifest_sha256, plan.report_sha256, plan.extract_started_at, plan.extract_finished_at, len(headers), len(lines), len(links), len(till)))
            _copy(conn, "entry_header", HEADER_COLUMNS, ([run_id] + [h[k] for k in HEADER_COLUMNS[1:]] for h in headers))
            slc = {(t["entry_ref"], t["line_no"]): t["sub_ledger_code"] for t in texts}
            _copy(conn, "entry_line", LINE_COLUMNS, ([run_id] + [sub_ledger_ref(salt, slc[(l["entry_ref"], l["line_no"])]) if k == "sub_ledger_ref" else l[k] for k in LINE_COLUMNS[1:]] for l in lines))
            _copy(conn, "entry_identity", IDENTITY_COLUMNS, ([run_id] + [i[k] for k in IDENTITY_COLUMNS[1:]] for i in identity))
            _copy(conn, "entry_line_text", TEXT_COLUMNS, ([run_id] + [t[k] for k in TEXT_COLUMNS[1:]] for t in texts))
            _copy(conn, "creditor_bill_link", LINK_COLUMNS, ([run_id, plan.creditors_run_id] + [k[x] for x in LINK_COLUMNS[2:]] for k in links))
            _copy(conn, "till_day", TILL_COLUMNS, ([run_id, plan.cash_run_id] + [t[x] for x in TILL_COLUMNS[2:]] for t in till))
            log.info("run %s: %d entries, %d lines, %d links, %d till days inserted", run_id, len(headers), len(lines), len(links), len(till))
            for cr in plan.source_controls:
                conn.execute("SELECT entry.record_control(%s,%s,%s,'source',%s,'extract',%s)", (run_id, cr["control"], cr["dimension"], Decimal(cr["left"]), Decimal(cr["right"])))
            mart = dims_from_db(conn, run_id)
            for k in sorted(set(plan.expected) | set(mart)):
                conn.execute("SELECT entry.record_control(%s,%s,%s,'extract',%s,'mart',%s)", (run_id, k[0], k[1], plan.expected.get(k, ZERO), mart.get(k, ZERO)))
            failed = conn.execute("SELECT control_id, count(*) FROM entry.control_result WHERE entry_run_id = %s AND verdict <> 'PASS' GROUP BY 1", (run_id,)).fetchall()
            if failed:
                raise LoadError("mart_controls", f"{sum(f[1] for f in failed)} control(s) have a non-zero variance", {f[0]: f[1] for f in failed})
            bad = {cid: v for cid, v in conn.execute("SELECT check_id, violations FROM entry.mart_checks(%s)", (run_id,)) if v}
            bad.update({cid: v for cid, v in conn.execute("SELECT check_id, violations FROM entry.cross_checks(%s)", (run_id,)) if v})
            if bad:
                raise LoadError("mart_controls", "structural or cross-domain checks failed", bad)
    except LoadError as e:
        record_rejection(conn, run_id, plan.manifest_sha256, e.stage, e.reason, e.failed)
        log.error("run %s REFUSED at %s: %s %s", run_id, e.stage, e.reason, e.failed)
        raise
    except psycopg.Error as e:
        reason = safe_reason(e)
        record_rejection(conn, run_id, plan.manifest_sha256, "load", reason, None)
        log.error("run %s FAILED during load: %s (transaction rolled back)", run_id, reason)
        raise LoadError("load", reason) from None
    return summarize(conn, run_id, who, time.monotonic() - t0)


def verify_loaded(conn, run_id: str) -> dict:
    assert_loader_identity(conn)
    res = conn.execute("SELECT entry.verify_run(%s)", (run_id,)).fetchone()[0]
    log.info("run %s verify: %s", run_id, {k: v for k, v in res.items() if k not in ("structural", "cross")})
    return res


def summarize(conn, run_id: str, who: str, seconds: float) -> dict:
    one = lambda q, *p: conn.execute(q, p).fetchone()  # noqa: E731
    st = one("SELECT recon_state, publication_state, register_report_date, till_balance_date, creditors_run_id, cash_run_id FROM entry.run WHERE entry_run_id = %s", run_id)
    n = one("SELECT (SELECT count(*) FROM entry.entry_header WHERE entry_run_id = %s), (SELECT count(*) FROM entry.entry_line WHERE entry_run_id = %s), (SELECT count(*) FROM entry.creditor_bill_link WHERE entry_run_id = %s), "
            "(SELECT count(*) FROM entry.till_day WHERE entry_run_id = %s)", run_id, run_id, run_id, run_id)
    ctl = one("SELECT count(*), count(*) FILTER (WHERE verdict = 'PASS'), count(*) FILTER (WHERE left_layer = 'source'), count(*) FILTER (WHERE left_layer = 'extract'), coalesce(max(abs(variance)), 0) FROM entry.control_result WHERE entry_run_id = %s", run_id)
    by = dict(conn.execute("SELECT link_status, count(*) FROM entry.creditor_bill_link WHERE entry_run_id = %s GROUP BY 1", (run_id,)).fetchall())
    return {"run_id": run_id, "loaded_by": who, "seconds": round(seconds, 1), "recon_state": st[0], "publication_state": st[1], "register_report_date": str(st[2]), "till_balance_date": str(st[3]),
            "creditors_run_id": st[4], "cash_run_id": st[5], "entries": n[0], "lines": n[1], "links": n[2], "till_days": n[3], "links_by_status": by,
            "controls": {"total": ctl[0], "pass": ctl[1], "source_to_extract": ctl[2], "extract_to_mart": ctl[3], "max_abs_variance": str(ctl[4])},
            "checks": {cid: v for cid, v in conn.execute("SELECT check_id, violations FROM entry.mart_checks(%s) UNION ALL SELECT check_id, violations FROM entry.cross_checks(%s)", (run_id, run_id))}}


def render_report(r: dict) -> str:
    L = [f"# Entry layer load report: {r['run_id']}", "", f"register as of {r['register_report_date']}; till date {r['till_balance_date']}; creditors run {r['creditors_run_id']}; cash run {r['cash_run_id']}; loaded by `{r['loaded_by']}` in {r['seconds']}s",
         f"**State: recon_state `{r['recon_state']}`, publication_state `{r['publication_state']}`**", "",
         f"- {r['entries']:,} entries, {r['lines']:,} lines, {r['links']:,} creditor bill links {r['links_by_status']}, {r['till_days']:,} till store-days", "",
         "## Controls", f"- {r['controls']['total']} recorded, {r['controls']['pass']} PASS (source to extract {r['controls']['source_to_extract']}, extract to mart {r['controls']['extract_to_mart']}); max abs variance {r['controls']['max_abs_variance']}",
         f"- structural and cross-domain checks (violations): {json.dumps(r['checks'])}"]
    return "\n".join(L) + "\n"


def main(argv: list[str]) -> int:
    import psycopg

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if len(argv) not in (3, 5) or argv[1] not in ("load", "verify"):
        print(__doc__ + "\n    load needs:  load <run folder> <creditors run id> <cash run id>")
        return 2
    info = loader_conninfo()
    if not info:
        print("No loader connection: set FPA_ENTRY_LOADER_URL, create .secrets/entry_loader.env, or run in an interactive terminal.")
        return 2
    try:
        with psycopg.connect(info, autocommit=True) as conn:
            db = conn.execute("SELECT current_database()").fetchone()[0]
            if db in PROTECTED_DB:
                print(f"refusing to use database '{db}'")
                return 3
            if argv[1] == "verify":
                print(json.dumps(verify_loaded(conn, argv[2]), indent=2))
                return 0
            if len(argv) != 5:
                print("load needs: load <run folder> <creditors run id> <cash run id>")
                return 2
            salt = salt_value()
            plan = preflight(Path(argv[2]), argv[3], argv[4], salt)
            res = load_run(conn, plan, salt)
            (Path(argv[2]) / "staging" / "mart_load_report.md").write_text(render_report(res), encoding="utf-8")
            print(render_report(res))
            return 0
    except AlreadyLoaded as e:
        print(f"{e}: already loaded, identical content; nothing was written")
        return 0
    except LoadError as e:
        print(f"REFUSED at {e.stage}: {e.reason} {e.failed if e.failed else ''}")
        return 1
    except psycopg.OperationalError:
        print("could not connect as the loader login")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
