"""Corrections end to end: HTTP, real app database (one rolled-back connection), real gold_fpa for source lines and the engine overlay. Skipped without either."""
from __future__ import annotations

from decimal import Decimal as D

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.adjustments import router as adj_router
from app.appdb.conn import app_connection
from app.auth import router as auth_router
from app.auth import service as auth
from app.corrections import overlay
from app.corrections import router as cor_router
from app.corrections import service as svc
from app.mgmt import service as msvc

try:
    _c = app_connection()
    _c.close()
    HAVE_DB = True
except Exception:  # noqa: BLE001
    HAVE_DB = False


def gold_db():
    try:
        from app.gold import db as gold
        url = gold.database_url()
        if not url:
            return None
        db = gold.GoldDb(url)
        with db.session("pnl") as g:
            g.execute("SELECT 1").fetchone()
        return db
    except Exception:  # noqa: BLE001
        return None


GOLD = gold_db()
pytestmark = [pytest.mark.skipif(not HAVE_DB, reason="fpa_app not reachable"), pytest.mark.skipif(GOLD is None, reason="gold_fpa not reachable")]
H = {"X-FPA-Request": "1"}
PW = "Correct-Horse-Battery-9"


class Shared:
    def __init__(self):
        self.c = app_connection()
        self.c.execute("SAVEPOINT sp")

    def execute(self, *a, **k):
        return self.c.execute(*a, **k)

    def commit(self):
        self.c.execute("RELEASE SAVEPOINT sp")
        self.c.execute("SAVEPOINT sp")

    def rollback(self):
        self.c.execute("ROLLBACK TO SAVEPOINT sp")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture()
def env(monkeypatch):
    s = Shared()
    for mod in (auth, adj_router, cor_router, overlay):
        monkeypatch.setattr(mod, "app_connection", lambda: s)
    app = FastAPI()
    app.include_router(auth_router.router)
    app.include_router(cor_router.router)
    app.state.db = GOLD
    s.execute("UPDATE app_user SET role = 'viewer' WHERE role = 'admin'")      # inside this rolled-back transaction only: a real administrator may exist now
    auth.bootstrap_admin("boss@example.test", "Boss", PW)
    admin = TestClient(app)
    admin.post("/api/v1/auth/login", json={"email": "boss@example.test", "password": PW}, headers=H)

    def person(email, role):
        t = admin.post("/api/v1/auth/admin/users", json={"email": email, "display_name": email, "role": role}, headers=H).json()["data"]["temporary_password"]
        c = TestClient(app)
        c.post("/api/v1/auth/login", json={"email": email, "password": t}, headers=H)
        c.post("/api/v1/auth/change-password", json={"current_password": t, "new_password": "A-Fresh-Passphrase-42"}, headers=H)
        c.post("/api/v1/auth/login", json={"email": email, "password": "A-Fresh-Passphrase-42"}, headers=H)
        return c
    try:
        yield {"app": app, "person": person, "db": s}
    finally:
        s.c.rollback()
        s.c.close()


def a_line(group_like: str, month="2026-08") -> dict:
    """A real RETAIL posted employee-cost line of a complete month, found in gold."""
    with GOLD.session("pnl") as g:
        return g.execute("""SELECT cost_tag_key, entcode, profit_effect FROM gold_fpa.voucher_lines WHERE entity = 'RETAIL' AND cost_tag_key IS NOT NULL AND fin_group = %s
                            AND to_char(entdt, 'YYYY-MM') = %s AND site_kind = 'STORE' AND release_status = 'P' AND abs(profit_effect) > 1000 ORDER BY cost_tag_key LIMIT 1""", (group_like, month)).fetchone()


def make(c, line, **kw):
    body = {"source_entity": "RETAIL", "scope": "LINE", "line_keys": [line["cost_tag_key"]], "reason_code": "WRONG_CLASSIFICATION", "reason_text": "booked to the wrong management group",
            "evidence_reference": "ticket 1", **kw}
    return c.post("/api/v1/corrections", json=body, headers=H)


def go(c, rid, action, comment=None):
    return c.post(f"/api/v1/corrections/{rid}/{action}", json={"comment": comment}, headers=H)


