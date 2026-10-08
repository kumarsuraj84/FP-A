"""
Offline staging validation for the Cash pilot (package cash_pilot_01, contract cash-wc-1.0).

    python tools/extraction_broker/cash_stage.py data/inbox/run_YYYYMMDD_NNN

Reads ONLY the Parquet files and manifest of one broker run. It never talks to Oracle, never loads Postgres, never touches the frontend. It:

  1. validates the manifest and requires every dataset to be `ok` (a capped, failed or skipped dataset fails the run);
  2. rejects the run if the PRE source controls differ from the POST source controls (a source refreshed mid-extract);
  3. parses every amount as an exact decimal (no float) and every date strictly;
  4. checks the till rows (one row per store, a single till date) and the bank rows (the same ledgers in every register);
  5. reconciles source control -> extract with a 0.00 tolerance (stores, till totals, bank totals and row counts);
  6. applies the two business ties as HARD failures: the two current registers agree on every posted figure, and each ledger's FY25-26
     closing equals its FY26-27 opening. A run that fails a tie is not loadable;
  7. writes cash_store_till.parquet, cash_bank_ledger.parquet, validation_report.json and VALIDATION_REPORT.md (aggregates and ledger names only).

A bank figure here is a LEDGER BOOK figure: PROVISIONAL, NOT BANK-RECONCILED. Nothing is netted into a "cash position".
The current date is never read.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import manifest as mf  # noqa: E402

ZERO = Decimal(0)
_NUM = re.compile(r"^-?([0-9]+(\.[0-9]+)?|\.[0-9]+)$")
_DATE = re.compile(r"^([0-9]{4})-([0-9]{2})-([0-9]{2})$")
EXPECTED_DATASETS = {
    "c1_till_control_pre": "control_pre", "c2_bank_control_pre": "control_pre",
    "e1_store_till": "extract", "e2_bank_site_register": "extract", "e3_bank_gl_register": "extract", "e4_bank_prior_year_closing": "extract",
    "c1_till_control_post": "control_post", "c2_bank_control_post": "control_post",
}
SOURCES = {"e2_bank_site_register": "site_register", "e3_bank_gl_register": "gl_register", "e4_bank_prior_year_closing": "prior_year_closing"}
TILL_COLUMNS = ["site_code", "store_name", "till_date", "cumulative_balance", "mtd_debit", "mtd_credit", "fytd_debit", "fytd_credit", "last_activity_date"]
MONEY = ["open_dr", "open_cr", "posted_dr", "posted_cr", "unposted_dr", "unposted_cr", "future_posted_dr", "future_posted_cr", "future_unposted_dr", "future_unposted_cr",
         "contra_posted_dr", "contra_posted_cr"]
COUNTS = ["open_rows", "posted_rows", "unposted_rows", "future_rows"]


class StageError(RuntimeError):
    pass


def parse_decimal(text, field: str = "value") -> Decimal | None:
    if text is None:
        return None
    t = str(text).strip()
    if not _NUM.match(t):
        raise StageError(f"{field}: '{t[:20]}' is not a plain decimal number")
    try:
        return Decimal(t)
    except InvalidOperation as e:  # pragma: no cover
        raise StageError(f"{field}: not a decimal") from e


def parse_date(text) -> date | None:
    if text is None or str(text).strip() == "":
        return None
    m = _DATE.match(str(text).strip())
    if not m:
        raise StageError(f"'{str(text)[:12]}' is not a YYYY-MM-DD date")
    try:
        return date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError as e:
        raise StageError(f"'{text}' is not a valid date") from e


def load(run_dir: Path, name: str) -> list[dict]:
    import pyarrow.parquet as pq

    return [{k.lower(): v for k, v in r.items()} for r in pq.read_table(run_dir / f"{name}.parquet").to_pylist()]


def money(r: dict, k: str) -> Decimal:
    v = parse_decimal(r.get(k), k)
    return ZERO if v is None else v


def count(r: dict, k: str) -> int:
    v = r.get(k)
    return 0 if v is None else int(Decimal(str(v)))


class Recon:
    def __init__(self):
        self.rows: list[dict] = []

    def add(self, cid: str, dim: str, a_layer: str, a, b_layer: str, b):
        a, b = Decimal(a), Decimal(b)
        self.rows.append({"control": cid, "dimension": dim, "left_layer": a_layer, "left": str(a), "right_layer": b_layer, "right": str(b), "variance": str(b - a), "verdict": "PASS" if a == b else "FAIL"})

    @property
    def failed(self):
        return [r for r in self.rows if r["verdict"] == "FAIL"]


def _norm(rows: list[dict]) -> list[str]:
    return sorted(json.dumps({k: (None if v is None else str(v)) for k, v in sorted(r.items())}, sort_keys=True) for r in rows)


def bank_row(r: dict, source: str) -> dict:
    out = {"source": source, "ledger_code": str(r["glcode"]), "ledger_name": r["glname"], "gl_type": r.get("gl_type"), "nature": r.get("nature"), "extinct": r.get("extinct")}
    for k in MONEY:
        out[k] = money(r, k)
    for k in COUNTS:
        out[k] = count(r, k)
    out["future_net"] = out["future_posted_dr"] - out["future_posted_cr"] + out["future_unposted_dr"] - out["future_unposted_cr"]
    out["has_movement"] = (out["open_rows"] + out["posted_rows"] + out["unposted_rows"] + out["future_rows"]) > 0
    out["last_posted_date"] = parse_date(r.get("last_posted_date"))
    out["last_entry_date"] = parse_date(r.get("last_entry_date"))
    out["register_report_date"] = parse_date(r.get("report_date"))
    out["sites"] = None if r.get("sites") is None else int(Decimal(str(r["sites"])))
    return out


def validate(run_dir: Path) -> dict:
    report: dict = {"run": run_dir.name, "verdict": "FAILED", "hard_failures": [], "controls": [], "ties": [], "aggregates": {}}
    fail = report["hard_failures"].append

    v = mf.validate_manifest(run_dir)
    if not v.ok:
        for e in v.errors:
            fail(f"manifest: {e}")
    m = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    if m.get("package") not in ("cash_pilot_01", "cash_live_01") or m.get("manifest_version") != 2:
        fail("manifest: not a cash_pilot_01 / cash_live_01 / manifest_version 2 run")
    contract = m.get("contract") or {}
    if not contract:
        fail("manifest: contract block missing")
    by = {d["dataset"]: d for d in m["datasets"]}
    for name, role in EXPECTED_DATASETS.items():
        d = by.get(name)
        if d is None:
            fail(f"dataset {name} is missing")
        elif d["status"] != "ok":
            fail(f"dataset {name} has status '{d['status']}'")
        elif d.get("role") != role:
            fail(f"dataset {name} has role '{d.get('role')}', expected '{role}'")
    if report["hard_failures"]:
        return finish(run_dir, report, None, None)
    report["manifest_sha256"] = mf.sha256_file(run_dir / "manifest.json")
    report["contract"] = contract

    try:
        for kind in ("c1_till_control", "c2_bank_control"):
            if _norm(load(run_dir, f"{kind}_pre")) != _norm(load(run_dir, f"{kind}_post")):
                fail(f"REFRESH RACE: {kind} differs between PRE and POST")
        c1, c2 = load(run_dir, "c1_till_control_pre"), load(run_dir, "c2_bank_control_pre")
        if len(c1) != 1 or len(c2) != 1:
            fail("each source control must have exactly one row")
            return finish(run_dir, report, None, None)
        c1, c2 = c1[0], c2[0]

        # ── till ──
        e1 = load(run_dir, "e1_store_till")
        if not e1:
            fail("e1_store_till is empty")
            return finish(run_dir, report, None, None)
        till_date = parse_date(c1["till_date"])
        as_of = parse_date(c2["report_date"])
        if till_date is None or as_of is None or till_date > as_of:
            fail(f"till date {till_date} must exist and not be after the register report date {as_of}")
            return finish(run_dir, report, None, None)
        stores, seen = [], set()
        for r in e1:
            if sorted(r) != sorted(TILL_COLUMNS):
                fail("e1_store_till columns differ from the contract")
                return finish(run_dir, report, None, None)
            if r["site_code"] in seen or not r["site_code"]:
                fail(f"store code {r['site_code']!r} is empty or duplicated: no deduplication is done")
            seen.add(r["site_code"])
            if parse_date(r["till_date"]) != till_date:
                fail(f"store {r['site_code']}: till date differs from the source control")
            bal = parse_decimal(r["cumulative_balance"], "cumulative_balance")
            stores.append({"site_code": r["site_code"], "store_name": r["store_name"], "cumulative_balance": ZERO if bal is None else bal,
                           "mtd_debit": money(r, "mtd_debit"), "mtd_credit": money(r, "mtd_credit"), "fytd_debit": money(r, "fytd_debit"), "fytd_credit": money(r, "fytd_credit"),
                           "last_activity_date": parse_date(r["last_activity_date"])})

        # ── bank ──
        banks: dict[str, list[dict]] = {}
        for ds, src in SOURCES.items():
            rows = load(run_dir, ds)
            if not rows:
                fail(f"{ds} is empty")
                continue
            banks[src] = [bank_row(r, src) for r in rows]
            codes = [b["ledger_code"] for b in banks[src]]
            if len(set(codes)) != len(codes):
                fail(f"{ds}: a ledger appears twice")
        if report["hard_failures"]:
            return finish(run_dir, report, None, None)
        sets = {s: {b["ledger_code"] for b in rows} for s, rows in banks.items()}
        if len({frozenset(x) for x in sets.values()}) != 1:
            fail("the three registers do not list the same ledgers")
            return finish(run_dir, report, None, None)
        site = {b["ledger_code"]: b for b in banks["site_register"]}
        gl = {b["ledger_code"]: b for b in banks["gl_register"]}
        prior = {b["ledger_code"]: b for b in banks["prior_year_closing"]}
        if any(b["register_report_date"] != as_of for b in banks["site_register"] if b["has_movement"]):
            fail("a site-register row carries a report date different from the source control")
    except StageError as e:
        fail(str(e))
        return finish(run_dir, report, None, None)

    # ── source control -> extract (exact) ──
    rc = Recon()
    rc.add("T1", "stores", "source", Decimal(count(c1, "stores_with_a_row")), "extract", Decimal(len(stores)))
    for key, col in (("T2", "sum_cumulative"), ("T3", "mtd_debit"), ("T4", "mtd_credit"), ("T5", "fytd_debit"), ("T6", "fytd_credit")):
        src_col = {"sum_cumulative": "cumulative_balance"}.get(col, col)
        rc.add(key, col, "source", parse_decimal(c1[col], col) or ZERO, "extract", sum((s[src_col] for s in stores), ZERO))
    rc.add("B1", "ledgers_with_entries", "source", Decimal(count(c2, "ledgers_with_entries")), "extract", Decimal(sum(1 for b in banks["site_register"] if b["has_movement"])))
    for i, k in enumerate(MONEY[:6]):
        rc.add(f"B{i + 2}", k, "source", parse_decimal(c2[k], k) or ZERO, "extract", sum((b[k] for b in banks["site_register"]), ZERO))
    for i, k in enumerate(COUNTS):
        rc.add(f"B{i + 8}", k, "source", Decimal(count(c2, k)), "extract", Decimal(sum(b[k] for b in banks["site_register"])))
    report["controls"] = rc.rows
    for r in rc.failed:
        fail(f"control {r['control']} ({r['dimension']}): source {r['left']} vs extract {r['right']}")

    # ── business ties (hard) ──
    ties = []
    for code, s in site.items():
        g, p = gl[code], prior[code]
        for k in ("posted_dr", "posted_cr", "open_dr", "open_cr", "contra_posted_dr", "contra_posted_cr", "future_net"):
            if s[k] != g[k]:
                ties.append({"tie": "site_vs_gl_register", "ledger": s["ledger_name"], "field": k, "site": str(s[k]), "gl": str(g[k])})
        prior_close = p["open_dr"] - p["open_cr"] + p["posted_dr"] - p["posted_cr"] + p["unposted_dr"] - p["unposted_cr"]
        if prior_close != s["open_dr"] - s["open_cr"]:
            ties.append({"tie": "prior_year_closing_vs_opening", "ledger": s["ledger_name"], "prior_closing": str(prior_close), "opening": str(s["open_dr"] - s["open_cr"])})
    report["ties"] = {"checked_ledgers": len(site), "violations": ties}
    for t in ties[:20]:
        fail(f"tie {t['tie']} broken for {t['ledger']}")

    # ── aggregates (the loader compares the mart to these) ──
    def tot(rows, k):
        return str(sum((r[k] for r in rows), ZERO))

    report["aggregates"] = {
        "as_of_date": as_of.isoformat(), "till_balance_date": till_date.isoformat(), "stores": len(stores),
        "till": {k: tot(stores, k) for k in ("cumulative_balance", "mtd_debit", "mtd_credit", "fytd_debit", "fytd_credit")},
        "bank_rows": sum(len(r) for r in banks.values()),
        "bank": {src: {**{k: tot(rows, k) for k in MONEY + ["future_net"]}, **{k: sum(r[k] for r in rows) for k in COUNTS}, "ledgers": len(rows), "with_movement": sum(1 for r in rows if r["has_movement"])} for src, rows in banks.items()},
        "site_register_position": {
            "opening": str(sum((b["open_dr"] - b["open_cr"] for b in banks["site_register"]), ZERO)),
            "posted_closing": str(sum((b["open_dr"] - b["open_cr"] + b["posted_dr"] - b["posted_cr"] for b in banks["site_register"]), ZERO)),
            "including_unposted": str(sum((b["open_dr"] - b["open_cr"] + b["posted_dr"] - b["posted_cr"] + b["unposted_dr"] - b["unposted_cr"] for b in banks["site_register"]), ZERO)),
        },
    }
    report["verdict"] = "PASSED" if not report["hard_failures"] else "FAILED"
    return finish(run_dir, report, stores, banks)


def finish(run_dir: Path, report: dict, stores, banks) -> dict:
    out = run_dir / "staging"
    out.mkdir(exist_ok=True)
    if report["verdict"] == "PASSED" and stores is not None:
        write_derived(out, stores, banks, report)
    (out / "validation_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    (out / "VALIDATION_REPORT.md").write_text(render_md(report), encoding="utf-8")
    return report


def write_derived(out: Path, stores: list[dict], banks: dict[str, list[dict]], report: dict) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    dec = pa.decimal128(24, 4)

    def table(rows: list[dict], decimals: set[str], dates: set[str], ints: set[str]):
        cols = list(rows[0].keys())
        arrs = []
        for c in cols:
            vals = [r[c] for r in rows]
            if c in decimals:
                for x in vals:
                    if x is not None and x != x.quantize(Decimal("0.0001")):
                        raise StageError(f"{c} has more than 4 decimal places; widen the schema deliberately")
                arrs.append(pa.array(vals, type=dec))
            elif c in dates:
                arrs.append(pa.array(vals, type=pa.date32()))
            elif c in ints:
                arrs.append(pa.array(vals, type=pa.int32()))
            elif c == "has_movement":
                arrs.append(pa.array(vals, type=pa.bool_()))
            else:
                arrs.append(pa.array(vals, type=pa.string()))
        return pa.table(arrs, names=cols)

    pq.write_table(table(stores, {"cumulative_balance", "mtd_debit", "mtd_credit", "fytd_debit", "fytd_credit"}, {"last_activity_date"}, set()), out / "cash_store_till.parquet")
    flat = [r for rows in banks.values() for r in rows]
    pq.write_table(table(flat, set(MONEY) | {"future_net"}, {"last_posted_date", "last_entry_date", "register_report_date"}, set(COUNTS) | {"sites"}), out / "cash_bank_ledger.parquet")
    report["outputs"] = {"cash_store_till": mf.sha256_file(out / "cash_store_till.parquet"), "cash_bank_ledger": mf.sha256_file(out / "cash_bank_ledger.parquet")}


def _cr(v) -> str:
    return f"{Decimal(v) / Decimal(10_000_000):,.2f}"


def render_md(r: dict) -> str:
    L = [f"# Cash pilot staging validation: {r['run']}", "", f"**Verdict: {r['verdict']}**", ""]
    if r["hard_failures"]:
        L += ["## Hard failures", *[f"- {x}" for x in r["hard_failures"]], ""]
    c = r["controls"]
    if c:
        L += [f"## Source to extract controls: {len(c)} checked, {sum(1 for x in c if x['verdict'] == 'PASS')} pass", ""]
    t = r.get("ties")
    if t:
        L += [f"## Business ties: {t['checked_ledgers']} ledgers checked, {len(t['violations'])} violations", ""]
    a = r.get("aggregates")
    if a:
        L += [f"## Totals (₹ Cr)", f"- as of {a['as_of_date']}; till balance date {a['till_balance_date']}; stores {a['stores']}",
              f"- Store till cash {_cr(a['till']['cumulative_balance'])}; month-to-date Dr {_cr(a['till']['mtd_debit'])} Cr {_cr(a['till']['mtd_credit'])}",
              f"- Bank ledgers (BOOK, provisional, not bank-reconciled), site register: opening {_cr(a['site_register_position']['opening'])}, posted closing {_cr(a['site_register_position']['posted_closing'])}, "
              f"including unposted {_cr(a['site_register_position']['including_unposted'])}"]
    return "\n".join(L) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    rep = validate(Path(argv[1]))
    print(f"{rep['run']}: {rep['verdict']}  controls {len(rep['controls'])}, failures {len(rep['hard_failures'])}")
    for f in rep["hard_failures"][:30]:
        print("  FAIL", f)
    return 0 if rep["verdict"] == "PASSED" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
