"""
Offline staging validation for the entry layer (package entry_pilot_01, contract drill-1.0).

    python tools/extraction_broker/entry_stage.py data/inbox/run_YYYYMMDD_NNN

Reads ONLY the Parquet files and manifest of one broker run. It never talks to Oracle, never loads Postgres, never touches the frontend. It:

  1. validates the manifest (every dataset `ok`, roles right) and rejects the run if the PRE source controls differ from the POST ones (refresh race);
  2. requires ONE snapshot: the outstanding cube's report date equals the site register's report date;
  3. builds entries from lines: identity (site, entry type, entry number) -> entry_ref; all lines of an entry are kept; a line that appears in two selections must be
     IDENTICAL in both (a conflicting duplicate fails the run; nothing is deduplicated by guessing);
  4. E3 every entry balances; E1/E2 source controls (entries, lines, exact Dr/Cr, lines-per-entry histogram) equal the extract exactly;
  5. derives the creditor bill links: EXACT (one distinct entry AND the entry's net amount for that ledger and sub-ledger equals the bill amount), STRONG (one entry,
     amount differs), AMBIGUOUS (several: never resolved to one), NOT_LINKED (NO_MATCH, or REGISTER_COVERAGE_UNAVAILABLE for bills the register does not reach);
  6. writes derived Parquet, validation_report.json and VALIDATION_REPORT.md.

TELEMETRY RULE: narration, references, cheque fields, preparer / releaser names, sub-ledger codes and entry numbers are never printed, logged, put in an error message or written
to the report. Reports and errors contain counts, control ids and dataset names only.
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
import creditors_stage as cs  # noqa: E402
import manifest as mf  # noqa: E402

ZERO = Decimal(0)
_NUM = re.compile(r"^-?([0-9]+(\.[0-9]+)?|\.[0-9]+)$")
_DATE = re.compile(r"^([0-9]{4})-([0-9]{2})-([0-9]{2})$")
SEL_NAMES = ("creditors_cur", "creditors_old", "bank")   # one source-control query per selection (same names as packages.SEL_NAMES)
EXPECTED = {
    **{f"c1_totals_{n}_pre": "control_pre" for n in SEL_NAMES}, **{f"c2_histogram_{n}_pre": "control_pre" for n in SEL_NAMES}, "c3_bills_pre": "control_pre", "c4_register_pre": "control_pre",
    "h1_lines_creditors_cur": "extract", "h1b_lines_creditors_old": "extract", "h2_lines_bank": "extract",
    "l1a_links_current": "extract", "l1b_links_prior": "extract", "l1c_bills_before_coverage": "extract", "l2_till_day": "extract",
    **{f"c1_totals_{n}_post": "control_post" for n in SEL_NAMES}, "c3_bills_post": "control_post", "c4_register_post": "control_post",
}
LINE_DATASETS = {"h1_lines_creditors_cur": "creditors_cur", "h1b_lines_creditors_old": "creditors_old", "h2_lines_bank": "bank"}
LINE_COLUMNS = ["site_code", "entry_type_short", "entry_type_long", "entry_no", "entry_date", "seq", "glcode", "glname", "glnature", "slcode", "debit", "credit", "release_status", "created_by_site",
                "cubename", "narration", "reference_no", "reference_date", "cheque_no", "cheque_date", "counter_ledgers", "prepared_by", "prepared_on", "modified_by", "modified_on", "released_by", "released_on"]
TEXT_FIELDS = ["narration", "reference_no", "reference_date", "cheque_no", "cheque_date", "counter_ledgers", "prepared_by", "prepared_on", "modified_by", "modified_on", "released_by", "released_on"]
LINK_COLUMNS = ["document_code", "sub_ledger_code", "ledger_code", "bill_amount", "matched_entries", "site_code", "entry_type_short", "entry_no", "entry_net_dr_minus_cr"]
KEY_USED = "ledger + sub-ledger + document_no = entry_no"


class StageError(RuntimeError):
    """The message never carries a data value."""


def entry_ref(site: str, typ: str, no: str) -> str:
    return hashlib.sha256(f"v1|{site}|{typ}|{no}".encode("utf-8")).hexdigest()[:32]


def dec(v, field: str, where: str) -> Decimal | None:
    if v is None:
        return None
    t = str(v).strip()
    if not _NUM.match(t):
        raise StageError(f"{where}: field '{field}' is not a plain decimal number")
    try:
        return Decimal(t)
    except InvalidOperation as e:  # pragma: no cover
        raise StageError(f"{where}: field '{field}' is not a decimal") from e


def dt(v, field: str, where: str) -> date | None:
    if v is None or str(v).strip() == "":
        return None
    m = _DATE.match(str(v).strip())
    if not m:
        raise StageError(f"{where}: field '{field}' is not a YYYY-MM-DD date")
    try:
        return date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError as e:
        raise StageError(f"{where}: field '{field}' is not a valid date") from e


def load(run_dir: Path, name: str) -> list[dict]:
    import pyarrow.parquet as pq

    return [{k.lower(): v for k, v in r.items()} for r in pq.read_table(run_dir / f"{name}.parquet").to_pylist()]


def _norm(rows: list[dict]) -> list[str]:
    return sorted(json.dumps({k: (None if v is None else str(v)) for k, v in sorted(r.items())}, sort_keys=True) for r in rows)


def as_int(v) -> int:
    return int(Decimal(str(v)))


class Recon:
    def __init__(self):
        self.rows: list[dict] = []

    def add(self, cid: str, dim: str, a, b):
        a, b = Decimal(a), Decimal(b)
        self.rows.append({"control": cid, "dimension": dim, "left_layer": "source", "left": str(a), "right_layer": "extract", "right": str(b), "variance": str(b - a), "verdict": "PASS" if a == b else "FAIL"})

    @property
    def failed(self):
        return [r for r in self.rows if r["verdict"] == "FAIL"]


def build_lines(run_dir: Path, by: dict, fail) -> tuple[dict, dict]:
    """-> (lines keyed by (site, type, no, seq) with the set of selections that extracted them, per-selection list of entry keys)."""
    lines: dict[tuple, dict] = {}
    per_sel_entries: dict[str, dict[tuple, int]] = {}
    for ds, sel in LINE_DATASETS.items():
        seen = set()
        counts: dict[tuple, int] = Counter()
        for i, r in enumerate(load(run_dir, ds)):
            if sorted(r) != sorted(LINE_COLUMNS):
                raise StageError(f"{ds}: columns differ from the contract")
            where = f"{ds} row {i + 1}"
            for k in ("site_code", "entry_type_short", "entry_no", "seq", "glcode", "glname"):
                if r.get(k) in (None, ""):
                    raise StageError(f"{where}: required field '{k}' is empty")
            ident = (str(r["site_code"]), r["entry_type_short"], str(r["entry_no"]))
            key = ident + (str(r["seq"]),)
            if key in seen:
                raise StageError(f"{ds}: a line appears twice in the same dataset (no deduplication is done)")
            seen.add(key)
            debit, credit = dec(r["debit"], "debit", where) or ZERO, dec(r["credit"], "credit", where) or ZERO
            if debit < 0 or credit < 0:
                raise StageError(f"{where}: a debit or credit is negative")
            if r["release_status"] not in ("Posted", "Unposted"):
                raise StageError(f"{where}: release status is neither Posted nor Unposted")
            d = dt(r["entry_date"], "entry_date", where)
            if d is None:
                raise StageError(f"{where}: entry_date is missing")
            canon = {**{k: r[k] for k in LINE_COLUMNS}, "debit": debit, "credit": credit, "entry_date": d, "seq": str(r["seq"])}
            prev = lines.get(key)
            if prev is not None:
                if {k: v for k, v in prev.items() if k != "selections"} != canon:
                    raise StageError("a line extracted by two selections differs between them (conflicting duplicate)")
                prev["selections"].add(sel)
            else:
                lines[key] = {**canon, "selections": {sel}}
            counts[ident] += 1
        per_sel_entries[sel] = counts
    return lines, per_sel_entries


def validate(run_dir: Path, write: bool = True) -> dict:
    report: dict = {"run": run_dir.name, "verdict": "FAILED", "hard_failures": [], "controls": [], "aggregates": {}}
    fail = report["hard_failures"].append
    v = mf.validate_manifest(run_dir)
    for e in (v.errors if not v.ok else []):
        fail(f"manifest: {e}")
    m = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    if m.get("package") != "entry_pilot_01" or m.get("manifest_version") != 2:
        fail("manifest: not an entry_pilot_01 / manifest_version 2 run")
    contract = m.get("contract") or {}
    if not contract:
        fail("manifest: contract block missing")
    by = {d["dataset"]: d for d in m["datasets"]}
    for name, role in EXPECTED.items():
        d = by.get(name)
        if d is None:
            fail(f"dataset {name} is missing")
        elif d["status"] != "ok":
            fail(f"dataset {name} has status '{d['status']}'")
        elif d.get("role") != role:
            fail(f"dataset {name} has role '{d.get('role')}', expected '{role}'")
    if report["hard_failures"]:
        return finish(run_dir, report, None, write)
    report["manifest_sha256"] = mf.sha256_file(run_dir / "manifest.json")
    report["contract"] = contract
    try:
        for kind in [f"c1_totals_{n}" for n in SEL_NAMES] + ["c3_bills", "c4_register"]:
            if _norm(load(run_dir, f"{kind}_pre")) != _norm(load(run_dir, f"{kind}_post")):
                fail(f"REFRESH RACE: {kind} differs between PRE and POST")
        c3 = load(run_dir, "c3_bills_pre")
        if len(c3) != 1:
            fail("c3_bills_pre must have exactly one row")
            return finish(run_dir, report, None, write)
        c3 = c3[0]
        c4 = load(run_dir, "c4_register_pre")
        if len(c4) != 1:
            fail("c4_register_pre must have exactly one row")
            return finish(run_dir, report, None, write)
        as_of = dt(c4[0]["register_report_date"], "register_report_date", "c4")
        cube = dt(c3["cube_report_date"], "cube_report_date", "c3")
        if as_of is None or cube is None or as_of != cube:
            fail("the outstanding cube and the site register are not the same snapshot (report dates differ)")
            return finish(run_dir, report, None, write)
        if contract.get("as_of_cutoff") and as_of.isoformat() != contract["as_of_cutoff"]:
            fail(f"the source has moved on: its report date is not the pinned cutoff {contract['as_of_cutoff']}: refresh creditors and cash first, then re-pin the cutoff")
            return finish(run_dir, report, None, write)
        lines, per_sel = build_lines(run_dir, by, fail)

        # entries
        groups: dict[tuple, list[dict]] = defaultdict(list)
        for key, ln in lines.items():
            groups[key[:3]].append(ln)
        headers, entry_lines, identity, texts = [], [], [], []
        unbalanced = 0
        for ident, ls in sorted(groups.items()):
            ls.sort(key=lambda x: (int(Decimal(x["seq"])), x["seq"]))
            ref = entry_ref(*ident)
            dates = {x["entry_date"] for x in ls}
            longs = {x["entry_type_long"] for x in ls}
            if len(dates) != 1 or len(longs) > 1:
                fail("an entry has lines with different dates or entry types")
                return finish(run_dir, report, None, write)
            statuses = {x["release_status"] for x in ls}
            tdr, tcr = sum((x["debit"] for x in ls), ZERO), sum((x["credit"] for x in ls), ZERO)
            if tdr != tcr:
                unbalanced += 1
            sels = sorted({s for x in ls for s in x["selections"]})
            headers.append({"entry_ref": ref, "site_code": ident[0], "entry_type_short": ident[1], "entry_type_long": ls[0]["entry_type_long"], "entry_date": dates.pop(),
                            "release_status": "Mixed" if len(statuses) > 1 else next(iter(statuses)), "line_count": len(ls), "total_dr": tdr, "total_cr": tcr, "selections": sels})
            identity.append({"entry_ref": ref, "site_code": ident[0], "entry_type_short": ident[1], "entry_no": ident[2], "created_by_site": next((x["created_by_site"] for x in ls if x["created_by_site"]), None)})
            for n, x in enumerate(ls, start=1):
                entry_lines.append({"entry_ref": ref, "line_no": n, "source_seq": x["seq"], "ledger_code": x["glcode"], "ledger_name": x["glname"], "ledger_nature": x["glnature"], "debit": x["debit"],
                                    "credit": x["credit"], "release_status": x["release_status"], "cube_name": x["cubename"]})
                texts.append({"entry_ref": ref, "line_no": n, "sub_ledger_code": x["slcode"], **{k: x[k] for k in TEXT_FIELDS}})
        if unbalanced:
            fail(f"E3: {unbalanced} entries do not balance (total debit differs from total credit)")

        # E1 / E2: source controls
        rc = Recon()
        c1 = {r["selection"]: r for n in SEL_NAMES for r in load(run_dir, f"c1_totals_{n}_pre")}
        for sel in ("creditors_cur", "creditors_old", "bank"):
            ex_lines = [ln for ln in lines.values() if sel in ln["selections"]]
            ex_entries = {(ln["site_code"], ln["entry_type_short"], ln["entry_no"]) for ln in ex_lines}
            s = c1.get(sel)
            if s is None:
                fail(f"the c1 totals have no row for selection {sel}")
                continue
            rc.add(f"E1_{sel}", "entries", as_int(s["entries"]), len(ex_entries))
            rc.add(f"E1_{sel}", "lines", as_int(s["lines"]), len(ex_lines))
            rc.add(f"E1_{sel}", "debit", dec(s["sum_debit"], "sum_debit", "c1") or ZERO, sum((ln["debit"] for ln in ex_lines), ZERO))
            rc.add(f"E1_{sel}", "credit", dec(s["sum_credit"], "sum_credit", "c1") or ZERO, sum((ln["credit"] for ln in ex_lines), ZERO))
        src_hist: dict[tuple, int] = {}
        for r in (x for n in SEL_NAMES for x in load(run_dir, f"c2_histogram_{n}_pre")):
            src_hist[(r["selection"], as_int(r["lines_per_entry"]))] = as_int(r["entries"])
        for sel, counts in per_sel.items():
            ex_hist = Counter(counts.values())
            for n in sorted({k[1] for k in src_hist if k[0] == sel} | set(ex_hist)):
                rc.add(f"E2_{sel}", f"entries with {n} lines", src_hist.get((sel, n), 0), ex_hist.get(n, 0))

        # bridge 1: creditor bill links
        hdr_ref = {h["entry_ref"]: h for h in headers}
        net_by_entry_cache: dict[str, Decimal] = {}
        links, seen_bills = [], set()
        windows = {"l1a_links_current": "CURRENT_FY", "l1b_links_prior": "PRIOR_YEARS_IN_COVERAGE", "l1c_bills_before_coverage": "BEFORE_COVERAGE"}
        counts_by_window = Counter()
        for ds, cover in windows.items():
            for i, r in enumerate(load(run_dir, ds)):
                where = f"{ds} row {i + 1}"
                if not r.get("document_code") or not r.get("sub_ledger_code"):
                    raise StageError(f"{where}: the bill identity is incomplete")
                key = cs.source_row_key(str(r["document_code"]), str(r["sub_ledger_code"]))
                if key in seen_bills:
                    raise StageError(f"{ds}: a bill appears in two windows or twice")
                seen_bills.add(key)
                counts_by_window[cover] += 1
                amount = dec(r["bill_amount"], "bill_amount", where) or ZERO
                if cover == "BEFORE_COVERAGE":
                    links.append({"source_row_key": key, "ledger_code": str(r["ledger_code"]), "bill_amount": amount, "link_status": "NOT_LINKED", "not_linked_reason": "REGISTER_COVERAGE_UNAVAILABLE",
                                  "key_used": KEY_USED, "matched_entries": 0, "entry_ref": None, "entry_net_amount": None, "amount_agrees": None, "coverage": cover})
                    continue
                m_ = as_int(r["matched_entries"])
                ref = None
                net = None
                agrees = None
                if m_ == 0:
                    status, reason = "NOT_LINKED", "NO_MATCH"
                elif m_ > 1:
                    status, reason = "AMBIGUOUS", None
                else:
                    ref = entry_ref(str(r["site_code"]), r["entry_type_short"], str(r["entry_no"]))
                    if ref not in hdr_ref:
                        raise StageError(f"{where}: a linked entry was not extracted (the bridge and the entry extract disagree)")
                    net = dec(r["entry_net_dr_minus_cr"], "entry_net_dr_minus_cr", where)
                    agrees = abs(net) == abs(amount)
                    status, reason = ("EXACT" if agrees else "STRONG"), None
                links.append({"source_row_key": key, "ledger_code": str(r["ledger_code"]), "bill_amount": amount, "link_status": status, "not_linked_reason": reason, "key_used": KEY_USED,
                              "matched_entries": m_, "entry_ref": ref, "entry_net_amount": net, "amount_agrees": agrees, "coverage": cover})
        rc.add("E6_bills", "open bills current FY", as_int(c3["bills_current_fy"]), counts_by_window["CURRENT_FY"])
        rc.add("E6_bills", "open bills prior years", as_int(c3["bills_prior_years"]), counts_by_window["PRIOR_YEARS_IN_COVERAGE"])
        rc.add("E6_bills", "open bills before register coverage", as_int(c3["bills_before_coverage"]), counts_by_window["BEFORE_COVERAGE"])
        rc.add("E6_bills", "open bills in total", as_int(c3["open_bills"]), len(links))

        # bridge 2: till days
        till, seen_td = [], set()
        for i, r in enumerate(load(run_dir, "l2_till_day")):
            where = f"l2_till_day row {i + 1}"
            k = (str(r["site_code"]), str(r["day"]))
            if k in seen_td:
                raise StageError("l2_till_day: a store/day appears twice")
            seen_td.add(k)
            till.append({"site_code": k[0], "day": dt(r["day"], "day", where), "debit": dec(r["debit"], "debit", where) or ZERO, "credit": dec(r["credit"], "credit", where) or ZERO,
                         "cumulative_balance": dec(r["cumulative_balance"], "cumulative_balance", where) or ZERO})
        if not till:
            fail("l2_till_day is empty")
        report["controls"] = rc.rows
        for r in rc.failed:
            fail(f"control {r['control']} ({r['dimension']}): source {r['left']} vs extract {r['right']}")
    except StageError as e:
        fail(str(e))
        return finish(run_dir, report, None, write)

    by_status = Counter(k["link_status"] for k in links)
    report["aggregates"] = {
        "register_report_date": as_of.isoformat(), "till_balance_date": max(t["day"] for t in till).isoformat(), "entries": len(headers), "lines": len(entry_lines),
        "lines_by_selection": {s: sum(1 for ln in lines.values() if s in ln["selections"]) for s in ("creditors_cur", "creditors_old", "bank")},
        "total_dr": str(sum((h["total_dr"] for h in headers), ZERO)), "total_cr": str(sum((h["total_cr"] for h in headers), ZERO)), "links": len(links), "links_by_status": dict(by_status),
        "links_by_coverage": dict(counts_by_window), "till_days": len(till),
    }
    report["verdict"] = "PASSED" if not report["hard_failures"] else "FAILED"
    return finish(run_dir, report, (headers, entry_lines, identity, texts, links, till), write)


def finish(run_dir: Path, report: dict, data, write: bool = True) -> dict:
    if not write:                      # a re-derivation (the loader's preflight) never touches the files it is checking
        report["derived"] = data
        return report
    out = run_dir / "staging"
    out.mkdir(exist_ok=True)
    if report["verdict"] == "PASSED" and data is not None:
        write_derived(out, data, report)
    (out / "validation_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    (out / "VALIDATION_REPORT.md").write_text(render_md(report), encoding="utf-8")
    return report


def write_derived(out: Path, data, report: dict) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    names = ["entry_header", "entry_line", "entry_identity", "entry_line_text", "creditor_bill_link", "till_day"]
    decs = {"total_dr", "total_cr", "debit", "credit", "bill_amount", "entry_net_amount", "cumulative_balance"}
    dates = {"entry_date", "day"}
    ints = {"line_count", "line_no", "matched_entries"}
    report["outputs"] = {}
    for name, rows in zip(names, data):
        cols = list(rows[0].keys()) if rows else []
        arrs = []
        for c in cols:
            vals = [r[c] for r in rows]
            if c in decs:
                for x in vals:
                    if x is not None and x != x.quantize(Decimal("0.0001")):
                        raise StageError(f"{c} has more than 4 decimal places; widen the schema deliberately")
                arrs.append(pa.array(vals, type=pa.decimal128(24, 4)))
            elif c in dates:
                arrs.append(pa.array(vals, type=pa.date32()))
            elif c in ints:
                arrs.append(pa.array(vals, type=pa.int32()))
            elif c == "amount_agrees":
                arrs.append(pa.array(vals, type=pa.bool_()))
            elif c == "selections":
                arrs.append(pa.array(vals, type=pa.list_(pa.string())))
            else:
                arrs.append(pa.array(vals, type=pa.string()))
        pq.write_table(pa.table(arrs, names=cols), out / f"{name}.parquet")
        report["outputs"][name] = mf.sha256_file(out / f"{name}.parquet")


def render_md(r: dict) -> str:
    L = [f"# Entry layer staging validation: {r['run']}", "", f"**Verdict: {r['verdict']}**", ""]
    if r["hard_failures"]:
        L += ["## Hard failures", *[f"- {x}" for x in r["hard_failures"]], ""]
    c = r["controls"]
    if c:
        L += [f"## Source to extract controls: {len(c)} checked, {sum(1 for x in c if x['verdict'] == 'PASS')} pass", ""]
    a = r.get("aggregates")
    if a:
        L += ["## Counts", f"- register report date {a['register_report_date']}; till balance date {a['till_balance_date']}", f"- {a['entries']:,} entries, {a['lines']:,} lines; lines by selection {a['lines_by_selection']}",
              f"- {a['links']:,} creditor bills linked: by status {a['links_by_status']}; by coverage {a['links_by_coverage']}", f"- {a['till_days']:,} till store-days"]
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
