"""
Creditors pilot loader: one validated, immutable run folder -> schema `cred`, in ONE transaction, never promoted.

    python tools/creditors_mart/loader.py load   data/inbox/run_YYYYMMDD_NNN     # preflight, load, controls, commit (or roll back everything)
    python tools/creditors_mart/loader.py verify run_YYYYMMDD_NNN                # separate gate: loaded -> verified (structural checks, in SQL)

Rules this file enforces (each is covered by tests/test_cred_loader.py):
  * PREFLIGHT runs before any database connection is used and writes nothing to the database: manifest and file hashes, the staging
    report (verdict PASSED, hash chain manifest -> report -> derived Parquet), and a re-check that every derived row still carries the
    raw extracted values exactly.
  * It connects only through a login that is a member of cred_loader and of no other cred role, never as a superuser, `postgres`,
    cred_owner or any application role. Its password comes from the environment, a git-ignored secret file, or a hidden prompt.
  * Run metadata first, then vendor snapshots, then items, then identity rows, then controls; derived fields come only from the
    already-approved staging output. Nothing is cleaned or corrected.
  * Duplicate or conflicting identities are refused (database constraints plus controls). No ordinal, no deduplication, no "keep first".
  * Source -> extract controls come from the validated staging report; extract -> mart controls are computed here and compared before
    the commit. ANY failure rolls back every row of the run.
  * It never promotes, never purges, never calls an owner or promoter function. A finished load is recon_state 'loaded',
    publication_state 'unpublished'.
  * Logs, reports and rejection records contain run ids, counts, timings and control ids only: no vendor names, codes or row values.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "extraction_broker"))
sys.path.insert(0, str(HERE))
import creditors_stage as cs  # noqa: E402
import manifest as mf  # noqa: E402

log = logging.getLogger("cred_loader")
ZERO = Decimal(0)
RUN_ID = re.compile(r"^run_[0-9]{8}_[0-9]{3}$")
PROTECTED_DB = {"fpa", "postgres", "template0", "template1"}
FORBIDDEN_LOGINS = {"postgres", "cred_owner", "cred_promoter", "cred_verifier", "cred_api_reader", "cred_finance_reader", "fpa_app", "admin"}
OTHER_CRED_ROLES = ["cred_owner", "cred_promoter", "cred_verifier", "cred_api_reader", "cred_finance_reader"]
SECRET_FILE = HERE.parents[1] / ".secrets" / "cred_loader.env"

ITEM_COLUMNS = [
    "extraction_run_id", "as_of_date", "source_row_key", "identity_k1_signature", "row_fingerprint", "document_code", "sub_ledger_code", "ledger_code",
    "ledger_name", "drcr", "amount", "adjusted", "pending", "document_no", "document_type", "document_initial", "ref_no", "created_by_site", "due_date_basis",
    "document_date", "due_date", "ref_date", "entry_date", "document_date_raw", "due_date_raw", "ref_date_raw", "entry_date_raw", "document_age_days",
    "document_age_bucket", "overdue_days", "due_status", "date_quality_status", "classification_status",
]
VENDOR_COLUMNS = ["extraction_run_id", "sub_ledger_code", "vendor_ref", "slid", "vendor_name", "party_class", "party_class_type", "credit_days", "vendor_extinct", "vendor_fingerprint"]
VENDOR_ATTRS = ["slid", "vendor_name", "party_class", "party_class_type", "credit_days", "vendor_extinct", "vendor_fingerprint"]
IDENTITY_COLUMNS = ["extraction_run_id", "source_row_key", "ledger_code", "drcr", "pending", "entry_date_raw"]
# raw values that must survive from the extract into the derived rows exactly (text compared as text, numbers as exact decimals)
RAW_TEXT = ["ledger_code", "ledger_name", "drcr", "document_no", "document_type", "document_initial", "ref_no", "created_by_site", "due_date_basis",
            "slid", "vendor_name", "party_class", "party_class_type", "vendor_extinct"]
RAW_DATES = ["document_date", "due_date", "ref_date", "entry_date"]


class LoadError(Exception):
    """A refused or failed load. `stage` is one of precheck, staging_report, load, mart_controls; `failed` lists control ids and counts only."""

    def __init__(self, stage: str, reason: str, failed: dict | None = None):
        super().__init__(f"{stage}: {reason}")
        self.stage, self.reason, self.failed = stage, reason, failed or {}


class AlreadyLoaded(Exception):
    """The identical run (same id, same manifest hash) is already in the mart: nothing was written."""


# ───────────── connection and secrets ─────────────


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
    """Connection for the loader login only: FPA_CRED_LOADER_URL, else the git-ignored .secrets/cred_loader.env, else a hidden prompt."""
    from psycopg.conninfo import make_conninfo

    url = os.environ.get("FPA_CRED_LOADER_URL")
    if url:
        return url
    cfg = _read_env_file(Path(os.environ.get("FPA_CRED_LOADER_ENV", SECRET_FILE)))
    if cfg.get("password"):
        return make_conninfo(host=cfg.get("host", "localhost"), port=cfg.get("port", "5432"), dbname=cfg.get("dbname", "fpa_pilot"), user=cfg.get("user", ""), password=cfg["password"])
    if not sys.stdin.isatty():
        return None
    import getpass

    try:
        host = input("PostgreSQL host [localhost]: ").strip() or "localhost"
        port = input("Port [5432]: ").strip() or "5432"
        dbname = input("Database [fpa_pilot]: ").strip() or "fpa_pilot"
        user = input("Loader login (a member of cred_loader): ").strip()
        password = getpass.getpass("Password (hidden, not stored): ")
    except (EOFError, KeyboardInterrupt):                 # no real terminal attached (Windows reports NUL as a tty)
        return None
    return make_conninfo(host=host, port=port, dbname=dbname, user=user, password=password)


def vendor_ref_salt() -> str:
    """The secret key of the pseudonymous vendor_ref. It must stay the same for ever, or vendor_ref would change between runs."""
    salt = os.environ.get("FPA_VENDOR_REF_SALT") or _read_env_file(Path(os.environ.get("FPA_CRED_LOADER_ENV", SECRET_FILE))).get("vendor_ref_salt")
    if not salt and sys.stdin.isatty():
        import getpass

        try:
            salt = getpass.getpass("Vendor pseudonym key (hidden, keep it identical for every load): ")
        except (EOFError, KeyboardInterrupt):
            salt = None
    if not salt or len(salt) < 32:
        raise LoadError("precheck", "the vendor pseudonym key is missing or shorter than 32 characters")
    return salt


def vendor_ref(salt: str, sub_ledger_code: str) -> str:
    return "V" + hmac.new(salt.encode("utf-8"), sub_ledger_code.encode("utf-8"), hashlib.sha256).hexdigest()[:12]


def assert_loader_identity(conn) -> str:
    """Refuse to run as anything but the loader: not a superuser, not postgres/owner/promoter/verifier/readers, a member of cred_loader."""
    row = conn.execute(
        "SELECT current_user, (SELECT rolsuper FROM pg_roles WHERE rolname = current_user), pg_has_role(current_user, 'cred_loader', 'MEMBER'), "
        "ARRAY(SELECT r FROM unnest(%s::text[]) r WHERE pg_has_role(current_user, r, 'MEMBER'))", (OTHER_CRED_ROLES,)).fetchone()
    who, is_super, is_loader, others = row
    if who in FORBIDDEN_LOGINS or is_super:
        raise LoadError("precheck", f"refusing to load as '{who}' (superuser or privileged/other-application role)")
    if not is_loader:
        raise LoadError("precheck", f"'{who}' is not a member of cred_loader")
    if others:
        raise LoadError("precheck", f"'{who}' also holds other cred roles ({', '.join(others)}): the loader must hold cred_loader only")
    return who


# ───────────── preflight (no database) ─────────────


@dataclass
class Plan:
    run_id: str
    run_dir: Path
    manifest_sha256: str
    report_sha256: str
    derived_sha256: str
    as_of: str
    contract: dict
    extract_started_at: str
    extract_finished_at: str
    expected_rows: int
    expected_identity_rows: int
    items: list[dict]
    identity: list[dict]
    vendors: list[dict]
    source_controls: list[dict]
    expected: dict = field(default_factory=dict)       # extract-layer aggregates to be matched by the mart


def _pq(path: Path) -> list[dict]:
    import pyarrow.parquet as pq

    return pq.read_table(path).to_pylist()


def preflight(run_dir: Path | str, salt: str) -> Plan:
    """Everything that can be refused without the database. Raises LoadError; touches no database and writes no file."""
    run_dir = Path(run_dir)
    run_id = run_dir.name
    if not RUN_ID.match(run_id) or not run_dir.is_dir():
        raise LoadError("precheck", "the run folder name must look like run_YYYYMMDD_NNN and exist")
    v = mf.validate_manifest(run_dir)
    if not v.ok:
        raise LoadError("precheck", f"manifest validation failed ({len(v.errors)} error(s)): " + "; ".join(e.split(':')[0] for e in v.errors[:3]))
    m = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    if m.get("package") != "creditors_pilot_01" or m.get("manifest_version") != 2 or not m.get("contract"):
        raise LoadError("precheck", "not a creditors_pilot_01 / manifest_version 2 run")
    by = {d["dataset"]: d for d in m["datasets"]}
    for name in cs.EXPECTED_DATASETS:
        if name not in by or by[name]["status"] != "ok":
            raise LoadError("precheck", f"dataset {name} is missing or not ok")
    manifest_sha = mf.sha256_file(run_dir / "manifest.json")

    stage = run_dir / "staging"
    rp = stage / "validation_report.json"
    if not rp.exists():
        raise LoadError("staging_report", "staging validation has not been run for this folder")
    report = json.loads(rp.read_text(encoding="utf-8"))
    if report.get("run") != run_id or report.get("verdict") != "PASSED" or report.get("hard_failures"):
        raise LoadError("staging_report", f"the staging report is not PASSED (verdict {report.get('verdict')})")
    if report.get("manifest_sha256") != manifest_sha:
        raise LoadError("staging_report", "the manifest changed after staging validation (hash mismatch)")
    outs = report.get("outputs") or {}
    dp, ip = stage / "creditor_open_items.parquet", stage / "creditor_identity_snapshot.parquet"
    if not dp.exists() or not ip.exists():
        raise LoadError("staging_report", "the derived Parquet files are missing")
    derived_sha, identity_sha = mf.sha256_file(dp), mf.sha256_file(ip)
    if outs.get("creditor_open_items") != derived_sha or outs.get("creditor_identity_snapshot") != identity_sha:
        raise LoadError("staging_report", "a derived Parquet file does not match the hash recorded by staging validation")

    items, identity = _pq(dp), _pq(ip)
    raw = cs.load(run_dir, "e1_open_items", cs.E1_COLUMNS)
    c3 = cs.load(run_dir, "c3_snapshot_control_pre")
    if len(c3) != 1:
        raise LoadError("precheck", "the snapshot source control must have exactly one row")
    n = len(items)
    if not (n == len(raw) == by["e1_open_items"]["row_count"] == cs.as_int(c3[0]["item_rows"])) or n == 0:
        raise LoadError("precheck", f"row counts disagree (derived {n}, extract {len(raw)}, manifest {by['e1_open_items']['row_count']}, source control {c3[0]['item_rows']})")
    if len(identity) != by["e2_identity_all_rows"]["row_count"]:
        raise LoadError("precheck", "identity row count disagrees with the manifest")

    # the derived rows must still carry the raw extracted values exactly: nothing was cleaned, corrected or dropped
    raw_by = {}
    for r in raw:
        k = (r["document_code"], r["sub_ledger_code"])
        if k in raw_by:
            raise LoadError("precheck", "duplicate business key in the raw extract")
        raw_by[k] = r
    seen = set()
    for d in items:
        r = raw_by.get((d["document_code"], d["sub_ledger_code"]))
        if r is None:
            raise LoadError("precheck", "a derived row has no raw extract row")
        if d["source_row_key"] != cs.source_row_key(d["document_code"], d["sub_ledger_code"]) or d["identity_k1_signature"] != cs.k1_signature(d["document_code"], d["ledger_code"], d["sub_ledger_code"], d["drcr"]):
            raise LoadError("precheck", "a derived row carries a source_row_key that does not match its identity parts")
        if d["source_row_key"] in seen:
            raise LoadError("precheck", "duplicate source_row_key in the derived rows")
        seen.add(d["source_row_key"])
        for c in RAW_TEXT:
            if d[c] != r[c]:
                raise LoadError("precheck", f"derived value differs from the extract ({c})")
        for c in RAW_DATES:
            if d[f"{c}_raw"] != r[c]:
                raise LoadError("precheck", f"derived date text differs from the extract ({c})")
        for c in ("amount", "pending", "adjusted"):
            if cs.parse_decimal(r[c]) != d[c]:
                raise LoadError("precheck", f"derived amount differs from the extract ({c})")
        if (cs.parse_decimal(r["credit_days"]) is None) != (d["credit_days"] is None) or (d["credit_days"] is not None and Decimal(d["credit_days"]) != cs.parse_decimal(r["credit_days"])):
            raise LoadError("precheck", "derived credit_days differs from the extract")
        if str(d["as_of_date"]) != r["as_of_date"] or d["as_of_date"].isoformat() != report["as_of_date"]:
            raise LoadError("precheck", "as_of_date differs between the extract, the derived rows and the report")
    e2 = cs.load(run_dir, "e2_identity_all_rows", cs.E2_COLUMNS)
    e2_keys = {cs.source_row_key(r["document_code"], r["sub_ledger_code"]) for r in e2}
    if len(e2_keys) != len(e2) or {i["source_row_key"] for i in identity} != e2_keys:
        raise LoadError("precheck", "the identity snapshot does not match the identity extract")

    vendors: dict[str, dict] = {}
    for d in items:
        v_ = {c: d[c] for c in VENDOR_ATTRS}
        cur = vendors.setdefault(d["sub_ledger_code"], v_)
        if cur != v_:
            raise LoadError("precheck", "one vendor carries conflicting attributes within the run")
    vendor_rows = [{"sub_ledger_code": s, "vendor_ref": vendor_ref(salt, s), **a} for s, a in sorted(vendors.items())]
    if len({v_["vendor_ref"] for v_ in vendor_rows}) != len(vendor_rows):
        raise LoadError("precheck", "two vendors produced the same pseudonym")

    started = min(d["extracted_at"] for d in m["datasets"] if d["role"] == "control_pre")
    finished = max(d["extracted_at"] for d in m["datasets"] if d["role"] == "control_post")
    contract = m["contract"]
    plan = Plan(run_id=run_id, run_dir=run_dir, manifest_sha256=manifest_sha, report_sha256=mf.sha256_file(rp), derived_sha256=derived_sha, as_of=report["as_of_date"],
                contract=contract, extract_started_at=started, extract_finished_at=finished, expected_rows=cs.as_int(c3[0]["item_rows"]),
                expected_identity_rows=by["e2_identity_all_rows"]["row_count"], items=items, identity=identity, vendors=vendor_rows, source_controls=report["controls"])
    plan.expected = dims_from_groups(groups_from_items(items), vendors_from_items(items), classes_from_items(items), counts=(len(items), len(vendor_rows), len(identity), sum(1 for i in identity if i["pending"] != 0)))
    return plan


# ───────────── aggregates: the extract side and the mart side use the SAME dimension builder ─────────────


def groups_from_items(items: list[dict]) -> dict:
    g: dict = defaultdict(lambda: [0, ZERO, ZERO])
    for d in items:
        x = g[(d["ledger_code"], d["drcr"], d["document_age_bucket"], d["due_status"], d["date_quality_status"])]
        x[0] += 1; x[1] += abs(d["pending"]); x[2] += d["pending"]
    return g


def vendors_from_items(items: list[dict]) -> dict:
    return {"all": len({d["sub_ledger_code"] for d in items}),
            **{f"ledger {led}": len({d["sub_ledger_code"] for d in items if d["ledger_code"] == led}) for led in {d["ledger_code"] for d in items}},
            **{f"drcr {dr}": len({d["sub_ledger_code"] for d in items if d["drcr"] == dr}) for dr in {d["drcr"] for d in items}},
            **{f"ledger {led} {dr}": len({d["sub_ledger_code"] for d in items if d["ledger_code"] == led and d["drcr"] == dr}) for led, dr in {(d["ledger_code"], d["drcr"]) for d in items}}}


def classes_from_items(items: list[dict]) -> dict:
    g: dict = defaultdict(lambda: [0, ZERO])
    for d in items:
        x = g[(d["party_class"], d["drcr"])]
        x[0] += 1; x[1] += abs(d["pending"])
    return g


def dims_from_groups(groups: dict, vendors: dict, classes: dict, counts: tuple) -> dict:
    """{(control_id, dimension): Decimal}. Built from grouped rows, so Python and SQL feed the very same builder."""
    out: dict = {}
    rows = sum(g[0] for g in groups.values())
    out[("M-C1", "rows total")] = Decimal(rows)
    out[("M-C2", "credit outstanding")] = sum((g[1] for k, g in groups.items() if k[1] == "Cr"), ZERO)
    out[("M-C3", "creditor debit balances")] = sum((g[1] for k, g in groups.items() if k[1] == "Dr"), ZERO)
    out[("M-C4", "signed net")] = sum((g[2] for g in groups.values()), ZERO)

    def add(cid, label, keyf):
        acc: dict = defaultdict(lambda: [0, ZERO, ZERO])
        for k, g in groups.items():
            a = acc[keyf(k)]
            a[0] += g[0]; a[1] += g[1]; a[2] += g[2]
        for kk, a in acc.items():
            out[(cid, f"{label} {kk} rows")] = Decimal(a[0])
            out[(cid, f"{label} {kk} abs")] = a[1]
            out[(cid, f"{label} {kk} signed")] = a[2]

    add("M-C9", "ledger/drcr", lambda k: f"{k[0]}/{k[1]}")
    add("M-C5", "document age", lambda k: f"{k[2]}/{k[1]}")
    add("M-C7", "due status", lambda k: f"{k[3]}/{k[1]}")
    add("M-C6", "date quality", lambda k: f"{k[4]}/{k[1]}")
    for k, v in vendors.items():
        out[("M-C8", f"vendors {k}")] = Decimal(v)
    for (cls, dr), a in classes.items():
        out[("M-C10", f"party class {cls}/{dr} rows")] = Decimal(a[0])
        out[("M-C10", f"party class {cls}/{dr} abs")] = a[1]
    n_items, n_vendors, n_ident, n_ident_open = counts
    out[("M-C11", "open_item rows")] = Decimal(n_items)
    out[("M-C11", "vendor_snapshot rows")] = Decimal(n_vendors)
    out[("M-C11", "identity_snapshot rows")] = Decimal(n_ident)
    out[("M-C11", "identity_snapshot open rows")] = Decimal(n_ident_open)
    return out


def dims_from_db(conn, run_id: str) -> dict:
    groups: dict = defaultdict(lambda: [0, ZERO, ZERO])
    for led, dr, bk, du, dq, n, a, s in conn.execute(
            "SELECT ledger_code, drcr, document_age_bucket, due_status, date_quality_status, count(*), sum(abs(pending)), sum(pending) FROM cred.open_item "
            "WHERE extraction_run_id = %s GROUP BY 1,2,3,4,5", (run_id,)):
        groups[(led, dr.strip(), bk, du, dq)] = [n, a, s]
    vendors: dict = {}
    for gl, gd, led, dr, v in conn.execute(
            "SELECT GROUPING(ledger_code), GROUPING(drcr), ledger_code, drcr, count(DISTINCT sub_ledger_code) FROM cred.open_item WHERE extraction_run_id = %s "
            "GROUP BY GROUPING SETS ((), (ledger_code), (drcr), (ledger_code, drcr))", (run_id,)):
        key = "all" if gl and gd else f"drcr {dr.strip()}" if gl else f"ledger {led}" if gd else f"ledger {led} {dr.strip()}"
        vendors[key] = v
    classes = {(cls, dr.strip()): [n, a] for cls, dr, n, a in conn.execute(
        "SELECT v.party_class, i.drcr, count(*), sum(abs(i.pending)) FROM cred.open_item i JOIN cred.vendor_snapshot v USING (extraction_run_id, sub_ledger_code) "
        "WHERE i.extraction_run_id = %s GROUP BY 1,2", (run_id,))}
    one = lambda q: conn.execute(q, (run_id,)).fetchone()[0]  # noqa: E731
    counts = (one("SELECT count(*) FROM cred.open_item WHERE extraction_run_id = %s"), one("SELECT count(*) FROM cred.vendor_snapshot WHERE extraction_run_id = %s"),
              one("SELECT count(*) FROM cred.identity_snapshot WHERE extraction_run_id = %s"), one("SELECT count(*) FROM cred.identity_snapshot WHERE extraction_run_id = %s AND pending <> 0"))
    return dims_from_groups(groups, vendors, classes, counts)


# ───────────── the load ─────────────


def safe_reason(e: BaseException) -> str:
    """What may be stored or logged about a failure: the error class and the constraint name. Never the DETAIL, which carries row values."""
    diag = getattr(e, "diag", None)
    cname = getattr(diag, "constraint_name", None) if diag else None
    return f"{type(e).__name__}" + (f" (constraint {cname})" if cname else "")


def record_rejection(conn, run_id: str, manifest_sha: str | None, stage: str, reason: str, failed: dict | None) -> None:
    try:
        conn.execute("INSERT INTO cred.load_rejection (extraction_run_id, manifest_sha256, stage, reason, failed_controls) VALUES (%s,%s,%s,%s,%s)",
                     (run_id, manifest_sha, stage, reason[:300], json.dumps(failed or {})))
    except Exception as e:  # noqa: BLE001
        log.warning("could not record the rejection (%s)", safe_reason(e))


def _copy(conn, table: str, columns: list[str], rows) -> int:
    n = 0
    with conn.cursor() as cur, cur.copy(f"COPY cred.{table} ({', '.join(columns)}) FROM STDIN") as cp:
        for r in rows:
            cp.write_row(r)
            n += 1
    return n


def load_run(conn, plan: Plan) -> dict:
    """Load one preflighted run. All-or-nothing. Returns an aggregate-only summary. The caller's connection must be autocommit."""
    who = assert_loader_identity(conn)
    t0 = time.monotonic()
    run_id = plan.run_id
    prior = conn.execute("SELECT extraction_run_id, manifest_sha256 FROM cred.run WHERE extraction_run_id = %s OR manifest_sha256 = %s", (run_id, plan.manifest_sha256)).fetchall()
    if prior:
        if len(prior) == 1 and prior[0][0] == run_id and prior[0][1] == plan.manifest_sha256:
            log.info("run %s is already loaded: nothing written", run_id)
            raise AlreadyLoaded(run_id)
        record_rejection(conn, run_id, plan.manifest_sha256, "precheck", "this run id or this manifest is already loaded with different content", None)
        raise LoadError("precheck", "this run id or this manifest is already loaded with different content")
    try:
        import psycopg

        with conn.transaction():
            c = plan.contract
            conn.execute(
                "INSERT INTO cred.run (extraction_run_id, as_of_date, package, contract_version, rules_version, hash_spec_version, rules, source_object, scope_ledger_codes,"
                " manifest_sha256, staging_report_sha256, derived_parquet_sha256, extract_started_at, extract_finished_at, expected_rows, expected_identity_rows)"
                " VALUES (%s,%s,'creditors_pilot_01',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (run_id, plan.as_of, c["contract_version"], c["rules_version"], c["hash_spec_version"],
                 json.dumps({k: c[k] for k in ("valid_date_min", "valid_date_max", "age_buckets")}), c["scope"]["source_object"], [str(x) for x in c["scope"]["ledger_codes"]],
                 plan.manifest_sha256, plan.report_sha256, plan.derived_sha256, plan.extract_started_at, plan.extract_finished_at, plan.expected_rows, plan.expected_identity_rows))
            n_v = _copy(conn, "vendor_snapshot", VENDOR_COLUMNS, ([run_id] + [v[col] for col in VENDOR_COLUMNS[1:]] for v in plan.vendors))
            n_i = _copy(conn, "open_item", ITEM_COLUMNS, ([run_id if col == "extraction_run_id" else d[col] for col in ITEM_COLUMNS] for d in plan.items))
            n_e = _copy(conn, "identity_snapshot", IDENTITY_COLUMNS, ([run_id if col == "extraction_run_id" else d[col] for col in IDENTITY_COLUMNS] for d in plan.identity))
            log.info("run %s: %d vendors, %d items, %d identity rows inserted", run_id, n_v, n_i, n_e)

            # the pseudonym must be stable: a vendor already in the previous run must get the same vendor_ref (a changed key would break it)
            drift = conn.execute(
                "SELECT count(*) FROM cred.vendor_snapshot cur JOIN cred.vendor_snapshot prev USING (sub_ledger_code) WHERE cur.extraction_run_id = %s "
                "AND prev.extraction_run_id = (SELECT extraction_run_id FROM cred.run WHERE extraction_run_id <> %s ORDER BY loaded_at DESC LIMIT 1) AND cur.vendor_ref <> prev.vendor_ref",
                (run_id, run_id)).fetchone()[0]
            if drift:
                raise LoadError("mart_controls", "the vendor pseudonym key differs from the previous run", {"vendor_ref_drift": drift})

            for cr in plan.source_controls:                      # source -> extract: from the validated staging report
                conn.execute("SELECT cred.record_control(%s,%s,%s,'source',%s,'extract',%s)", (run_id, cr["control"], cr["dimension"], Decimal(cr["left"]), Decimal(cr["right"])))
            mart = dims_from_db(conn, run_id)                    # extract -> mart: computed here, compared before the commit
            keys = sorted(set(plan.expected) | set(mart))
            for k in keys:
                conn.execute("SELECT cred.record_control(%s,%s,%s,'extract',%s,'mart',%s)", (run_id, k[0], k[1], plan.expected.get(k, ZERO), mart.get(k, ZERO)))
            failed = conn.execute("SELECT control_id, count(*) FROM cred.control_result WHERE extraction_run_id = %s AND verdict <> 'PASS' GROUP BY 1", (run_id,)).fetchall()
            if failed:
                raise LoadError("mart_controls", f"{sum(f[1] for f in failed)} control(s) have a non-zero variance", {f[0]: f[1] for f in failed})
            bad = {cid: v for cid, v in conn.execute("SELECT check_id, violations FROM cred.mart_checks(%s)", (run_id,)) if v}
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
    result = summarize(conn, plan, who, time.monotonic() - t0)
    log.info("run %s loaded: state %s/%s in %.1fs, %d controls all PASS", run_id, result["recon_state"], result["publication_state"], result["seconds"], result["controls"]["total"])
    return result


