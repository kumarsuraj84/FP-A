"""Management P&L engine: line math and rules on small synthetic inputs (no database, no config files)."""
from decimal import Decimal as D

import pytest

from app.mgmt import config as cfg
from app.mgmt import engine as eng

CR = 10_000_000
RULES = cfg.DEFAULT_RULES


def row(month, kind, gl, grp, cr, site=None, entity="SUBCO", mapped=True):
    return {"month": month, "site_kind": kind, "site_code": site, "entity": entity, "glname": gl, "fin_group": grp, "is_mapped": mapped, "pe": D(str(cr)) * CR}


def book_for(rows, sales=100, cogs=60, month="2026-08", lmap=None, site_loc=None):
    cg = [{"month": month, "ns": D(sales) * CR, "cogs": D(cogs) * CR}] if sales is not None else []
    return eng.build_book(rows, cg, lmap or {}, site_loc or {})


def lines_of(book, items, months, entity="consolidated"):
    ls = eng.shape_lines(eng.compute_pnl(book, items, months, entity), months)
    return {l["key"]: l for l in ls}


BASE = [row("2026-08", "STORE", "Sales - POS", "01-Net Sales", 100), row("2026-08", "STORE", "Store rent", "01-Rent", -5),
        row("2026-08", "STORE", "Shop wages", "02-Employee Cost", -4), row("2026-08", "WAREHOUSE", "Warehouse rent", "01-Rent", -2),
        row("2026-08", "HEAD_OFFICE", "HO salary", "02-Employee Cost", -3), row("2026-08", "STORE", "Other income", "02-Other Income", 1)]


def test_location_rule_and_book_lines():
    b = book_for(BASE)
    L = lines_of(b, [], ["2026-08"])
    v = lambda k, layer="book": L[k]["values"]["2026-08"][layer]
    assert v("revenue") == D("100") and v("other_operating_income") == D("1") and v("total_income") == D("101")
    assert v("material_cost") == D("-60")                      # product cost comes from the COGS table
    assert v("material_margin") == D("41") and v("total_store_expenses") == D("-9")
    assert v("store_ebitda") == D("32")                        # STORES location only
    assert v("dc_cost") == D("-2") and v("ho_cost") == D("-3") and v("corporate_ebitda") == D("27")
    assert v("corporate_ebitda", "adjustment") == 0 and v("corporate_ebitda", "total") == D("27")


def test_pct_lines_are_points_of_total_income():
    L = lines_of(book_for(BASE), [], ["2026-08"])
    assert L["pct_corporate_ebitda"]["values"]["2026-08"]["total"] == (D(27) / D(101) * 100).quantize(D("0.0001"))
    assert L["pct_corporate_ebitda"]["kind"] == "pct" and "pct_total_income" not in L


def test_below_ebitda_lines_are_not_in_corporate_ebitda():
    rows = BASE + [row("2026-08", "HEAD_OFFICE", "Interest", "24-Interest Income", 7), row("2026-08", "HEAD_OFFICE", "Bank int", "21-Finance Cost", -1)]
    L = lines_of(book_for(rows), [], ["2026-08"])
    assert L["interest_income"]["total"]["total"] == D("7") and L["finance_cost"]["total"]["total"] == D("-1")
    assert L["corporate_ebitda"]["total"]["total"] == D("27") and L["ho_cost"]["total"]["total"] == D("-3")


def test_site_override_unmapped_and_excluded():
    lmap = {"Gratuity": {"mgmt_group": "02-Employee Cost"}, "Stock Transfer Sent": {"mgmt_group": cfg.EXCLUDED}}
    rows = BASE + [row("2026-08", "VIRTUAL", "Adv", "07-Advertisement And Sales Promotion", -1, site=312), row("2026-08", "STORE", "Gratuity", "16-Miscellaneous Expenses", -2),
                   row("2026-08", "STORE", "Mystery", "UNMAPPED", -0.5, mapped=False), row("2026-08", "STORE", "Stock Transfer Sent", "UNMAPPED", 50, mapped=False)]
    b = book_for(rows, lmap=lmap, site_loc={312: {"location_type": "HO"}})
    assert b.cells[("2026-08", "SUBCO", "HO", "advertisement")] == D("-1")          # virtual site 312 is HO in the MIS
    assert b.cells[("2026-08", "SUBCO", "STORES", "employee_cost")] == D("-6")      # map override beats the gold group
    assert b.exceptions["Mystery"]["amount_cr"] == D("-0.5")                         # listed, never silently dropped or spread
    assert b.excluded["Stock Transfer Sent"] == D("50")
    assert eng.line_targets("STORES", "revenue") == "revenue" and eng.line_targets("HO", "revenue") is None