def lines_of(lo, hi):
    with GOLD.session("pnl") as g:
        ctx = msvc.run(g, lo, hi)
    return {x["key"]: x for x in ctx["lines"]}, ctx


def test_group_correction_moves_amount_between_lines_with_net_zero_and_total_equals_book_plus_reclass(env):
    line = a_line("02-Employee Cost")
    assert line is not None
    m = env["person"]("mgr@example.test", "fpa_manager")
    r = make(m, line, corrected_group="16-Miscellaneous Expenses")
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    rid = d["request_id"]
    assert d["lines"][0]["original_group"] == "02-Employee Cost" and d["lines"][0]["fingerprint"] and len(d["lines"][0]["fingerprint"]) == 64
    base, _ = lines_of("2026-08", "2026-08")
    p = m.get(f"/api/v1/corrections/{rid}/preview").json()["data"]
    assert D(p["net_by_group_cr"]) == 0 and D(p["net_by_month_cr"]) == 0
    assert go(m, rid, "submit").json()["data"]["status"] == "SUBMITTED"
    assert go(m, rid, "approve").json()["data"]["status"] == "APPROVED"
    assert go(m, rid, "activate").json()["data"]["counts_in_management_total"] is True
    after, ctx = lines_of("2026-08", "2026-08")
    pe = D(line["profit_effect"]) / D(10_000_000)
    ec, oe = after["employee_cost"]["values"]["2026-08"], after["other_expenses"]["values"]["2026-08"]
    assert abs(ec["reclass"] - -pe) <= D("0.0001") and abs(oe["reclass"] - pe) <= D("0.0001")
    for k in [x for x in after if not x.startswith("pct_")]:
        c = after[k]["values"]["2026-08"]
        assert c["total"] == base[k]["values"]["2026-08"]["total"] if k in ("total_store_expenses", "store_ebitda", "corporate_ebitda") else True
        assert abs(c["total"] - (c["book"] + c["reclass"] + c["adjustment"])) <= D("0.0002")
    assert len(ctx["reclass"]) == 1


def test_month_correction_moves_between_months_and_window_total_is_unchanged(env):
    line = a_line("02-Employee Cost")
    m = env["person"]("mgr2@example.test", "fpa_manager")
    rid = make(m, line, corrected_month="2026-09").json()["data"]["request_id"]
    for a in ("submit", "approve", "activate"):
        assert go(m, rid, a).status_code == 200
    after, _ = lines_of("2026-08", "2026-09")
    v = after["employee_cost"]["values"]
    pe = D(line["profit_effect"]) / D(10_000_000)
    assert abs(v["2026-08"]["reclass"] - -pe) <= D("0.0001") and abs(v["2026-09"]["reclass"] - pe) <= D("0.0001")
    assert after["store_ebitda"]["total"]["reclass"] == 0 or abs(after["store_ebitda"]["total"]["reclass"]) <= D("0.0001")


def test_a_draft_or_pending_correction_does_not_touch_the_numbers(env):
    line = a_line("02-Employee Cost")
    m = env["person"]("mgr3@example.test", "fpa_manager")
    rid = make(m, line, corrected_group="16-Miscellaneous Expenses").json()["data"]["request_id"]
    go(m, rid, "submit"), go(m, rid, "approve")                       # approved but not activated
    _, ctx = lines_of("2026-08", "2026-08")
    assert ctx["reclass"] == []


def test_source_change_stops_approval_and_pauses_an_active_overlay(env, monkeypatch):
    line = a_line("02-Employee Cost")
    m = env["person"]("mgr4@example.test", "fpa_manager")
    rid = make(m, line, corrected_group="16-Miscellaneous Expenses").json()["data"]["request_id"]
    go(m, rid, "submit")
    real = svc.fingerprint
    monkeypatch.setattr(svc, "fingerprint", lambda g: "b" * 64)
    r = go(m, rid, "approve")
    assert r.status_code == 409 and "Source changed" in r.json()["detail"]
    monkeypatch.setattr(svc, "fingerprint", real)
    for a in ("approve", "activate"):
        assert go(m, rid, a).status_code == 200
    assert len(lines_of("2026-08", "2026-08")[1]["reclass"]) == 1
    monkeypatch.setattr(svc, "fingerprint", lambda g: "c" * 64)
    res = m.post("/api/v1/corrections/source-check", headers=H).json()["data"]
    assert rid in res["changed"]
    assert m.get(f"/api/v1/corrections/{rid}").json()["data"]["status"] == "SOURCE_REVIEW_REQUIRED"
    assert lines_of("2026-08", "2026-08")[1]["reclass"] == []


