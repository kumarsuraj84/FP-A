"""Management P&L configuration: constants, rule defaults and loaders for the git-ignored files in config/mgmt/.
The data files hold real finance numbers and are never committed; tools/mgmt/seed_from_workbook.py (re)generates them."""
from __future__ import annotations

import csv
import json
import os
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date
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


_force_source: ContextVar = ContextVar("mapping_force_source", default=None)
_overlay: ContextVar = ContextVar("mapping_overlay", default=None)


def mapping_source() -> str:
    """FPA_MAPPING_SOURCE: csv (default, the legacy files) or app (the governed, versioned, effective-dated rules in fpa_app). A deliberate cut-over, never a silent mix.
    A request-scoped override exists only for validation and impact previews."""
    f = _force_source.get()
    if f in ("csv", "app"):
        return f
    v = os.environ.get("FPA_MAPPING_SOURCE", "csv").lower()
    return v if v in ("csv", "app") else "csv"


@contextmanager
def forced(source: str | None = None, overlay: dict | None = None):
    """Run a block with another mapping source and/or one proposed rule laid over the mapping (validation and previews). Request-scoped (a ContextVar), never global."""
    a, b = _force_source.set(source), _overlay.set(overlay)
    try:
        yield
    finally:
        _force_source.reset(a)
        _overlay.reset(b)


def cache_token() -> tuple:
    """Part of every cache key that depends on the mapping, so a validation or preview never reads or writes the normal cache entry."""
    o = _overlay.get()
    return (mapping_source(), (o["domain"], o["source_key"], o["mapped_value"], str(o["effective_from"])) if o else None)


def apply_overlay(domain: str, month: str | None, out: dict) -> dict:
    o = _overlay.get()
    if o and o["domain"] == domain and o["effective_from"] <= _first(month):
        out = dict(out)
        a = o.get("attrs") or {}
        if domain == "LEDGER_GROUP":
            out[o["source_key"]] = {"ledger": o["source_key"], "mgmt_group": o["mapped_value"], "major_group": a.get("major_group", ""), "category": a.get("category", ""),
                                    "location_rule": a.get("location_rule", ""), "source": "proposed rule", "note": a.get("note", "")}
        elif o["source_key"].isdigit():
            out[int(o["source_key"])] = {"site_code": o["source_key"], "short_name": a.get("short_name", ""), "location_type": o["mapped_value"], "reason": "proposed rule"}
    return out


_rules_cache: dict = {"t": 0.0, "rows": []}
RULES_TTL = 30


def clear_mapping_cache() -> None:
    _rules_cache["t"] = 0.0


def app_rules() -> list[dict]:
    """ACTIVE and RETIRED mapping rules of the app database (cached for RULES_TTL seconds). Raises when the app database cannot be read: an app-sourced mapping must never fall
    back silently to something else."""
    if time.time() - _rules_cache["t"] < RULES_TTL:
        return _rules_cache["rows"]
    from ..appdb.conn import app_connection
    with app_connection() as c:
        rows = c.execute("SELECT domain, source_key, mapped_value, attrs, effective_from, effective_to, version FROM mapping_rule WHERE status IN ('ACTIVE', 'RETIRED') ORDER BY version").fetchall()
    _rules_cache.update(t=time.time(), rows=rows)
    return rows


def _first(month: str | None) -> date:
    if month:
        return date(int(month[:4]), int(month[5:7]), 1)
    t = date.today()
    return date(t.year, t.month, 1)


def effective(rules: list[dict], domain: str, month: str | None) -> dict[str, dict]:
    """{source_key: rule} in force in `month` (default: this month). The highest version wins when two overlap."""
    m = _first(month)
    out: dict[str, dict] = {}
    for r in rules:
        if r["domain"] == domain and r["effective_from"] <= m and (r["effective_to"] is None or r["effective_to"] >= m):
            out[r["source_key"]] = r
    return out


def ledger_map(month: str | None = None) -> dict[str, dict]:
    """ledger -> mapping row. From the legacy CSV, or (FPA_MAPPING_SOURCE=app) from the rules in force in `month`."""
    if mapping_source() == "app":
        m = {n: {"ledger": n, "mgmt_group": EXCLUDED, "major_group": "", "category": "inventory flow", "location_rule": "excluded", "source": "engine_default",
                 "note": "Inventory flow ledger; COGS comes from cogs_store_month."} for n in DEFAULT_EXCLUDED_LEDGERS}
        for k, r in effective(app_rules(), "LEDGER_GROUP", month).items():
            a = r["attrs"] or {}
            m[k] = {"ledger": k, "mgmt_group": r["mapped_value"], "major_group": a.get("major_group", ""), "category": a.get("category", ""), "location_rule": a.get("location_rule", ""),
                    "source": f"mapping v{r['version']}", "note": a.get("note", "")}
        return apply_overlay("LEDGER_GROUP", month, m)
    return apply_overlay("LEDGER_GROUP", month, _ledger_map_csv())


def site_codes_ever() -> list[int]:
    """Every site code any mapping rule names, in any period (the SQL needs them all; the month decides the location type)."""
    codes = {int(r["source_key"]) for r in app_rules() if r["domain"] == "SITE_LOCATION" and r["source_key"].isdigit()} if mapping_source() == "app" else set(site_loc())
    o = _overlay.get()
    if o and o["domain"] == "SITE_LOCATION" and o["source_key"].isdigit():
        codes.add(int(o["source_key"]))
    return sorted(codes)


def ledger_map_provider():
    """What the engine takes as `lmap`: the plain dict for the CSV, or a function month -> dict (rules by effective date) for the app source."""
    return (lambda month: ledger_map(month)) if mapping_source() == "app" else ledger_map()


def site_loc_provider():
    return (lambda month: site_loc(month)) if mapping_source() == "app" else site_loc()


def resolve(provider, month: str | None):
    """A provider (dict or function) at a month."""
    return provider(month) if callable(provider) else provider


def _ledger_map_csv() -> dict[str, dict]:
    m = {n: {"ledger": n, "mgmt_group": EXCLUDED, "major_group": "", "category": "inventory flow", "location_rule": "excluded", "source": "engine_default",
             "note": "Inventory flow ledger; COGS comes from cogs_store_month."} for n in DEFAULT_EXCLUDED_LEDGERS}
    for r in _read_csv("mgmt_ledger_map.csv"):
        m[r["ledger"]] = r
    return m


def ledger_map_rows() -> list[dict]:
    return list(ledger_map().values())


def site_loc(month: str | None = None) -> dict[int, dict]:
    if mapping_source() == "app":
        base = {int(k): {"site_code": k, "short_name": (r["attrs"] or {}).get("short_name", ""), "location_type": r["mapped_value"], "reason": (r["attrs"] or {}).get("note", "")}
                for k, r in effective(app_rules(), "SITE_LOCATION", month).items() if k.isdigit()}
    else:
        base = {int(r["site_code"]): r for r in _read_csv("mgmt_site_loc.csv") if r.get("site_code", "").isdigit()}
    return apply_overlay("SITE_LOCATION", month, base)


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