def test_cogs_correction_is_one_percent_of_net_sales_each_month():
    b = book_for(BASE)
    items = eng.evaluate_adjustments(b, ["2026-08"], [], RULES)
    c = [i for i in items if i["id"].startswith("RULE-COGSCORR")]
    assert len(c) == 1 and c[0]["amount_cr"] == D("-1.00")
    L = lines_of(b, items, ["2026-08"])
    mc = L["material_cost"]["values"]["2026-08"]
    assert (mc["book"], mc["adjustment"], mc["total"]) == (D("-60"), D("-1"), D("-61"))


def test_no_management_layer_before_first_rule_month():
    b = book_for(BASE, month="2026-03")
    assert not eng.evaluate_adjustments(b, ["2026-03"], [], RULES)


def test_bifurcation_reclass_nets_to_zero_and_moves_dc_to_stores():
    rows = BASE + [row("2026-08", "WAREHOUSE", "Early Payment Discount GM", "02-COGS(Others)", 0.8)]
    b = book_for(rows)
    items = eng.evaluate_adjustments(b, ["2026-08"], [], RULES)
    bif = [i for i in items if "COGSBIF" in i["id"]]
    assert sum((i["amount_cr"] for i in bif), D(0)) == 0
    L = lines_of(b, items, ["2026-08"])
    assert L["dc_cost"]["values"]["2026-08"]["total"] == D("-2")                   # the 0.8 credit leaves DC cost
    assert L["material_cost"]["values"]["2026-08"]["adjustment"] == D("0.8") - D("1")


def test_advertisement_reclass_clears_ho_and_dc():
    rows = BASE + [row("2026-08", "HEAD_OFFICE", "MKTG", "07-Advertisement And Sales Promotion", -0.4), row("2026-08", "WAREHOUSE", "MKTG2", "07-Advertisement And Sales Promotion", -0.1)]
    b = book_for(rows)
    L = lines_of(b, eng.evaluate_adjustments(b, ["2026-08"], [], RULES), ["2026-08"])
    assert L["advertisement"]["values"]["2026-08"]["total"] == D("-0.5")
    assert L["ho_cost"]["values"]["2026-08"]["total"] == D("-3") and L["dc_cost"]["values"]["2026-08"]["total"] == D("-2")


def reg(**kw):
    r = {"id": "X-1", "month": "2026-08", "mis_line": "employee_cost", "location_type": "STORES", "amount_cr": "-0.25", "kind": "provision", "rule": "fixed monthly provision", "owner": "F",
         "status": "confirmed", "source": "t", "note": "", "entity": "SUBCO", "counterparty": ""}
    r.update(kw)
    r["amount"] = D(r["amount_cr"])
    return r


def test_register_row_lands_in_adjustment_layer_and_proposed_switch():
    b = book_for(BASE)
    rows = [reg(), reg(id="X-2", status="proposed", amount_cr="-0.05", location_type="HO")]
    on = eng.evaluate_adjustments(b, ["2026-08"], rows, RULES, include_proposed=True)
    off = eng.evaluate_adjustments(b, ["2026-08"], rows, RULES, include_proposed=False)
    assert {"X-1", "X-2"} <= {i["id"] for i in on} and "X-2" not in {i["id"] for i in off}
    assert [i for i in on if i["id"] == "X-2"][0]["provisional"] is True
    L = lines_of(b, on, ["2026-08"])
    assert L["employee_cost"]["values"]["2026-08"]["adjustment"] == D("-0.25")
    assert L["ho_cost"]["values"]["2026-08"]["adjustment"] == D("-0.05")


def test_fixed_provisions_continue_after_last_register_month():
    b = book_for(BASE, month="2026-09")
    rows = [reg(rule="fixed monthly provision", month="2026-08")]
    items = eng.evaluate_adjustments(b, ["2026-09"], rows, RULES, True, last_month="2026-10")
    prov = [i for i in items if i["id"].startswith("PROV-")]
    assert len(prov) == 4 and all(i["status"] == "proposed" and i["provisional"] for i in prov)
    assert sum((i["amount_cr"] for i in prov), D(0)) == D("-0.41")
    assert not [i for i in eng.evaluate_adjustments(b, ["2026-09"], rows, RULES, False, last_month="2026-10") if i["id"].startswith("PROV-")]
    assert not [i for i in eng.evaluate_adjustments(b, ["2026-09"], rows, RULES, True, last_month="2026-08") if i["id"].startswith("PROV-")]


