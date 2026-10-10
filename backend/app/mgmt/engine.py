"""Management (MIS) P&L engine. All money is Decimal in INR Cr (costs negative, as the MIS shows them).

Layers: BOOK = gold_fpa as posted (ledger -> management group via the mgmt map, location type from the site kind); ADJUSTMENT = provisions, manual journals, reclasses,
the Citykart Ventures stop-gap and eliminations from the adjustments register and the rules in config. total = book + adjustment.

Location type rule: site kind STORE, VIRTUAL, EXTERNAL -> STORES; HEAD_OFFICE -> HO; WAREHOUSE, WAREHOUSE_OTHER, WAREHOUSE_LEGACY -> DC; a site in mgmt_site_loc.csv overrides it.
Entity: SUBCO (Citykart Stores) unless the site is a CKVPL-* / CRPL-* site (HOLDCO, Citykart Ventures), or gold carries an `entity` column, which then wins.
"""
from __future__ import annotations

import time
from collections import defaultdict
from datetime import date
from decimal import Decimal as D

from . import config as cfg

ZERO = D(0)
CR = D(10_000_000)
Q4 = D("0.0001")
STORE_EXP = ("rent", "employee_cost", "power_fuel", "advertisement", "freight", "other_expenses")
BELOW = ("interest_income", "finance_cost")

# (key, label, kind, formula) - formula: ("atom",) | ("sum", [keys]) | ("pct", num, den)
LINES = [
    ("revenue", "Revenue from operations", "value", ("atom",)),
    ("other_operating_income", "Other operating income", "value", ("atom",)),
    ("total_income", "Total income", "subtotal", ("sum", ["revenue", "other_operating_income"])),
    ("material_cost", "Material cost", "value", ("atom",)),
    ("material_margin", "Material margin", "subtotal", ("sum", ["total_income", "material_cost"])),
    ("rent", "Rent", "value", ("atom",)),
    ("employee_cost", "Employee cost", "value", ("atom",)),
    ("power_fuel", "Power and fuel", "value", ("atom",)),
    ("advertisement", "Advertisement and sales promotion", "value", ("atom",)),
    ("freight", "Freight forwarding", "value", ("atom",)),
    ("other_expenses", "Other expenses", "value", ("atom",)),
    ("total_store_expenses", "Total store expenses", "subtotal", ("sum", list(STORE_EXP))),
    ("store_ebitda", "Store EBITDA", "subtotal", ("sum", ["material_margin", "total_store_expenses"])),
    ("dc_cost", "DC cost", "value", ("atom",)),
    ("ho_cost", "HO cost", "value", ("atom",)),
    ("total_corporate", "Total corporate cost", "subtotal", ("sum", ["dc_cost", "ho_cost"])),
    ("corporate_ebitda", "Corporate EBITDA", "subtotal", ("sum", ["store_ebitda", "total_corporate"])),
    ("one_time", "One-time expense", "value", ("atom",)),
    ("ebitda_post_one_time", "EBITDA post one-time items", "subtotal", ("sum", ["corporate_ebitda", "one_time"])),
    ("interest_income", "Interest income", "value", ("atom",)),
    ("finance_cost", "Finance cost", "value", ("atom",)),
]
LABEL = {k: l for k, l, _, _ in LINES}
SECTION = {k: ("below_ebitda" if k in BELOW or k in ("one_time", "ebitda_post_one_time") else "ebitda") for k, *_ in LINES}
PCT_KEYS = [k for k, *_ in LINES if k not in ("total_income", *BELOW)]
COMPONENTS = {k: f[1] for k, _, _, f in LINES if f[0] == "sum"}


def q4(x: D) -> D:
    return x.quantize(Q4)


def month_list(lo: str, hi: str) -> list[str]:
    y, m = int(lo[:4]), int(lo[5:7])
    out = []
    while f"{y:04d}-{m:02d}" <= hi:
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def line_targets(loc: str, key: str) -> str | None:
    """The P&L line an atomic (location, key) amount lands in; None = not part of the MIS P&L (e.g. revenue outside the stores)."""
    if key in ("other_operating_income", "interest_income", "finance_cost", "one_time"):
        return key
    if key == "revenue":
        return "revenue" if loc == "STORES" else None
    if loc == "STORES":
        return "other_expenses" if key == "director_remuneration" else key
    return "dc_cost" if loc == "DC" else "ho_cost"