def verify_loaded(conn, run_id: str) -> dict:
    """A separate gate: ask the database to check the loaded run structurally and move recon_state loaded -> verified (still unpublished)."""
    assert_loader_identity(conn)
    res = conn.execute("SELECT cred.verify_run(%s)", (run_id,)).fetchone()[0]
    log.info("run %s verify: %s", run_id, {k: v for k, v in res.items() if k != "structural"})
    return res


# ───────────── report (aggregates only) ─────────────


def summarize(conn, plan: Plan, who: str, seconds: float) -> dict:
    run_id = plan.run_id
    one = lambda q, *p: conn.execute(q, p).fetchone()  # noqa: E731
    st = one("SELECT recon_state, publication_state FROM cred.run WHERE extraction_run_id = %s", run_id)
    cr, dr, net = one("SELECT coalesce(sum(abs(pending)) FILTER (WHERE drcr = 'Cr'), 0), coalesce(sum(abs(pending)) FILTER (WHERE drcr = 'Dr'), 0), coalesce(sum(pending), 0) FROM cred.open_item WHERE extraction_run_id = %s", run_id)
    ctl = one("SELECT count(*), count(*) FILTER (WHERE verdict = 'PASS'), count(*) FILTER (WHERE left_layer = 'source'), count(*) FILTER (WHERE left_layer = 'extract'), "
              "coalesce(max(abs(variance)), 0) FROM cred.control_result WHERE extraction_run_id = %s", run_id)
    mon = one("SELECT coalesce(max(abs(variance)), 0) FROM cred.control_result WHERE extraction_run_id = %s AND left_layer = 'extract' AND control_id NOT IN ('M-C1','M-C8','M-C11') AND dimension NOT LIKE '%% rows' AND dimension NOT LIKE '%% rows total'", run_id)
    cnt = one("SELECT (SELECT count(*) FROM cred.open_item WHERE extraction_run_id = %s), (SELECT count(*) FROM cred.vendor_snapshot WHERE extraction_run_id = %s), "
              "(SELECT count(DISTINCT source_row_key) FROM cred.open_item WHERE extraction_run_id = %s), (SELECT count(*) FROM cred.identity_snapshot WHERE extraction_run_id = %s)", run_id, run_id, run_id, run_id)
    live = one("SELECT count(*) FROM cred.run WHERE publication_state = 'live'")[0]   # the loader cannot read live_run, by design
    rows = lambda q: [list(r) for r in conn.execute(q, (run_id,)).fetchall()]  # noqa: E731
    return {
        "extraction_run_id": run_id, "as_of_date": plan.as_of, "loaded_by": who, "seconds": round(seconds, 2),
        "recon_state": st[0], "publication_state": st[1], "live_runs": live,
        "rows": {"open_item": cnt[0], "vendor_snapshot": cnt[1], "distinct_source_keys": cnt[2], "identity_snapshot": cnt[3]},
        "credit_outstanding": str(cr), "creditor_debit_balance": str(dr), "signed_net": str(net),
        "document_age": [[b, d.strip(), n, str(a)] for b, d, n, a in rows("SELECT document_age_bucket, drcr, count(*), sum(abs(pending)) FROM cred.open_item WHERE extraction_run_id = %s GROUP BY 1,2 ORDER BY 1,2")],
        "due_status": [[b, d.strip(), n, str(a)] for b, d, n, a in rows("SELECT due_status, drcr, count(*), sum(abs(pending)) FROM cred.open_item WHERE extraction_run_id = %s GROUP BY 1,2 ORDER BY 1,2")],
        "ledger_totals": [[l, d.strip(), n, str(a), str(s)] for l, d, n, a, s in rows("SELECT ledger_code, drcr, count(*), sum(abs(pending)), sum(pending) FROM cred.open_item WHERE extraction_run_id = %s GROUP BY 1,2 ORDER BY 1,2")],
        "distinct_vendors": one("SELECT count(DISTINCT sub_ledger_code) FROM cred.open_item WHERE extraction_run_id = %s", run_id)[0],
        "controls": {"total": ctl[0], "pass": ctl[1], "source_to_extract": ctl[2], "extract_to_mart": ctl[3], "max_abs_variance": str(ctl[4]), "max_abs_money_variance": str(mon[0])},
        "mart_checks": {cid: v for cid, v in conn.execute("SELECT check_id, violations FROM cred.mart_checks(%s)", (run_id,))},
        "extract_vs_mart": {"row_variance": str(max((abs(Decimal(r[4]) - Decimal(r[3])) for r in conn.execute(
            "SELECT control_id, dimension, 0, left_value, right_value FROM cred.control_result WHERE extraction_run_id = %s AND left_layer = 'extract' AND (dimension LIKE %s OR dimension LIKE %s OR control_id IN ('M-C1','M-C8','M-C11'))",
            (run_id, "% rows", "% rows total")).fetchall()), default=ZERO)), "money_variance": str(mon[0])},
        "scale_gt_2_decimals_informational": one("SELECT count(*) FROM cred.open_item WHERE extraction_run_id = %s AND (scale(pending) > 2 OR scale(amount) > 2)", run_id)[0],
    }


