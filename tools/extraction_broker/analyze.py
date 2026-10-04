"""
Turns a discovery run (Parquet + manifest) into a structural report: objects found, columns and types, row
estimates, keys and indexes, candidate date / GL / SL / site fields, existing finance views and the cube registry.

Everything is labelled UNVERIFIED: names and types are evidence, not confirmed meaning. Missing statistics stay
"no statistics" and are never shown as zero. No transaction rows are read here: this only reads metadata datasets
and the small registry list.

    python tools/extraction_broker/analyze.py data/inbox/run_YYYYMMDD_NNN
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import manifest as mf  # noqa: E402
from packages import cube_copy_tables  # noqa: E402

CATEGORIES = {
    "p_and_l": r"P_AND_L|PNL|PROFIT",
    "cash_bank": r"CASH|BANK",
    "mop_settlement": r"MOP|SETTLE",
    "creditors_payables": r"CREDITOR|PAYABLE|VENDOR|SUPPLIER|PURCHASE|\bGRC|(^|[_$])PO([_$]|$)|OUTSTAND",
    "ledger_voucher": r"LEDGER|VOUCHER|(^|[_$])(GL|SL)([_$]|$)",
    "cube": r"CUBE|OLAP",
    "cogs": r"COGS",
    "finance_general": r"FIN",
}
FIELD_PATTERNS = {
    "date": r"DATE|(^|_)DT($|_)|TIME|PERIOD|FY|MONTH|YEAR",
    "due_or_document_date": r"DUE|DOC.?DATE|DOCDT|INV.?DATE|VOUCHER.?DATE|BILL.?DATE|POSTING",
    "gl_account": r"(^|_)GL($|_)|LEDGER|ACCOUNT|(^|_)ACC($|_)|COA",
    "sub_ledger_party": r"(^|_)SL($|_)|SUBLEDGER|PARTY|VENDOR|SUPPLIER|CUSTOMER|(^|_)SCODE|PCODE",
    "site_store": r"SITE|STORE|BRANCH|LOCATION|ADMSITE",
    "document_ref": r"VOUCHER|VCH|DOCNO|DOC_NO|INVOICE|BILLNO|GRC|(^|_)PO($|_)|REF",
    "amount": r"AMOUNT|(^|_)AMT($|_)|DEBIT|CREDIT|(^|_)DR($|_)|(^|_)CR($|_)|BALANCE|NET",
}
DATE_TYPES = ("DATE", "TIMESTAMP")
REGISTRY_HIT = re.compile(r"FINREGSITE|FINOTSD|BILLCOLL|SITE_REG|OUTSTAND", re.I)
LABEL = "UNVERIFIED"


def _rows(run: Path, name: str, loadable: set[str]) -> list[dict] | None:
    if name not in loadable:
        return None
    import pyarrow.parquet as pq

    return [{k.upper(): v for k, v in r.items()} for r in pq.read_table(run / f"{name}.parquet").to_pylist()]


def _short(v, n=70):
    s = str(v)
    return s if len(s) <= n else s[: n - 1] + "…"


def analyze(run: Path) -> dict:
    verdict = mf.validate_manifest(run)
    if not verdict.ok:
        raise SystemExit("manifest does not validate; refusing to analyse:\n  " + "\n  ".join(verdict.errors))
    load = set(verdict.loadable)
    man = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    S: dict = {"label": LABEL, "run_id": man["run_id"], "datasets": {}, "caveats": list(verdict.warnings)}
    for d in man["datasets"]:
        S["datasets"][d["dataset"]] = {"status": d["status"], "rows": d["row_count"], "cap": d["row_cap"], "source": d["source_object"]}

    S["scope"] = "MISRETAIL only (the MIS data warehouse). SSRK is live production and out of scope."

    objects = _rows(run, "d01_finance_objects", load) or []
    S["finance_like_objects"] = {
        "total": len(objects),
        "by_owner_type": {f"{o}.{t}": n for (o, t), n in sorted(Counter((r["OWNER"], r["OBJECT_TYPE"]) for r in objects).items())},
        "by_category": {},
    }
    for cat, pat in CATEGORIES.items():
        hits = [f"{r['OWNER']}.{r['OBJECT_NAME']}" for r in objects if re.search(pat, r["OBJECT_NAME"], re.I)]
        S["finance_like_objects"]["by_category"][cat] = {"count": len(hits), "examples": hits[:25]}
    known = [r for r in objects if re.match(r"(T|V)_FINANCE", r["OBJECT_NAME"], re.I)]
    S["known_finance_names"] = sorted(f"{r['OWNER']}.{r['OBJECT_NAME']} ({r['OBJECT_TYPE']})" for r in known)

    stats = _rows(run, "d02_table_stats", load) or []
    S["row_estimates"] = {
        "tables_with_statistics": sum(1 for r in stats if r["NUM_ROWS"] is not None),
        "tables_without_statistics": sum(1 for r in stats if r["NUM_ROWS"] is None),
        "note": "NUM_ROWS comes from optimizer statistics (an estimate as of LAST_ANALYZED). Tables without statistics are NOT zero rows.",
        "largest": [
            {"object": f"{r['OWNER']}.{r['TABLE_NAME']}", "estimated_rows": int(r["NUM_ROWS"]), "last_analyzed": str(r["LAST_ANALYZED"])[:10] if r["LAST_ANALYZED"] else "no statistics"}
            for r in stats
            if r["NUM_ROWS"] is not None
        ][:30],
    }

    cols = _rows(run, "d04_columns", load) or []
    types = Counter(r["DATA_TYPE"] for r in cols)
    S["columns"] = {"total": len(cols), "objects": len({(r["OWNER"], r["TABLE_NAME"]) for r in cols}), "by_type": dict(types.most_common())}

    per_obj: dict[tuple, list[dict]] = defaultdict(list)
    for r in cols:
        per_obj[(r["OWNER"], r["TABLE_NAME"])].append(r)

    # candidate fields per object (name/type evidence only)
    cand: dict[str, dict] = {}
    for (o, t), cs in per_obj.items():
        hit = {}
        for fld, pat in FIELD_PATTERNS.items():
            names = [c["COLUMN_NAME"] for c in cs if re.search(pat, c["COLUMN_NAME"], re.I)]
            if fld == "date":
                names = [c["COLUMN_NAME"] for c in cs if str(c["DATA_TYPE"]).startswith(DATE_TYPES) or re.search(pat, c["COLUMN_NAME"], re.I)]
            if names:
                hit[fld] = names[:12]
        if sum(1 for f in ("date", "gl_account", "sub_ledger_party", "site_store", "amount") if f in hit) >= 3:
            cand[f"{o}.{t}"] = hit
    S["candidate_ledger_like_objects"] = {"label": LABEL, "count": len(cand), "objects": dict(list(sorted(cand.items()))[:60])}
    S["date_columns_by_type"] = {
        "date_or_timestamp_columns": sum(1 for r in cols if str(r["DATA_TYPE"]).startswith(DATE_TYPES)),
        "text_columns_named_like_dates": sum(1 for r in cols if r["DATA_TYPE"] in ("VARCHAR2", "CHAR", "NVARCHAR2") and re.search(r"DATE|(^|_)DT($|_)", r["COLUMN_NAME"], re.I)),
        "note": "A date held in a text column needs explicit parsing; flagged here, not assumed.",
    }

    # keys
    cons = _rows(run, "d07_constraints", load) or []
    cc = _rows(run, "d08_constraint_columns", load) or []
    pk_cols: dict[tuple, list] = defaultdict(list)
    for r in cc:
        if r["CONSTRAINT_TYPE"] == "P":
            pk_cols[(r["OWNER"], r["TABLE_NAME"])].append((r["POSITION"], r["COLUMN_NAME"]))
    tables = {(r["OWNER"], r["TABLE_NAME"]) for r in stats}
    with_pk = {t for t in tables if t in pk_cols}
    idx = _rows(run, "d09_indexes", load) or []
    ucols = _rows(run, "d10_index_columns", load) or []
    unique_idx = {(r["TABLE_OWNER"], r["TABLE_NAME"], r["INDEX_NAME"]) for r in idx if r["UNIQUENESS"] == "UNIQUE"}
    uidx_cols: dict[tuple, list] = defaultdict(list)
    for r in ucols:
        k = (r["TABLE_OWNER"], r["TABLE_NAME"], r["INDEX_NAME"])
        if k in unique_idx:
            uidx_cols[k].append((r["COLUMN_POSITION"], r["COLUMN_NAME"]))
    S["keys"] = {
        "label": LABEL,
        "tables_in_scope": len(tables),
        "tables_with_primary_key": len(with_pk),
        "tables_without_primary_key": len(tables - with_pk),
        "tables_with_unique_index": len({(o, t) for (o, t, _i) in uidx_cols}),
        "primary_keys_of_largest_tables": {
            f"{o}.{t}": [c for _p, c in sorted(pk_cols[(o, t)])]
            for (o, t) in [(r["OWNER"], r["TABLE_NAME"]) for r in stats if r["NUM_ROWS"] is not None][:30]
            if (o, t) in pk_cols
        },
        "note": "Cube copy tables often have no declared key: a missing primary key is a finding, not an error.",
    }

    views = _rows(run, "d03_view_meta", load) or []
    deps = _rows(run, "d11_view_dependencies", load) or []
    dep_by: dict[tuple, list] = defaultdict(list)
    for r in deps:
        dep_by[(r["OWNER"], r["NAME"])].append(f"{r['REFERENCED_OWNER']}.{r['REFERENCED_NAME']}")
    S["finance_views"] = {
        "count": len(views),
        "named_finance": [
            {"view": f"{r['OWNER']}.{r['VIEW_NAME']}", "reads_from": sorted(set(dep_by.get((r["OWNER"], r["VIEW_NAME"]), [])))[:12]}
            for r in views
            if re.match(r"(V|T)_FINANCE|.*FINANCE", r["VIEW_NAME"], re.I)
        ][:80],
    }

    tc = _rows(run, "d05_table_comments", load) or []
    S["documented_objects"] = {"table_comments": len(tc), "column_comments": (S["datasets"].get("d06_column_comments") or {}).get("rows")}

    # cube copies: copy id -> cube name -> fiscal-year date range, read from MISRETAIL's own cube tables
    heads = _rows(run, "d12_cube_copy_headers", load) or []
    probed = cube_copy_tables({"d01_finance_objects": objects, "d04_columns": cols})
    seen = {r["SOURCE_TABLE"] for r in heads}
    copies = [
        {
            "table": r["SOURCE_TABLE"],
            "cube_code": int(r["CUBE_CODE"]) if r["CUBE_CODE"] is not None else None,
            "cube_name": r["CUBENAME"],
            "start_date": str(r["START_DATE"])[:10] if r["START_DATE"] else None,
            "end_date": str(r["END_DATE"])[:10] if r["END_DATE"] else None,
            "report_date": str(r["REPORT_DATE"])[:10] if r["REPORT_DATE"] else None,
        }
        for r in sorted(heads, key=lambda x: (str(x["SOURCE_TABLE"]).split("_")[0], int(str(x["SOURCE_TABLE"]).rsplit("_", 1)[1])))
    ]
    stat_rows = {r["TABLE_NAME"]: r["NUM_ROWS"] for r in stats}
    reg = {
        "label": LABEL,
        "copies_with_data": copies,
        "copies_returning_no_row": sorted(set(probed) - seen),
        "statistics_vs_probe": [
            {"table": t, "optimizer_estimate": stat_rows.get(t), "probe": "has rows" if t in seen else "no row returned"}
            for t in sorted(set(probed))
            if (stat_rows.get(t) in (0, None)) or t not in seen
        ][:40],
        "note": (
            "Evidence only. A mapping stays UNVERIFIED until an operator confirms it (registry-confirm). A copy that returns no "
            "row is empty or mid-refresh; it is NOT proof the cube holds no data. Optimizer NUM_ROWS = 0 is likewise not proof."
        ),
    }
    S["cube_copies"] = reg
    S["not_scanned"] = ["every schema other than MISRETAIL (SSRK is live production: out of scope)", "transaction data of any kind"]
    return S


def render(S: dict) -> str:
    L = [f"# Discovery report · {S['run_id']}  [{S['label']}]", "", "Structure and statistics only. No transaction rows.", ""]
    L += [f"Scope: {S['scope']}", ""]
    f = S["finance_like_objects"]
    L += ["", f"## Finance-like objects (name match, scoped schemas): {f['total']:,}", ""]
    L += [f"- {k}: {v:,}" for k, v in f["by_owner_type"].items()]
    L += ["", "| Category | Objects | Examples |", "|---|---:|---|"]
    for k, v in f["by_category"].items():
        L.append(f"| {k} | {v['count']:,} | {', '.join(v['examples'][:4])} |")
    if S["known_finance_names"]:
        L += ["", f"### Known `T_FINANCE_* / V_FINANCE_*` objects ({len(S['known_finance_names'])})", ""]
        L += [f"- {n}" for n in S["known_finance_names"][:60]]
    r = S["row_estimates"]
    L += ["", "## Row estimates (optimizer statistics)", "", f"- with statistics: {r['tables_with_statistics']:,}; **without statistics: {r['tables_without_statistics']:,}** (not zero rows)", ""]
    L += ["| Object | Est. rows | Last analysed |", "|---|---:|---|"] + [f"| {x['object']} | {x['estimated_rows']:,} | {x['last_analyzed']} |" for x in r["largest"][:25]]
    c = S["columns"]
    L += ["", f"## Columns: {c['total']:,} across {c['objects']:,} objects", "", "- types: " + ", ".join(f"{k} {v:,}" for k, v in list(c["by_type"].items())[:12])]
    d = S["date_columns_by_type"]
    L += [f"- DATE/TIMESTAMP columns: {d['date_or_timestamp_columns']:,}; text columns named like dates: {d['text_columns_named_like_dates']:,}. {d['note']}"]
    k = S["keys"]
    L += ["", "## Keys", "", f"- tables in scope {k['tables_in_scope']:,}: with primary key {k['tables_with_primary_key']:,}, without {k['tables_without_primary_key']:,}; with a unique index {k['tables_with_unique_index']:,}", f"- {k['note']}", ""]
    for t, cols in list(k["primary_keys_of_largest_tables"].items())[:15]:
        L.append(f"- {t}: PK ({', '.join(cols)})")
    cand = S["candidate_ledger_like_objects"]
    L += ["", f"## Candidate ledger-like objects [{cand['label']}]: {cand['count']:,}", "", "(date + GL/account + sub-ledger/party + site + amount candidates by name/type)", ""]
    for name, hit in list(cand["objects"].items())[:25]:
        L.append(f"- **{name}** — " + "; ".join(f"{fld}: {', '.join(v[:4])}" for fld, v in hit.items()))
    fv = S["finance_views"]
    L += ["", f"## Finance views: {fv['count']:,} in scope; named finance: {len(fv['named_finance'])}", ""]
    for v in fv["named_finance"][:30]:
        L.append(f"- {v['view']} ← {', '.join(v['reads_from'][:5]) or 'dependencies not visible'}")
    reg = S["cube_copies"]
    L += ["", f"## Cube copies in MISRETAIL [{reg['label']}]", "", "| Copy table | Cube code | Cube name | From | To | Last refresh |", "|---|---:|---|---|---|---|"]
    for c in reg["copies_with_data"]:
        L.append(f"| {c['table']} | {c['cube_code']} | {c['cube_name']} | {c['start_date']} | {c['end_date']} | {c['report_date']} |")
    L += ["", f"Copies that returned no row (empty or mid-refresh): {len(reg['copies_returning_no_row'])}"]
    L += [f"- {t}" for t in reg["copies_returning_no_row"][:40]]
    if reg["statistics_vs_probe"]:
        L += ["", "Statistics vs probe (a zero estimate is not proof of an empty table):"]
        L += [f"- {x['table']}: estimate {x['optimizer_estimate'] if x['optimizer_estimate'] is not None else 'no statistics'}; probe: {x['probe']}" for x in reg["statistics_vs_probe"][:20]]
    L += ["", reg["note"]]
    L += ["", "## Not scanned in this pass", ""] + [f"- {x}" for x in S["not_scanned"]]
    if S["caveats"]:
        L += ["", "## Caveats", ""] + [f"- {x}" for x in S["caveats"]]
    return "\n".join(L) + "\n"


def main(argv: list[str]) -> int:
    run = Path(argv[0])
    S = analyze(run)
    (run / "discovery_summary.json").write_text(json.dumps(S, indent=2, default=str), encoding="utf-8")
    (run / "DISCOVERY_REPORT.md").write_text(render(S), encoding="utf-8")
    print(f"wrote {run / 'DISCOVERY_REPORT.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
