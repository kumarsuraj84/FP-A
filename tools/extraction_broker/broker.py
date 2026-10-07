"""
FP&A extraction broker.

    Inventory Automation Oracle  ->  guarded SELECT  ->  Parquet + manifest  ->  FP&A inbox

FP&A never connects to Oracle, never reads, copies, decrypts or logs the Inventory Automation credential.
This script only talks to the running Inventory Automation app on localhost (its own HTTP API), asks it to run
guarded, capped SELECTs on ITS existing connection, and copies the Parquet files it produces into
data/inbox/run_<date>_<nnn>/ together with a manifest that FP&A validates before loading anything.

    python tools/extraction_broker/broker.py plan   discovery_01            # guard report, touches nothing
    python tools/extraction_broker/broker.py run    discovery_01            # backs up platform.db, then extracts
    python tools/extraction_broker/broker.py verify data/inbox/run_...      # what the loader checks
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import guard  # noqa: E402
import manifest as mf  # noqa: E402
import packages  # noqa: E402
import pl_actuals  # noqa: E402,F401  (registers pl_actuals_01)
import pl_probe  # noqa: E402,F401  (registers pl_meta_probe_01)
import area_probe  # noqa: E402,F401  (registers store_area_probe_01)
import cogs_probe  # noqa: E402,F401  (registers cogs_meta_probe_01, cogs_scan_01)
import identity_probe  # noqa: E402,F401  (registers entry_identity_probe_01)
import login_probe  # noqa: E402,F401  (registers login_access_probe_01)
import ssrk_probe  # noqa: E402,F401  (registers ssrk_meta_probe_01)
import ssrk_probe2  # noqa: E402,F401  (registers ssrk_meta_probe_02)
import login_probe2  # noqa: E402,F401  (registers misretail_visibility_probe_01)
import ssrk_probe3  # noqa: E402,F401  (registers ssrk_range_probe_01)
import ssrk_probe4  # noqa: E402,F401  (registers ssrk_range_probe_02)
import ssrk_probe5  # noqa: E402,F401  (registers ssrk_range_probe_03)
import ssrk_probe6  # noqa: E402,F401  (registers ssrk_day_sample_01)
import ssrk_probe7  # noqa: E402,F401  (registers ssrk_logic_probe_01)
import ssrk_probe8  # noqa: E402,F401  (registers ssrk_masters_01)
import ssrk_books  # noqa: E402,F401  (registers ssrk_books_probe_01)
import ssrk_probe9  # noqa: E402,F401  (registers ssrk_cube_probe_01)
import ssrk_otsd  # noqa: E402,F401  (registers ssrk_otsd_probe_01)
import creditors_live  # noqa: E402,F401  (registers creditors_live_01)
import cash_live_probe  # noqa: E402,F401  (registers cash_live_probe_01)
import cash_bank_live  # noqa: E402,F401  (registers cash_bank_live_01)
import readiness  # noqa: E402
from packages import PACKAGE_META, PACKAGES, Dataset  # noqa: E402

BROKER_VERSION = "1"
REPO = Path(__file__).resolve().parents[2]
INBOX = REPO / "data" / "inbox"
API = os.environ.get("FPA_BROKER_API", "http://localhost:4001/api/v1")
INVENTORY_HOME = Path(os.environ.get("FPA_INVENTORY_HOME", r"C:\Users\Citykart\Desktop\AI_WORK\INVENTORY AUTOMATION"))
ORACLE_CONNECTION_NAME = os.environ.get("FPA_ORACLE_CONNECTION_NAME", "Oracle MISRETAIL (ODBC)")
PAUSE_BETWEEN_QUERIES_S = 2.0
TERMINAL = {"success", "failed", "cancelled", "error"}


class BrokerError(RuntimeError):
    pass


_SECRET = re.compile(r"(?i)\b(pwd|password|uid|user|authorization|x-tower-key)\s*[=:]\s*[^;\s,}]+")


def redact(text: str) -> str:
    return _SECRET.sub(lambda m: f"{m.group(1)}=***", str(text))[:600]


def assert_local(url: str) -> None:
    host = urllib.parse.urlparse(url).hostname
    if host not in ("localhost", "127.0.0.1", "::1"):
        raise BrokerError("the broker only talks to the Inventory Automation app on this machine (localhost)")


def http(method: str, path: str, body: dict | None = None, timeout: int = 30):
    assert_local(API)
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(f"{API}{path}", data=data, method=method, headers={"Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        raise BrokerError(f"{method} {path} -> HTTP {e.code}: {redact(detail)}") from None
    except urllib.error.URLError as e:
        raise BrokerError(f"cannot reach the Inventory Automation app at {API}: {redact(e.reason)}") from None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def first_object(sql: str) -> str:
    m = re.search(r"(?i)\bfrom\s+([\w$#.\"]+)", sql)
    return m.group(1).strip('"').upper() if m else "UNKNOWN"


# ───────────── safety: back up the app's database before the first change ─────────────


def backup_platform_db() -> Path:
    src = INVENTORY_HOME / "data_lake" / "metadata" / "platform.db"
    if not src.exists():
        raise BrokerError("Inventory Automation platform.db was not found; refusing to continue without a backup")
    dst_dir = src.parent / "backups"
    dst_dir.mkdir(exist_ok=True)
    dst = dst_dir / f"platform_pre_fpa_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    # SQLite's online backup API: consistent even while the app is running, and the source is opened read-only
    with closing(sqlite3.connect(f"file:{src.as_posix()}?mode=ro", uri=True)) as s, closing(sqlite3.connect(dst)) as d:
        s.backup(d)
    with closing(sqlite3.connect(f"file:{dst.as_posix()}?mode=ro", uri=True)) as d:
        if d.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise BrokerError("the platform.db backup failed its integrity check")
    return dst


# ───────────── talking to the app ─────────────


def find_oracle_connection() -> int:
    conns = http("GET", "/connections")
    hits = [c for c in conns if c.get("name") == ORACLE_CONNECTION_NAME and c.get("db_type") == "oracle"]
    if len(hits) != 1:
        raise BrokerError(f"expected exactly one active Oracle connection named '{ORACLE_CONNECTION_NAME}', found {len(hits)}")
    if not hits[0].get("is_active", True):
        raise BrokerError("the Oracle connection is marked inactive in Inventory Automation")
    return int(hits[0]["id"])  # only the id is used; nothing else about the connection is read or kept


def ensure_query(conn_id: int, name: str, checked: guard.Checked, description: str, timeout_s: int) -> int:
    found = http("GET", "/queries?search=" + urllib.parse.quote(name))
    for q in found:
        if q["name"] == name:
            if guard.query_hash(q["sql_query"]) != checked.query_hash:
                raise BrokerError(f"query '{name}' already exists with different SQL; refusing to overwrite")
            return int(q["id"])
    created = http(
        "POST",
        "/queries",
        {
            "name": name,
            "description": description,
            "connection_id": conn_id,
            "sql_query": checked.sql,
            "status": "active",
            "output_format": "parquet",
            "row_limit": checked.row_cap,
            "timeout_seconds": timeout_s,
            "append_mode": False,
        },
    )
    return int(created["id"])


def run_and_wait(qid: int, timeout_s: int) -> dict:
    run_uuid = http("POST", f"/extraction/trigger/{qid}")["run_uuid"]
    t0 = time.monotonic()
    last = {}
    try:
        while True:
            time.sleep(2)
            last = http("GET", f"/extraction/status/{run_uuid}")
            if last["status"] in TERMINAL:
                return last
            if time.monotonic() - t0 > timeout_s + 60:
                http("POST", f"/extraction/cancel/{run_uuid}")
                last["status"] = "failed"
                last["error_message"] = "broker timeout: cancelled"
                return last
    except KeyboardInterrupt:
        http("POST", f"/extraction/cancel/{run_uuid}")
        raise


TIMEOUT_MESSAGE = "broker timeout: cancelled"
ODBC_FAULT_MARKER = "returned a result with an exception set"   # the generic driver fault the same statement raised once and not the next time


def _retryable(st: dict) -> bool:
    msg = str(st.get("error_message") or "")
    return msg == TIMEOUT_MESSAGE or ODBC_FAULT_MARKER in msg


def run_with_retry(qid: int, timeout_s: int, attempts: int = 1) -> dict:
    """run_and_wait, repeated ONLY after the broker's own timeout cancel or the generic ODBC fault (the queries are read-only SELECTs, so a repeat is safe). Any other failure ends it at once."""
    st = {}
    for n in range(1, attempts + 1):
        st = run_and_wait(qid, timeout_s)
        if st["status"] == "success" or not _retryable(st):
            break
        if n < attempts:
            print(f"      (attempt {n} of {attempts} failed with a timeout or the generic ODBC fault: trying again)")
    return st