# --------------------------------------------------------------------------- book

class Book:
    def __init__(self):
        self.cells: dict[tuple, D] = defaultdict(D)            # (month, entity, loc, key) -> Cr
        self.by_ledger: dict[tuple, D] = defaultdict(D)        # (month, entity, loc, ledger) -> Cr   (mapped ledgers only)
        self.sales: dict[str, D] = defaultdict(D)              # month -> net sales ex GST of STORE sites (cogs table)
        self.cogs: dict[str, D] = defaultdict(D)
        self.exceptions: dict[str, dict] = {}                  # ledger -> {amount, months, reason}
        self.excluded: dict[str, D] = defaultdict(D)
        self.unclassified = ZERO
        self.non_store_revenue = ZERO
        self.group_source: dict[str, str] = {}
        self.holdco_months: set[str] = set()


def resolve_group(glname: str, fin_group: str | None, is_mapped: bool, lmap: dict) -> tuple[str | None, str]:
    e = lmap.get(glname)
    if e and e.get("mgmt_group"):
        return e["mgmt_group"], "map"
    if is_mapped and fin_group and fin_group != "UNMAPPED":
        return fin_group, "gold"
    return None, "unmapped"


def build_book(rows: list[dict], cogs_rows: list[dict], lmap: dict, site_loc: dict) -> Book:
    """rows: month 'YYYY-MM', site_kind, site_code (set only for sites in site_loc, else None), entity, glname, fin_group, is_mapped, pe (rupees).
    cogs_rows: month, ns, cogs (rupees) for STORE sites."""
    b = Book()
    for r in rows:
        amt = D(str(r["pe"])) / CR
        m, ent, glname = r["month"], r.get("entity") or "SUBCO", r["glname"]
        grp, src = resolve_group(glname, r.get("fin_group"), bool(r.get("is_mapped")), lmap)
        if grp == cfg.EXCLUDED:
            b.excluded[glname] += amt
            continue
        key = cfg.KEY_OF_GROUP.get(grp) if grp else None
        if key is None:
            ex = b.exceptions.setdefault(glname, {"ledger": glname, "amount_cr": ZERO, "months": set(), "reason": "no management group" if grp is None else f"group {grp} is not a P&L group"})
            ex["amount_cr"] += amt
            ex["months"].add(m)
            continue
        sc = r.get("site_code")
        loc = site_loc[sc]["location_type"] if sc in site_loc else cfg.LOC_OF_KIND.get(r["site_kind"])
        if loc is None:
            b.unclassified += amt
            continue
        if key == "revenue" and loc != "STORES":
            b.non_store_revenue += amt
            continue
        b.cells[(m, ent, loc, key)] += amt
        b.by_ledger[(m, ent, loc, glname)] += amt
        b.group_source[glname] = src
        if ent == "HOLDCO":
            b.holdco_months.add(m)
    for c in cogs_rows:
        b.sales[c["month"]] += D(str(c["ns"])) / CR
        b.cogs[c["month"]] += D(str(c["cogs"])) / CR
    for m, v in b.cogs.items():
        b.cells[(m, "SUBCO", "STORES", "material_cost")] += -v      # product cost from the COGS table
    return b


# --------------------------------------------------------------------------- adjustments

def _item(id_, m, ent, loc, line, amt, kind, status, rule, owner="", source="", note="", origin="register", group=None):
    return {"id": id_, "month": m, "entity": ent, "location_type": loc, "mis_line": line, "amount_cr": amt, "kind": kind, "status": status, "rule": rule,
            "owner": owner, "source": source, "note": note, "origin": origin, "provisional": status in ("proposed", "stopgap"), "group": group or id_.split("-")[0]}