def test_validation_and_roles(env):
    line = a_line("02-Employee Cost")
    m, v = env["person"]("mgr5@example.test", "fpa_manager"), env["person"]("view@example.test", "viewer")
    assert make(v, line, corrected_group="16-Miscellaneous Expenses").status_code == 403
    for bad, text in (({"corrected_group": None}, "corrected"), ({"corrected_group": "99-Nope"}, "Management P&L group"), ({"reason_text": "x"}, "10 characters"),
                      ({"reason_code": "WHY"}, "reason code"), ({"corrected_group": "02-Employee Cost"}, "Nothing to correct"), ({"line_keys": [999999999999]}, "do not exist")):
        r = make(m, line, **{"corrected_group": "16-Miscellaneous Expenses", **bad})
        assert r.status_code in (404, 422) and text in r.json()["detail"], (bad, r.text)


def test_one_active_correction_per_line_and_history_and_reversal(env):
    line = a_line("02-Employee Cost")
    m = env["person"]("mgr6@example.test", "fpa_manager")
    r1 = make(m, line, corrected_group="16-Miscellaneous Expenses").json()["data"]["request_id"]
    r2 = make(m, line, corrected_group="01-Rent").json()["data"]["request_id"]
    for a in ("submit", "approve", "activate"):
        assert go(m, r1, a).status_code == 200
    go(m, r2, "submit"), go(m, r2, "approve")
    assert go(m, r2, "activate").status_code == 409                      # conflict is detected at activation
    env["db"].rollback()
    assert go(m, r1, "request-reversal", "wrong classification chosen").json()["data"]["status"] == "REVERSAL_REQUESTED"
    assert go(m, r1, "approve-reversal").json()["data"]["status"] == "REVERSED"
    assert lines_of("2026-08", "2026-08")[1]["reclass"] == []
    h = m.get(f"/api/v1/corrections/{r1}/history").json()["data"]
    assert [e["event_type"] for e in h] == ["CREATED", "SUBMITTED", "APPROVED", "ACTIVATED", "REVERSAL_REQUESTED", "REVERSAL_APPROVED"]


def test_voucher_scope_expands_into_lines_and_bulk_needs_one_target(env):
    line = a_line("02-Employee Cost")
    m = env["person"]("mgr7@example.test", "fpa_manager")
    r = m.post("/api/v1/corrections", json={"source_entity": "RETAIL", "scope": "VOUCHER", "voucher": line["entcode"], "corrected_month": "2026-09", "reason_code": "WRONG_MONTH",
                                            "reason_text": "the whole voucher belongs to September", "evidence_reference": "email 12"}, headers=H)
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["scope_type"] == "VOUCHER" and d["line_count"] >= 1 and d["correction_type"] == "EXPENSE_MONTH"
    assert len({x["corrected_month"] for x in d["lines"]}) == 1


def test_source_lines_lists_a_voucher_with_group_month_and_correctability(env):
    line = a_line("02-Employee Cost")
    m = env["person"]("mgr8@example.test", "fpa_manager")
    r = m.get("/api/v1/corrections/source-lines", params={"entity": "RETAIL", "voucher": line["entcode"]})
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    row = next(x for x in d["lines"] if x["cost_tag_key"] == line["cost_tag_key"])
    assert row["correctable"] is True and row["management_group"] == "02-Employee Cost" and row["month"] == "2026-08" and row["active_correction"] is None
    assert "02-Employee Cost" in d["groups"]
    assert m.get("/api/v1/corrections/source-lines", params={"entity": "RETAIL", "voucher": "NO-SUCH-VOUCHER"}).status_code == 404