# ───────────── helpers over parquet (pyarrow is only needed here and in manifest checks) ─────────────


def parquet_info(path: Path, date_columns: tuple[str, ...]) -> dict:
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    pf = pq.ParquetFile(path)
    info = {"row_count": pf.metadata.num_rows, "columns": [f.name for f in pf.schema_arrow], "min_date": None, "max_date": None}
    cols = [c for c in date_columns if c in info["columns"]]
    if cols and info["row_count"]:
        table = pq.read_table(path, columns=cols)
        lo, hi = [], []
        for c in cols:
            mm = pc.min_max(table[c]).as_py()
            if mm.get("min") is not None:
                lo.append(mm["min"])
                hi.append(mm["max"])
        if lo:
            info["min_date"] = min(lo).isoformat()
            info["max_date"] = max(hi).isoformat()
    return info


def read_rows(path: Path) -> list[dict]:
    import pyarrow.parquet as pq

    return [{k.upper(): v for k, v in r.items()} for r in pq.read_table(path).to_pylist()]


def next_run_dir() -> tuple[str, Path]:
    INBOX.mkdir(parents=True, exist_ok=True)
    day = datetime.now().strftime("%Y%m%d")
    n = 1
    while (INBOX / f"run_{day}_{n:03d}").exists():
        n += 1
    run_id = f"run_{day}_{n:03d}"
    path = INBOX / run_id
    path.mkdir()
    return run_id, path