def evaluate_adjustments(book: Book, months: list[str], register: list[dict], rules: dict, include_proposed: bool = True, last_month: str | None = None) -> list[dict]:
    """Register rows + rule rows evaluated against the book, for the given months. Returns items {id, month, entity, location_type, mis_line, amount_cr, ...}."""
    items: list[dict] = []
    mset = set(months)
    for r in register:
        m = r["month"]
        if m not in mset:
            continue
        if r["status"] == "in_books":                      # memo: the books already carry it
            continue
        if r["status"] == "proposed" and not include_proposed:
            continue
        if r["entity"] == "HOLDCO" and r["kind"] == "stopgap_entity" and m in book.holdco_months:
            continue                                        # gold carries Ventures for this month: it wins over the workbook stop-gap
        amt, note = r["amount"], r.get("note", "")
        rule = r.get("rule", "")
        if rule.startswith("true_up:"):                     # management figure replaces what the books carry for that ledger
            ledger = rule.split(":", 1)[1]
            booked = sum((v for (mm, e, lo, lg), v in book.by_ledger.items() if mm == m and lg == ledger and e == r["entity"]), ZERO)
            note = f"{note} Management figure {q4(amt)} less booked {q4(booked)} ({ledger}).".strip()
            amt = amt - booked
        it = _item(r["id"], m, r["entity"], r["location_type"], r["mis_line"], amt, r["kind"], r["status"], rule, r.get("owner", ""), r.get("source", ""), note)
        it["counterparty"] = r.get("counterparty", "")
        it["counterparty_entity"] = r.get("counterparty_entity", "")
        items.append(it)
        if r["kind"] == "one_time" and r["location_type"] in ("HO", "DC"):   # a one-time item is excluded from HO/DC cost
            items.append(_item(r["id"] + "-ADDBACK", m, r["entity"], r["location_type"], "other_expenses", -amt, "reclass", r["status"], "one-time item excluded from cost",
                               r.get("owner", ""), r.get("source", ""), "Adds the one-time item back to the cost line it was booked in.", group=r["id"].split("-")[0]))

    cc = rules["cogs_correction"]
    for m in months:
        if m >= cc["from_month"]:
            rev = book.cells.get((m, "SUBCO", "STORES", "revenue"), ZERO)
            items.append(_item("RULE-COGSCORR-" + m, m, "SUBCO", "STORES", "material_cost", -D(cc["pct"]) * rev, "provision", "confirmed",
                               f"{D(cc['pct']) * 100:.1f}% of net sales, every month (the only shrinkage provision)", "Finance", "rule", "Computed from the month's store revenue.", "rule", "RULE"))
    bf = rules["cogs_bifurcation"]
    for m in months:
        if m >= bf["from_month"]:
            tot = ZERO
            for loc in ("DC", "HO"):
                v = sum((x for (mm, e, lo, lg), x in book.by_ledger.items() if mm == m and lo == loc and lg in bf["ledgers"] and e == "SUBCO"), ZERO)
                if v:
                    items.append(_item(f"RULE-COGSBIF-{loc}-{m}", m, "SUBCO", loc, "material_cost", -v, "reclass", "confirmed", "purchase discounts booked at DC/HO are charged to stores", "Finance", "rule",
                                       "Reclass of purchase / early-payment discounts from DC and HO to stores material cost.", "rule", "RULE"))
                    tot += v
            if tot:
                items.append(_item("RULE-COGSBIF-STORES-" + m, m, "SUBCO", "STORES", "material_cost", tot, "reclass", "confirmed", "purchase discounts booked at DC/HO are charged to stores", "Finance", "rule",
                                   "Counter entry of the COGS bifurcation (stores side).", "rule", "RULE"))
    ar = rules["adv_reclass"]
    for m in months:
        if m >= ar["from_month"]:
            tot = ZERO
            for loc in ("DC", "HO"):
                v = book.cells.get((m, "SUBCO", loc, "advertisement"), ZERO)
                if v:
                    items.append(_item(f"RULE-ADVMOVE-{loc}-{m}", m, "SUBCO", loc, "advertisement", -v, "reclass", "confirmed", "all HO and DC advertisement is charged to stores", "Finance", "rule",
                                       "Advertisement movement HO/DC to stores.", "rule", "RULE"))
                    tot += v
            if tot:
                items.append(_item("RULE-ADVMOVE-STORES-" + m, m, "SUBCO", "STORES", "advertisement", tot, "reclass", "confirmed", "all HO and DC advertisement is charged to stores", "Finance", "rule",
                                   "Counter entry of the advertisement movement (stores side).", "rule", "RULE"))
    # fixed monthly provisions continue after the last month the register covers (proposed, provisional)
    prov_months = [r["month"] for r in register if r["kind"] == "provision" and r.get("rule", "").startswith("fixed")]
    last_reg = max(prov_months) if prov_months else None
    if include_proposed and last_reg:
        for m in months:
            if m > last_reg and (last_month is None or m <= last_month):
                for p in rules["fixed_provisions"]:
                    items.append(_item(f"PROV-{p['id']}-{m}", m, "SUBCO", p["location_type"], p["line"], D(p["amount_cr"]), p["kind"], "proposed", "fixed monthly provision continued by rule",
                                       "Finance", "rule", p["label"] + " continued after the last month in the register.", "rule", "PROV"))
    return items