def test_preview_of_an_unsaved_request_writes_nothing_and_nets_to_zero(env):
    line = a_line("02-Employee Cost")
    m = env["person"]("mgr9@example.test", "fpa_manager")
    before = env["db"].execute("SELECT count(*) AS n FROM correction_request").fetchone()["n"]
    r = m.post("/api/v1/corrections/preview", json={"source_entity": "RETAIL", "scope": "LINE", "line_keys": [line["cost_tag_key"]], "corrected_group": "16-Miscellaneous Expenses", "reason_code": "WRONG_CLASSIFICATION",
                                                    "reason_text": "booked to the wrong management group", "evidence_reference": "ticket"}, headers=H)
    assert r.status_code == 200, r.text
    p = r.json()["data"]
    assert D(p["net_by_group_cr"]) == 0 and D(p["net_by_month_cr"]) == 0 and p["lines"] == 1
    assert env["db"].execute("SELECT count(*) AS n FROM correction_request").fetchone()["n"] == before


def test_reclass_reaches_the_expense_heads_the_site_rows_and_the_store_league_with_totals_unchanged(env):
    from app.mgmt import expenses as ex
    line = a_line("02-Employee Cost")
    m = env["person"]("mgr10@example.test", "fpa_manager")
    with GOLD.session("pnl") as g:
        base = ex.load(g, "store", "2026-08", "2026-08", "consolidated")
        base_cells = {k: dict(v) for k, v in base.cells.items()}
        base_sites = ex.site_table(g, base)
        base_ctx = msvc.run(g, "2026-08", "2026-08")
        base_league = msvc.stores(g, base_ctx)
    rid = make(m, line, corrected_group="16-Miscellaneous Expenses").json()["data"]["request_id"]
    for a in ("submit", "approve", "activate"):
        assert go(m, rid, a).status_code == 200
    pe = D(line["profit_effect"]) / D(10_000_000)               # negative for a cost
    with GOLD.session("pnl") as g:
        x = ex.load(g, "store", "2026-08", "2026-08", "consolidated")
        d_emp = x.cells[("2026-08", "employee_cost")]["adj"] - base_cells.get(("2026-08", "employee_cost"), {"adj": D(0)})["adj"]
        d_oth = x.cells[("2026-08", "other_expenses")]["adj"] - base_cells.get(("2026-08", "other_expenses"), {"adj": D(0)})["adj"]
        assert abs(d_emp - pe) <= D("0.0001") and abs(d_oth + pe) <= D("0.0001")            # expense sign: the cost leaves employee cost and enters other expenses
        assert x.cells[("2026-08", "employee_cost")]["adj0"] == base_cells.get(("2026-08", "employee_cost"), {"adj0": D(0)})["adj0"]       # adjustments alone are untouched
        tot_b = sum((c["adj"] for (mm, h), c in base_cells.items()), D(0))
        tot_a = sum((c["adj"] for (mm, h), c in x.cells.items()), D(0))
        assert abs(tot_a - tot_b) <= D("0.0001")                                           # nets to zero across heads
        sites = ex.site_table(g, x)
        site_code = int(next(r for r in sites["rows"] if True and r["site_code"] is not None and r["site_code"] == int(a_site(line)))["site_code"]) if a_site(line) else None
        assert site_code is not None
        before = next(r for r in base_sites["rows"] if r["site_code"] == site_code)
        after = next(r for r in sites["rows"] if r["site_code"] == site_code)
        assert abs(after["total"] - before["total"]) <= D("0.0001")                         # a within-store move leaves the store's total expense unchanged
        assert abs((after["adj"]["employee_cost"] - before["adj"]["employee_cost"]) - pe) <= D("0.0001")
        league = msvc.stores(g, msvc.run(g, "2026-08", "2026-08"))
        assert abs(D(str(league["summary"]["four_wall"])) - D(str(base_league["summary"]["four_wall"]))) <= D("0.0002")


def a_site(line):
    with GOLD.session("pnl") as g:
        r = g.execute("SELECT tag_site_code FROM gold_fpa.voucher_lines WHERE entity = 'RETAIL' AND cost_tag_key = %s", (line["cost_tag_key"],)).fetchone()
    return r["tag_site_code"] if r else None
