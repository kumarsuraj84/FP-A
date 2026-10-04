"""
Evidence for the creditor data contract, read from a `payables_probe_01` run.

Collects what the data says about (1) whether a missing due date can be reconstructed, (2) date quality on OPEN exposure,
(3) which ledgers / party classes make up the payable population, and (4) how AMOUNT, ADJUSTED and PENDING reconcile.
It chooses nothing: every conclusion is left "pending" for finance. No party names or codes appear in the output.

    python tools/extraction_broker/payables_evidence.py data/inbox/run_YYYYMMDD_NNN
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import manifest as mf  # noqa: E402

CR = 1e7  # rupees per crore


def _rows(run: Path, name: str, loadable: set[str]) -> list[dict]:
    if name not in loadable:
        raise SystemExit(f"dataset {name} is not loadable in this run")
    import pyarrow.parquet as pq

    return [{k.upper(): v for k, v in r.items()} for r in pq.read_table(run / f"{name}.parquet").to_pylist()]


def pct(n, d) -> str:
    return f"{100 * n / d:.1f}%" if d else "n/a"


def build(run: Path) -> dict:
    v = mf.validate_manifest(run)
    if not v.ok:
        raise SystemExit("manifest does not validate:\n  " + "\n  ".join(v.errors))
    load = set(v.loadable)
    q1, q2, q3, q4 = (_rows(run, n, load) for n in ("q1_due_date_derivation", "q2_date_quality_by_exposure", "q3_payable_population", "q4_amount_adjusted_pending"))
    E: dict = {"run": run.name}

    # integrity: the joins must not multiply or drop rows
    totals = {"q2": sum(int(r["TOTAL_ROWS"]) for r in q2), "q3": sum(int(r["ROW_COUNT"]) for r in q3), "q4": sum(int(r["TOTAL_ROWS"]) for r in q4)}
    E["rows"] = {**totals, "consistent": len(set(totals.values())) == 1, "open_rows_q1": sum(int(r["OPEN_ROWS"]) for r in q1)}

    # 3. population by ledger
    led: dict = collections.defaultdict(lambda: {"name": None, "type": None, "nature": None, "rows": 0, "Cr": [0, 0.0], "Dr": [0, 0.0], "classes": collections.Counter()})
    for r in q3:
        a = led[int(r["LEDGER_CODE"])]
        a["name"], a["type"], a["nature"] = r["LEDGER_NAME"], r["LEDGER_TYPE"], r["LEDGER_NATURE"]
        a["rows"] += int(r["ROW_COUNT"])
        a[r["DRCR"]][0] += int(r["OPEN_ROWS"])
        a[r["DRCR"]][1] += r["ABS_SUM_PENDING"] or 0
        a["classes"][str(r["PARTY_CLASS"])] += int(r["OPEN_ROWS"])
    E["ledgers"] = [
        {
            "ledger_code": k, "name": a["name"], "type": a["type"], "nature": a["nature"], "rows": a["rows"],
            "open_cr_rows": a["Cr"][0], "open_cr_crore": round(a["Cr"][1] / CR, 2), "open_dr_rows": a["Dr"][0],
            "open_dr_crore": round(a["Dr"][1] / CR, 2), "net_cr_minus_dr_crore": round((a["Cr"][1] - a["Dr"][1]) / CR, 2),
            "party_classes_open_rows": dict(a["classes"].most_common(5)),
        }
        for k, a in sorted(led.items(), key=lambda kv: -(kv[1]["Cr"][1] + kv[1]["Dr"][1]))
    ]
    fam = [x for x in E["ledgers"] if x["type"] == "Liability" and str(x["name"]).startswith("Sundry Creditors")]
    E["creditor_family"] = {
        "ledgers": [x["name"] for x in fam],
        "open_cr_rows": sum(x["open_cr_rows"] for x in fam), "open_cr_crore": round(sum(x["open_cr_crore"] for x in fam), 2),
        "open_dr_rows": sum(x["open_dr_rows"] for x in fam), "open_dr_crore": round(sum(x["open_dr_crore"] for x in fam), 2),
        "net_payable_crore": round(sum(x["net_cr_minus_dr_crore"] for x in fam), 2),
        "note": "Dr items inside creditor ledgers are shown as found: debit balances, NOT classified as vendor advances.",
    }
    pcx: dict = collections.defaultdict(lambda: [0, 0.0])
    for r in q3:
        k = f"{r['PARTY_CLASS']} / {r['DRCR']}"
        pcx[k][0] += int(r["OPEN_ROWS"])
        pcx[k][1] += r["ABS_SUM_PENDING"] or 0
    E["open_by_party_class"] = [{"group": k, "open_rows": n, "crore": round(a / CR, 2)} for k, (n, a) in sorted(pcx.items(), key=lambda kv: -kv[1][1]) if n]

    # 4. AMOUNT / ADJUSTED / PENDING
    E["reconciliation"] = [
        {
            "group": f"{r['DRCR']}/{r['PENDING_STATE']}", "rows": int(r["TOTAL_ROWS"]),
            "adjusted_null": int(r["ADJUSTED_NULL"]), "adjusted_zero": int(r["ADJUSTED_ZERO"]), "adjusted_positive": int(r["ADJUSTED_POSITIVE"]), "adjusted_negative": int(r["ADJUSTED_NEGATIVE"]),
            "pending_eq_amount_minus_adjusted": pct(r["P_EQ_AMOUNT_MINUS_ADJ"], r["TOTAL_ROWS"]), "pending_eq_amount_plus_adjusted": pct(r["P_EQ_AMOUNT_PLUS_ADJ"], r["TOTAL_ROWS"]),
            "pending_eq_sign_times_abs_difference": pct(r["P_EQ_ABS_DIFFERENCE"], r["TOTAL_ROWS"]), "pending_eq_amount": pct(r["P_EQ_AMOUNT"], r["TOTAL_ROWS"]),
            "adjusted_exceeds_amount": int(r["ADJ_EXCEEDS_AMOUNT"]), "pending_exceeds_amount": int(r["PENDING_EXCEEDS_AMOUNT"]),
        }
        for r in q4
    ]
    E["pending_formula_holds_everywhere"] = all(int(r["P_EQ_ABS_DIFFERENCE"]) == int(r["TOTAL_ROWS"]) for r in q4)

    # 2. date quality on open exposure
    dq = []
    for r in q2:
        row = {"group": f"{r['PENDING_STATE']}/{r['DRCR']}", "rows": int(r["TOTAL_ROWS"]), "abs_pending_crore": round((r["ABS_PENDING"] or 0) / CR, 2)}
        for k in ("DOC_PRE2000", "DOC_AFTER_REPORT", "DUE_AFTER_REPORT", "DOC_NULL", "DUE_NULL", "CREDIT_NULL"):
            row[k.lower()] = {"rows": int(r[f"{k}_ROWS"]), "crore": round((r[f"{k}_ABS"] or 0) / CR, 2)}
        row["entry_pre2000_rows"], row["entry_after_report_rows"] = int(r["ENTRY_PRE2000_ROWS"]), int(r["ENTRY_AFTER_REPORT_ROWS"])
        dq.append(row)
    E["date_quality"] = dq

    # 1. due date derivation
    def agg(keyf):
        out: dict = collections.defaultdict(lambda: [0, 0, 0, 0])
        for r in q1:
            a = out[keyf(r)]
            a[0] += int(r["OPEN_ROWS"])
            a[1] += int(r["COMPARABLE_ROWS"])
            a[2] += int(r["EQ_DOCUMENT_PLUS_CREDIT"])
            a[3] += int(r["EQ_ENTRY_PLUS_CREDIT"])
        return {str(k): {"open_rows": n, "comparable_rows": c, "eq_document_plus_credit": e1, "share_document": pct(e1, c), "eq_entry_plus_credit": e2, "share_entry": pct(e2, c)} for k, (n, c, e1, e2) in sorted(out.items(), key=lambda kv: -kv[1][0])}

    E["derivation"] = {
        "by_due_and_credit_state": agg(lambda r: f"{r['DUE_STATE']} / {r['CREDIT_DAYS_STATE']}"),
        "by_basis": agg(lambda r: f"{r['DUE_DATE_BASIS']} / {r['DUE_STATE']}"),
        "by_drcr": agg(lambda r: f"{r['DRCR']} / {r['DUE_STATE']}"),
        "by_party_class": {k: v for k, v in agg(lambda r: f"{r['SL_CLASS']} / {r['DUE_STATE']}").items() if v["comparable_rows"]},
    }
    missing = collections.defaultdict(int)
    for r in q1:
        if r["DUE_STATE"] == "due_null":
            missing[f"{r['DRCR']} / {r['SL_CLASS']} / {r['CREDIT_DAYS_STATE']}"] += int(r["OPEN_ROWS"])
    E["missing_due_open_rows"] = dict(sorted(missing.items(), key=lambda kv: -kv[1]))
    tds = sum(n for k, n in missing.items() if " / TDS / " in k)
    E["missing_due_summary"] = {"all_open_rows_without_due_date": sum(missing.values()), "of_which_tds_class": tds, "of_which_cr_not_tds": sum(n for k, n in missing.items() if k.startswith("Cr /") and " / TDS / " not in k),
                                "of_which_cr_not_tds_with_positive_credit_days": sum(n for k, n in missing.items() if k.startswith("Cr /") and " / TDS / " not in k and k.endswith("credit_days_positive"))}
    return E


def render(E: dict) -> str:
    L = [f"# Payables evidence · {E['run']}", "", "Source: `MISRETAIL.T$FINOTSD_533` joined inside MISRETAIL to `LEDGER_MV` and `SUB_LEDGER_MV`. Aggregates only; **nothing is derived, written or decided**.", ""]
    r = E["rows"]
    L += [f"Join integrity: cube rows {r['q3']:,} (q2 {r['q2']:,}, q4 {r['q4']:,}); open rows {r['open_rows_q1']:,}. Consistent: **{r['consistent']}**.", ""]
    L += ["## 3. Payable population: the cube holds only these ledgers", "", "| Ledger | Type | Nature | Open Cr rows | Open Cr (₹ Cr) | Open Dr rows | Open Dr (₹ Cr) | Net Cr−Dr (₹ Cr) | Party classes (open rows) |", "|---|---|---|---:|---:|---:|---:|---:|---|"]
    for x in E["ledgers"]:
        L.append(f"| {x['name']} | {x['type']} | {x['nature']} | {x['open_cr_rows']:,} | {x['open_cr_crore']:,.2f} | {x['open_dr_rows']:,} | {x['open_dr_crore']:,.2f} | {x['net_cr_minus_dr_crore']:,.2f} | {', '.join(f'{k} {v:,}' for k, v in x['party_classes_open_rows'].items())} |")
    f = E["creditor_family"]
    L += ["", f"Sundry-Creditors family ({len(f['ledgers'])} ledgers): open Cr **₹{f['open_cr_crore']:,.2f} Cr** ({f['open_cr_rows']:,} rows); open Dr inside them **₹{f['open_dr_crore']:,.2f} Cr** ({f['open_dr_rows']:,} rows); net ₹{f['net_payable_crore']:,.2f} Cr. {f['note']}", ""]
    L += ["### Open exposure by party class and Dr/Cr", "", "| Party class / DRCR | Open rows | ₹ Cr (absolute) |", "|---|---:|---:|"] + [f"| {x['group']} | {x['open_rows']:,} | {x['crore']:,.2f} |" for x in E["open_by_party_class"][:14]]
    L += ["", "## 4. AMOUNT, ADJUSTED, PENDING", "", f"`pending = sign(amount) × (|amount| − |adjusted|)` holds on every row of every group: **{E['pending_formula_holds_everywhere']}**.", "", "| Group | Rows | adjusted null / zero / + / − | = amount−adj | = amount+adj | = sign×(\\|a\\|−\\|adj\\|) | = amount |", "|---|---:|---|---:|---:|---:|---:|"]
    for x in E["reconciliation"]:
        L.append(f"| {x['group']} | {x['rows']:,} | {x['adjusted_null']:,} / {x['adjusted_zero']:,} / {x['adjusted_positive']:,} / {x['adjusted_negative']:,} | {x['pending_eq_amount_minus_adjusted']} | {x['pending_eq_amount_plus_adjusted']} | {x['pending_eq_sign_times_abs_difference']} | {x['pending_eq_amount']} |")
    L += ["", "## 2. Date quality, weighted by absolute pending exposure", "", "| Group | Rows | Exposure ₹ Cr | Doc < 2000 | Doc > report date | Due > report date | Doc null | Due null | Credit days null |", "|---|---:|---:|---|---|---|---|---|---|"]
    for x in E["date_quality"]:
        c = lambda k: f"{x[k]['rows']:,} / ₹{x[k]['crore']:,.2f}"  # noqa: E731
        L.append(f"| {x['group']} | {x['rows']:,} | {x['abs_pending_crore']:,.2f} | {c('doc_pre2000')} | {c('doc_after_report')} | {c('due_after_report')} | {c('doc_null')} | {c('due_null')} | {c('credit_null')} |")
    d = E["derivation"]
    L += ["", "## 1. Can a missing due date be reconstructed? (open rows)", "", "Match = stored DUE_DATE equals basis date + SUB_LEDGER_MV.CREDIT_DAYS, among rows that have both a due date and credit days.", ""]
    for title, key in (("By due-date and credit-days state", "by_due_and_credit_state"), ("By DUE_DATE_BASIS", "by_basis"), ("By Dr/Cr", "by_drcr"), ("By party class (comparable rows only)", "by_party_class")):
        L += [f"### {title}", "", "| Group | Open rows | Comparable | = document + credit | = entry + credit |", "|---|---:|---:|---:|---:|"]
        for k, x in d[key].items():
            L.append(f"| {k} | {x['open_rows']:,} | {x['comparable_rows']:,} | {x['eq_document_plus_credit']:,} ({x['share_document']}) | {x['eq_entry_plus_credit']:,} ({x['share_entry']}) |")
        L.append("")
    m = E["missing_due_summary"]
    L += [f"Open rows with NO due date: {m['all_open_rows_without_due_date']:,}, of which TDS class {m['of_which_tds_class']:,}; open credit rows without a due date outside TDS: {m['of_which_cr_not_tds']:,} ({m['of_which_cr_not_tds_with_positive_credit_days']:,} of them have positive credit days; the rest have credit days = 0, which is indistinguishable from 'no terms set').", ""]
    L += ["## Conclusions: all pending finance", "", "- Is `PENDING` the authoritative open balance? pending", "- Which ledgers form the creditor book? pending", "- Can a missing due date be derived from master terms? pending", "- Which date drives ageing / due status? pending"]
    return "\n".join(L) + "\n"


def main(argv: list[str]) -> int:
    run = Path(argv[0])
    E = build(run)
    (run / "PAYABLES_EVIDENCE.json").write_text(json.dumps(E, indent=2, default=str), encoding="utf-8")
    (run / "PAYABLES_EVIDENCE.md").write_text(render(E), encoding="utf-8")
    print(f"wrote {run / 'PAYABLES_EVIDENCE.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