# ───────────── commands ─────────────


def cmd_plan(package: str) -> int:
    ds = PACKAGES[package]
    bad = 0
    print(f"Package {package}: {len(ds)} datasets. Guard report (nothing is sent anywhere):\n")
    for d in ds:
        if d.sql is None:
            print(f"  {d.name:<28} {d.kind:<9} (SQL is built from {', '.join(d.depends_on)} at run time, and guarded then)")
            continue
        try:
            c = guard.check(d.sql, d.kind)
            print(f"  {d.name:<28} {d.kind:<9} cap {c.row_cap:>7,}  hash {c.query_hash[:10]}  OK")
        except guard.GuardError as e:
            bad += 1
            print(f"  {d.name:<28} {d.kind:<9} REJECTED: {e}")
    print("\nAll static datasets pass the guard." if not bad else f"\n{bad} dataset(s) rejected.")
    return 1 if bad else 0


BASELINE = INBOX / ".entry_register_baseline.json"


def _probe(conn_id: int, d) -> dict | None:
    """Run one readiness query and read its single row straight from the app's output file (nothing is copied into the inbox). None = it did not complete."""
    try:
        checked = guard.check(d.sql, d.kind)
        qid = ensure_query(conn_id, f"FPA__entry_readiness__{d.name}__{checked.query_hash[:8]}", checked, f"FP&A extraction broker | readiness | {d.description}", 120)
        st = run_and_wait(qid, 120)
        if st["status"] != "success" or not Path(st["output_path"]).exists():
            return None
        rows = read_rows(Path(st["output_path"]))
        return {k.lower(): v for k, v in rows[0].items()} if len(rows) == 1 else None
    except (BrokerError, guard.GuardError, LookupError, OSError):
        return None


def check_entry_readiness(conn_id: int) -> tuple[bool, str]:
    reg, cube = (_probe(conn_id, d) for d in packages.ENTRY_READINESS)
    ready, reason = readiness.assess(reg, cube, readiness.load_baseline(BASELINE))
    if ready:
        readiness.record_baseline(BASELINE, int(float(reg["register_rows"])), str(reg["register_report_date"]))
    return ready, reason


def check_pl_readiness(conn_id: int, as_of: str) -> tuple[bool, str]:
    """P&L readiness: the current register is non-empty, has a report date, and that date IS the requested as-of date (an as-of ahead of the register would read a half-loaded day)."""
    reg = _probe(conn_id, packages.ENTRY_READINESS[0])
    if reg is None:
        return False, readiness.PROBE_FAILED
    ready, reason = readiness.assess(reg, {"cube_report_date": as_of}, readiness.load_baseline(BASELINE))
    if not ready and reason == readiness.MISMATCH:
        reason = f"{reason} (the register's report date is {reg.get('register_report_date')}, the requested as-of date is {as_of})"
    return ready, reason