# --------------------------------------------------------------------------- P&L

def compute_pnl(book: Book, items: list[dict], months: list[str], entity: str = "consolidated", reclass: list[dict] | None = None) -> dict:
    """-> {lines: [...], atoms: {(month, line): {book, reclass, adj}}, detail}.  `reclass` = active line corrections (corrections/overlay.py): each moves an existing book
    amount between management groups and/or months, so every item posts +x and -x and the reclass layer nets to zero over all lines and months."""
    ent_ok = (lambda e: True) if entity == "consolidated" else (lambda e: e == entity.upper())
    atoms: dict[tuple, dict] = defaultdict(lambda: {"book": ZERO, "adj": ZERO, "reclass": ZERO})
    detail: dict[tuple, dict] = defaultdict(lambda: {"book": ZERO, "adj": ZERO})
    mset = set(months)
    for (m, e, loc, key), v in book.cells.items():
        if m in mset and ent_ok(e):
            ln = line_targets(loc, key)
            if ln:
                atoms[(m, ln)]["book"] += v
                if ln in ("dc_cost", "ho_cost"):
                    detail[(m, ln, key)]["book"] += v
    for rc in reclass or []:
        if not ent_ok(rc["entity"]):
            continue
        for m, key, sign in ((rc["month_from"], rc["key_from"], -1), (rc["month_to"], rc["key_to"], 1)):
            ln = line_targets(rc["location_type"], key)
            if ln and m in mset:
                atoms[(m, ln)]["reclass"] += sign * rc["amount_cr"]
    for it in items:
        if it["month"] in mset and ent_ok(it["entity"]):
            if it["kind"] == "elimination" and entity != "consolidated":
                continue
            ln = line_targets(it["location_type"], it["mis_line"])
            if ln:
                atoms[(it["month"], ln)]["adj"] += it["amount_cr"]
                if ln in ("dc_cost", "ho_cost"):
                    detail[(it["month"], ln, it["mis_line"])]["adj"] += it["amount_cr"]
    return {"atoms": atoms, "detail": detail}


def _layer_values(atoms, month: str, layer: str) -> dict[str, D]:
    v: dict[str, D] = {}
    for key, _, kind, f in LINES:
        if f[0] == "atom":
            v[key] = atoms[(month, key)][layer] if (month, key) in atoms else ZERO
        elif f[0] == "sum":
            v[key] = sum((v[k] for k in f[1]), ZERO)
    return v


def shape_lines(calc: dict, months: list[str]) -> list[dict]:
    atoms = calc["atoms"]
    per = {m: {"book": _layer_values(atoms, m, "book"), "adj": _layer_values(atoms, m, "adj"), "rc": _layer_values(atoms, m, "reclass")} for m in months}
    # total over the window: sum the atoms, then derive (so subtotals and percentages are exact)
    tot_atoms = defaultdict(lambda: {"book": ZERO, "adj": ZERO, "reclass": ZERO})
    for (m, ln), c in atoms.items():
        if m in per:
            tot_atoms[("*", ln)]["book"] += c["book"]
            tot_atoms[("*", ln)]["adj"] += c["adj"]
            tot_atoms[("*", ln)]["reclass"] += c["reclass"]
    tot = {"book": _layer_values(tot_atoms, "*", "book"), "adj": _layer_values(tot_atoms, "*", "adj"), "rc": _layer_values(tot_atoms, "*", "reclass")}

    def cell(pair, key):
        """Management Total = Book + Reclass + Adjustment, on every line. `reclass` is the net-zero movement of active corrections."""
        return {"book": q4(pair["book"][key]), "reclass": q4(pair["rc"][key]), "adjustment": q4(pair["adj"][key]), "total": q4(pair["book"][key] + pair["rc"][key] + pair["adj"][key])}

    def pcell(pair, key):    # percentage points of total income; adjustment = total less book
        bi, ti = pair["book"]["total_income"], pair["book"]["total_income"] + pair["rc"]["total_income"] + pair["adj"]["total_income"]
        b = pair["book"][key] / bi * 100 if bi else ZERO
        t = (pair["book"][key] + pair["rc"][key] + pair["adj"][key]) / ti * 100 if ti else ZERO
        return {"book": q4(b), "adjustment": q4(t - b), "total": q4(t)}
    out = [{"key": key, "label": label, "kind": kind, "section": SECTION[key], "values": {m: cell(per[m], key) for m in months}, "total": cell(tot, key)} for key, label, kind, _ in LINES]
    for key in PCT_KEYS:
        out.append({"key": "pct_" + key, "label": LABEL[key] + " % of total income", "kind": "pct", "section": SECTION[key], "values": {m: pcell(per[m], key) for m in months}, "total": pcell(tot, key)})
    return out


