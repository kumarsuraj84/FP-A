"""Intercompany loan / interest / service maths (synthetic rows), the related-party GL classifier, and a live smoke (skipped when the gold database is unreachable)."""
import datetime as dt
import os
from decimal import Decimal as D

import pytest

from app.gold import intercompany as ic, related_gl as rgl

CSV = """role,pair_id,entity,glcode,glname,side,status,note
loan,LOAN,VENTURES,1,HC Loan,asset,proposed,
loan,LOAN,RETAIL,2,SC Loan,liability,CONFIRMED,
service_income,SERVICE,VENTURES,3,Sales - Service,income,proposed,
service_charge,SERVICE,RETAIL,4,Fee A,expense,proposed,
service_charge,SERVICE,RETAIL,5,Fee B,expense,proposed,
other,OTHER,RETAIL,6,Nets to nil,income,proposed,
loan,LOAN,RETAIL,2,duplicate ignored,liability,proposed,
loan,LOAN,MARS,9,bad entity,asset,proposed,
loan,LOAN,RETAIL,abc,bad code,asset,proposed,
"""
CR = 10_000_000


def r(entity, gl, month, dr=0, cr=0):
    return {"entity": entity, "glcode": gl, "month": month, "dr": D(dr) * CR, "cr": D(cr) * CR, "lines": 1}


def test_parse():
    rows = ic.parse(CSV)
    assert [(x["entity"], x["glcode"]) for x in rows] == [("VENTURES", 1), ("RETAIL", 2), ("VENTURES", 3), ("RETAIL", 4), ("RETAIL", 5), ("RETAIL", 6)]
    assert rows[1]["status"] == "confirmed"


def test_example_file_is_parseable():
    ex = ic.ROOT / "config" / "mgmt" / "intercompany_ledgers.example.csv"
    got = ic.parse(ex.read_text(encoding="utf-8"))
    assert {x["role"] for x in got} >= {"loan", "interest_accrual", "interest_payable", "service_income", "service_charge", "other"}


def test_net_orientation():
    assert ic.net("asset", D(10), D(4)) == 6 and ic.net("expense", D(10), D(4)) == 6
    assert ic.net("liability", D(10), D(4)) == -6 and ic.net("income", D(10), D(4)) == -6


def synthetic():
    led = ic.parse(CSV)
    rows = [r("VENTURES", 1, "2025-08", dr=10), r("RETAIL", 2, "2025-08", cr=10), r("VENTURES", 1, "2025-09", cr=3), r("RETAIL", 2, "2025-09", dr=3),
            r("VENTURES", 3, "2025-07", cr=7.33), r("RETAIL", 4, "2025-07", dr=5), r("RETAIL", 5, "2025-07", dr=2),
            r("VENTURES", 3, "2025-10", cr=6.33), r("RETAIL", 4, "2025-10", dr=6),
            r("RETAIL", 5, "2025-12", dr=0.001),                     # tiny posting outside a billing month
            r("RETAIL", 6, "2025-07", dr=4, cr=4)]
    return led, rows


def test_loan_mirrors_and_movement():
    led, rows = synthetic()
    d = ic.build(led, rows, [], dt.date(2025, 4, 1), dt.date(2026, 1, 1))
    assert d["loan"]["mirrors"] is True and d["controls"]["loan_mirror_variance"] == 0
    assert d["loan"]["net_movement_cr"] == D("7.0000") and d["loan"]["drawn_cr"] == D("10.0000") and d["loan"]["repaid_cr"] == D("3.0000")
    assert [m["cumulative_cr"] for m in d["loan"]["by_month"]] == [D("10.0000"), D("7.0000")]
    assert "Opening balance before 2025-04 is not in the data" in d["loan"]["balance_note"]


def test_loan_break_is_shown_not_forced():
    led, rows = synthetic()
    rows.append(r("RETAIL", 2, "2025-09", cr=1))
    d = ic.build(led, rows, [], None, None)
    assert d["loan"]["mirrors"] is False and d["controls"]["loan_mirror_variance_cr"] == D("-1.0000")
    assert [m["mirrors"] for m in d["loan"]["by_month"]] == [True, False]


