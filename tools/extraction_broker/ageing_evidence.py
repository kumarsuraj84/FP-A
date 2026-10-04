"""
Evidence for the creditor ageing definition, read from an `ageing_probe_01` run.

This collects what the data says. It does NOT choose the ageing rule: every conclusion is left "pending" for finance.
Output never contains amounts, party codes or names; only counts, dates, day values and shares.

    python tools/extraction_broker/ageing_evidence.py data/inbox/run_YYYYMMDD_NNN
"""
from __future__ import annotations

import collections
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import manifest as mf  # noqa: E402


def _rows(run: Path, name: str, loadable: set[str]) -> list[dict]:
    if name not in loadable:
        raise SystemExit(f"dataset {name} is not loadable in this run; cannot build the evidence")
    import pyarrow.parquet as pq

    return [{k.upper(): v for k, v in r.items()} for r in pq.read_table(run / f"{name}.parquet").to_pylist()]


def pct(n: float, d: float) -> str:
    return f"{100 * n / d:.1f}%" if d else "n/a"


def build(run: Path) -> dict:
    v = mf.validate_manifest(run)
    if not v.ok:
        raise SystemExit("manifest does not validate:\n  " + "\n  ".join(v.errors))
    load = set(v.loadable)
    R = lambda n: _rows(run, n, load)  # noqa: E731

    p02, p03, p04 = R("p02_due_date_basis"), R("p03_null_counts_and_ranges")[0], R("p04_drcr_distribution")
    p05, p06, p07 = R("p05_day_count_consistency")[0], R("p06_due_minus_date_days"), R("p07_vendor_due_terms")
    sample, ledger, sub = R("p08_sample_50"), R("m01_ledger_mv"), R("m02_sub_ledger_mv")
    p01 = R("p01_report_date_distribution")
    total = int(p03["TOTAL_ROWS"])
    E: dict = {"run": run.name, "total_rows": total}

    # 1. DUE_DATE_BASIS
    E["due_date_basis"] = [{"value": r["DUE_DATE_BASIS"], "rows": int(r["ROW_COUNT"]), "share": pct(r["ROW_COUNT"], total), "due_date_filled": int(r["DUE_DATE_FILLED"])} for r in p02]

    # 2. which dates are populated
    filled = {k: int(p03[f"{k}_FILLED"]) for k in ("DOCUMENT_DATE", "DUE_DATE", "REF_DATE", "ENTRY_DATE")}
    E["dates_filled"] = {k.lower(): {"rows": n, "share": pct(n, total)} for k, n in filled.items()}
    E["date_ranges"] = {k: [str(p03[f"MIN_{k}"])[:10], str(p03[f"MAX_{k}"])[:10]] for k in ("DOCUMENT_DATE", "DUE_DATE", "REF_DATE", "ENTRY_DATE")}
    E["rows_with_neither_document_nor_due_date"] = int(p03["NEITHER_DOCUMENT_NOR_DUE_DATE"])
    E["rows_with_no_date_at_all"] = int(p03["NO_DATE_AT_ALL"])
    E["due_before_document"] = int(p03["DUE_BEFORE_DOCUMENT"])
    E["report_dates"] = [{"report_date": str(r["REPORT_DATE"])[:10], "rows": int(r["ROW_COUNT"])} for r in p01]

    # 3. due date vs vendor credit days
    credit = {int(r["SLCODE"]): r["CREDIT_DAYS"] for r in sub if r["SLCODE"] is not None}
    by_basis: dict = collections.defaultdict(lambda: [0, 0])
    joined = rows_known = 0
    vendors = set()
    for r in p07:
        slc = int(r["SUB_LEDGER_CODE"])
        vendors.add(slc)
        cd = credit.get(slc)
        n = int(r["ROW_COUNT"])
        if cd is None:
            continue
        rows_known += n
        by_basis[r["DUE_DATE_BASIS"]][0] += n
        if int(r["DUE_MINUS_DOCUMENT_DAYS"]) == int(cd):
            joined += n
            by_basis[r["DUE_DATE_BASIS"]][1] += n
    E["due_vs_credit_days"] = {
        "due_dated_rows_with_known_credit_days": rows_known,
        "rows_where_due_minus_document_equals_credit_days": joined,
        "share": pct(joined, rows_known),
        "by_basis": {str(b): {"rows": n, "equal": m, "share": pct(m, n)} for b, (n, m) in by_basis.items()},
        "vendors_with_due_dated_rows": len(vendors),
        "vendors_found_in_master": sum(1 for s in vendors if s in credit),
    }
    by = collections.defaultdict(list)
    for r in p06:
        by[r["BASIS"]].append((int(r["DAYS"]), int(r["ROW_COUNT"])))
    E["due_minus_date_days_top"] = {b: sorted(x, key=lambda t: -t[1])[:6] for b, x in by.items()}

    # 4. which day-count matches what
    E["day_count_matches"] = {k.lower(): {"rows": int(p05[k]), "share_of_all_rows": pct(p05[k], total)} for k in p05 if k != "TOTAL_ROWS"}
    E["day_count_ranges"] = {
        "no_of_days_base_on_entry_date": [int(p03["MIN_DAYS_ENTRY"]), int(p03["MAX_DAYS_ENTRY"])],
        "no_of_days_base_on_ref_date": [int(p03["MIN_DAYS_REF"]), int(p03["MAX_DAYS_REF"])],
        "days_ref_filled": int(p03["DAYS_REF_FILLED"]),
    }
    offsets = set()
    for r in sample:
        if r["ENTRY_DATE"] is not None and r["NO_OF_DAYS_BASE_ON_ENTRY_DATE"] is not None:
            offsets.add((r["ENTRY_DATE"] + dt.timedelta(days=int(r["NO_OF_DAYS_BASE_ON_ENTRY_DATE"]))).date().isoformat())
    E["sample_entry_plus_days_entry_dates"] = sorted(offsets)
    E["sample_rows"] = len(sample)

    # 5. DR / CR
    E["drcr"] = [
        {
            "value": r["DRCR"], "rows": int(r["ROW_COUNT"]), "amount_sign": "negative" if (r["MAX_AMOUNT"] or 0) <= 0 else "positive",
            "pending_sign": "<= 0" if (r["MAX_PENDING"] or 0) <= 0 else ">= 0",
        }
        for r in p04
    ]
    E["pending"] = {"zero": int(p03["PENDING_ZERO"]), "zero_share": pct(p03["PENDING_ZERO"], total), "negative": int(p03["PENDING_NEGATIVE"]), "filled": int(p03["PENDING_FILLED"])}

    # 6. vendor key
    ids = [r["SLID"] for r in sub]
    E["vendor_key"] = {
        "sub_ledger_master_rows": len(sub),
        "slcode_unique": len({r["SLCODE"] for r in sub}) == len(sub),
        "slid_unique": len({i for i in ids if i}) == len([i for i in ids if i]),
        "slid_null": sum(1 for i in ids if not i),
        "gl_sl_pair_unique": len({(r["GLCODE"], r["SLCODE"]) for r in sub}) == len(sub),
        "all_due_dated_cube_vendors_found_by_slcode": E["due_vs_credit_days"]["vendors_with_due_dated_rows"] == E["due_vs_credit_days"]["vendors_found_in_master"],
        "sl_class_type": collections.Counter(r["SL_CLASS_TYPE"] for r in sub).most_common(8),
        "sl_class": collections.Counter(r["SL_CLASS"] for r in sub).most_common(8),
        "credit_days_filled": sum(1 for r in sub if r["CREDIT_DAYS"] is not None),
        "credit_days_values": [(None if k is None else int(k), n) for k, n in collections.Counter(r["CREDIT_DAYS"] for r in sub).most_common(6)],
        "ledger_master_rows": len(ledger),
        "ledger_type": collections.Counter(r["TYPE"] for r in ledger).most_common(6),
    }
    return E


