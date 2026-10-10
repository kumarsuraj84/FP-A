"""Mapping Governance over HTTP against the real app database (one rolled-back connection) and real gold_fpa. Skipped without either."""
from __future__ import annotations

from datetime import date
from decimal import Decimal as D

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.appdb import conn as appconn
from app.appdb.conn import app_connection
from app.auth import router as auth_router
from app.auth import service as auth
from app.mapping import router as map_router
from app.mgmt import config as cfg

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
    for mod in (auth, map_router, appconn):
        monkeypatch.setattr(mod, "app_connection", lambda: s)
    cfg.clear_mapping_cache()
    app = FastAPI()
    app.include_router(auth_router.router)
    app.include_router(map_router.router)
    app.state.db = GOLD
    s.execute("UPDATE app_user SET role = 'viewer' WHERE role = 'admin'")      # inside this rolled-back transaction only
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
        yield {"app": app, "admin": admin, "person": person, "db": s}
    finally:
        cfg.clear_mapping_cache()
        s.c.rollback()
        s.c.close()


def post(c, url, body=None):
    return c.post("/api/v1/mapping" + url, json=body or {}, headers=H)


def top_ledger():
    with GOLD.session("pnl") as g:
        return g.execute("""SELECT glname FROM gold_fpa.pnl_store_month WHERE entity = 'RETAIL' AND month = '2026-09-01' AND fin_group = '02-Employee Cost' AND site_kind = 'STORE'
                            GROUP BY glname ORDER BY abs(sum(profit_effect)) DESC LIMIT 1""").fetchone()["glname"]


def test_baseline_import_is_admin_only_idempotent_and_identical_to_the_csv(env):
    assert post(env["person"]("mgr@example.test", "fpa_manager"), "/import").status_code == 403
    r = post(env["admin"], "/import")
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["imported"]["LEDGER_GROUP"] > 50 and d["skipped_existing"] == 0
    assert post(env["admin"], "/import").json()["data"]["imported"] == {"LEDGER_GROUP": 0, "SITE_LOCATION": 0}
    v = env["admin"].get("/api/v1/mapping/validate").json()["data"]
    assert v["key_difference_count"] == 0 and v["line_differences"] == [] and v["identical"] is True
    listing = env["admin"].get("/api/v1/mapping", params={"domain": "LEDGER_GROUP", "limit": 5}).json()["data"]
    assert listing["source_in_use"] == "csv" and listing["counts"]["ACTIVE"] > 50
    assert all(i["source"] == "legacy_csv_import" and i["version"] == 1 and i["effective_from"] == "2000-01" for i in listing["items"])


def test_a_change_is_a_new_version_effective_from_a_month_and_the_engine_reads_by_month(env):
    post(env["admin"], "/import")
    ledger = top_ledger()
    m = env["person"]("mgr2@example.test", "fpa_manager")
    r = post(m, "", {"domain": "LEDGER_GROUP", "source_key": ledger, "mapped_value": "16-Miscellaneous Expenses", "effective_from": "2026-09", "reason": "booked to the wrong group since September", "evidence_ref": "ticket 9"})
    assert r.status_code == 200, r.text
    mid = r.json()["data"]["mapping_id"]
    assert r.json()["data"]["version"] == 2 and r.json()["data"]["supersedes_id"]
    for a in ("submit", "approve", "activate"):
        assert post(m, f"/{mid}/{a}").status_code == 200
    one = m.get(f"/api/v1/mapping/{mid}").json()["data"]
    assert [v["version"] for v in one["versions"]] == [1, 2] and one["versions"][0]["status"] == "RETIRED" and one["versions"][0]["effective_to"] == "2026-08"
    assert [e["event_type"] for e in one["events"]] == ["CREATED", "SUBMITTED", "APPROVED", "ACTIVATED"]
    with cfg.forced("app", None):
        cfg.clear_mapping_cache()
        assert cfg.ledger_map("2026-08")[ledger]["mgmt_group"] == "02-Employee Cost"                  # history is unchanged
        assert cfg.ledger_map("2026-09")[ledger]["mgmt_group"] == "16-Miscellaneous Expenses"
        assert cfg.ledger_map("2027-03")[ledger]["mgmt_group"] == "16-Miscellaneous Expenses"