def test_one_time_item_leaves_ho_cost_and_sits_below_corporate_ebitda():
    rows = BASE + [row("2026-08", "HEAD_OFFICE", "Share capital fee", "14-Legal and Professional Expenses", -0.825)]
    b = book_for(rows)
    items = eng.evaluate_adjustments(b, ["2026-08"], [reg(id="ONETIME-1", mis_line="one_time", location_type="HO", amount_cr="-0.825", kind="one_time", rule="below EBITDA")], RULES)
    L = lines_of(b, items, ["2026-08"])
    g = lambda k: L[k]["values"]["2026-08"]["total"]
    assert g("ho_cost") == D("-3") and g("one_time") == D("-0.825")
    assert g("ebitda_post_one_time") == g("corporate_ebitda") + D("-0.825")


def test_true_up_replaces_the_booked_amount():
    rows = BASE + [row("2026-08", "VIRTUAL", "Business Auxiliary Service", "02-Other Income", 0.44)]
    b = book_for(rows)
    items = eng.evaluate_adjustments(b, ["2026-08"], [reg(id="SIS-1", mis_line="other_operating_income", amount_cr="0.4376", kind="income_adjustment", rule="true_up:Business Auxiliary Service")], RULES)
    sis = [i for i in items if i["id"] == "SIS-1"][0]
    assert sis["amount_cr"] == D("0.4376") - D("0.44")
    assert lines_of(b, items, ["2026-08"])["other_operating_income"]["values"]["2026-08"]["total"] == D("1") + D("0.44") + sis["amount_cr"]


def test_in_books_rows_are_memo_only():
    b = book_for(BASE)
    assert "X-1" not in {i["id"] for i in eng.evaluate_adjustments(b, ["2026-08"], [reg(status="in_books")], RULES)}


def test_holdco_stopgap_is_used_until_gold_carries_the_entity():
    stop = reg(id="VENT-1", mis_line="ho_cost" if False else "employee_cost", location_type="HO", amount_cr="-1.5", kind="stopgap_entity", status="stopgap", entity="HOLDCO")
    b = book_for(BASE)
    items = eng.evaluate_adjustments(b, ["2026-08"], [stop], RULES)
    assert "VENT-1" in {i["id"] for i in items}
    L = lines_of(b, items, ["2026-08"])
    assert L["ho_cost"]["values"]["2026-08"]["adjustment"] == D("-1.5")
    assert lines_of(b, items, ["2026-08"], "holdco")["ho_cost"]["values"]["2026-08"]["total"] == D("-1.5")        # entity filter
    assert lines_of(b, items, ["2026-08"], "subco")["ho_cost"]["values"]["2026-08"]["total"] == D("-3")
    gold = book_for(BASE + [row("2026-08", "HEAD_OFFICE", "CRPL salary", "02-Employee Cost", -1.4, entity="HOLDCO")])
    assert "VENT-1" not in {i["id"] for i in eng.evaluate_adjustments(gold, ["2026-08"], [stop], RULES)}          # gold wins over the stop-gap


def test_eliminations_apply_to_consolidated_only():
    el = reg(id="EL-1", mis_line="ho_cost", location_type="HO", amount_cr="0.12", kind="elimination", entity="HOLDCO", counterparty="Citykart Stores")
    b = book_for(BASE)
    items = eng.evaluate_adjustments(b, ["2026-08"], [el], RULES)
    assert lines_of(b, items, ["2026-08"])["ho_cost"]["values"]["2026-08"]["adjustment"] == D("0.12")
    assert lines_of(b, items, ["2026-08"], "holdco")["ho_cost"]["values"]["2026-08"]["adjustment"] == 0


def test_window_total_sums_months_and_derives_subtotals():
    rows = BASE + [{**r, "month": "2026-09"} for r in BASE]
    b = eng.build_book(rows, [{"month": "2026-08", "ns": 100 * CR, "cogs": 60 * CR}, {"month": "2026-09", "ns": 100 * CR, "cogs": 60 * CR}], {}, {})
    L = lines_of(b, [], ["2026-08", "2026-09"])
    assert L["corporate_ebitda"]["total"]["total"] == D("54")