def test_service_unmatched_difference_is_kept():
    led, rows = synthetic()
    d = ic.build(led, rows, [], None, None)
    s = d["service"]
    assert s["billed_holdco_cr"] == D("13.6600") and s["charged_subco_cr"] == D("13.0010")
    assert s["unmatched_cr"] == D("0.6590")                                      # 0.33 + 0.33 - 0.001
    assert s["billings"] == 2 and [b["difference_cr"] for b in s["by_quarter"]] == [D("0.3300"), D("0.3300")]
    assert s["other_months"]["months"] == ["2025-12"] and s["other_months"]["difference_cr"] == D("-0.0010")
    assert s["constant_difference"] is True
    e = d["effect_on_ebitda"]
    assert e["consolidated_cr"] == 0 and e["subco_standalone_cr"] == D("-13.0010") and e["holdco_standalone_cr"] == D("13.6600")
    assert any("unmatched" in f["reason"] for f in d["flags"])


def test_nets_to_nil_is_flagged():
    led, rows = synthetic()
    d = ic.build(led, rows, [], None, None)
    assert any(f["glcode"] == 6 and "nets to nil" in f["reason"] for f in d["flags"])


def test_missing_config_gives_empty_but_valid_shape():
    d = ic.build([], [], [], None, None)
    assert d["loan"]["net_movement_cr"] == 0 and all(not p["configured"] for p in d["pairs"]) and d["service"]["billings"] == 0


# ---- related-party GL entries ----
NAMES = rgl.parse("""books_of_entity,party_pattern,counterparty_entity,status,note
RETAIL,^citykart retail pvt\\.? ?ltd,HOLDCO,proposed,
VENTURES,^citykart stores pvt\\.? ?ltd,SUBCO,confirmed,
RETAIL,^citykart stores pvt\\.? ?ltd,SAME_COMPANY,proposed,
RETAIL,(bad,HOLDCO,proposed,
""")


def line(entity, ent, gl, vendor, dr=0, cr=0, month=(2025, 8, 5), glname="L"):
    return {"entity": entity, "entcode": ent, "entno": None, "entdt": dt.date(*month), "entry_type": "Voucher", "enttype": "V", "glcode": gl, "glname": glname, "slcode": 1, "vendor_name": vendor,
            "damount": D(dr), "camount": D(cr), "release_status": "P", "narration": "n"}


def test_party_register_parsing_and_entity_scoping():
    assert len(NAMES) == 3                                                       # bad regex skipped
    assert rgl.match_party(NAMES, "RETAIL", "CITYKART RETAIL PVT. LTD. (GGN-WH)")["counterparty_entity"] == "HOLDCO"
    assert rgl.match_party(NAMES, "VENTURES", "CITYKART RETAIL PVT LTD (Delhi)") is None                 # a pattern only applies to its own books
    assert rgl.match_party(NAMES, "RETAIL", "CITYKART STORES PVT LTD (ISD)")["counterparty_entity"] == "SAME_COMPANY"


def test_classify_party_or_ledger_and_mirror():
    led = ic.parse(CSV)
    raw = [line("RETAIL", "A", 50, "CITYKART RETAIL PVT LTD (Delhi)", dr=2), line("VENTURES", "B", 51, "CITYKART STORES PVT. LTD. (Delhi)", cr=2),
           line("RETAIL", "C", 4, None, dr=5), line("RETAIL", "D", 60, "Some Vendor", dr=9), line("RETAIL", "E", 50, "CITYKART STORES PVT LTD (ISD)", cr=1.5)]
    got = rgl.classify(NAMES, led, raw)
    assert [(x["entcode"], x["reason"], x["counterparty_entity"]) for x in got] == [("A", "party", "HOLDCO"), ("B", "party", "SUBCO"), ("C", "ledger:service_charge", "HOLDCO"), ("E", "party", "SAME_COMPANY")]
    b = rgl.build(got, NAMES)
    assert b["total_entries"] == 4 and b["by_entity"]["RETAIL"]["entries"] == 2 and b["same_company"]["credit"] == D("1.5")
    assert b["mirror"]["mirrors"] is True                                        # HoldCo Cr 2 = SubCo Dr 2 on party-tagged lines
    only_ledger = rgl.build(got, NAMES, basis="ledger")
    assert only_ledger["total_entries"] == 1 and only_ledger["entries"][0]["reason"] == "ledger:service_charge"
    assert rgl.build(got, NAMES, entity="VENTURES")["total_entries"] == 1
    assert rgl.build(got, NAMES, from_month="2025-09")["total_entries"] == 0
    got.append(rgl.classify(NAMES, led, [line("RETAIL", "F", 50, "CITYKART RETAIL PVT LTD (Haryana)", cr=100)])[0])
    assert rgl.build(got, NAMES)["mirror"]["mirrors"] is False                   # shown, not forced
    assert rgl.build(got, NAMES, limit=1, offset=1)["returned"] == 1