def cmd_run(package: str, only: set[str] | None) -> int:
    datasets = [d for d in PACKAGES[package] if not only or d.name in only]
    if not datasets:
        raise BrokerError("no datasets selected")
    # 1. guard everything we can before touching anything
    for d in datasets:
        if d.sql:
            guard.check(d.sql, d.kind)
    # 2. preconditions
    conn_id = find_oracle_connection()
    backup = backup_platform_db()
    print(f"Backed up platform.db -> {backup.name}")
    if package == "pl_actuals_01":
        ready, reason = check_pl_readiness(conn_id, PACKAGE_META[package]["contract"]["as_of_cutoff"])
        if not ready:
            print(f"SOURCE_NOT_READY — {reason}. Nothing was extracted and no run folder was created.")
            return 3
        print("Source ready: register non-empty and its report date equals the requested as-of date.\n")
    if package == "entry_pilot_01":
        ready, reason = check_entry_readiness(conn_id)   # before any run folder exists: a not-ready source leaves nothing that looks like a candidate run
        if not ready:
            print(f"SOURCE_NOT_READY — {reason}. Nothing was extracted and no run folder was created.")
            return 3
        print("Source ready: register non-empty, report date present and equal to the cube's.\n")
    run_id, run_dir = next_run_dir()
    print(f"Run {run_id} -> {run_dir}\n")
    m = {
        "run_id": run_id,
        "package": package,
        "created_at": now_iso(),
        "broker_version": BROKER_VERSION,
        "platform_db_backup": backup.name,
        "source": "Inventory Automation extraction service (localhost); Oracle credential never read by FP&A",
        "datasets": [],
    }
    meta = PACKAGE_META.get(package, {})
    if meta.get("contract"):
        m["manifest_version"] = 2
        m["contract"] = meta["contract"]
        m["protocol"] = {"order": [d.name for d in datasets], "halt_on_failure": bool(meta.get("halt_on_failure"))}
    mf.write_manifest(run_dir, m)
    results: dict[str, list[dict]] = {}
    failed: set[str] = set()

    for d in datasets:
        entry = {
            "dataset": d.name, "kind": d.kind, "source_object": None, "logical_source": None, "copy_id": None,
            "query_id": None, "query_hash": "0" * 64, "extracted_at": None, "row_count": 0, "row_cap": 0,
            "min_date": None, "max_date": None, "file_name": f"{d.name}.parquet", "file_size": 0, "sha256": "0" * 64,
            "status": "pending", "description": d.description, "error": None, "role": d.role,
        }
        m["datasets"].append(entry)
        try:
            if any(dep in failed or dep not in results for dep in d.depends_on):
                entry["status"] = "skipped"
                entry["error"] = "a dataset it depends on did not complete"
                print(f"  {d.name:<28} skipped")
                continue
            sql = d.sql if d.sql else d.build(results)
            checked = guard.check(sql, d.kind)
            entry.update(source_object=first_object(checked.sql), query_hash=checked.query_hash, row_cap=checked.row_cap)
            name = f"FPA__{package}__{d.name}__{checked.query_hash[:8]}"
            timeout_s = int(meta.get("timeout_s") or (300 if d.kind == "metadata" else 600))
            qid = ensure_query(conn_id, name, checked, f"FP&A extraction broker | {package} | {d.kind} | {d.description}", timeout_s)
            entry["query_id"] = qid
            t0 = time.monotonic()
            st = run_with_retry(qid, timeout_s, int(meta.get("attempts") or 1))
            if st["status"] != "success":
                raise BrokerError(redact(st.get("error_message") or f"run ended with status {st['status']}"))
            out = Path(st["output_path"])
            if not out.exists():
                raise BrokerError("the app reported success but the Parquet file is not on disk")
            dst = run_dir / entry["file_name"]
            shutil.copy2(out, dst)
            info = parquet_info(dst, d.date_columns)
            entry.update(
                extracted_at=now_iso(), row_count=info["row_count"], min_date=info["min_date"], max_date=info["max_date"],
                file_size=dst.stat().st_size, sha256=mf.sha256_file(dst),
                status=("sampled" if d.kind == "sample" else "capped") if info["row_count"] >= checked.row_cap else "ok",
            )
            results[d.name] = read_rows(dst) if (d.name in {x for dd in datasets for x in dd.depends_on}) else []
            print(f"  {d.name:<28} {entry['status']:<7} {info['row_count']:>9,} rows  {time.monotonic() - t0:5.1f}s")
        except (BrokerError, guard.GuardError, LookupError) as e:
            entry["status"] = "failed"
            entry["error"] = redact(e)
            failed.add(d.name)
            print(f"  {d.name:<28} FAILED  {entry['error']}")
        mf.write_manifest(run_dir, m)
        if meta.get("halt_on_failure") and entry["status"] in ("failed", "capped"):
            # a pilot never carries on after a failed or truncated step: no extract after a failed control
            for later in datasets[datasets.index(d) + 1:]:
                m["datasets"].append({"dataset": later.name, "kind": later.kind, "role": later.role, "status": "skipped", "error": "run halted after an earlier failure", **{k: None for k in ("source_object", "logical_source", "copy_id", "query_id", "extracted_at", "min_date", "max_date")}, "query_hash": "0" * 64, "row_count": 0, "row_cap": 0, "file_name": f"{later.name}.parquet", "file_size": 0, "sha256": "0" * 64, "description": later.description})
            print(f"\n  HALTED after {d.name}: {entry['status']}")
            break
        time.sleep(PAUSE_BETWEEN_QUERIES_S)  # one query at a time, with a breather for the database

    m["finished_at"] = now_iso()
    mf.write_manifest(run_dir, m)
    v = mf.validate_manifest(run_dir)
    print(f"\nManifest check: {'OK' if v.ok else 'ERRORS'}; loadable {len(v.loadable)}/{len(datasets)}")
    for e in v.errors:
        print("  ERROR  ", e)
    for w in v.warnings:
        print("  warning", w)
    return 0 if v.ok else 1