def test_reconcile_ties_and_explains_documented_overrides():
    b = book_for(BASE)
    ls = eng.shape_lines(eng.compute_pnl(b, [], ["2026-08"]), ["2026-08"])
    pub = {("2026-08", "revenue"): D("100"), ("2026-08", "other_operating_income"): D("0.97"), ("2026-08", "rent"): D("-5.001"), ("2026-08", "corporate_ebitda"): D("26.97"),
           ("2026-08", "total_income"): D("100.97"), ("2026-08", "material_margin"): D("40.97"), ("2026-08", "store_ebitda"): D("31.97"), ("2026-08", "dc_cost"): D("-2"),
           ("2026-08", "ho_cost"): D("-3"), ("2026-08", "total_corporate"): D("-5"), ("2026-08", "material_cost"): D("-60"), ("2026-08", "total_store_expenses"): D("-9")}
    ov = [{"month": "2026-08", "line": "other_operating_income", "expected": D("0.03"), "reason": "hard-coded in the MIS sheet"}]
    rec = eng.reconcile(ls, ["2026-08"], pub, ov, RULES)
    cell = {c["line"]: c for c in rec["cells"]}
    assert cell["revenue"]["tied"] and cell["rent"]["tied"]
    assert not cell["other_operating_income"]["tied"] and cell["other_operating_income"]["explained"]
    assert cell["corporate_ebitda"]["explained"]                                 # the override flows through the subtotals
    assert rec["months"][0]["status"] == "TIED"
    bad = eng.reconcile(ls, ["2026-08"], {**pub, ("2026-08", "rent"): D("-6")}, ov, RULES)
    assert bad["months"][0]["status"] == "VARIANCE" and "rent" in bad["months"][0]["untied_lines"]


def test_bridge_adds_up_to_the_portal_total():
    b = book_for(BASE)
    items = eng.evaluate_adjustments(b, ["2026-08"], [reg()], RULES)
    ls = eng.shape_lines(eng.compute_pnl(b, items, ["2026-08"]), ["2026-08"])
    br = eng.bridge(ls, items, ["2026-08"], {("2026-08", "corporate_ebitda"): D("25.7")}, [])["window"]
    steps = [s["amount_cr"] for s in br if s["kind"] in ("book", "adjustment")]
    portal = next(s for s in br if s["kind"] == "subtotal")["amount_cr"]
    assert sum(steps, D(0)) == portal == ls[[l["key"] for l in ls].index("corporate_ebitda")]["total"]["total"]


def test_stores_apportionment_uses_one_blended_rate_and_reconciles():
    b = book_for(BASE)
    items = eng.evaluate_adjustments(b, ["2026-08"], [reg(amount_cr="-0.3")], RULES)
    ls = eng.shape_lines(eng.compute_pnl(b, items, ["2026-08"]), ["2026-08"])
    sites = [{"month": "2026-08", "site_code": 1, "ns": 60 * CR, "cogs": 36 * CR}, {"month": "2026-08", "site_code": 2, "ns": 40 * CR, "cogs": 24 * CR}]
    srows = [{"month": "2026-08", "site_code": 1, "glname": "Store rent", "fin_group": "01-Rent", "is_mapped": True, "pe": -3 * CR},
             {"month": "2026-08", "site_code": 2, "glname": "Store rent", "fin_group": "01-Rent", "is_mapped": True, "pe": -2 * CR}]
    res = eng.build_stores(srows, sites, {1: {"short_name": "AAA"}, 2: {"short_name": "BBB"}}, items, ["2026-08"], ls, {}, "consolidated")
    assert res["rate"] == D("0.05")                                  # (2 + 3) / 100
    assert res["summary"]["reconciles"] and res["summary"]["apportioned"] == D("-5.0000")
    r1 = res["rows"][0]
    assert r1["store"] == "AAA" and r1["apportioned"] == D("-3.0000")
    # gratuity-type store adjustment (-0.3) and the 1% correction are spread pro rata to net sales
    assert r1["store_expenses"] == D("-3") + D("-0.3") * D("0.6")
    assert r1["rgm"] == D("24") + D("-1") * D("0.6")
    hold = eng.build_stores(srows, sites, {}, items, ["2026-08"], ls, {}, "holdco")
    assert hold["rows"] == [] and hold["rate"] == 0