def test_entry_groups_lines_per_entity_and_entcode():
    led = ic.parse(CSV)
    raw = [line("RETAIL", "A", 4, None, dr=1, glname="Fee A"), line("RETAIL", "A", 5, None, dr=2, glname="Fee B"), line("VENTURES", "A", 3, None, cr=3, glname="Sales - Service")]
    b = rgl.build(rgl.classify(NAMES, led, raw), NAMES)
    assert b["total_entries"] == 2                                               # same entcode in two entities stays two entries
    e = next(x for x in b["entries"] if x["entity"] == "RETAIL")
    assert e["debit"] == 3 and e["ledgers"] == ["Fee A", "Fee B"] and e["lines"] == 2


def test_example_names_file_is_parseable():
    ex = rgl.ROOT / "config" / "mgmt" / "related_party_names.example.csv"
    assert {n["counterparty_entity"] for n in rgl.parse(ex.read_text(encoding="utf-8"))} == {"HOLDCO", "SUBCO", "SAME_COMPANY"}


# ---- live smoke ----
def _client():
    if os.environ.get("FPA_SOURCE", "").lower() != "gold":
        pytest.skip("FPA_SOURCE=gold not set")
    from app.gold.db import database_url
    if not database_url():
        pytest.skip("gold database not configured")
    from fastapi.testclient import TestClient
    from app.creditors_api.main import create_app
    app = create_app()
    if not app.state.settings.finance_token:
        pytest.skip("finance token not configured")
    try:
        import psycopg
        psycopg.connect(database_url(), connect_timeout=5).close()
    except Exception:
        pytest.skip("gold database unreachable")
    return TestClient(app), {"Authorization": f"Bearer {app.state.settings.finance_token}"}


def test_by_fy_pre_carry_gap_and_uncarried_ledger():
    led = ic.parse(CSV + "loan_uncarried,LOAN,RETAIL,7,Old loan,liability,proposed,\n")
    rows = [r("RETAIL", 2, "2018-06", cr=5), r("RETAIL", 2, "2019-03", cr=2),                 # FY2018: SubCo only (HoldCo does not carry it)
            r("VENTURES", 1, "2020-06", dr=6), r("RETAIL", 2, "2020-06", cr=6),                 # FY2020 mirrors
            r("VENTURES", 1, "2021-02", cr=1), r("RETAIL", 2, "2021-02", dr=1),                 # FY2020 again (Feb-21)
            r("RETAIL", 7, "2019-03", dr=1.5)]
    d = ic.build(led, rows, [], None, None)
    fy = {f["fy"]: f for f in d["loan"]["by_fy"]}
    assert fy["FY2018"]["one_sided"] is True and fy["FY2018"]["difference_cr"] == D("-7.0000")
    assert fy["FY2020"]["matches"] is True and fy["FY2020"]["holdco_net_cr"] == D("5.0000")
    nc = d["loan"]["not_carried"]
    assert nc["pre_carry_gap_cr"] == D("-7.0000") and nc["pre_carry_years"] == ["FY2018"]
    assert nc["ledger"]["glcode"] == 7 and nc["ledger"]["net_cr"] == D("-1.5000")
    assert nc["after_uncarried_difference_cr"] == D("-5.5000")                          # holdco 5 - (subco 12 - 1.5) ... = 5 - 10.5
    assert d["loan"]["carried_years_mirror"] is True and d["controls"]["loan_carried_years_variance_cr"] == 0 and d["loan"]["mirrors"] is False
    assert ic.fy_of("2020-03") == "FY2019" and ic.fy_of("2020-04") == "FY2020"