def test_preview_shows_cost_moving_between_lines_from_the_effective_month_and_the_store_total_unchanged(env):
    ledger = top_ledger()
    m = env["person"]("mgr3@example.test", "fpa_manager")
    r = post(m, "/preview", {"domain": "LEDGER_GROUP", "source_key": ledger, "mapped_value": "16-Miscellaneous Expenses", "effective_from": "2026-09", "reason": "preview only, nothing is saved"})
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    by = {x["key"]: x for x in d["lines"]}
    assert d["from_month"] == "2026-09" and "employee_cost" in by and "other_expenses" in by
    assert D(by["employee_cost"]["change"]) == -D(by["other_expenses"]["change"]) and D(by["employee_cost"]["change"]) != 0
    assert "total_store_expenses" not in by and "store_ebitda" not in by                    # a move between store lines does not change the totals
    assert env["db"].execute("SELECT count(*) AS n FROM mapping_rule WHERE source_key = %s", (ledger,)).fetchone()["n"] == 0      # nothing was written


def test_lifecycle_rules_roles_and_one_pending_proposal(env):
    post(env["admin"], "/import")
    ledger = top_ledger()
    maker, checker, view = env["person"]("maker@example.test", "fpa_manager"), env["person"]("checker@example.test", "finance_reviewer"), env["person"]("view@example.test", "viewer")
    body = {"domain": "LEDGER_GROUP", "source_key": ledger, "mapped_value": "16-Miscellaneous Expenses", "effective_from": "2026-09", "reason": "booked to the wrong group since September"}
    assert post(view, "", body).status_code == 403
    for bad, text in (({"mapped_value": "99-Nope"}, "Management P&L groups"), ({"reason": "short"}, "10 characters"), ({"effective_from": "2026-13"}, "month"), ({"domain": "SITE_LOCATION", "source_key": "abc", "mapped_value": "HO"}, "number"),
                      ({"effective_from": "2000-01"}, "must start after"), ({"mapped_value": "02-Employee Cost"}, "already mapped")):
        r = post(maker, "", {**body, **bad})
        assert r.status_code in (409, 422) and text in r.json()["detail"], (bad, r.text)
    mid = post(maker, "", body).json()["data"]["mapping_id"]
    assert post(maker, "", {**body, "mapped_value": "01-Rent"}).status_code == 409                       # one pending proposal per key
    post(maker, f"/{mid}/submit")
    env["db"].execute("UPDATE app_setting SET value = 'off' WHERE key = 'single_user_mode'")
    assert post(maker, f"/{mid}/approve").status_code == 403                                             # the requester cannot approve
    assert post(checker, f"/{mid}/approve").status_code == 200
    assert post(checker, f"/{mid}/activate").status_code == 200
    assert post(checker, f"/{mid}/retire", {"comment": "no"}).status_code == 422
    assert post(checker, f"/{mid}/retire", {"comment": "the rule was proposed in error"}).json()["data"]["status"] == "RETIRED"


def test_site_location_rule_and_validation_flags_a_difference(env):
    post(env["admin"], "/import")
    m = env["person"]("mgr4@example.test", "fpa_manager")
    r = post(m, "", {"domain": "SITE_LOCATION", "source_key": "999999", "mapped_value": "DC", "effective_from": "2026-04", "reason": "a new warehouse site is a DC for management"})
    assert r.status_code == 200, r.text
    mid = r.json()["data"]["mapping_id"]
    for a in ("submit", "approve", "activate"):
        post(m, f"/{mid}/{a}")
    v = env["admin"].get("/api/v1/mapping/validate").json()["data"]
    assert v["identical"] is False and any(x["domain"] == "SITE_LOCATION" and x["key"] == "999999" and x["csv"] is None and x["app"] == "DC" for x in v["key_differences"])


def test_mapping_cutover_is_recorded_only_when_identical_and_only_by_an_administrator(env):
    admin, mgr = env["admin"], env["person"]("mgr5@example.test", "fpa_manager")
    body = {"first_month": "2026-11", "comment": "validated identical, switching to the governed mapping"}
    assert post(mgr, "/cutover", body).status_code == 403
    r = post(admin, "/cutover", body)
    assert r.status_code == 409 and "not identical" in r.json()["detail"]                              # nothing imported yet: the app mapping is empty
    post(admin, "/import")
    r = post(admin, "/cutover", body)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["first_month"] == "2026-11" and "FPA_MAPPING_SOURCE=app" in r.json()["data"]["next"]
    assert env["db"].execute("SELECT domain, identical FROM cutover_record").fetchone() == {"domain": "MAPPING", "identical": True}