def line_totals(lines: list[dict], month: str) -> dict[str, D]:
    return {ln["key"]: ln["values"][month]["total"] for ln in lines}


# --------------------------------------------------------------------------- reconciliation

def expected_variance(line: str, month: str, overrides: list[dict]) -> tuple[D, list[str]]:
    """Portal minus MIS that the documented hard-coded overrides explain, summed through subtotal components."""
    if line in COMPONENTS:
        tot, why = ZERO, []
        for c in COMPONENTS[line]:
            v, w = expected_variance(c, month, overrides)
            tot += v
            why += w
        return tot, why
    hits = [o for o in overrides if o["month"] == month and o["line"] == line]
    return sum((o["expected"] for o in hits), ZERO), [o["reason"] for o in hits]


def reconcile(lines: list[dict], months: list[str], published: dict, overrides: list[dict], rules: dict) -> dict:
    tol, tol_sub = D(rules["tolerance_cr"]), D(rules["subtotal_tolerance_cr"])
    kind = {ln["key"]: ln["kind"] for ln in lines}
    cells, mstat = [], []
    for m in months:
        mine = line_totals(lines, m)
        untied = []
        have = False
        for key, label, k, _ in LINES:
            if (m, key) not in published:
                continue
            have = True
            mis, portal = published[(m, key)], mine[key]
            var = portal - mis
            t = tol_sub if k == "subtotal" else tol
            exp, why = expected_variance(key, m, overrides)
            tied = abs(var) <= t
            explained = (not tied) and abs(var - exp) <= t and exp != 0
            cells.append({"month": m, "line": key, "label": label, "mis": q4(mis), "portal": q4(portal), "variance": q4(var), "tied": tied, "explained": explained,
                          "explained_by": why if (explained or (exp != 0 and abs(var - exp) <= t)) else []})
            if not (tied or explained):
                untied.append(key)
        ce = next((c for c in cells if c["month"] == m and c["line"] == "corporate_ebitda"), None)
        mstat.append({"month": m, "status": ("TIED" if not untied else "VARIANCE") if have else "NO_MIS_DATA", "untied_lines": untied,
                      "corporate_ebitda": {k: ce[k] for k in ("mis", "portal", "variance")} if ce else None})
    return {"cells": cells, "months": mstat, "tolerance_cr": q4(tol), "subtotal_tolerance_cr": q4(tol_sub)}


def corp_effect(it: dict) -> D:
    ln = line_targets(it["location_type"], it["mis_line"])
    return it["amount_cr"] if ln in ("revenue", "other_operating_income", "material_cost", *STORE_EXP, "dc_cost", "ho_cost") else ZERO


