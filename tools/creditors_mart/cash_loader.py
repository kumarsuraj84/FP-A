"""
Cash pilot loader: one validated, immutable run folder -> schema `cash`, in ONE transaction, never promoted.

    python tools/creditors_mart/cash_loader.py load   data/inbox/run_YYYYMMDD_NNN     # preflight, load, controls, commit (or roll back everything)
    python tools/creditors_mart/cash_loader.py verify run_YYYYMMDD_NNN                # separate gate: loaded -> verified (structural checks, in SQL)

Same rules as the creditors loader (each is covered by tests/test_cash_loader.py):
  * PREFLIGHT touches no database: manifest and file hashes, the staging report (verdict PASSED, hash chain manifest -> report -> derived Parquet),
    and a re-derivation of every derived row from the raw extract, which must match exactly.
  * It connects only through a login that is a member of cash_loader and of no other role, never as a superuser, postgres or an owner.
  * Source -> extract controls come from the validated staging report; extract -> mart controls are computed in SQL here (including the
    generated position columns, so the arithmetic is checked independently) and compared before the commit. ANY failure rolls back the run.
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
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "extraction_broker"))
sys.path.insert(0, str(HERE))
import cash_stage as cs  # noqa: E402
import manifest as mf  # noqa: E402

log = logging.getLogger("cash_loader")
ZERO = Decimal(0)
RUN_ID = re.compile(r"^run_[0-9]{8}_[0-9]{3}$")
PROTECTED_DB = {"fpa", "postgres", "template0", "template1"}
FORBIDDEN_LOGINS = {"postgres", "cash_owner", "cash_promoter", "cash_verifier", "cash_api_reader", "cred_owner", "cred_loader", "fpa_app", "admin"}
OTHER_ROLES = ["cash_owner", "cash_promoter", "cash_verifier", "cash_api_reader", "cred_owner", "cred_loader", "cred_promoter", "cred_verifier", "cred_api_reader", "cred_finance_reader"]
SECRET_FILE = HERE.parents[1] / ".secrets" / "cash_loader.env"

TILL_COLUMNS = ["run_id", "site_code", "store_name", "cumulative_balance", "mtd_debit", "mtd_credit", "fytd_debit", "fytd_credit", "last_activity_date"]
BANK_COLUMNS = ["run_id", "source", "ledger_code", "ledger_name", "gl_type", "nature", "extinct", "has_movement", "opening_dr", "opening_cr", "posted_dr", "posted_cr", "unposted_dr",
                "unposted_cr", "future_net", "contra_posted_dr", "contra_posted_cr", "opening_rows", "posted_rows", "unposted_rows", "future_rows", "last_posted_date",
                "last_entry_date", "register_report_date", "sites"]
BANK_SUMS = ["opening_dr", "opening_cr", "posted_dr", "posted_cr", "unposted_dr", "unposted_cr", "future_net", "contra_posted_dr", "contra_posted_cr"]


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

    url = os.environ.get("FPA_CASH_LOADER_URL")
    if url:
        return url
    cfg = _read_env_file(Path(os.environ.get("FPA_CASH_LOADER_ENV", SECRET_FILE)))
    if cfg.get("password"):
        return make_conninfo(host=cfg.get("host", "localhost"), port=cfg.get("port", "5432"), dbname=cfg.get("dbname", "fpa_pilot"), user=cfg.get("user", ""), password=cfg["password"])
    if not sys.stdin.isatty():
        return None
    import getpass

    try:
        host = input("PostgreSQL host [localhost]: ").strip() or "localhost"
        port = input("Port [5432]: ").strip() or "5432"
        dbname = input("Database [fpa_pilot]: ").strip() or "fpa_pilot"
        user = input("Loader login (a member of cash_loader): ").strip()
        password = getpass.getpass("Password (hidden, not stored): ")
    except (EOFError, KeyboardInterrupt):
        return None
    return make_conninfo(host=host, port=port, dbname=dbname, user=user, password=password)


def assert_loader_identity(conn) -> str:
    row = conn.execute(
        "SELECT current_user, (SELECT rolsuper FROM pg_roles WHERE rolname = current_user), pg_has_role(current_user, 'cash_loader', 'MEMBER'), "
        "ARRAY(SELECT r FROM unnest(%s::text[]) r WHERE pg_has_role(current_user, r, 'MEMBER'))", (OTHER_ROLES,)).fetchone()
    who, is_super, is_loader, others = row
    if who in FORBIDDEN_LOGINS or is_super:
        raise LoadError("precheck", f"refusing to load as '{who}' (superuser or privileged/other-application role)")
    if not is_loader:
        raise LoadError("precheck", f"'{who}' is not a member of cash_loader")
    if others:
        raise LoadError("precheck", f"'{who}' also holds other roles ({', '.join(others)}): the loader must hold cash_loader only")
    return who


@dataclass
class Plan:
    run_id: str
    run_dir: Path
    manifest_sha256: str
    report_sha256: str
    as_of: str
    till_date: str
    contract: dict
    extract_started_at: str
    extract_finished_at: str
    stores: list[dict]
    banks: list[dict]
    source_controls: list[dict]
    expected: dict = field(default_factory=dict)


def _pq(path: Path) -> list[dict]:
    import pyarrow.parquet as pq

    return pq.read_table(path).to_pylist()


def preflight(run_dir: Path | str) -> Plan:
    run_dir = Path(run_dir)
    if not RUN_ID.match(run_dir.name):
        raise LoadError("precheck", f"'{run_dir.name}' is not a run folder name")
    v = mf.validate_manifest(run_dir)
    if not v.ok:
        raise LoadError("precheck", f"manifest invalid: {v.errors[:3]}")
    manifest_sha = mf.sha256_file(run_dir / "manifest.json")
    m = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    if m.get("package") != "cash_pilot_01":
        raise LoadError("precheck", "not a cash_pilot_01 run")
    rep_path = run_dir / "staging" / "validation_report.json"
    if not rep_path.exists():
        raise LoadError("staging_report", "no staging report: run cash_stage.py first")
    rep = json.loads(rep_path.read_text(encoding="utf-8"))
    if rep.get("verdict") != "PASSED" or rep.get("hard_failures"):
        raise LoadError("staging_report", f"staging verdict is {rep.get('verdict')}")
    if rep.get("manifest_sha256") != manifest_sha:
        raise LoadError("staging_report", "the staging report does not belong to this manifest (the manifest changed after validation)")
    for name, key in (("cash_store_till", "cash_store_till"), ("cash_bank_ledger", "cash_bank_ledger")):
        p = run_dir / "staging" / f"{name}.parquet"
        if not p.exists() or mf.sha256_file(p) != rep["outputs"][key]:
            raise LoadError("staging_report", f"{name}.parquet does not match the staging report hash")
    # the derived rows must still equal what a fresh derivation from the raw extract gives, exactly
    fresh_stores = [{"site_code": r["site_code"], "store_name": r["store_name"], "cumulative_balance": cs.parse_decimal(r["cumulative_balance"]) or ZERO,
                     "mtd_debit": cs.money(r, "mtd_debit"), "mtd_credit": cs.money(r, "mtd_credit"), "fytd_debit": cs.money(r, "fytd_debit"), "fytd_credit": cs.money(r, "fytd_credit"),
                     "last_activity_date": cs.parse_date(r["last_activity_date"])} for r in cs.load(run_dir, "e1_store_till")]
    stores = _pq(run_dir / "staging" / "cash_store_till.parquet")
    if sorted(map(repr, fresh_stores)) != sorted(map(repr, [{k: s[k] for k in fresh_stores[0]} for s in stores])):
        raise LoadError("staging_report", "the derived store rows differ from the raw extract")
    fresh_banks = [cs.bank_row(r, src) for ds, src in cs.SOURCES.items() for r in cs.load(run_dir, ds)]
    banks = _pq(run_dir / "staging" / "cash_bank_ledger.parquet")
    key = lambda d: (d["source"], d["ledger_code"])  # noqa: E731
    fb, db = {key(x): x for x in fresh_banks}, {key(x): x for x in banks}
    if set(fb) != set(db) or any(any(fb[k][c] != db[k][c] for c in fb[k]) for k in fb):
        raise LoadError("staging_report", "the derived bank rows differ from the raw extract")
    agg = rep["aggregates"]
    expected = {("T_stores", "count"): Decimal(agg["stores"])}
    for k, val in agg["till"].items():
        expected[("T_till_sum", k)] = Decimal(val)
    expected[("B_rows", "all_sources")] = Decimal(agg["bank_rows"])
    for src, d in agg["bank"].items():
        for k in BANK_SUMS:
            expected[(f"B_sum_{src}", k)] = Decimal(d[k])
        expected[(f"B_rows_{src}", "ledgers")] = Decimal(d["ledgers"])
        expected[(f"B_rows_{src}", "with_movement")] = Decimal(d["with_movement"])
    for k, val in agg["site_register_position"].items():
        expected[("B_position_site_register", k)] = Decimal(val)
    c = m["contract"]
    times = [d.get("extracted_at") for d in m["datasets"] if d.get("extracted_at")]
    return Plan(run_dir.name, run_dir, manifest_sha, mf.sha256_file(rep_path), agg["as_of_date"], agg["till_balance_date"], c, min(times), max(times), stores, banks, rep["controls"], expected)


def dims_from_db(conn, run_id: str) -> dict:
    one = lambda q, *p: conn.execute(q, p).fetchone()  # noqa: E731
    out = {("T_stores", "count"): Decimal(one("SELECT count(*) FROM cash.store_till WHERE run_id = %s", run_id)[0])}
    r = one("SELECT coalesce(sum(cumulative_balance),0), coalesce(sum(mtd_debit),0), coalesce(sum(mtd_credit),0), coalesce(sum(fytd_debit),0), coalesce(sum(fytd_credit),0) FROM cash.store_till WHERE run_id = %s", run_id)
    for k, val in zip(("cumulative_balance", "mtd_debit", "mtd_credit", "fytd_debit", "fytd_credit"), r):
        out[("T_till_sum", k)] = Decimal(val)
    out[("B_rows", "all_sources")] = Decimal(one("SELECT count(*) FROM cash.bank_ledger WHERE run_id = %s", run_id)[0])
    for src in ("site_register", "gl_register", "prior_year_closing"):
        r = one("SELECT " + ", ".join(f"coalesce(sum({k}),0)" for k in BANK_SUMS) + ", count(*), count(*) FILTER (WHERE has_movement) FROM cash.bank_ledger WHERE run_id = %s AND source = %s", run_id, src)
        for k, val in zip(BANK_SUMS, r):
            out[(f"B_sum_{src}", k)] = Decimal(val)
        out[(f"B_rows_{src}", "ledgers")] = Decimal(r[len(BANK_SUMS)])
        out[(f"B_rows_{src}", "with_movement")] = Decimal(r[len(BANK_SUMS) + 1])
    r = one("SELECT coalesce(sum(opening_balance),0), coalesce(sum(posted_closing),0), coalesce(sum(including_unposted),0) FROM cash.bank_ledger WHERE run_id = %s AND source = 'site_register'", run_id)
    for k, val in zip(("opening", "posted_closing", "including_unposted"), r):
        out[("B_position_site_register", k)] = Decimal(val)
    return out


def safe_reason(e: BaseException) -> str:
    diag = getattr(e, "diag", None)
    cname = getattr(diag, "constraint_name", None) if diag else None
    return f"{type(e).__name__}" + (f" (constraint {cname})" if cname else "")


def record_rejection(conn, run_id: str, manifest_sha: str | None, stage: str, reason: str, failed: dict | None) -> None:
    try:
        conn.execute("INSERT INTO cash.load_rejection (run_id, manifest_sha256, stage, reason, failed_controls) VALUES (%s,%s,%s,%s,%s)", (run_id, manifest_sha, stage, reason[:300], json.dumps(failed or {})))
    except Exception as e:  # noqa: BLE001
        log.warning("could not record the rejection (%s)", safe_reason(e))


def _copy(conn, table: str, columns: list[str], rows) -> int:
    n = 0
    with conn.cursor() as cur, cur.copy(f"COPY cash.{table} ({', '.join(columns)}) FROM STDIN") as cp:
        for r in rows:
            cp.write_row(r)
            n += 1
    return n


def load_run(conn, plan: Plan) -> dict:
    who = assert_loader_identity(conn)
    t0 = time.monotonic()
    run_id = plan.run_id
    prior = conn.execute("SELECT run_id, manifest_sha256 FROM cash.run WHERE run_id = %s OR manifest_sha256 = %s", (run_id, plan.manifest_sha256)).fetchall()
    if prior:
        if len(prior) == 1 and prior[0][0] == run_id and prior[0][1] == plan.manifest_sha256:
            raise AlreadyLoaded(run_id)
        record_rejection(conn, run_id, plan.manifest_sha256, "precheck", "this run id or this manifest is already loaded with different content", None)
        raise LoadError("precheck", "this run id or this manifest is already loaded with different content")
    try:
        import psycopg

        with conn.transaction():
            c = plan.contract
            conn.execute(
                "INSERT INTO cash.run (run_id, as_of_date, till_balance_date, package, contract_version, rules, manifest_sha256, staging_report_sha256, extract_started_at,"
                " extract_finished_at, expected_store_rows, expected_bank_rows) VALUES (%s,%s,%s,'cash_pilot_01',%s,%s,%s,%s,%s,%s,%s,%s)",
                (run_id, plan.as_of, plan.till_date, c["contract"], json.dumps({k: v for k, v in c.items() if k != "caps"}), plan.manifest_sha256, plan.report_sha256,
                 plan.extract_started_at, plan.extract_finished_at, len(plan.stores), len(plan.banks)))
            n_t = _copy(conn, "store_till", TILL_COLUMNS, ([run_id] + [s[k] for k in TILL_COLUMNS[1:]] for s in plan.stores))
            n_b = _copy(conn, "bank_ledger", BANK_COLUMNS, ([run_id] + [b[k] for k in BANK_COLUMNS[1:]] for b in plan.banks))
            log.info("run %s: %d stores, %d bank-ledger rows inserted", run_id, n_t, n_b)
            for cr in plan.source_controls:
                conn.execute("SELECT cash.record_control(%s,%s,%s,'source',%s,'extract',%s)", (run_id, cr["control"], cr["dimension"], Decimal(cr["left"]), Decimal(cr["right"])))
            mart = dims_from_db(conn, run_id)
            for k in sorted(set(plan.expected) | set(mart)):
                conn.execute("SELECT cash.record_control(%s,%s,%s,'extract',%s,'mart',%s)", (run_id, k[0], k[1], plan.expected.get(k, ZERO), mart.get(k, ZERO)))
            failed = conn.execute("SELECT control_id, count(*) FROM cash.control_result WHERE run_id = %s AND verdict <> 'PASS' GROUP BY 1", (run_id,)).fetchall()
            if failed:
                raise LoadError("mart_controls", f"{sum(f[1] for f in failed)} control(s) have a non-zero variance", {f[0]: f[1] for f in failed})
            bad = {cid: v for cid, v in conn.execute("SELECT check_id, violations FROM cash.mart_checks(%s)", (run_id,)) if v}
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
    res = conn.execute("SELECT cash.verify_run(%s)", (run_id,)).fetchone()[0]
    log.info("run %s verify: %s", run_id, {k: v for k, v in res.items() if k != "structural"})
    return res


def summarize(conn, run_id: str, who: str, seconds: float) -> dict:
    one = lambda q, *p: conn.execute(q, p).fetchone()  # noqa: E731
    st = one("SELECT recon_state, publication_state, as_of_date, till_balance_date FROM cash.run WHERE run_id = %s", run_id)
    till = one("SELECT count(*), coalesce(sum(cumulative_balance),0) FROM cash.store_till WHERE run_id = %s", run_id)
    ctl = one("SELECT count(*), count(*) FILTER (WHERE verdict = 'PASS'), count(*) FILTER (WHERE left_layer = 'source'), count(*) FILTER (WHERE left_layer = 'extract'), coalesce(max(abs(variance)),0) FROM cash.control_result WHERE run_id = %s", run_id)
    bank = conn.execute("SELECT ledger_name, opening_balance, posted_closing, unposted_movement, including_unposted FROM cash.bank_ledger WHERE run_id = %s AND source = 'site_register' AND has_movement ORDER BY posted_closing", (run_id,)).fetchall()
    return {"run_id": run_id, "loaded_by": who, "seconds": round(seconds, 1), "recon_state": st[0], "publication_state": st[1], "as_of_date": str(st[2]), "till_balance_date": str(st[3]),
            "stores": till[0], "store_till_cash": str(till[1]), "controls": {"total": ctl[0], "pass": ctl[1], "source_to_extract": ctl[2], "extract_to_mart": ctl[3], "max_abs_variance": str(ctl[4])},
            "bank_site_register": [(a, str(b), str(c), str(d), str(e)) for a, b, c, d, e in bank],
            "mart_checks": {cid: v for cid, v in conn.execute("SELECT check_id, violations FROM cash.mart_checks(%s)", (run_id,))}}


def render_report(r: dict) -> str:
    cr = lambda v: f"{Decimal(v) / Decimal(10_000_000):,.2f}"  # noqa: E731
    L = [f"# Cash mart load report: {r['run_id']}", "", f"as of {r['as_of_date']}; till balance date {r['till_balance_date']}; loaded by `{r['loaded_by']}` in {r['seconds']}s",
         f"**State: recon_state `{r['recon_state']}`, publication_state `{r['publication_state']}`**", "",
         f"- stores {r['stores']:,}; Store Till Cash (excludes bank balances) {cr(r['store_till_cash'])} Cr", "",
         "## Controls", f"- {r['controls']['total']} recorded, {r['controls']['pass']} PASS (source to extract {r['controls']['source_to_extract']}, extract to mart {r['controls']['extract_to_mart']}); max abs variance {r['controls']['max_abs_variance']}",
         f"- structural checks (violations): {json.dumps(r['mart_checks'])}", "",
         "## Bank ledger book position, site register (PROVISIONAL, NOT BANK-RECONCILED), ₹ Cr", "| Ledger | Opening | Posted closing | Unposted | Including unposted |", "|---|---|---|---|---|",
         *[f"| {a} | {cr(b)} | {cr(c)} | {cr(d)} | {cr(e)} |" for a, b, c, d, e in r["bank_site_register"]]]
    return "\n".join(L) + "\n"


def main(argv: list[str]) -> int:
    import psycopg

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if len(argv) != 3 or argv[1] not in ("load", "verify", "report"):
        print(__doc__)
        return 2
    info = loader_conninfo()
    if not info:
        print("No loader connection: set FPA_CASH_LOADER_URL, create .secrets/cash_loader.env, or run in an interactive terminal.")
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
            plan = preflight(Path(argv[2]))
            res = load_run(conn, plan)
            out = Path(argv[2]) / "staging" / "mart_load_report.md"
            out.write_text(render_report(res), encoding="utf-8")
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
