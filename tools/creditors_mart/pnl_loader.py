"""
P&L actuals loader: two validated, immutable run folders (pl_actuals_01 + cogs_scan_01) -> schema `pnl`, in ONE transaction, never promoted.

    python tools/creditors_mart/pnl_loader.py load   <pl_actuals_01 run folder> <cogs_scan_01 run folder>   # preflight, load, controls, commit (or roll back everything)
    python tools/creditors_mart/pnl_loader.py verify run_YYYYMMDD_NNN                                       # separate gate: loaded -> verified (structural checks, in SQL)
    python tools/creditors_mart/pnl_loader.py report run_YYYYMMDD_NNN

Same rules as the other loaders (each covered by tests/test_pnl_mart.py):
  * PREFLIGHT touches no database: both manifests and file hashes, the staging report (verdict PASSED, tied to this manifest) and a full re-derivation of every staged row from the raw extract.
  * It connects only through a login that is a member of pnl_loader and of no other role, never as a superuser, postgres or an owner.
  * Source -> extract controls come from the staging report; extract -> mart controls are computed in SQL here and compared before the commit. ANY failure rolls back the run.
  * It never promotes. A finished load is recon_state 'loaded', publication_state 'unpublished'.
  * Logs and rejection records carry run ids, counts and control ids only.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "extraction_broker"))
sys.path.insert(0, str(HERE))
import manifest as mf  # noqa: E402
import pl_stage as ps  # noqa: E402

log = logging.getLogger("pnl_loader")
ZERO = Decimal(0)
RUN_ID = re.compile(r"^run_[0-9]{8}_[0-9]{3}$")
PROTECTED_DB = {"fpa", "postgres", "template0", "template1"}
FORBIDDEN_LOGINS = {"postgres", "pnl_owner", "pnl_promoter", "pnl_verifier", "pnl_api_reader", "cred_owner", "cred_loader", "cash_owner", "cash_loader", "entry_owner", "entry_loader", "fpa_app", "admin"}
OTHER_ROLES = ["pnl_owner", "pnl_promoter", "pnl_verifier", "pnl_api_reader", "cash_owner", "cash_loader", "cash_promoter", "cash_verifier", "cash_api_reader", "cred_owner", "cred_loader", "cred_promoter",
               "cred_verifier", "cred_api_reader", "cred_finance_reader", "entry_owner", "entry_loader", "entry_promoter", "entry_verifier", "entry_api_reader", "entry_finance_reader"]
SECRET_FILE = HERE.parents[1] / ".secrets" / "pnl_loader.env"

SITE_COLUMNS = ["run_id", "site_code", "store_name", "opening_date", "store_status", "store_current_status", "cluster_type", "region_type", "state", "store_type", "last_bill_date"]
GL_COLUMNS = ["run_id", "site_code", "month", "glcode", "ledger_name", "group_label", "section", "entry_type_short", "release_status", "debit", "credit", "lines"]
COGS_COLUMNS = ["run_id", "site_code", "month", "sl_v", "tax_amt", "cogs_v", "sl_q", "rows_n", "bill_days", "first_bill", "last_bill"]
TIE_COLUMNS = ["run_id", "site_code", "month", "books_sales", "cogs_table_sales_ex_gst", "difference", "tied"]
SECTIONS = ps.SECTIONS


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

    url = os.environ.get("FPA_PNL_LOADER_URL")
    if url:
        return url
    cfg = _read_env_file(Path(os.environ.get("FPA_PNL_LOADER_ENV", SECRET_FILE)))
    if cfg.get("password"):
        return make_conninfo(host=cfg.get("host", "localhost"), port=cfg.get("port", "5432"), dbname=cfg.get("dbname", "fpa_pilot"), user=cfg.get("user", ""), password=cfg["password"])
    if not sys.stdin.isatty():
        return None
    import getpass

    try:
        host = input("PostgreSQL host [localhost]: ").strip() or "localhost"
        port = input("Port [5432]: ").strip() or "5432"
        dbname = input("Database [fpa_pilot]: ").strip() or "fpa_pilot"
        user = input("Loader login (a member of pnl_loader): ").strip()
        password = getpass.getpass("Password (hidden, not stored): ")
    except (EOFError, KeyboardInterrupt):
        return None
    return make_conninfo(host=host, port=port, dbname=dbname, user=user, password=password)


def assert_loader_identity(conn) -> str:
    row = conn.execute(
        "SELECT current_user, (SELECT rolsuper FROM pg_roles WHERE rolname = current_user), pg_has_role(current_user, 'pnl_loader', 'MEMBER'), "
        "ARRAY(SELECT r FROM unnest(%s::text[]) r WHERE pg_has_role(current_user, r, 'MEMBER'))", (OTHER_ROLES,)).fetchone()
    who, is_super, is_loader, others = row
    if who in FORBIDDEN_LOGINS or is_super:
        raise LoadError("precheck", f"refusing to load as '{who}' (superuser or privileged/other-application role)")
    if not is_loader:
        raise LoadError("precheck", f"'{who}' is not a member of pnl_loader")
    if others:
        raise LoadError("precheck", f"'{who}' also holds other roles ({', '.join(others)}): the loader must hold pnl_loader only")
    return who


@dataclass
class Plan:
    run_id: str
    run_dir: Path
    cogs_run_id: str
    manifest_sha256: str
    cogs_manifest_sha256: str
    report_sha256: str
    as_of: str
    cogs_last_bill: str
    contract: dict
    extract_started_at: str
    extract_finished_at: str
    data: dict
    source_controls: list[dict]
    expected: dict = field(default_factory=dict)
    tolerance: Decimal = ZERO


def _d(v) -> date | None:
    return None if v in (None, "") else date.fromisoformat(str(v)[:10])


def expected_dims(data: dict) -> dict:
    """The extract-side figures the mart must reproduce, derived from the re-derived staging rows (not from the database)."""
    gl, cg, tie = data["gl_site_month"], data["cogs_site_month"], data["sales_tieout"]
    out = {("P_gl", "rows"): Decimal(len(gl)), ("P_gl", "debit"): sum((r["debit"] for r in gl), ZERO), ("P_gl", "credit"): sum((r["credit"] for r in gl), ZERO), ("P_gl", "lines"): Decimal(sum(r["lines"] for r in gl))}
    for s in SECTIONS:
        out[("P_section_net", s)] = sum((r["credit"] - r["debit"] for r in gl if r["section"] == s), ZERO)
    for st in ("Posted", "Unposted"):
        out[("P_status_net", st)] = sum((r["credit"] - r["debit"] for r in gl if r["release_status"] == st), ZERO)
    out[("P_cogs", "rows")] = Decimal(len(cg))
    for k in ("sl_v", "tax_amt", "cogs_v", "sl_q"):
        out[("P_cogs", k)] = sum((r[k] for r in cg), ZERO)
    out[("P_tieout", "rows")] = Decimal(len(tie))
    out[("P_tieout", "tied")] = Decimal(sum(1 for t in tie if t["tied"]))
    out[("P_tieout", "difference")] = sum((t["difference"] for t in tie), ZERO)
    out[("P_sites", "rows")] = Decimal(len(data["site_master"]))
    out[("P_groups", "rows")] = Decimal(len(data["group_section"]))
    return out


def preflight(pl_dir: Path | str, cogs_dir: Path | str) -> Plan:
    pl_dir, cogs_dir = Path(pl_dir), Path(cogs_dir)
    for d in (pl_dir, cogs_dir):
        if not RUN_ID.match(d.name):
            raise LoadError("precheck", f"'{d.name}' is not a run folder name")
    for d in (pl_dir, cogs_dir):
        v = mf.validate_manifest(d)
        if not v.ok:
            raise LoadError("precheck", f"manifest invalid ({d.name}): {v.errors[:3]}")
    m = json.loads((pl_dir / "manifest.json").read_text(encoding="utf-8"))
    mc = json.loads((cogs_dir / "manifest.json").read_text(encoding="utf-8"))
    if m.get("package") != "pl_actuals_01" or mc.get("package") != "cogs_scan_01":
        raise LoadError("precheck", "the folders are not a pl_actuals_01 run and a cogs_scan_01 run")
    rep_path = pl_dir / "staging" / "validation_report.json"
    if not rep_path.exists():
        raise LoadError("staging_report", "no staging report: run pl_stage.py first")
    rep = json.loads(rep_path.read_text(encoding="utf-8"))
    if rep.get("verdict") != "PASSED" or rep.get("hard_failures"):
        raise LoadError("staging_report", f"staging verdict is {rep.get('verdict')}")
    manifest_sha, cogs_sha = mf.sha256_file(pl_dir / "manifest.json"), mf.sha256_file(cogs_dir / "manifest.json")
    if rep.get("manifest_sha256") != manifest_sha or rep.get("cogs_manifest_sha256") != cogs_sha or rep.get("cogs_run") != cogs_dir.name:
        raise LoadError("staging_report", "the staging report does not belong to these manifests (a manifest changed after validation)")
    fresh = ps.validate(pl_dir, cogs_dir, write=False)                         # a full re-derivation from the raw extract: it must still pass, and must equal the report
    if fresh["verdict"] != "PASSED":
        raise LoadError("staging_report", "the re-derivation from the raw extract no longer passes")
    if fresh["aggregates"] != rep["aggregates"] or fresh["controls"] != rep["controls"]:
        raise LoadError("staging_report", "the re-derived figures differ from the staging report")
    data = fresh["derived"]
    for name in ("gl_site_month", "cogs_site_month", "sales_tieout", "site_master", "group_section"):
        p = pl_dir / "staging" / f"{name}.parquet"
        if not p.exists():
            raise LoadError("staging_report", f"{name}.parquet is missing")
        import pyarrow.parquet as pq

        if pq.ParquetFile(p).metadata.num_rows != len(data[name]):
            raise LoadError("staging_report", f"{name}.parquet does not match the re-derivation")
    times = [d.get("extracted_at") for d in m["datasets"] if d.get("extracted_at")]
    agg = rep["aggregates"]
    return Plan(pl_dir.name, pl_dir, cogs_dir.name, manifest_sha, cogs_sha, mf.sha256_file(rep_path), agg["as_of"], agg["cogs_last_bill_date"], m["contract"], min(times), max(times), data,
                rep["controls"], expected_dims(data), Decimal(agg["tolerance_rupees"]))


def dims_from_db(conn, run_id: str) -> dict:
    one = lambda q, *p: conn.execute(q, p).fetchone()  # noqa: E731
    r = one("SELECT count(*), coalesce(sum(debit),0), coalesce(sum(credit),0), coalesce(sum(lines),0) FROM pnl.gl_site_month WHERE run_id = %s", run_id)
    out = {("P_gl", "rows"): Decimal(r[0]), ("P_gl", "debit"): Decimal(r[1]), ("P_gl", "credit"): Decimal(r[2]), ("P_gl", "lines"): Decimal(r[3])}
    got = dict(conn.execute("SELECT section, sum(credit - debit) FROM pnl.gl_site_month WHERE run_id = %s GROUP BY 1", (run_id,)).fetchall())
    for s in SECTIONS:
        out[("P_section_net", s)] = Decimal(got.get(s, 0))
    got = dict(conn.execute("SELECT release_status, sum(credit - debit) FROM pnl.gl_site_month WHERE run_id = %s GROUP BY 1", (run_id,)).fetchall())
    for st in ("Posted", "Unposted"):
        out[("P_status_net", st)] = Decimal(got.get(st, 0))
    r = one("SELECT count(*), coalesce(sum(sl_v),0), coalesce(sum(tax_amt),0), coalesce(sum(cogs_v),0), coalesce(sum(sl_q),0) FROM pnl.cogs_site_month WHERE run_id = %s", run_id)
    out[("P_cogs", "rows")] = Decimal(r[0])
    for k, val in zip(("sl_v", "tax_amt", "cogs_v", "sl_q"), r[1:]):
        out[("P_cogs", k)] = Decimal(val)
    r = one("SELECT count(*), count(*) FILTER (WHERE tied), coalesce(sum(difference),0) FROM pnl.sales_tieout WHERE run_id = %s", run_id)
    out[("P_tieout", "rows")], out[("P_tieout", "tied")], out[("P_tieout", "difference")] = Decimal(r[0]), Decimal(r[1]), Decimal(r[2])
    out[("P_sites", "rows")] = Decimal(one("SELECT count(*) FROM pnl.site WHERE run_id = %s", run_id)[0])
    out[("P_groups", "rows")] = Decimal(one("SELECT count(*) FROM pnl.group_section WHERE run_id = %s", run_id)[0])
    return out


def safe_reason(e: BaseException) -> str:
    diag = getattr(e, "diag", None)
    cname = getattr(diag, "constraint_name", None) if diag else None
    return f"{type(e).__name__}" + (f" (constraint {cname})" if cname else "")


def record_rejection(conn, run_id: str, manifest_sha: str | None, stage: str, reason: str, failed: dict | None) -> None:
    try:
        conn.execute("INSERT INTO pnl.load_rejection (run_id, manifest_sha256, stage, reason, failed_controls) VALUES (%s,%s,%s,%s,%s)", (run_id, manifest_sha, stage, reason[:300], json.dumps(failed or {})))
    except Exception as e:  # noqa: BLE001
        log.warning("could not record the rejection (%s)", safe_reason(e))


def _copy(conn, table: str, columns: list[str], rows) -> int:
    n = 0
    with conn.cursor() as cur, cur.copy(f"COPY pnl.{table} ({', '.join(columns)}) FROM STDIN") as cp:
        for r in rows:
            cp.write_row(r)
            n += 1
    return n


def load_run(conn, plan: Plan) -> dict:
    who = assert_loader_identity(conn)
    t0 = time.monotonic()
    run_id = plan.run_id
    prior = conn.execute("SELECT run_id, manifest_sha256 FROM pnl.run WHERE run_id = %s OR manifest_sha256 = %s", (run_id, plan.manifest_sha256)).fetchall()
    if prior:
        if len(prior) == 1 and prior[0][0] == run_id and prior[0][1] == plan.manifest_sha256:
            raise AlreadyLoaded(run_id)
        record_rejection(conn, run_id, plan.manifest_sha256, "precheck", "this run id or this manifest is already loaded with different content", None)
        raise LoadError("precheck", "this run id or this manifest is already loaded with different content")
    try:
        import psycopg

        with conn.transaction():
            c, d = plan.contract, plan.data
            conn.execute(
                "INSERT INTO pnl.run (run_id, as_of_date, cogs_run_id, cogs_last_bill_date, package, contract_version, rules, manifest_sha256, cogs_manifest_sha256, staging_report_sha256,"
                " extract_started_at, extract_finished_at, expected_gl_rows, expected_cogs_rows, expected_sites, tolerance_rupees) VALUES (%s,%s,%s,%s,'pl_actuals_01',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (run_id, plan.as_of, plan.cogs_run_id, plan.cogs_last_bill, c["contract"], json.dumps(c), plan.manifest_sha256, plan.cogs_manifest_sha256, plan.report_sha256,
                 plan.extract_started_at, plan.extract_finished_at, len(d["gl_site_month"]), len(d["cogs_site_month"]), len(d["site_master"]), plan.tolerance))
            _copy(conn, "site", SITE_COLUMNS, ([run_id, s["site_code"], s["store_name"], _d(s["opening_date"]), s["store_status"], s["store_current_status"], s["cluster_type"], s["region_type"],
                                               s["state"], s["store_type"], _d(s["last_bill_date"])] for s in d["site_master"]))
            _copy(conn, "group_section", ["run_id", "group_label", "section"], ([run_id, g["group_label"], g["section"]] for g in d["group_section"]))
            n_gl = _copy(conn, "gl_site_month", GL_COLUMNS, ([run_id] + [r[k] for k in GL_COLUMNS[1:]] for r in d["gl_site_month"]))
            n_cg = _copy(conn, "cogs_site_month", COGS_COLUMNS, ([run_id, r["site_code"], r["month"], r["sl_v"], r["tax_amt"], r["cogs_v"], r["sl_q"], r["rows_n"], r["bill_days"], _d(r["first_bill"]), _d(r["last_bill"])]
                                                              for r in d["cogs_site_month"]))
            _copy(conn, "sales_tieout", TIE_COLUMNS, ([run_id] + [t[k] for k in TIE_COLUMNS[1:]] for t in d["sales_tieout"]))
            log.info("run %s: %d book rows, %d COGS rows inserted", run_id, n_gl, n_cg)
            for cr in plan.source_controls:
                conn.execute("SELECT pnl.record_control(%s,%s,%s,'source',%s,'extract',%s)", (run_id, cr["control"], cr["dimension"], Decimal(cr["left"]), Decimal(cr["right"])))
            mart = dims_from_db(conn, run_id)
            for k in sorted(set(plan.expected) | set(mart)):
                conn.execute("SELECT pnl.record_control(%s,%s,%s,'extract',%s,'mart',%s)", (run_id, k[0], k[1], plan.expected.get(k, ZERO), mart.get(k, ZERO)))
            failed = conn.execute("SELECT control_id, count(*) FROM pnl.control_result WHERE run_id = %s AND verdict <> 'PASS' GROUP BY 1", (run_id,)).fetchall()
            if failed:
                raise LoadError("mart_controls", f"{sum(f[1] for f in failed)} control(s) have a non-zero variance", {f[0]: f[1] for f in failed})
            bad = {cid: v for cid, v in conn.execute("SELECT check_id, violations FROM pnl.mart_checks(%s)", (run_id,)) if v}
            if bad:
                raise LoadError("mart_controls", "structural mart checks failed", bad)
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
    res = conn.execute("SELECT pnl.verify_run(%s)", (run_id,)).fetchone()[0]
    log.info("run %s verify: %s", run_id, {k: v for k, v in res.items() if k != "structural"})
    return res


def summarize(conn, run_id: str, who: str, seconds: float) -> dict:
    one = lambda q, *p: conn.execute(q, p).fetchone()  # noqa: E731
    st = one("SELECT recon_state, publication_state, as_of_date, cogs_last_bill_date, cogs_run_id FROM pnl.run WHERE run_id = %s", run_id)
    n = one("SELECT (SELECT count(*) FROM pnl.gl_site_month WHERE run_id = %s), (SELECT count(*) FROM pnl.cogs_site_month WHERE run_id = %s), (SELECT count(*) FROM pnl.site WHERE run_id = %s), "
            "(SELECT count(DISTINCT site_code) FROM pnl.gl_site_month WHERE run_id = %s)", run_id, run_id, run_id, run_id)
    ctl = one("SELECT count(*), count(*) FILTER (WHERE verdict = 'PASS'), count(*) FILTER (WHERE left_layer = 'source'), count(*) FILTER (WHERE left_layer = 'extract'), coalesce(max(abs(variance)),0) FROM pnl.control_result WHERE run_id = %s", run_id)
    sect = dict(conn.execute("SELECT section, sum(credit - debit) FROM pnl.gl_site_month WHERE run_id = %s GROUP BY 1", (run_id,)).fetchall())
    tie = one("SELECT count(*), count(*) FILTER (WHERE tied) FROM pnl.sales_tieout WHERE run_id = %s", run_id)
    return {"run_id": run_id, "loaded_by": who, "seconds": round(seconds, 1), "recon_state": st[0], "publication_state": st[1], "as_of_date": str(st[2]), "cogs_last_bill_date": str(st[3]), "cogs_run_id": st[4],
            "gl_rows": n[0], "cogs_rows": n[1], "sites_master": n[2], "sites_in_books": n[3], "sections_net": {k: str(v) for k, v in sect.items()},
            "tieout": {"site_months": tie[0], "tied": tie[1]},
            "controls": {"total": ctl[0], "pass": ctl[1], "source_to_extract": ctl[2], "extract_to_mart": ctl[3], "max_abs_variance": str(ctl[4])},
            "mart_checks": {cid: v for cid, v in conn.execute("SELECT check_id, violations FROM pnl.mart_checks(%s)", (run_id,))}}


def render_report(r: dict) -> str:
    cr = lambda v: f"{Decimal(v) / Decimal(10_000_000):,.2f}"  # noqa: E731
    L = [f"# P&L actuals mart load report: {r['run_id']}", "", f"books as of {r['as_of_date']}; COGS table newest bill date {r['cogs_last_bill_date']} (COGS run {r['cogs_run_id']}); loaded by `{r['loaded_by']}` in {r['seconds']}s",
         f"**State: recon_state `{r['recon_state']}`, publication_state `{r['publication_state']}`**", "",
         f"- {r['gl_rows']:,} book rows over {r['sites_in_books']} sites; {r['cogs_rows']:,} COGS-table site-months; site master {r['sites_master']} sites",
         f"- sales tie-out (books vs COGS table ex-GST): {r['tieout']['tied']:,} of {r['tieout']['site_months']:,} site-months tied", "",
         "## Net by section, all months loaded (credit less debit, Cr)", *[f"- {k}: {cr(v)}" for k, v in sorted(r["sections_net"].items())], "",
         "## Controls", f"- {r['controls']['total']} recorded, {r['controls']['pass']} PASS (source to extract {r['controls']['source_to_extract']}, extract to mart {r['controls']['extract_to_mart']}); max abs variance {r['controls']['max_abs_variance']}",
         f"- structural checks (violations): {json.dumps(r['mart_checks'])}"]
    return "\n".join(L) + "\n"


def main(argv: list[str]) -> int:
    import psycopg

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ok = (len(argv) == 4 and argv[1] == "load") or (len(argv) == 3 and argv[1] in ("verify", "report"))
    if not ok:
        print(__doc__)
        return 2
    info = loader_conninfo()
    if not info:
        print("No loader connection: set FPA_PNL_LOADER_URL, create .secrets/pnl_loader.env, or run in an interactive terminal.")
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
            if argv[1] == "report":
                who = assert_loader_identity(conn)
                print(render_report(summarize(conn, argv[2], who, 0.0)))
                return 0
            plan = preflight(Path(argv[2]), Path(argv[3]))
            res = load_run(conn, plan)
            (Path(argv[2]) / "staging" / "mart_load_report.md").write_text(render_report(res), encoding="utf-8")
            print(render_report(res))
            return 0
    except AlreadyLoaded as e:
        print(f"{e}: already loaded, identical content; nothing was written")
        return 0
    except LoadError as e:
        print(f"REFUSED at {e.stage}: {e.reason} {e.failed if e.failed else ''}")
        return 1
    except psycopg.OperationalError as e:
        print("could not connect as the loader login")
        log.debug("%s", type(e).__name__)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