def bridge(book_lines: list[dict], items: list[dict], months: list[str], published: dict, overrides: list[dict], entity: str = "consolidated") -> dict:
    """Corporate EBITDA: books -> adjustments by group -> portal -> published MIS, per month and for the window."""
    def steps(ms):
        book_ce = sum((next(l for l in book_lines if l["key"] == "corporate_ebitda")["values"][m]["book"] for m in ms), ZERO)
        grp: dict[tuple, D] = defaultdict(D)
        for it in items:
            if it["month"] in ms and (entity == "consolidated" or it["entity"] == entity.upper()):
                e = corp_effect(it)
                if e:
                    grp[(it["group"], it["kind"], it["status"])] += e
        out = [{"label": "Portal books: corporate EBITDA", "kind": "book", "amount_cr": q4(book_ce)}]
        run = book_ce
        for (g, kind, status), v in sorted(grp.items()):
            if q4(v) != 0:
                out.append({"label": f"{g} ({kind}, {status})", "kind": "adjustment", "amount_cr": q4(v)})
                run += v
        out.append({"label": "Portal management view: corporate EBITDA", "kind": "subtotal", "amount_cr": q4(run)})
        mis = [published.get((m, "corporate_ebitda")) for m in ms]
        if all(x is not None for x in mis):
            tot_mis = sum(mis, ZERO)
            exp = sum((expected_variance("corporate_ebitda", m, overrides)[0] for m in ms), ZERO)
            out.append({"label": "Documented hard-coded overrides in the MIS sheet", "kind": "override", "amount_cr": q4(-exp)})
            out.append({"label": "Unexplained residual (books vs workbook: timing, rounding, ledger postings)", "kind": "residual", "amount_cr": q4(tot_mis - (run - exp))})
            out.append({"label": "Published MIS: corporate EBITDA", "kind": "mis", "amount_cr": q4(tot_mis)})
        return out
    return {"window": steps(set(months)), "by_month": {m: steps({m}) for m in months}}


# --------------------------------------------------------------------------- stores & apportionment

