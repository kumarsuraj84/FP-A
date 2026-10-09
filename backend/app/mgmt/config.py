"""Management P&L configuration: constants, rule defaults and loaders for the git-ignored files in config/mgmt/.
The data files hold real finance numbers and are never committed; tools/mgmt/seed_from_workbook.py (re)generates them."""
from __future__ import annotations

import csv
import json
from decimal import Decimal
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
CONFIG_DIR = REPO / "config" / "mgmt"

ENTITIES = ("SUBCO", "HOLDCO")          # SUBCO = Citykart Stores (CKSPL); HOLDCO = Citykart Ventures (CKVPL-* warehouses, CRPL-HO)
LOCATIONS = ("STORES", "DC", "HO")

# Location type per site kind (documented rule). A site listed in mgmt_site_loc.csv overrides it (e.g. CKSPL-ISD is HO in the MIS).
LOC_OF_KIND = {"STORE": "STORES", "VIRTUAL": "STORES", "EXTERNAL": "STORES",
               "HEAD_OFFICE": "HO", "WAREHOUSE": "DC", "WAREHOUSE_OTHER": "DC", "WAREHOUSE_LEGACY": "DC"}

# management group (finance SK-GRP) -> atomic P&L key
KEY_OF_GROUP = {
    "01-Net Sales": "revenue", "02-Other Income": "other_operating_income",
    "02-COGS(Others)": "material_cost", "02-COGS(Product)": "material_cost", "02-COGS(Correction)": "material_cost",
    "01-Rent": "rent", "02-Employee Cost": "employee_cost", "03-Power and Fuel Expenses": "power_fuel",
    "07-Advertisement And Sales Promotion": "advertisement", "08-Freight Outward": "freight",
    "05-Director remunaration": "director_remuneration", "24-Interest Income": "interest_income", "21-Finance Cost": "finance_cost",
}
for _g in ("09-Insurance", "10-Travelling & Conveyance Expenses", "11-Communication", "12-Repairs and Maintenance-Others", "13-Packing Materials And Expenses",
           "14-Legal and Professional Expenses", "16-Miscellaneous Expenses", "17-Bank Charges", "20-Printing & Stationery"):
    KEY_OF_GROUP[_g] = "other_expenses"
EXCLUDED = "EXCLUDED"                   # management group of ledgers deliberately kept out of the P&L (inventory flow)

# ledgers the engine excludes by default: inventory flow, COGS comes from cogs_store_month
DEFAULT_EXCLUDED_LEDGERS = ("Stock Transfer Received", "Stock Transfer Sent", "Purchase - IGST", "Purchase - SGST+CGST", "Purchase - Local - Non Taxable",
                            "Purchase Return - IGST", "Purchase Return - SGST+CGST", "Sales - Customer")
# unmapped ledger names that look like intercompany charges (informational flag only)
INTERCO_HINTS = ("warehousing support", "trademark license", "strategizing fee", "marketing support", "stewardship", "sales - service")

DEFAULT_RULES = {
    "tolerance_cr": "0.005",
    "subtotal_tolerance_cr": "0.01",
    "cogs_correction": {"pct": "0.01", "from_month": "2026-04"},
    "cogs_bifurcation": {"from_month": "2026-04", "ledgers": ["Discount on Purchases", "Early Payment Discount Apps", "Early Payment Discount GM"]},
    "adv_reclass": {"from_month": "2026-08"},
    "fixed_provisions": [
        {"id": "GRAT-S", "label": "Gratuity provision, stores", "line": "employee_cost", "location_type": "STORES", "amount_cr": "-0.25", "kind": "provision"},
        {"id": "GRAT-HO", "label": "Gratuity provision, HO", "line": "employee_cost", "location_type": "HO", "amount_cr": "-0.05", "kind": "provision"},
        {"id": "AUDIT", "label": "Audit fee provision", "line": "other_expenses", "location_type": "HO", "amount_cr": "-0.05", "kind": "provision"},
        {"id": "CSR", "label": "CSR provision", "line": "other_expenses", "location_type": "HO", "amount_cr": "-0.06", "kind": "provision"},
    ],
    "ho_line_note": "HO cost = HO rows excluding other income, interest income and finance cost; director remuneration stays in HO.",
}


def _read_csv(name: str) -> list[dict]:
    p = CONFIG_DIR / name
    if not p.exists():
        return []
    with p.open(encoding="utf-8-sig", newline="") as f:
        return [{k.strip(): (v or "").strip() for k, v in r.items() if k} for r in csv.DictReader(f)]


def rules() -> dict:
    out = json.loads(json.dumps(DEFAULT_RULES))
    p = CONFIG_DIR / "rules.json"
    if p.exists():
        out.update(json.loads(p.read_text(encoding="utf-8")))
    return out


def ledger_map() -> dict[str, dict]:
    m = {n: {"ledger": n, "mgmt_group": EXCLUDED, "major_group": "", "category": "inventory flow", "location_rule": "excluded", "source": "engine_default",
             "note": "Inventory flow ledger; COGS comes from cogs_store_month."} for n in DEFAULT_EXCLUDED_LEDGERS}
    for r in _read_csv("mgmt_ledger_map.csv"):
        m[r["ledger"]] = r
    return m


def ledger_map_rows() -> list[dict]:
    return list(ledger_map().values())


def site_loc() -> dict[int, dict]:
    return {int(r["site_code"]): r for r in _read_csv("mgmt_site_loc.csv") if r.get("site_code", "").isdigit()}


def adjustments() -> list[dict]:
    rows = _read_csv("adjustments.csv")
    for r in rows:
        r["amount"] = Decimal(r["amount_cr"]) if r.get("amount_cr") else Decimal(0)
        r["entity"] = (r.get("entity") or "SUBCO").upper()
    return rows


def mis_published() -> dict[tuple[str, str], Decimal]:
    return {(r["month"], r["line"]): Decimal(r["value_cr"]) for r in _read_csv("mis_published.csv") if r.get("value_cr")}


def mis_overrides() -> list[dict]:
    rows = _read_csv("mis_overrides.csv")
    for r in rows:
        r["expected"] = Decimal(r["portal_minus_mis_cr"])
    return rows


def files_present() -> dict[str, bool]:
    return {n: (CONFIG_DIR / n).exists() for n in ("mgmt_ledger_map.csv", "adjustments.csv", "mis_published.csv", "mis_overrides.csv", "mgmt_site_loc.csv", "rules.json")}
