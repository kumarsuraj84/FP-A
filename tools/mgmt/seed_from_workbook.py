"""Regenerate the management P&L config files in config/mgmt/ from the finance workbooks (read-only, openpyxl read_only).

  python tools/mgmt/seed_from_workbook.py --pl "P & L _New Version _FY27_Aug'26_updated.xlsx" --mis "Citykart MIS Format_Aug'26.xlsx" [--last-month 2026-08] [--gold]

Writes (all git-ignored, real finance numbers): mgmt_ledger_map.csv, mgmt_site_loc.csv, adjustments.csv, mis_published.csv, mis_overrides.csv, and rules.json if absent.
--gold also reads gold_fpa.dim_ledger (read-only) to flag ledgers the gold master leaves unmapped. Needs openpyxl (not a backend dependency): pip install openpyxl.

Workbook -> register: the FILTER column of 'Main Data Sheet' tells the row's origin (STORE_DATA book, VENTURE_DATA second entity, COGS P_/C_ product cost and 1% correction,
COGS Bifurcation, SIS_<month>, Gratuity_*, Audit, CSR, Incentive_HO, Advertisment_Movement Ho to Stores, Salary Move to Director). Amounts: 'Final Balance (In Lakhs)' / 100 = Cr.
Rules (not rows): COGS correction 1% of net sales, COGS bifurcation (DC/HO purchase discounts to stores), advertisement movement from the last workbook month onward.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import sys
from collections import defaultdict
from decimal import Decimal as D
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.mgmt import config as cfg  # noqa: E402

OUT = cfg.CONFIG_DIR
DECISIONS = {   # finance decisions (user-confirmed): ledger -> (group, note)
    "Gratuity": ("02-Employee Cost", "Finance decision: Gratuity is Employee Cost (gold master has Miscellaneous)."),
    "Professional Charges": ("14-Legal and Professional Expenses", "Finance decision: Professional Charges is Legal and Professional (gold master has Employee Cost)."),
    "NOTICE PAY RECOVERY": ("02-Employee Cost", "Finance decision: Employee Cost. The workbook has it under 02-Other Income; immaterial (0.46 lakh)."),
}
MIS_ROWS = {5: "revenue", 6: "other_operating_income", 7: "total_income", 12: "material_cost", 13: "material_margin", 15: "rent", 16: "employee_cost", 17: "power_fuel",
            18: "advertisement", 19: "freight", 20: "other_expenses", 21: "total_store_expenses", 22: "store_ebitda", 24: "dc_cost", 25: "ho_cost", 26: "total_corporate",
            27: "corporate_ebitda", 30: "one_time", 31: "ebitda_post_one_time"}
OVERRIDES = [   # MIS sheet hard-codes: portal (ledger) minus MIS that they explain
    ("2026-05", "other_operating_income", "0.031", "hardcode", "MIS sheet hard-codes other operating income for May; the ledger is higher by about 0.031 Cr."),
    ("2026-06", "other_expenses", "0.036", "hardcode", "MIS sheet hard-codes other expenses for June; the ledger is higher by about 0.036 Cr."),
    ("2026-05", "dc_cost", "-0.026", "hardcode", "MIS sheet hard-codes DC cost for May; the ledger is lower by about 0.026 Cr."),
]


def rows_of(path: str, sheet: str):
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    return list(wb[sheet].iter_rows(values_only=True))


def month_of(v) -> str | None:
    if isinstance(v, (dt.datetime, dt.date)):
        return f"{v.year:04d}-{v.month:02d}"
    return None


def write(name: str, fields: list[str], rows: list[dict]):
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / name).open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"{name}: {len(rows)} rows")


def d4(x) -> str:
    return str(D(str(x)).quantize(D("0.0001")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pl", required=True)
    ap.add_argument("--mis", required=True)
    ap.add_argument("--first-month", default="2026-04")
    ap.add_argument("--last-month", default="2026-08")
    ap.add_argument("--gold", action="store_true")
    a = ap.parse_args()

    data = rows_of(a.pl, "Main Data Sheet")
    head = [str(h).strip() if h is not None else "" for h in data[1]]
    ix = {h: i for i, h in enumerate(head)}
    recs = []
    for r in data[2:]:
        if r[ix["SK-GRP"]] is None or r[ix["FY-YEAR"]] is None:
            continue
        m = month_of(r[ix["EXP-MTH"]])
        if m is None or not (a.first_month <= m <= a.last_month):
            continue
        recs.append({"filter": r[ix["FILTER"]] or "", "ledger": r[ix["LEDGER"]], "grp": r[ix["SK-GRP"]], "maj": r[ix["SK-MAJ-GRP"]] or "", "cat": r[ix["Category"]] or "",
                     "loc": r[ix["LOCATION FILTER"]], "month": m, "cr": D(str(r[ix["Final Balance (In Lakhs)"]] or 0)) / 100})
    print("workbook rows in window:", len(recs))

    # ---- ledger map
    led: dict[str, dict] = {}
    for r in recs:
        if not r["ledger"]:
            continue
        e = led.setdefault(r["ledger"], {"ledger": r["ledger"], "mgmt_group": r["grp"], "major_group": r["maj"], "category": r["cat"], "location_rule": "by_site", "source": "workbook", "note": ""})
        if not e["category"] and r["cat"]:
            e["category"] = r["cat"]
    for l, (g, note) in DECISIONS.items():
        e = led.setdefault(l, {"ledger": l, "major_group": "", "category": "", "location_rule": "by_site"})
        e.update(mgmt_group=g, source="decision", note=note)
    gold_unmapped: set[str] = set()
    if a.gold:
        from app.gold import db as gold
        with gold.GoldDb(gold.database_url()).session() as c:
            have = {r["glname"]: r["is_mapped"] for r in c.execute("SELECT glname, bool_or(is_mapped) AS is_mapped FROM gold_fpa.dim_ledger GROUP BY 1").fetchall()}
        for l, e in led.items():
            if l not in have:
                e["source"] += ";not_in_gold_master"
                e["note"] = (e["note"] + " Ledger not in gold dim_ledger.").strip()
            elif not have[l]:
                gold_unmapped.add(l)
                e["source"] += ";gold_unmapped"
                e["note"] = (e["note"] + " Gold dim_ledger leaves this ledger UNMAPPED; management group applied.").strip()
        print("gold-unmapped workbook ledgers:", len(gold_unmapped))
    lmap = [led[k] for k in sorted(led)] + [{"ledger": n, "mgmt_group": cfg.EXCLUDED, "major_group": "", "category": "inventory flow", "location_rule": "excluded", "source": "engine_default",
                                              "note": "Inventory flow ledger; COGS comes from cogs_store_month."} for n in cfg.DEFAULT_EXCLUDED_LEDGERS]
    write("mgmt_ledger_map.csv", ["ledger", "mgmt_group", "major_group", "category", "location_rule", "source", "note"], lmap)
    write("mgmt_site_loc.csv", ["site_code", "short_name", "location_type", "reason"],
          [{"site_code": 312, "short_name": "CKSPL-ISD", "location_type": "HO", "reason": "The MIS treats CKSPL-ISD (a virtual site in gold) as HO."}])

    # ---- adjustments register
    def line_of(r):
        g = cfg.KEY_OF_GROUP.get(led[r["ledger"]]["mgmt_group"] if r["ledger"] in led else r["grp"])
        return g or cfg.KEY_OF_GROUP.get(r["grp"])
    out: list[dict] = []
    agg: dict[tuple, D] = defaultdict(D)
    for r in recs:
        f = r["filter"]
        if f in ("STORE_DATA",) or f.startswith("COGS P_") or f.startswith("COGS C_") or f == "COGS Bifurcation":
            continue
        line = line_of(r)
        if f == "VENTURE_DATA":
            agg[("VENT", r["month"], r["loc"], line)] += r["cr"]
        elif f.startswith("SIS_"):
            agg[("SIS", r["month"], "STORES", "other_operating_income")] += r["cr"]
        elif f.startswith("Advertisment_Movement"):
            if r["month"] < a.last_month:
                agg[("ADVMOVE", r["month"], r["loc"], "advertisement")] += r["cr"]
        else:
            agg[(f, r["month"], r["loc"], line)] += r["cr"]
    meta = {"Gratuity_Stores": ("GRAT-S", "provision", "fixed monthly provision, 25 lakh, allocated to stores pro rata to net sales", "confirmed"),
            "Gratuity_HO": ("GRAT-HO", "provision", "fixed monthly provision, 5 lakh", "confirmed"),
            "Audit": ("AUDIT", "provision", "fixed monthly provision, 5 lakh", "confirmed"),
            "CSR": ("CSR", "provision", "fixed monthly provision, 6 lakh", "confirmed"),
            "Incentive_HO": ("INCENT-HO", "provision", "quarterly HO incentive provision (workbook amounts)", "confirmed"),
            "Salary Move to Director": ("SALDIR", "reclass", "salary moved to director remuneration inside HO", "confirmed"),
            "ADVMOVE": ("ADVMOVE", "reclass", "advertisement movement HO/DC to stores, explicit workbook amounts (from the last workbook month: RULE-ADVMOVE)", "confirmed"),
            "SIS": ("SIS", "income_adjustment", "true_up:Business Auxiliary Service", "confirmed"),
            "VENT": ("VENT", "stopgap_entity", "stop-gap: Citykart Ventures cost from the workbook until gold carries the entity", "stopgap")}
    notes = {"SIS": "SIS income per finance. Books carry it as Business Auxiliary Service at state virtual sites; the adjustment is the finance figure less the booked amount.",
             "VENT": "HoldCo (Citykart Ventures) from VENTURE_DATA; interest income and finance cost are below EBITDA (informational).",
             "ADVMOVE": "Workbook rows; the June row over-credits HO by about 0.10 Cr against the HO book (workbook quirk, finance to confirm)."}
    for (kind, m, loc, line), v in sorted(agg.items(), key=lambda kv: (kv[0][1], kv[0][0], kv[0][2] or "", kv[0][3] or "")):
        if abs(v) < D("0.00005") or line is None:
            continue
        pre, k, rule, status = meta[kind]
        out.append({"id": f"{pre}-{m}-{loc}-{line}" if kind in ("VENT", "SALDIR", "ADVMOVE") else f"{pre}-{m}-{loc}", "month": m, "mis_line": line, "location_type": loc, "amount_cr": d4(v),
                    "kind": k, "rule": rule, "owner": "Finance", "status": status, "source": "workbook Main Data Sheet FILTER=" + (kind if kind in meta and kind in ("SIS", "VENT", "ADVMOVE") else kind),
                    "note": notes.get(kind, ""), "entity": "HOLDCO" if kind == "VENT" else "SUBCO", "counterparty": ""})
    mis = rows_of(a.mis, "P&L")
    hdr = mis[3]
    cols = {c: month_of(v) for c, v in enumerate(hdr) if month_of(v) and a.first_month <= month_of(v) <= a.last_month}
    cols = {c: m for c, m in cols.items() if c >= 30}      # monthly block (the quarterly / annual blocks repeat the dates further right)
    first_cols = {}
    for c, m in sorted(cols.items()):
        first_cols.setdefault(m, c)
    pub = []
    for ri, key in MIS_ROWS.items():
        for m, c in first_cols.items():
            v = mis[ri][c] if ri < len(mis) and c < len(mis[ri]) else None
            if isinstance(v, (int, float)):
                pub.append({"month": m, "line": key, "value_cr": str(D(repr(v)).quantize(D("0.000001")))})
    ot = [p for p in pub if p["line"] == "one_time" and D(p["value_cr"]) != 0]
    for p in ot:
        out.append({"id": f"ONETIME-{p['month']}", "month": p["month"], "mis_line": "one_time", "location_type": "HO", "amount_cr": d4(p["value_cr"]), "kind": "one_time", "rule": "shown below corporate EBITDA, excluded from HO cost",
                    "owner": "Finance", "status": "confirmed", "source": "MIS P&L row: Increase in Authorised Share Capital", "note": "Increase in Authorised Share Capital", "entity": "SUBCO", "counterparty": ""})
    write("adjustments.csv", ["id", "month", "mis_line", "location_type", "amount_cr", "kind", "rule", "owner", "status", "source", "note", "entity", "counterparty"], out)
    write("mis_published.csv", ["month", "line", "value_cr"], [p for p in pub if p["line"] != "one_time" or D(p["value_cr"]) != 0])
    write("mis_overrides.csv", ["month", "line", "portal_minus_mis_cr", "category", "reason"],
          [{"month": m, "line": l, "portal_minus_mis_cr": v, "category": c, "reason": why} for m, l, v, c, why in OVERRIDES])
    if not (OUT / "rules.json").exists():
        (OUT / "rules.json").write_text(json.dumps({k: cfg.DEFAULT_RULES[k] for k in ("tolerance_cr", "subtotal_tolerance_cr", "cogs_correction", "cogs_bifurcation", "adv_reclass", "fixed_provisions")}, indent=2), encoding="utf-8")
        print("rules.json written")


if __name__ == "__main__":
    main()