def build_stores(site_rows: list[dict], cogs_site: list[dict], names: dict, items: list[dict], months: list[str], pnl_lines: list[dict], lmap: dict, entity: str) -> dict:
    """Per-store 4-wall and apportioned EBITDA. DC + HO cost is spread at one blended rate per month = (DC + HO cost) / total store net sales.
    Store-level adjustments (STORES location) are allocated pro rata to net sales, as the workbook does (gratuity, advertisement movement, COGS correction, bifurcation);
    other operating income adjustments (SIS) are not attributable to a store and stay unallocated."""
    rate_by_month: dict[str, D] = {}
    stores: dict[int, dict] = {}
    unalloc = defaultdict(D)
    dc_ho = {ln["key"]: ln["values"] for ln in pnl_lines if ln["key"] in ("dc_cost", "ho_cost")}
    if entity == "holdco":      # HoldCo has no stores: its DC and HO cost has nothing to be spread over
        z = q4(ZERO)
        return {"rate": z, "rate_by_month": {}, "summary": {"net_sales": z, "rgm": z, "store_expenses": z, "four_wall": z, "apportioned": z, "store_ebitda_after": z,
                "dc_total": q4(sum((dc_ho["dc_cost"][m]["total"] for m in months), ZERO)), "ho_total": q4(sum((dc_ho["ho_cost"][m]["total"] for m in months), ZERO)), "reconciles": True,
                "store_count": 0, "unallocated": []}, "rows": []}
    ns: dict[tuple, D] = defaultdict(D)
    for c in cogs_site:
        ns[(c["month"], c["site_code"])] += D(str(c["ns"])) / CR
    rgm_book: dict[tuple, D] = defaultdict(D)
    exp_book: dict[tuple, D] = defaultdict(D)
    for c in cogs_site:
        rgm_book[(c["month"], c["site_code"])] += (D(str(c["ns"])) - D(str(c["cogs"]))) / CR
    for r in site_rows:
        grp, _ = resolve_group(r["glname"], r.get("fin_group"), bool(r.get("is_mapped")), lmap)
        key = cfg.KEY_OF_GROUP.get(grp) if grp and grp != cfg.EXCLUDED else None
        if key is None or key in ("revenue", *BELOW):
            continue
        amt = D(str(r["pe"])) / CR
        k = (r["month"], r["site_code"])
        if key in ("material_cost", "other_operating_income"):
            rgm_book[k] += amt
        else:
            exp_book[k] += amt
    out_rows: dict[int, dict] = {}
    mset = set(months)
    for m in months:
        sites = [s for (mm, s) in ns if mm == m]
        tot_ns = sum((ns[(m, s)] for s in sites), ZERO)
        dcho = dc_ho["dc_cost"][m]["total"] + dc_ho["ho_cost"][m]["total"]
        rate = (-dcho / tot_ns) if tot_ns else ZERO
        rate_by_month[m] = rate
        al_rgm, al_exp = ZERO, ZERO
        for it in items:
            if it["month"] != m or it["location_type"] != "STORES" or it["entity"] != "SUBCO" or it["kind"] == "elimination":
                continue
            ln = line_targets("STORES", it["mis_line"])
            if ln == "other_operating_income":
                unalloc["Other operating income adjustment (SIS) - not attributable to a store"] += it["amount_cr"]
            elif ln == "material_cost":
                al_rgm += it["amount_cr"]
            elif ln in STORE_EXP:
                al_exp += it["amount_cr"]
        for s in sites:
            row = out_rows.setdefault(s, {"site_code": s, "store": names.get(s, {}).get("short_name"), "store_name": names.get(s, {}).get("store_name"), "store_type": names.get(s, {}).get("store_type"),
                                          "net_sales": ZERO, "rgm": ZERO, "store_expenses": ZERO, "apportioned": ZERO})
            w = ns[(m, s)] / tot_ns if tot_ns else ZERO
            row["net_sales"] += ns[(m, s)]
            row["rgm"] += rgm_book[(m, s)] + al_rgm * w
            row["store_expenses"] += exp_book[(m, s)] + al_exp * w
            row["apportioned"] += -rate * ns[(m, s)]
        # store-site book that is not in a row (sites with books but no sales row) is reported as unallocated below
    for k, v in list(exp_book.items()) + [(k, v) for k, v in rgm_book.items() if k not in ns]:
        if k[0] in mset and k not in ns:
            unalloc["Store-site postings with no sales row (closed or pre-opening sites)"] += v
    rows = []
    for s, r in sorted(out_rows.items(), key=lambda kv: -kv[1]["net_sales"]):
        fw = r["rgm"] + r["store_expenses"]
        rows.append({"store": r["store"], "site_code": str(s), "store_type": r["store_type"], "store_name": r["store_name"], "net_sales": q4(r["net_sales"]), "rgm": q4(r["rgm"]),
                     "rgm_pct": q4(r["rgm"] / r["net_sales"] * 100) if r["net_sales"] else q4(ZERO), "store_expenses": q4(r["store_expenses"]), "four_wall": q4(fw),
                     "apportioned": q4(r["apportioned"]), "ebitda_after": q4(fw + r["apportioned"]),
                     "ebitda_after_pct": q4((fw + r["apportioned"]) / r["net_sales"] * 100) if r["net_sales"] else q4(ZERO)})
    app_tot = sum((r["apportioned"] for r in out_rows.values()), ZERO)
    dc_tot = sum((dc_ho["dc_cost"][m]["total"] for m in months), ZERO)
    ho_tot = sum((dc_ho["ho_cost"][m]["total"] for m in months), ZERO)
    fw_tot = sum((r["four_wall"] for r in rows), ZERO)
    store_ebitda = next(l for l in pnl_lines if l["key"] == "store_ebitda")["total"]["total"]
    ns_tot = sum((r["net_sales"] for r in out_rows.values()), ZERO)
    summary = {"net_sales": q4(ns_tot), "rgm": q4(sum((r["rgm"] for r in rows), ZERO)), "store_expenses": q4(sum((r["store_expenses"] for r in rows), ZERO)), "four_wall": q4(fw_tot),
               "apportioned": q4(app_tot), "store_ebitda_after": q4(fw_tot + app_tot), "dc_total": q4(dc_tot), "ho_total": q4(ho_tot),
               "reconciles": abs(app_tot - (dc_tot + ho_tot)) <= D("0.0005"), "store_count": len(rows), "apportionment_difference": q4(app_tot - dc_tot - ho_tot),
               "unallocated": [{"label": k, "amount_cr": q4(v)} for k, v in unalloc.items()],
               "store_ebitda_pnl": q4(store_ebitda), "store_ebitda_gap_to_rows": q4(store_ebitda - fw_tot),
               "gap_note": "Store EBITDA in /pnl less the sum of store four-wall rows: SIS income and postings at virtual, external or closed sites, not tied to one store."}
    eff = (-(dc_tot + ho_tot) / ns_tot) if ns_tot else ZERO
    return {"rate": q4(eff), "rate_by_month": {m: q4(v) for m, v in rate_by_month.items()},
            "rate_basis": "fraction of net sales: one blended rate per month = (DC cost + HO cost) / total store net sales, applied to each store's net sales", "summary": summary, "rows": rows}
