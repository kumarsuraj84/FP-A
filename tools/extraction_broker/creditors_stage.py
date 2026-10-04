"""
Offline staging validation for the Creditors pilot (package creditors_pilot_01, contract creditors-pilot-1.0).

    python tools/extraction_broker/creditors_stage.py data/inbox/run_YYYYMMDD_NNN

Reads ONLY the Parquet files and manifest of one broker run. It never talks to Oracle, never loads Postgres and never
touches the frontend. It:

  1. validates the manifest and requires every dataset to be `ok` (a capped / failed / skipped dataset fails the run);
  2. rejects the run if the PRE source controls differ from the POST source controls (cube refreshed mid-extract);
  3. derives Document Age, Due Status, date quality, the identity key and the fingerprints from the raw extract;
  4. fails on any duplicate / null identity key (no ordinal, no deduplication, no "keep first");
  5. reconciles source controls -> extract -> staging (C1..C12) with exact decimals and a 0.00 tolerance;
  6. writes the derived Parquet, validation_report.json and VALIDATION_REPORT.md (aggregates only: no names, no codes).

Derived fields use the as_of_date carried in the data (the cube REPORT_DATE). The current date is never read here.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import manifest as mf  # noqa: E402

NULL = "~NULL~"
# Oracle's TM9 prints 0.5 as ".5" and -0.5 as "-.5", so a bare leading dot is valid
_NUM = re.compile(r"^-?([0-9]+(\.[0-9]+)?|\.[0-9]+)$")
_DATE = re.compile(r"^([0-9]{4})-([0-9]{2})-([0-9]{2})$")
ZERO = Decimal(0)

E1_COLUMNS = [
    "as_of_date", "document_code", "sub_ledger_code", "ledger_code", "ledger_name", "slid", "vendor_name", "party_class", "party_class_type",
    "credit_days", "vendor_extinct", "document_no", "document_type", "document_initial", "document_date", "due_date", "due_date_basis",
    "ref_no", "ref_date", "entry_date", "drcr", "amount", "adjusted", "pending", "created_by_site",
]
E2_COLUMNS = ["document_code", "sub_ledger_code", "ledger_code", "drcr", "pending", "entry_date", "as_of_date"]
EXPECTED_DATASETS = {
    "c1_source_control_pre": "control_pre", "c2_vendor_control_pre": "control_pre", "c3_snapshot_control_pre": "control_pre",
    "e1_open_items": "extract", "e2_identity_all_rows": "identity",
    "c1_source_control_post": "control_post", "c2_vendor_control_post": "control_post", "c3_snapshot_control_post": "control_post",
}
FINGERPRINT_FIELDS = ["ledger_code", "drcr", "amount", "adjusted", "pending", "document_date", "due_date", "ref_no", "ref_date", "entry_date",
                      "document_no", "document_type", "document_initial", "due_date_basis", "created_by_site"]
VENDOR_FIELDS = ["party_class", "party_class_type", "credit_days", "vendor_extinct", "vendor_name", "slid"]
BUCKET_ORDER = ["D0_30", "D31_60", "D61_90", "D91_180", "D181_365", "D365_PLUS",
                "UNCLASSIFIED_MISSING", "UNCLASSIFIED_BEFORE_MIN", "UNCLASSIFIED_AFTER_AS_OF", "UNCLASSIFIED_UNPARSEABLE"]
DUE_ORDER = ["NOT_YET_DUE", "PAST_DUE_OR_DUE_TODAY", "DUE_UNAVAILABLE", "DUE_INVALID"]


class StageError(RuntimeError):
    pass


# ───────────── pure rules (unit-tested) ─────────────


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_decimal(text, field: str = "value"):
    """Exact decimal from Oracle TM9 text. None stays None. Anything else that is not a plain number is an error."""
    if text is None:
        return None
    t = str(text).strip()
    if not _NUM.match(t):
        raise StageError(f"{field}: '{t[:20]}' is not a plain decimal number")
    try:
        return Decimal(t)
    except InvalidOperation as e:  # pragma: no cover - the regex already guards this
        raise StageError(f"{field}: not a decimal") from e


def parse_date(text):
    """-> (date | None, flag) with flag OK / MISSING / UNPARSEABLE. A year such as 0202 is a valid date, never silently fixed."""
    if text is None or str(text).strip() == "":
        return None, "MISSING"
    m = _DATE.match(str(text).strip())
    if not m:
        return None, "UNPARSEABLE"
    try:
        return date(int(m[1]), int(m[2]), int(m[3])), "OK"
    except ValueError:
        return None, "UNPARSEABLE"


def classify_age(doc, as_of: date, rules: dict):
    """-> (document_age_bucket, document_age_days | None, date_quality_status)"""
    d, flag = doc
    if flag == "MISSING":
        return "UNCLASSIFIED_MISSING", None, "MISSING"
    if flag == "UNPARSEABLE":
        return "UNCLASSIFIED_UNPARSEABLE", None, "UNPARSEABLE"
    if d < date.fromisoformat(rules["valid_date_min"]):
        return "UNCLASSIFIED_BEFORE_MIN", None, "BEFORE_MIN"
    if d > as_of:
        return "UNCLASSIFIED_AFTER_AS_OF", None, "AFTER_AS_OF"
    days = (as_of - d).days
    for name, edge in rules["age_buckets"]:
        if days <= edge:
            return name, days, "OK"
    return "D365_PLUS", days, "OK"


def classify_due(due, doc, as_of: date, rules: dict):
    """-> (due_status, overdue_days | None). Stored DUE_DATE only; a missing due date is never derived from CREDIT_DAYS."""
    d, flag = due
    if flag == "MISSING":
        return "DUE_UNAVAILABLE", None
    if flag == "UNPARSEABLE":
        return "DUE_INVALID", None
    if d < date.fromisoformat(rules["valid_date_min"]) or d > date.fromisoformat(rules["valid_date_max"]):
        return "DUE_INVALID", None
    if doc[0] is not None and d < doc[0]:
        return "DUE_INVALID", None
    if d > as_of:
        return "NOT_YET_DUE", None
    return "PAST_DUE_OR_DUE_TODAY", (as_of - d).days


def check_identity_parts(doc_code, sub_code) -> str | None:
    if doc_code is None or str(doc_code) == "" or sub_code is None or str(sub_code) == "":
        return "null_or_empty"
    if "|" in str(doc_code) or "|" in str(sub_code):
        return "contains_delimiter"
    return None


def source_row_key(doc_code: str, sub_code: str) -> str:
    return sha(f"v1|{doc_code}|{sub_code}")


def k1_signature(doc_code: str, ledger: str, sub_code: str, drcr: str) -> str:
    return sha(f"v1|{doc_code}|{ledger}|{sub_code}|{drcr}")


def canon(v) -> str:
    if v is None:
        return NULL
    if isinstance(v, Decimal):
        return "0" if v == 0 else format(v.normalize(), "f")
    return str(v)


def fingerprint(fields: list[str], row: dict) -> str:
    return sha("v1|" + "|".join(canon(row.get(f)) for f in fields))


# ───────────── io ─────────────


def load(run_dir: Path, name: str, columns: list[str] | None = None) -> list[dict]:
    import pyarrow.parquet as pq

    rows = [{k.lower(): v for k, v in r.items()} for r in pq.read_table(run_dir / f"{name}.parquet").to_pylist()]
    if columns is not None and rows:
        got = sorted(rows[0].keys())
        if got != sorted(columns):
            raise StageError(f"{name}: columns differ from the contract ({sorted(set(got) ^ set(columns))})")
    return rows


def as_int(v) -> int:
    return int(Decimal(str(v)))


def norm_rows(rows: list[dict]) -> list[str]:
    return sorted(json.dumps({k: (None if v is None else str(v)) for k, v in sorted(r.items())}, sort_keys=True) for r in rows)


# ───────────── validation ─────────────


class Recon:
    """Collects controls; every control compares two layers exactly. Any non-zero variance is a failure."""

    def __init__(self):
        self.rows: list[dict] = []

    def add(self, cid: str, dim: str, a_layer: str, a, b_layer: str, b):
        if isinstance(a, Decimal) or isinstance(b, Decimal):
            a, b = Decimal(a), Decimal(b)
        var = b - a
        self.rows.append({"control": cid, "dimension": dim, "left_layer": a_layer, "left": str(a), "right_layer": b_layer, "right": str(b), "variance": str(var), "verdict": "PASS" if var == 0 else "FAIL"})

    @property
    def failed(self):
        return [r for r in self.rows if r["verdict"] == "FAIL"]


def validate(run_dir: Path, baseline: dict | None = None) -> dict:
    report: dict = {"run": run_dir.name, "verdict": "FAILED", "hard_failures": [], "controls": [], "aggregates": {}, "informational": {}}
    fail = report["hard_failures"].append

    # 1. manifest and dataset status
    v = mf.validate_manifest(run_dir)
    if not v.ok:
        for e in v.errors:
            fail(f"manifest: {e}")
    m = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    if m.get("package") != "creditors_pilot_01" or m.get("manifest_version") != 2:
        fail("manifest: not a creditors_pilot_01 / manifest_version 2 run")
    rules = (m.get("contract") or {})
    if not rules:
        fail("manifest: contract block missing")
    by = {d["dataset"]: d for d in m["datasets"]}
    for name, role in EXPECTED_DATASETS.items():
        d = by.get(name)
        if d is None:
            fail(f"dataset {name} is missing")
        elif d["status"] != "ok":
            fail(f"dataset {name} has status '{d['status']}' (a capped, failed or skipped dataset fails the pilot)")
        elif d.get("role") != role:
            fail(f"dataset {name} has role '{d.get('role')}', expected '{role}'")
    if report["hard_failures"]:
        return finish(run_dir, report, None, None)
    report["manifest_sha256"] = mf.sha256_file(run_dir / "manifest.json")

    # 2. pre vs post source controls: a difference means the cube changed during the extraction window
    for kind in ("c1_source_control", "c2_vendor_control", "c3_snapshot_control"):
        if norm_rows(load(run_dir, f"{kind}_pre")) != norm_rows(load(run_dir, f"{kind}_post")):
            fail(f"REFRESH RACE: {kind} differs between PRE and POST")
    c1, c2, c3 = load(run_dir, "c1_source_control_pre"), load(run_dir, "c2_vendor_control_pre"), load(run_dir, "c3_snapshot_control_pre")
    if len(c3) != 1:
        fail("c3_snapshot_control_pre must have exactly one row")
        return finish(run_dir, report, None, None)
    c3 = c3[0]

    # 3. load the extract and the identity extract
    e1 = load(run_dir, "e1_open_items", E1_COLUMNS) if by["e1_open_items"]["row_count"] else []
    e2 = load(run_dir, "e2_identity_all_rows", E2_COLUMNS) if by["e2_identity_all_rows"]["row_count"] else []
    if not e1:
        fail("e1_open_items is empty")
        return finish(run_dir, report, None, None)

    # 4. as-of: exactly one report date everywhere
    as_ofs = {r["as_of_date"] for r in e1} | {r["as_of_date"] for r in e2} | {c3["min_as_of"], c3["max_as_of"]}
    if len(as_ofs) != 1 or as_int(c3["report_dates"]) != 1:
        fail(f"as_of_date is not a single value ({len(as_ofs)} distinct in data, {c3['report_dates']} in the source control)")
        return finish(run_dir, report, None, None)
    as_of_txt = next(iter(as_ofs))
    as_of, aflag = parse_date(as_of_txt)
    if aflag != "OK":
        fail("as_of_date is not a valid date")
        return finish(run_dir, report, None, None)
    report["as_of_date"] = as_of_txt

    # 5. derive row by row; identity checks never repair anything
    keys, k1s = Counter(), Counter()
    bad_identity = Counter()
    staged: list[dict] = []
    for r in e1:
        problem = check_identity_parts(r["document_code"], r["sub_ledger_code"])
        if problem:
            bad_identity[problem] += 1
            continue
        pend, amt, adj = parse_decimal(r["pending"], "pending"), parse_decimal(r["amount"], "amount"), parse_decimal(r["adjusted"], "adjusted")
        if pend is None or amt is None or pend == 0:
            fail("an extracted row has a null amount/pending or PENDING = 0 (out of scope)")
            break
        if r["drcr"] not in ("Cr", "Dr"):
            fail(f"unexpected DRCR value '{r['drcr']}'")
            break
        if (r["drcr"] == "Cr") != (pend < 0):
            fail("PENDING sign does not follow DRCR for at least one row (Cr must be negative, Dr positive)")
            break
        doc, due = parse_date(r["document_date"]), parse_date(r["due_date"])
        ref, ent = parse_date(r["ref_date"]), parse_date(r["entry_date"])
        bucket, age_days, dq = classify_age(doc, as_of, rules)
        due_status, overdue = classify_due(due, doc, as_of, rules)
        row = {**r, "amount": amt, "adjusted": adj, "pending": pend}
        key = source_row_key(r["document_code"], r["sub_ledger_code"])
        sig = k1_signature(r["document_code"], r["ledger_code"], r["sub_ledger_code"], r["drcr"])
        keys[key] += 1
        k1s[sig] += 1
        staged.append({
            "source_run_id": run_dir.name, "source_row_key": key, "identity_k1_signature": sig,
            "row_fingerprint": fingerprint(FINGERPRINT_FIELDS, row), "vendor_fingerprint": fingerprint(VENDOR_FIELDS, row),
            "as_of_date": as_of, "document_date": doc[0], "due_date": due[0], "ref_date": ref[0], "entry_date": ent[0],
            "document_date_raw": r["document_date"], "due_date_raw": r["due_date"], "ref_date_raw": r["ref_date"], "entry_date_raw": r["entry_date"],
            "document_code": r["document_code"], "sub_ledger_code": r["sub_ledger_code"], "ledger_code": r["ledger_code"], "ledger_name": r["ledger_name"],
            "slid": r["slid"], "vendor_name": r["vendor_name"], "party_class": r["party_class"], "party_class_type": r["party_class_type"],
            "credit_days": None if r["credit_days"] is None else int(parse_decimal(r["credit_days"], "credit_days")), "vendor_extinct": r["vendor_extinct"],
            "document_no": r["document_no"], "document_type": r["document_type"], "document_initial": r["document_initial"],
            "due_date_basis": r["due_date_basis"], "ref_no": r["ref_no"], "created_by_site": r["created_by_site"],
            "drcr": r["drcr"], "amount": amt, "adjusted": adj, "pending": pend,
            "document_age_days": age_days, "document_age_bucket": bucket, "overdue_days": overdue, "due_status": due_status,
            "date_quality_status": dq,
            "classification_status": "CREDIT_OUTSTANDING" if r["drcr"] == "Cr" else "CREDITOR_DEBIT_BALANCE_CLASSIFICATION_PENDING",
        })
    if bad_identity:
        fail(f"identity parts null/empty/contain '|': {dict(bad_identity)}")
    dup_keys = sum(1 for c in keys.values() if c > 1)
    dup_k1 = sum(1 for c in k1s.values() if c > 1)
    if dup_keys:
        fail(f"DUPLICATE PRIMARY KEY: {dup_keys} source_row_key value(s) occur more than once (no ordinal, no deduplication)")
    if dup_k1:
        fail(f"DUPLICATE K1 SIGNATURE: {dup_k1} value(s) occur more than once")
    if report["hard_failures"]:
        return finish(run_dir, report, None, None)

    rc = Recon()
    n = len(staged)

    # 6. source control -> extract (C1..C12)
    rc.add("C1", "total rows", "source c3", as_int(c3["item_rows"]), "extract e1", n)
    rc.add("C1", "total rows vs by-group c1", "source c3", as_int(c3["item_rows"]), "source c1 groups", sum(as_int(r["item_rows"]) for r in c1))
    grp_src = defaultdict(lambda: [0, ZERO, ZERO])
    for r in c1:
        g = grp_src[(r["ledger_code"], r["drcr"], r["doc_age_bucket"], r["due_status"])]
        g[0] += as_int(r["item_rows"]); g[1] += parse_decimal(r["abs_pending"]); g[2] += parse_decimal(r["signed_pending"])
    grp_ext = defaultdict(lambda: [0, ZERO, ZERO])
    for s in staged:
        g = grp_ext[(s["ledger_code"], s["drcr"], s["document_age_bucket"], s["due_status"])]
        g[0] += 1; g[1] += abs(s["pending"]); g[2] += s["pending"]
    for k in sorted(set(grp_src) | set(grp_ext)):
        a, b = grp_src.get(k, [0, ZERO, ZERO]), grp_ext.get(k, [0, ZERO, ZERO])
        d = "/".join(k)
        rc.add("C5/C7", f"rows {d}", "source c1", a[0], "extract", b[0])
        rc.add("C5/C7", f"abs {d}", "source c1", a[1], "extract", b[1])
        rc.add("C5/C7", f"signed {d}", "source c1", a[2], "extract", b[2])

    def roll(grp, idx):
        out = defaultdict(lambda: [0, ZERO, ZERO])
        for (led, dr, bk, du), vals in grp.items():
            for key in idx(led, dr, bk, du):
                for i in range(3):
                    out[key][i] += vals[i]
        return out

    views = {
        "C2/C3/C4 total": lambda l, d, b, u: [("all", "all")],
        "C1/C9 ledger x DRCR": lambda l, d, b, u: [(l, d)],
        "C5 bucket x DRCR": lambda l, d, b, u: [(b, d)],
        "C7 due status x DRCR": lambda l, d, b, u: [(u, d)],
        "C2/C3 ledger": lambda l, d, b, u: [(l, "all")],
        "C2/C3 DRCR": lambda l, d, b, u: [("all", d)],
    }
    for label, f in views.items():
        a, b = roll(grp_src, f), roll(grp_ext, f)
        for k in sorted(set(a) | set(b)):
            for i, what in enumerate(("rows", "abs", "signed")):
                rc.add(label.split()[0], f"{label} {k[0]}/{k[1]} {what}", "source c1", a[k][i] if k in a else 0, "extract", b[k][i] if k in b else 0)

    # vendors (C8)
    vend = {"all": set(), **{}}
    by_led, by_dr, by_both = defaultdict(set), defaultdict(set), defaultdict(set)
    for s in staged:
        vend["all"].add(s["sub_ledger_code"]); by_led[s["ledger_code"]].add(s["sub_ledger_code"]); by_dr[s["drcr"]].add(s["sub_ledger_code"]); by_both[(s["ledger_code"], s["drcr"])].add(s["sub_ledger_code"])
    for r in c2:
        gl, gd = as_int(r["g_ledger"]), as_int(r["g_drcr"])
        if gl and gd:
            k, ext = "all", len(vend["all"])
        elif gd:
            k, ext = f"ledger {r['ledger_code']}", len(by_led.get(r["ledger_code"], ()))
        elif gl:
            k, ext = f"drcr {r['drcr']}", len(by_dr.get(r["drcr"], ()))
        else:
            k, ext = f"ledger {r['ledger_code']} {r['drcr']}", len(by_both.get((r["ledger_code"], r["drcr"]), ()))
        rc.add("C8", f"vendors {k}", "source c2", as_int(r["vendors"]), "extract", ext)
        rc.add("C8", f"rows {k}", "source c2", as_int(r["item_rows"]), "extract", sum(1 for s in staged if (gl and gd) or (gd and s["ledger_code"] == r["ledger_code"]) or (gl and s["drcr"] == r["drcr"]) or (not gl and not gd and s["ledger_code"] == r["ledger_code"] and s["drcr"] == r["drcr"])))

    # keys, nulls, join coverage, as-of (C10, C12)
    rc.add("C10", "distinct identity keys = rows", "source c3", as_int(c3["distinct_identity_keys"]), "extract", len(keys))
    rc.add("C10", "distinct K1 signatures", "source c3", as_int(c3["distinct_k1_keys"]), "extract", len(k1s))
    rc.add("C10", "rows = distinct keys", "extract rows", n, "extract distinct", len(keys))
    rc.add("C10", "null identity rows", "source c3", as_int(c3["null_identity_rows"]), "extract", 0)
    rc.add("C6", "document_date missing rows", "source c3", as_int(c3["null_document_date_rows"]), "extract", sum(1 for s in staged if s["date_quality_status"] == "MISSING"))
    rc.add("C7", "due_date missing rows", "source c3", as_int(c3["null_due_date_rows"]), "extract", sum(1 for s in staged if s["due_date_raw"] is None))
    rc.add("C10", "rows without vendor master", "source c3", as_int(c3["rows_without_vendor_master"]), "extract", sum(1 for s in staged if s["slid"] is None))
    rc.add("C10", "rows without ledger master", "source c3", as_int(c3["rows_without_ledger_master"]), "extract", sum(1 for s in staged if s["ledger_name"] is None))
    rc.add("C12", "distinct as_of_date", "expected", 1, "extract", len(as_ofs))
    rc.add("C11", "e1 row count vs manifest", "manifest", by["e1_open_items"]["row_count"], "parquet", n)

    # 7. identity extract (e2) must agree with the extract: every open key, same ledger / drcr / pending
    e2_keys = Counter(source_row_key(r["document_code"], r["sub_ledger_code"]) for r in e2)
    e2_dup = sum(1 for c in e2_keys.values() if c > 1)
    rc.add("C10", "e2 duplicate identity keys", "expected", 0, "e2", e2_dup)
    e2_open = {}
    settled = 0
    for r in e2:
        p = parse_decimal(r["pending"], "e2 pending")
        if p is None:
            fail("e2 has a null PENDING")
            break
        if p == 0:
            settled += 1
        else:
            e2_open[source_row_key(r["document_code"], r["sub_ledger_code"])] = (r["ledger_code"], r["drcr"], p)
    e1_map = {s["source_row_key"]: (s["ledger_code"], s["drcr"], s["pending"]) for s in staged}
    rc.add("C10", "e2 open keys = e1 keys", "e1", len(e1_map), "e2 open", len(e2_open))
    rc.add("C10", "e2 vs e1 key/ledger/drcr/pending mismatches", "expected", 0, "e2", sum(1 for k, val in e2_open.items() if e1_map.get(k) != val) + sum(1 for k in e1_map if k not in e2_open))

    report["controls"] = rc.rows
    if rc.failed:
        for r in rc.failed[:20]:
            fail(f"CONTROL FAILED {r['control']} {r['dimension']}: {r['left_layer']} {r['left']} vs {r['right_layer']} {r['right']} (variance {r['variance']})")
    if report["hard_failures"]:
        return finish(run_dir, report, staged, None)

    # 8. aggregates for the review (no names, no codes of vendors or documents)
    def money(d):
        return str(d)

    cr = sum((abs(s["pending"]) for s in staged if s["drcr"] == "Cr"), ZERO)
    dr = sum((abs(s["pending"]) for s in staged if s["drcr"] == "Dr"), ZERO)
    net = sum((s["pending"] for s in staged), ZERO)
    agg = report["aggregates"]
    agg["rows"] = n
    agg["credit_rows"] = sum(1 for s in staged if s["drcr"] == "Cr")
    agg["debit_rows"] = n - agg["credit_rows"]
    agg["credit_outstanding"], agg["creditor_debit_balances"], agg["signed_net"] = money(cr), money(dr), money(net)
    agg["distinct_vendors"] = len(vend["all"])
    agg["distinct_keys"] = len(keys)
    agg["e2_rows"], agg["e2_settled_rows"], agg["e2_open_rows"] = len(e2), settled, len(e2_open)
    agg["ledger_totals"] = [{"ledger_code": k[0], "drcr": k[1], "rows": g[0], "abs": money(g[1]), "signed": money(g[2]), "vendors": len(by_both[(k[0], k[1])])}
                            for k, g in sorted(roll(grp_ext, views["C1/C9 ledger x DRCR"]).items())]
    names = {s["ledger_code"]: s["ledger_name"] for s in staged}
    for t in agg["ledger_totals"]:
        t["ledger_name"] = names.get(t["ledger_code"])
    agg["document_age"] = [{"bucket": b, "drcr": d, "rows": g[0], "abs": money(g[1])} for (b, d), g in sorted(roll(grp_ext, views["C5 bucket x DRCR"]).items(), key=lambda kv: (BUCKET_ORDER.index(kv[0][0]) if kv[0][0] in BUCKET_ORDER else 99, kv[0][1]))]
    agg["due_status"] = [{"status": u, "drcr": d, "rows": g[0], "abs": money(g[1])} for (u, d), g in sorted(roll(grp_ext, views["C7 due status x DRCR"]).items(), key=lambda kv: (DUE_ORDER.index(kv[0][0]) if kv[0][0] in DUE_ORDER else 99, kv[0][1]))]
    uncl = defaultdict(lambda: [0, ZERO])
    for s in staged:
        if s["document_age_bucket"].startswith("UNCLASSIFIED"):
            u = uncl[(s["date_quality_status"], s["drcr"])]
            u[0] += 1; u[1] += abs(s["pending"])
    agg["unclassified_document_age"] = [{"date_quality_status": k[0], "drcr": k[1], "rows": v[0], "abs": money(v[1])} for k, v in sorted(uncl.items())]
    pc = defaultdict(lambda: [0, ZERO])
    for s in staged:
        p = pc[(s["party_class"], s["drcr"])]
        p[0] += 1; p[1] += abs(s["pending"])
    agg["party_class"] = [{"party_class": k[0], "drcr": k[1], "rows": v[0], "abs": money(v[1])} for k, v in sorted(pc.items(), key=lambda kv: (str(kv[0][0]), kv[0][1]))]
    agg["credit_due_status_by_ledger"] = [
        {"ledger_code": led, "ledger_name": names.get(led), "status": st, "rows": g[0], "abs": money(g[1])}
        for (led, st), g in sorted(_credit_due(staged).items())
    ]
    agg["identity_extras"] = {"whitespace_padded_document_codes": sum(1 for s in staged if s["document_code"] != s["document_code"].strip()),
                              "vendor_class_null_rows": sum(1 for s in staged if s["party_class"] is None)}

    # 9. informational comparison with earlier evidence (never a gate)
    if baseline:
        report["informational"]["baseline_comparison"] = baseline_compare(agg, baseline)

    report["verdict"] = "PASSED"
    return finish(run_dir, report, staged, e2)


def _credit_due(staged):
    out = defaultdict(lambda: [0, ZERO])
    for s in staged:
        if s["drcr"] == "Cr":
            g = out[(s["ledger_code"], s["due_status"])]
            g[0] += 1; g[1] += abs(s["pending"])
    return out


def baseline_compare(agg: dict, baseline: dict) -> list[dict]:
    """Informational only: how this run sits against figures observed in earlier probe runs. Not a gate, not hard-coded production totals."""
    out = []
    for t in agg["ledger_totals"]:
        b = baseline.get((t["ledger_name"], t["drcr"]))
        if not b:
            continue
        out.append({"ledger": t["ledger_name"], "drcr": t["drcr"], "rows_now": t["rows"], "rows_baseline": b["rows"], "abs_now": t["abs"], "abs_baseline": str(b["abs"]),
                    "abs_difference": str(Decimal(t["abs"]) - Decimal(str(b["abs"])))})
    return out


def load_baseline(inbox: Path) -> dict | None:
    """Ledger x Dr/Cr rows and absolute pending from run_20261004_004 (an earlier, separate probe), if it is on disk."""
    p = inbox / "run_20261004_004" / "r1_creditor_due_by_ledger.parquet"
    if not p.exists():
        return None
    import pyarrow.parquet as pq

    out = defaultdict(lambda: {"rows": 0, "abs": ZERO})
    for r in pq.read_table(p).to_pylist():
        r = {k.lower(): v for k, v in r.items()}
        o = out[(r["ledger_name"], r["drcr"])]
        o["rows"] += as_int(r["open_rows"])
        o["abs"] += Decimal(str(r["abs_pending"])).quantize(Decimal("0.01"))
    return dict(out)


# ───────────── outputs ─────────────


def finish(run_dir: Path, report: dict, staged, e2) -> dict:
    out = run_dir / "staging"
    out.mkdir(exist_ok=True)
    if report["verdict"] == "PASSED" and staged is not None:
        write_derived(out, staged, e2 or [], report)
    (out / "validation_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    (out / "VALIDATION_REPORT.md").write_text(render_md(report), encoding="utf-8")
    return report


def write_derived(out: Path, staged: list[dict], e2: list[dict], report: dict) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    dec = pa.decimal128(24, 4)
    types = {"as_of_date": pa.date32(), "document_date": pa.date32(), "due_date": pa.date32(), "ref_date": pa.date32(), "entry_date": pa.date32(),
             "credit_days": pa.int32(), "amount": dec, "adjusted": dec, "pending": dec, "document_age_days": pa.int32(), "overdue_days": pa.int32()}
    cols = list(staged[0].keys())
    arrays = []
    for c in cols:
        vals = [r[c] for r in staged]
        if c in ("amount", "adjusted", "pending"):
            for x in vals:
                if x is not None and x != x.quantize(Decimal("0.0001")):
                    raise StageError(f"{c} has more than 4 decimal places; widen the schema deliberately")
        arrays.append(pa.array(vals, type=types.get(c, pa.string())))
    pq.write_table(pa.table(arrays, names=cols), out / "creditor_open_items.parquet")
    pa_keys = [source_row_key(r["document_code"], r["sub_ledger_code"]) for r in e2]
    ident = pa.table({
        "source_row_key": pa_keys, "ledger_code": [r["ledger_code"] for r in e2], "drcr": [r["drcr"] for r in e2],
        "pending": pa.array([parse_decimal(r["pending"]) for r in e2], type=dec), "entry_date_raw": [r["entry_date"] for r in e2],
        "as_of_date": [r["as_of_date"] for r in e2],
    })
    pq.write_table(ident, out / "creditor_identity_snapshot.parquet")
    report["outputs"] = {"creditor_open_items": mf.sha256_file(out / "creditor_open_items.parquet"), "creditor_identity_snapshot": mf.sha256_file(out / "creditor_identity_snapshot.parquet")}


def _cr(v) -> str:
    return f"{Decimal(v) / Decimal(10_000_000):,.2f}"


def render_md(r: dict) -> str:
    L = [f"# Creditors pilot staging validation: {r['run']}", "", f"**Verdict: {r['verdict']}**  as_of_date: {r.get('as_of_date', 'n/a')}", ""]
    if r["hard_failures"]:
        L += ["## Hard failures", *[f"- {x}" for x in r["hard_failures"]], ""]
    c = r["controls"]
    if c:
        L += [f"## Controls: {len(c)} checked, {sum(1 for x in c if x['verdict'] == 'PASS')} pass, {sum(1 for x in c if x['verdict'] == 'FAIL')} fail", ""]
    a = r.get("aggregates")
    if a:
        L += ["## Totals (₹ Cr unless stated)", f"- rows {a['rows']:,} (credit {a['credit_rows']:,}, debit {a['debit_rows']:,}); distinct vendors {a['distinct_vendors']:,}; distinct keys {a['distinct_keys']:,}",
              f"- Credit outstanding {_cr(a['credit_outstanding'])}; Creditor debit balances {_cr(a['creditor_debit_balances'])}; Signed net {_cr(a['signed_net'])}",
              f"- identity extract: {a['e2_rows']:,} rows ({a['e2_open_rows']:,} open, {a['e2_settled_rows']:,} settled)", "",
              "## Ledger totals", "| Ledger | Dr/Cr | Rows | Vendors | ₹ Cr abs | ₹ Cr signed |", "|---|---|---|---|---|---|"]
        L += [f"| {t['ledger_name']} | {t['drcr']} | {t['rows']:,} | {t['vendors']:,} | {_cr(t['abs'])} | {_cr(t['signed'])} |" for t in a["ledger_totals"]]
        L += ["", "## Document Age", "| Bucket | Dr/Cr | Rows | ₹ Cr abs |", "|---|---|---|---|"] + [f"| {t['bucket']} | {t['drcr']} | {t['rows']:,} | {_cr(t['abs'])} |" for t in a["document_age"]]
        L += ["", "## Unclassified Document Age", "| Date quality | Dr/Cr | Rows | ₹ Cr abs |", "|---|---|---|---|"] + [f"| {t['date_quality_status']} | {t['drcr']} | {t['rows']:,} | {_cr(t['abs'])} |" for t in a["unclassified_document_age"]]
        L += ["", "## Due Status", "| Status | Dr/Cr | Rows | ₹ Cr abs |", "|---|---|---|---|"] + [f"| {t['status']} | {t['drcr']} | {t['rows']:,} | {_cr(t['abs'])} |" for t in a["due_status"]]
        L += ["", "## Party class", "| Class | Dr/Cr | Rows | ₹ Cr abs |", "|---|---|---|---|"] + [f"| {t['party_class']} | {t['drcr']} | {t['rows']:,} | {_cr(t['abs'])} |" for t in a["party_class"]]
    return "\n".join(L) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    run_dir = Path(argv[1])
    rep = validate(run_dir, load_baseline(run_dir.parent))
    print(f"{rep['run']}: {rep['verdict']}  controls {len(rep['controls'])}, failures {len(rep['hard_failures'])}")
    for f in rep["hard_failures"][:30]:
        print("  FAIL", f)
    return 0 if rep["verdict"] == "PASSED" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