def cmd_verify(path: str) -> int:
    v = mf.validate_manifest(Path(path))
    print("OK" if v.ok else "NOT OK")
    for e in v.errors:
        print("  ERROR  ", e)
    for w in v.warnings:
        print("  warning", w)
    print(f"loadable: {len(v.loadable)}")
    return 0 if v.ok else 1


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):  # an Oracle error text can hold characters the Windows console cannot encode: never let printing kill a run
        stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "run"):
        p = sub.add_parser(name)
        p.add_argument("package", choices=sorted(PACKAGES))
        p.add_argument("--as-of", help="YYYY-MM-DD: REQUIRED for entry_pilot_01 (the business date the creditors and cash runs were built for); refused for any other package")
        if name == "run":
            p.add_argument("--only", help="comma-separated dataset names")
    sub.add_parser("verify").add_argument("run_dir")
    a = ap.parse_args(argv)
    try:
        if a.cmd in ("plan", "run"):
            if a.package == "entry_pilot_01":
                if not a.as_of:
                    raise BrokerError("entry_pilot_01 needs an explicit --as-of YYYY-MM-DD: there is no implicit today")
                try:
                    packages.configure_entry(a.as_of)
                except ValueError as e:
                    raise BrokerError(str(e)) from None
            elif a.package == "cogs_scan_02":
                if not a.as_of:
                    raise BrokerError("cogs_scan_02 needs an explicit --as-of YYYY-MM-DD (the same date as the P&L run): there is no implicit today")
                try:
                    cogs_probe.configure_cogs(a.as_of)
                except ValueError as e:
                    raise BrokerError(str(e)) from None
            elif a.package == "pl_actuals_01":
                if not a.as_of:
                    raise BrokerError("pl_actuals_01 needs an explicit --as-of YYYY-MM-DD (the register's own report date): there is no implicit today")
                try:
                    pl_actuals.configure_pl(a.as_of)
                except ValueError as e:
                    raise BrokerError(str(e)) from None
            elif a.package == "cash_bank_live_01":
                if not a.as_of:
                    raise BrokerError("cash_bank_live_01 needs an explicit --as-of YYYY-MM-DD, and it must be today (the live tables hold only the current position)")
                try:
                    cash_bank_live.configure_bank(a.as_of)
                except ValueError as e:
                    raise BrokerError(str(e)) from None
            elif a.package == "creditors_live_01":
                if not a.as_of:
                    raise BrokerError("creditors_live_01 needs an explicit --as-of YYYY-MM-DD, and it must be today (the live tables hold only the current position)")
                try:
                    creditors_live.configure_live(a.as_of)
                except ValueError as e:
                    raise BrokerError(str(e)) from None
            elif a.as_of:
                raise BrokerError(f"{a.package} does not take an as-of date")
        if a.cmd == "plan":
            return cmd_plan(a.package)
        if a.cmd == "run":
            return cmd_run(a.package, set(a.only.split(",")) if a.only else None)
        return cmd_verify(a.run_dir)
    except (BrokerError, guard.GuardError) as e:
        print(f"STOPPED: {redact(e)}")
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