def render_report(r: dict) -> str:
    cr = lambda v: f"{Decimal(v) / Decimal(10_000_000):,.2f}"  # noqa: E731
    L = [f"# Mart load report: {r['extraction_run_id']}", "", f"as_of_date {r['as_of_date']}; loaded by `{r['loaded_by']}` in {r['seconds']}s",
         f"**State: recon_state `{r['recon_state']}`, publication_state `{r['publication_state']}`** (live runs: {r['live_runs']})", "",
         "## Rows", *[f"- {k}: {v:,}" for k, v in r["rows"].items()], f"- distinct vendors: {r['distinct_vendors']:,}", "",
         "## Amounts (₹ Cr)", f"- Credit outstanding {cr(r['credit_outstanding'])}", f"- Creditor debit balance (classification pending) {cr(r['creditor_debit_balance'])}", f"- Signed net {cr(r['signed_net'])}", "",
         "## Controls", f"- {r['controls']['total']} recorded, {r['controls']['pass']} PASS (source to extract {r['controls']['source_to_extract']}, extract to mart {r['controls']['extract_to_mart']})",
         f"- maximum absolute variance: {r['controls']['max_abs_variance']}; extract vs mart row variance {r['extract_vs_mart']['row_variance']}; monetary variance {r['extract_vs_mart']['money_variance']}",
         f"- structural checks M1-M10 (violations): {json.dumps(r['mart_checks'])}", "",
         "## Ledger totals", "| Ledger | Dr/Cr | Rows | ₹ Cr abs | ₹ Cr signed |", "|---|---|---|---|---|", *[f"| {a} | {b} | {c:,} | {cr(d)} | {cr(e)} |" for a, b, c, d, e in r["ledger_totals"]], "",
         "## Document Age", "| Bucket | Dr/Cr | Rows | ₹ Cr abs |", "|---|---|---|---|", *[f"| {a} | {b} | {c:,} | {cr(d)} |" for a, b, c, d in r["document_age"]], "",
         "## Due Status", "| Status | Dr/Cr | Rows | ₹ Cr abs |", "|---|---|---|---|", *[f"| {a} | {b} | {c:,} | {cr(d)} |" for a, b, c, d in r["due_status"]]]
    return "\n".join(L) + "\n"


# ───────────── command line ─────────────


def main(argv: list[str]) -> int:
    import psycopg

    for stream in (sys.stdout, sys.stderr):                 # a Windows console may be cp1252, which cannot print the rupee sign
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
        print("No loader connection: set FPA_CRED_LOADER_URL, create .secrets/cred_loader.env, or run in an interactive terminal.")
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
            if argv[1] == "report":                           # numbers read from the mart itself for a run that is already loaded
                from types import SimpleNamespace

                assert_loader_identity(conn)
                row = conn.execute("SELECT as_of_date FROM cred.run WHERE extraction_run_id = %s", (argv[2],)).fetchone()
                if not row:
                    print("that run is not in the mart")
                    return 1
                res = summarize(conn, SimpleNamespace(run_id=argv[2], as_of=row[0].isoformat()), conn.execute("SELECT current_user").fetchone()[0], 0.0)
                print(render_report(res))
                return 0
            plan = preflight(Path(argv[2]), vendor_ref_salt())
            res = load_run(conn, plan)
            out = Path(argv[2]) / "staging" / "mart_load_report.md"
            out.write_text(render_report(res), encoding="utf-8")
            print(render_report(res))
            print(f"(report written to {out.name} inside the run folder)")
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