def test_table_classification_follows_the_tables_reason():
    led = ic.parse(CSV)
    base = {"entdt": dt.date(2025, 8, 5), "damount": D(1), "camount": D(0), "vendor_name": "x", "glname": "L"}
    got = rgl.classify_table(led, [{**base, "entity": "RETAIL", "entcode": "1", "glcode": 50, "reason": "party_holdco"}, {**base, "entity": "VENTURES", "entcode": "2", "glcode": 50, "reason": "party_subco"},
                                   {**base, "entity": "RETAIL", "entcode": "3", "glcode": 50, "reason": "same_company_isd"}, {**base, "entity": "RETAIL", "entcode": "4", "glcode": 4, "reason": "ledger_list"}])
    assert [(x["counterparty_entity"], x["reason"]) for x in got] == [("HOLDCO", "party"), ("SUBCO", "party"), ("SAME_COMPANY", "same_company"), ("HOLDCO", "ledger:service_charge")]


# ---- live smoke ----
def _client():
    if os.environ.get("FPA_SOURCE", "").lower() != "gold":
        pytest.skip("FPA_SOURCE=gold not set")
    from app.gold.db import database_url
    if not database_url():
        pytest.skip("gold database not configured")
    from fastapi.testclient import TestClient
    from app.creditors_api.main import create_app
    app = create_app()
    if not app.state.settings.finance_token:
        pytest.skip("finance token not configured")
    try:
        import psycopg
        psycopg.connect(database_url(), connect_timeout=5).close()
    except Exception:
        pytest.skip("gold database unreachable")
    return TestClient(app), {"Authorization": f"Bearer {app.state.settings.finance_token}"}


def test_live_smoke():
    ic.reload(); rgl.reload()
    if not ic.load():
        pytest.skip("config/mgmt/intercompany_ledgers.csv not present")
    c, h = _client()
    d = c.get("/api/v1/related-party/intercompany", headers=h).json()
    full = d["sources"]["full_ledger"]["present"]
    assert D(d["controls"]["service_unmatched_cr"]) == D("1.6463") and d["service"]["billings"] == 5          # service ledgers are only in voucher_lines
    assert all(D(b["difference_cr"]) == D("0.3300") for b in d["service"]["by_quarter"])
    if full:
        assert d["loan"]["full_history"] is True and d["loan"]["source"] == "related_party_gl_lines"
        assert D(d["loan"]["holdco_balance_cr"]) == D("141.2342") and D(d["loan"]["subco_balance_cr"]) == D("153.7177")
        assert d["controls"]["loan_carried_years_mirror"] is True and D(d["controls"]["loan_carried_years_variance_cr"]) == 0
        assert D(d["controls"]["loan_pre_carry_gap_cr"]) == D("-12.4835") and D(d["loan"]["not_carried"]["after_uncarried_difference_cr"]) == D("4.9765")
        assert d["controls"]["interest_variance_cr"] in ("0.0000", "-0.0000")
    else:
        assert D(d["controls"]["loan_mirror_variance_cr"]) == 0 and D(d["loan"]["net_movement_cr"]) == D("46.1684")
    g = c.get("/api/v1/related-party/gl-entries?limit=5", headers=h).json()
    assert g["total_entries"] > 0 and g["returned"] <= 5 and set(g["by_entity"]) == {"RETAIL", "VENTURES"}
    if full:
        assert g["source"]["entries"] == "related_party_gl_lines" and g["source"]["control"]["ok"] is True
        assert D(g["same_company"]["credit"]) == D("47965737.08")
    s = c.get("/api/v1/related-party/summary", headers=h).json()
    assert s["loans"]["available"] is True and s["loans"]["source"] == "ledger" and s["related_party_gl"]["entries"] == g["total_entries"]


def test_pg_pattern_translates_python_regex():
    from app.gold import related_gl as rg
    assert rg.pg_pattern(chr(92) + "bacme" + chr(92) + "b") == chr(92) + "yacme" + chr(92) + "y"
    assert rg.pg_pattern("(?i)acme") == "acme"
    for bad in ("x(?P<n>y)", "a(?i:b)"):
        try:
            rg.pg_pattern(bad)
            raise AssertionError(bad)
        except ValueError:
            pass
    assert rg.parse("books_of_entity,party_pattern,counterparty_entity\nRETAIL,x(?P<n>y),HOLDCO\n") == []