def render(E: dict) -> str:
    t = E["total_rows"]
    basis = ", ".join(f"{b['value'] or 'NULL'} {b['rows']:,} ({b['share']})" for b in E["due_date_basis"])
    f = E["dates_filled"]
    ranges = E["date_ranges"]
    dvc = E["due_vs_credit_days"]
    dm = E["day_count_matches"]
    k = E["vendor_key"]
    drcr = "; ".join(f"{x['value']}: {x['rows']:,} rows, amount {x['amount_sign']}, pending {x['pending_sign']}" for x in E["drcr"])
    top = lambda b: ", ".join(f"{d}d×{n:,}" for d, n in E["due_minus_date_days_top"][b][:4])  # noqa: E731
    L = [
        f"# Ageing-definition evidence · {E['run']}",
        "",
        "Source: `MISRETAIL.T$FINOTSD_533` (OUTSTANDING cube) and `LEDGER_MV` / `SUB_LEDGER_MV`. Observations only; **no rule is chosen**.",
        f"Rows probed: {t:,} (report snapshot(s): {', '.join(x['report_date'] for x in E['report_dates'])}).",
        "",
        "| Question | Evidence | Conclusion |",
        "|---|---|---|",
        f"| What does `DUE_DATE_BASIS` contain? | {basis} | pending |",
        f"| Which date is populated most consistently? | document_date {f['document_date']['share']}, entry_date {f['entry_date']['share']}, ref_date {f['ref_date']['share']}, **due_date {f['due_date']['share']}** ({f['due_date']['rows']:,} of {t:,}). Rows with neither document nor due date: {E['rows_with_neither_document_nor_due_date']}. Ranges: document {ranges['DOCUMENT_DATE'][0]}…{ranges['DOCUMENT_DATE'][1]}, entry {ranges['ENTRY_DATE'][0]}…{ranges['ENTRY_DATE'][1]}, due {ranges['DUE_DATE'][0]}…{ranges['DUE_DATE'][1]} | pending |",
        f"| Does due date align with credit days? | Where a due date exists, (due − document) equals the vendor's `CREDIT_DAYS` on {dvc['share']} of {dvc['due_dated_rows_with_known_credit_days']:,} rows (by basis: " + "; ".join(f"{b} {v['share']}" for b, v in dvc["by_basis"].items()) + f"). Common due−document gaps: {top('due_minus_document')}. Due before document: {E['due_before_document']} rows. Not yet shown: whether rows with NO due date could be derived from credit days | pending |",
        f"| Which day-count column matches ageing bands? | `no_of_days_base_on_entry_date` = (cube END_DATE − entry_date) on {dm['d_ent_end_ent']['share_of_all_rows']} of rows; `…ref_date` = (END_DATE − ref_date) on its {E['day_count_ranges']['days_ref_filled']:,} populated rows. Against REPORT_DATE: {dm['d_ent_rep_ent']['share_of_all_rows']} / {dm['d_ref_rep_ref']['share_of_all_rows']}. In the sample, entry_date + days_entry = {', '.join(E['sample_entry_plus_days_entry_dates'])} on every row (the cube's END_DATE, a future fiscal-year end). Day counts range {E['day_count_ranges']['no_of_days_base_on_entry_date'][0]}…{E['day_count_ranges']['no_of_days_base_on_entry_date'][1]} | pending |",
        f"| What do DR/CR mean in this cube? | {drcr}. `pending` = 0 on {E['pending']['zero']:,} rows ({E['pending']['zero_share']}), negative on {E['pending']['negative']:,} | pending |",
        f"| Canonical vendor key candidate | `SLCODE` unique across {k['sub_ledger_master_rows']:,} master rows: {k['slcode_unique']}; `SLID` unique: {k['slid_unique']} (null {k['slid_null']}); (GLCODE, SLCODE) unique: {k['gl_sl_pair_unique']}; every due-dated cube vendor ({dvc['vendors_with_due_dated_rows']:,}) found by SLCODE: {k['all_due_dated_cube_vendors_found_by_slcode']} | pending |",
        "",
        "## Supporting observations (not conclusions)",
        "",
        f"- The cube spans many party classes, not only trade suppliers: `SL_CLASS_TYPE` {k['sl_class_type']}; `SL_CLASS` {k['sl_class']}. GL master types: {k['ledger_type']}.",
        f"- `CREDIT_DAYS` is populated for {k['credit_days_filled']:,} of {k['sub_ledger_master_rows']:,} sub-ledgers; most common values {k['credit_days_values']}.",
        f"- Document dates run from {ranges['DOCUMENT_DATE'][0]} to {ranges['DOCUMENT_DATE'][1]} (a year-0202 date and future-dated documents exist: a data-quality finding to quantify).",
        f"- Sample ({E['sample_rows']} rows) is a random 0.1% row sample, kept for eyeballing fields side by side; it is not used for any share above.",
        "",
        "## Open before any larger extraction",
        "",
        "- Do rows with no due date get one from `SUB_LEDGER_MV.CREDIT_DAYS` (basis date + credit days)? (probe: the cube joined to the master, bounded)",
        "- How many rows have a year < 2000 or future document date, and are they open (pending ≠ 0)?",
        "- Which GL codes are payables (LEDGER_MV Liability / Control) and how do the cube's Dr/Cr rows split by those ledgers?",
        "- Is END_DATE = 2027-03-31 the as-on date finance expects, or should ageing be computed from dates as of the report date?",
    ]
    return "\n".join(L) + "\n"


def main(argv: list[str]) -> int:
    run = Path(argv[0])
    E = build(run)
    (run / "AGEING_EVIDENCE.json").write_text(json.dumps(E, indent=2, default=str), encoding="utf-8")
    (run / "AGEING_EVIDENCE.md").write_text(render(E), encoding="utf-8")
    print(f"wrote {run / 'AGEING_EVIDENCE.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
