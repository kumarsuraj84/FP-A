"""
Offline staging validation for the store P&L ACTUALS (packages pl_actuals_01 + cogs_scan_01).

    python tools/extraction_broker/pl_stage.py <pl_actuals_01 run folder> <cogs_scan_01 run folder>

Reads ONLY the Parquet files and manifests of the two broker runs: never Oracle, never Postgres, never the frontend. It:

  1. validates both manifests (every dataset `ok`) and requires the PRE and POST register controls to be identical (refresh race) and the register's report date to equal the
     contract's as-of date;
  2. E1: the monthly site / ledger chunks must add up EXACTLY to the different-shape control (lines, debit, credit per month and posting status);
  3. every ledger in the chunks exists in the GL master and is an Income or Expense ledger; each is mapped to a finance group by its exact name (the finance P&L's own mapping)
     and each group to a P&L section by the fixed table below. A ledger the finance mapping does not know is kept as section UNMAPPED with its amounts: never dropped, never guessed;
  4. the COGS table's site x month figures are staged as they are; sales per site and month in the books (GL "Sales - POS") are compared with the COGS table's sales ex-GST
     (SL_V less TAXAMT) and the differences are STORED for the reconciliation view, not hidden or forced;
  5. writes derived Parquet, validation_report.json and VALIDATION_REPORT.md. Reports and errors contain counts, control ids and dataset names only.

COGS is read from one pass over the table (no pre / post control: an 80 s full scan is not repeated); the sales tie-out is its cross-check.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import manifest as mf  # noqa: E402

ZERO = Decimal(0)
SALES_LEDGER = "Sales - POS"
TIE_TOLERANCE = Decimal("1000")          # rupees: a site-month whose books and COGS-table sales agree within this is "tied"

#: the finance P&L's own group labels -> the section of the P&L they belong to (a fixed, reviewable table: a label that is not here fails the run)
SECTION_OF_GROUP = {
    "01-Net Sales": "REVENUE",
    "02-Other Income": "OTHER_INCOME", "24-Interest Income": "OTHER_INCOME",
    "02-COGS(Product)": "COGS_BOOKS", "02-COGS(Others)": "COGS_BOOKS", "02-COGS(Correction)": "COGS_BOOKS",
    "01-Rent": "STORE_OPEX", "02-Employee Cost": "STORE_OPEX", "03-Power and Fuel Expenses": "STORE_OPEX", "05-Director remunaration": "STORE_OPEX",
    "07-Advertisement And Sales Promotion": "STORE_OPEX", "08-Freight Outward": "STORE_OPEX", "09-Insurance": "STORE_OPEX", "10-Travelling & Conveyance Expenses": "STORE_OPEX",
    "11-Communication": "STORE_OPEX", "12-Repairs and Maintenance-Others": "STORE_OPEX", "13-Packing Materials And Expenses": "STORE_OPEX",
    "14-Legal and Professional Expenses": "STORE_OPEX", "16-Miscellaneous Expenses": "STORE_OPEX", "17-Bank Charges": "STORE_OPEX", "20-Printing & Stationery": "STORE_OPEX",
    "21-Finance Cost": "FINANCE_COST",
}
SECTIONS = ["REVENUE", "COGS_BOOKS", "STORE_OPEX", "OTHER_INCOME", "FINANCE_COST", "UNMAPPED"]
PL_EXPECTED_ROLES = {"c0_register_pre": "control_pre", "c1_totals_old_pre": "control_pre", "c1_totals_cur_pre": "control_pre", "m1_gl_master": "extract", "m2_ledger_to_group": "extract",
                     "m3_group_to_major": "extract", "m4_site_master": "extract", "c0_register_post": "control_post", "c1_totals_cur_post": "control_post"}


class StageError(RuntimeError):
    """The message never carries a data value."""


class Recon:
    def __init__(self):
        self.rows: list[dict] = []

    def add(self, cid: str, dim: str, a, b):
        a, b = Decimal(a), Decimal(b)
        self.rows.append({"control": cid, "dimension": dim, "left_layer": "source", "left": str(a), "right_layer": "extract", "right": str(b), "variance": str(b - a), "verdict": "PASS" if a == b else "FAIL"})

    @property
    def failed(self):
        return [r for r in self.rows if r["verdict"] == "FAIL"]


def load(run_dir: Path, name: str) -> list[dict]:
    import pyarrow.parquet as pq

    return [{k.lower(): v for k, v in r.items()} for r in pq.read_table(run_dir / f"{name}.parquet").to_pylist()]


def dec(v, field: str, where: str) -> Decimal:
    if v is None or str(v).strip() == "":
        return ZERO
    try:
        return Decimal(str(v).strip())
    except Exception as e:  # noqa: BLE001
        raise StageError(f"{where}: field '{field}' is not a decimal number") from e


def _norm(rows: list[dict]) -> list[str]:
    return sorted(json.dumps({k: (None if v is None else str(v)) for k, v in sorted(r.items())}, sort_keys=True) for r in rows)


def _month_of(name: str) -> date:
    y, m = name[2:].split("_")
    return date(int(y), int(m), 1)


def _manifest(run_dir: Path, package: str, fail) -> dict | None:
    v = mf.validate_manifest(run_dir)
    for e in (v.errors if not v.ok else []):
        fail(f"manifest ({run_dir.name}): {e}")
    m = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    if m.get("package") != package:
        fail(f"manifest ({run_dir.name}): not a {package} run")
        return None
    for d in m["datasets"]:
        if d["status"] != "ok":
            fail(f"dataset {d['dataset']} of {run_dir.name} has status '{d['status']}'")
    return m


def validate(pl_dir: Path, cogs_dir: Path, write: bool = True) -> dict:
    report: dict = {"run": pl_dir.name, "cogs_run": cogs_dir.name, "verdict": "FAILED", "hard_failures": [], "controls": [], "aggregates": {}}
    fail = report["hard_failures"].append
    m = _manifest(pl_dir, "pl_actuals_01", fail)
    mc = _manifest(cogs_dir, "cogs_scan_01", fail)
    if m is None or mc is None or report["hard_failures"]:
        return _finish(pl_dir, report, None, write)
    contract = m.get("contract") or {}
    as_of = date.fromisoformat(contract["as_of_cutoff"])
    by = {d["dataset"]: d for d in m["datasets"]}
    for name, role in PL_EXPECTED_ROLES.items():
        if name not in by or by[name].get("role") != role:
            fail(f"dataset {name} is missing or has the wrong role")
    months = [k for k in by if k.startswith("g_")]
    if not months:
        fail("no monthly chunks")
    if report["hard_failures"]:
        return _finish(pl_dir, report, None, write)
    report["manifest_sha256"] = mf.sha256_file(pl_dir / "manifest.json")
    report["cogs_manifest_sha256"] = mf.sha256_file(cogs_dir / "manifest.json")
    report["contract"] = contract
    try:
        for kind in ("c0_register", "c1_totals_cur"):
            if _norm(load(pl_dir, f"{kind}_pre")) != _norm(load(pl_dir, f"{kind}_post")):
                fail(f"REFRESH RACE: {kind} differs between PRE and POST")
        c0 = load(pl_dir, "c0_register_pre")
        if len(c0) != 1 or c0[0]["register_report_date"] != as_of.isoformat() or not int(Decimal(str(c0[0]["register_rows"]))):
            fail("the register is empty, undated, or its report date is not the as-of date")
        if report["hard_failures"]:
            return _finish(pl_dir, report, None, write)

        gl = {}
        for r in load(pl_dir, "m1_gl_master"):
            gl[str(int(Decimal(str(r["glcode"]))))] = r
        l2g = {r["ledger"]: r["sk_grp"] for r in load(pl_dir, "m2_ledger_to_group")}
        seen_keys: set[tuple] = set()
        rows: list[dict] = []
        sums: dict[tuple, list] = defaultdict(lambda: [0, ZERO, ZERO])
        unknown = bad_type = unmapped_group = 0
        for name in sorted(months):
            mon = _month_of(name)
            for i, r in enumerate(load(pl_dir, name)):
                where = f"{name} row {i + 1}"
                g = gl.get(str(r["glcode"]))
                if g is None:
                    unknown += 1
                    continue
                if g["type"] not in ("Income", "Expense"):
                    bad_type += 1
                debit, credit = dec(r["debit"], "debit", where), dec(r["credit"], "credit", where)
                if debit < 0 or credit < 0:
                    raise StageError(f"{where}: a debit or credit is negative")
                key = (str(r["site_code"]), str(r["glcode"]), r["entry_type_short"], r["release_status"], mon)
                if key in seen_keys:
                    raise StageError(f"{name}: a site / ledger / entry type / status appears twice in one month chunk")
                seen_keys.add(key)
                lines = int(Decimal(str(r["lines_n"])))
                s = sums[(mon.strftime("%Y-%m"), r["release_status"])]
                s[0] += lines
                s[1] += debit
                s[2] += credit
                rows.append({"site_code": str(r["site_code"]), "month": mon, "glcode": str(r["glcode"]), "ledger_name": g["glname"], "entry_type_short": r["entry_type_short"],
                             "release_status": r["release_status"], "debit": debit, "credit": credit, "lines": lines})
        if unknown:
            fail(f"{unknown} chunk rows name a ledger that is not in the GL master")
        if bad_type:
            fail(f"{bad_type} chunk rows are on a ledger that is neither Income nor Expense")

        # E1: chunks == the different-shape control, exactly
        rc = Recon()
        ctl: dict[tuple, list] = {}
        for ds in ("c1_totals_old_pre", "c1_totals_cur_pre"):
            for r in load(pl_dir, ds):
                ctl[(r["month"], r["release_status"])] = [int(Decimal(str(r["lines_n"]))), dec(r["debit"], "debit", ds), dec(r["credit"], "credit", ds)]
        for key in sorted(set(ctl) | set(sums)):
            a = ctl.get(key, [0, ZERO, ZERO])
            b = sums.get(key, [0, ZERO, ZERO])
            tag = f"{key[0]}/{key[1]}"
            rc.add("E1_month_status", f"lines {tag}", a[0], b[0])
            rc.add("E1_month_status", f"debit {tag}", a[1], b[1])
            rc.add("E1_month_status", f"credit {tag}", a[2], b[2])

        # mapping and sections
        staged: list[dict] = []
        unmapped_ledgers: set[str] = set()
        for r in rows:
            grp = l2g.get(r["ledger_name"])
            if grp is None:
                sec, grp_label = "UNMAPPED", None
                unmapped_ledgers.add(r["glcode"])
            else:
                sec = SECTION_OF_GROUP.get(grp)
                grp_label = grp
                if sec is None:
                    unmapped_group += 1
                    continue
            staged.append({**r, "group_label": grp_label, "section": sec})
        if unmapped_group:
            fail(f"{unmapped_group} chunk rows are in a finance group that has no P&L section in the section table")
        for r in rc.failed:
            fail(f"control {r['control']} ({r['dimension']}): source {r['left']} vs extract {r['right']}")
        report["controls"] = rc.rows

        # COGS table (one pass) and the sales tie-out
        gcols = load(cogs_dir, "g1_site_month")
        cogs: list[dict] = []
        seen_c: set[tuple] = set()
        for i, r in enumerate(gcols):
            where = f"g1_site_month row {i + 1}"
            k = (str(r["site_code"]), r["month"])
            if k in seen_c:
                raise StageError("g1_site_month: a site / month appears twice")
            seen_c.add(k)
            cogs.append({"site_code": k[0], "month": date(int(k[1][:4]), int(k[1][5:7]), 1), "sl_v": dec(r["sl_v"], "sl_v", where), "tax_amt": dec(r["tax_amt"], "tax_amt", where),
                         "cogs_v": dec(r["cogs_v"], "cogs_v", where), "sl_q": dec(r["sl_q"], "sl_q", where), "rows_n": int(Decimal(str(r["rows_n"]))), "bill_days": int(Decimal(str(r["bill_days"]))),
                         "first_bill": r["first_bill"], "last_bill": r["last_bill"]})
        if not cogs:
            fail("the COGS scan is empty")
        books_sales: dict[tuple, Decimal] = defaultdict(Decimal)
        for r in staged:
            if r["ledger_name"] == SALES_LEDGER:
                books_sales[(r["site_code"], r["month"])] += r["credit"] - r["debit"]
        table_sales = {(c["site_code"], c["month"]): c["sl_v"] - c["tax_amt"] for c in cogs}
        tie = []
        for k in sorted(set(books_sales) | set(table_sales)):
            b, t = books_sales.get(k, ZERO), table_sales.get(k, ZERO)
            tie.append({"site_code": k[0], "month": k[1], "books_sales": b, "cogs_table_sales_ex_gst": t, "difference": b - t, "tied": abs(b - t) <= TIE_TOLERANCE})
        cogs_last = max(c["last_bill"] for c in cogs)
        sites_only_in_table = sorted({c["site_code"] for c in cogs} - {k[0] for k in books_sales})
        sm = load(pl_dir, "m4_site_master")
        site_rows = []
        for r in sm:
            site_rows.append({"site_code": str(int(Decimal(str(r["site_code"])))), "store_name": r["store_name"], "opening_date": r["opening_date"], "store_status": r["store_status"],
                              "store_current_status": r["store_current_status"], "cluster_type": r["cluster_type"], "region_type": r["region_type"], "state": r["state"],
                              "store_type": r["store_type"], "last_bill_date": r["last_bill_date"]})
        groups = [{"group_label": g, "section": s} for g, s in sorted(SECTION_OF_GROUP.items())]
    except StageError as e:
        fail(str(e))
        return _finish(pl_dir, report, None, write)

    tied = sum(1 for t in tie if t["tied"])
    report["aggregates"] = {
        "as_of": as_of.isoformat(), "months": sorted({r["month"].strftime("%Y-%m") for r in staged}), "sites_in_books": len({r["site_code"] for r in staged}), "ledgers": len({r["glcode"] for r in staged}),
        "gl_rows": len(staged), "rows_by_section": dict(Counter(r["section"] for r in staged)), "unmapped_ledgers": len(unmapped_ledgers),
        "cogs_rows": len(cogs), "cogs_last_bill_date": cogs_last, "cogs_sites": len({c["site_code"] for c in cogs}), "cogs_sites_without_books_sales": len(sites_only_in_table),
        "tieout_site_months": len(tie), "tieout_tied": tied, "tieout_not_tied": len(tie) - tied, "tolerance_rupees": str(TIE_TOLERANCE), "site_master_rows": len(site_rows),
    }
    report["verdict"] = "PASSED" if not report["hard_failures"] else "FAILED"
    return _finish(pl_dir, report, {"gl_site_month": staged, "cogs_site_month": cogs, "sales_tieout": tie, "site_master": site_rows, "group_section": groups}, write)


def _finish(run_dir: Path, report: dict, data, write: bool) -> dict:
    if not write:
        report["derived"] = data
        return report
    out = run_dir / "staging"
    out.mkdir(exist_ok=True)
    if report["verdict"] == "PASSED" and data is not None:
        import pyarrow as pa
        import pyarrow.parquet as pq

        for name, recs in data.items():
            cols = list(recs[0].keys()) if recs else []
            pq.write_table(pa.table({c: [r[c] for r in recs] for c in cols}), out / f"{name}.parquet")
    (out / "validation_report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    a = report.get("aggregates", {})
    L = [f"# P&L actuals staging validation: {report['run']} (+ COGS run {report.get('cogs_run')})", "", f"**Verdict: {report['verdict']}**", ""]
    if report["hard_failures"]:
        L += ["## Hard failures"] + [f"- {f}" for f in report["hard_failures"]] + [""]
    if a:
        L += ["## Counts", f"- as of {a['as_of']}; months {a['months'][0]} to {a['months'][-1]}; {a['sites_in_books']} sites, {a['ledgers']} P&L ledgers, {a['gl_rows']:,} site-ledger-month-status rows",
              f"- rows by section {a['rows_by_section']}; {a['unmapped_ledgers']} ledgers have no finance group (kept as UNMAPPED, shown separately)",
              f"- COGS table: {a['cogs_rows']:,} site-month rows, {a['cogs_sites']} sites, newest bill date {a['cogs_last_bill_date']}",
              f"- sales tie-out (books vs COGS table ex-GST), tolerance Rs {a['tolerance_rupees']}: {a['tieout_tied']:,} of {a['tieout_site_months']:,} site-months tied; {a['tieout_not_tied']} not tied; {a['cogs_sites_without_books_sales']} COGS-table sites have no books sales", ""]
    n = len(report["controls"])
    L += [f"## Controls: {n} source-to-extract checks, {sum(1 for c in report['controls'] if c['verdict'] == 'PASS')} pass"]
    (out / "VALIDATION_REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    return report


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    if len(argv) != 2:
        print(__doc__)
        return 2
    rep = validate(Path(argv[0]), Path(argv[1]))
    print(f"{rep['run']}: {rep['verdict']}  controls {len(rep['controls'])}, failures {len(rep['hard_failures'])}")
    for f in rep["hard_failures"][:20]:
        print("  FAIL", f)
    a = rep.get("aggregates") or {}
    if a:
        print(f"  as of {a['as_of']}; {a['sites_in_books']} sites; {a['gl_rows']:,} rows; unmapped ledgers {a['unmapped_ledgers']}; sales tie-out {a['tieout_tied']:,}/{a['tieout_site_months']:,} tied")
    return 0 if rep["verdict"] == "PASSED" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
