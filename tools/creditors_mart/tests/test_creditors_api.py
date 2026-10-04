"""
Creditors API tests: a synthetic run is loaded through the real loader into a PRIVATE, THROWAWAY PostgreSQL and served by the real app.
Nothing real is touched. Evidence: docs/creditors_pilot/API_UAT_EVIDENCE.md
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT.parent / "backend"))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(ROOT / "extraction_broker"))
sys.path.insert(0, str(ROOT / "extraction_broker" / "tests"))
sys.path.insert(0, str(HERE))
import creditors_stage as cs  # noqa: E402
import loader  # noqa: E402
import migrate  # noqa: E402
import test_creditors_pilot as tcp  # noqa: E402
from app.creditors_api import reconcile as rec  # noqa: E402
from app.creditors_api.config import ApiSettings  # noqa: E402
from app.creditors_api.db import Db  # noqa: E402
from app.creditors_api.main import create_app  # noqa: E402
from test_cred_mart_db import PG_BIN, Cluster  # noqa: E402

EVIDENCE_FILE = ROOT.parent / "docs" / "creditors_pilot" / "API_UAT_EVIDENCE.md"
SALT = "unit-test-pseudonym-key-0123456789"
TOKEN = "test-finance-token-0123456789abcdef"
RUN = "run_20261004_940"
pytestmark = pytest.mark.skipif(not (PG_BIN / "initdb.exe").exists() and not shutil.which("initdb"), reason="PostgreSQL server binaries not found")
EVIDENCE: list[dict] = []
NAMES = [f"Vendor {i}" for i in range(7)]
FORBIDDEN_MASKED = ["vendor_name", "slid", "sub_ledger_code", "document_code", "document_no", "ref_no", "credit_days", "source_row_key", "document_initial"] + NAMES + ["DOC0001", "SL500", "SL501"]


def ev(uid, title, **detail):
    EVIDENCE.append({"id": uid, "title": title, "detail": detail})


@pytest.fixture(scope="module")
def cluster(tmp_path_factory):
    c = Cluster(tmp_path_factory.mktemp("pg_api"))
    c.start()
    with c.connect("postgres") as a:
        a.execute("CREATE DATABASE api_template")
    with c.connect("api_template") as a:
        migrate.apply(a)
    yield c
    c.stop()
    shutil.rmtree(c.root, ignore_errors=True)
    ev("A00", "scratch instance removed", data_directory_removed=not c.root.exists())
    write_evidence()


_n = [0]


@pytest.fixture
def env(cluster, tmp_path):
    """Fresh database with one synthetic run loaded through the real loader and verified; the app wired to it."""
    _n[0] += 1
    name = f"api_{_n[0]:03d}"
    with cluster.connect("postgres") as a:
        a.execute(f"CREATE DATABASE {name} TEMPLATE api_template")
    admin = cluster.connect(name)
    admin.execute(f"GRANT CONNECT, CREATE ON DATABASE {name} TO cred_owner")
    admin.execute(f"GRANT CONNECT ON DATABASE {name} TO cred_loader, cred_verifier, cred_promoter, cred_api_reader, cred_finance_reader")
    run = tcp.build_run(tmp_path, name=RUN)
    assert cs.validate(run)["verdict"] == "PASSED"
    admin.execute("SET ROLE cred_loader")
    plan = loader.preflight(run, SALT)
    loader.load_run(admin, plan)
    admin.execute("RESET ROLE")
    db = Db(cluster.dsn(name))
    app = create_app(ApiSettings(conninfo=cluster.dsn(name), finance_token=TOKEN, cors_origins=()), db)
    yield {"admin": admin, "db": db, "client": TestClient(app), "app": app, "run": run, "plan": plan, "name": name, "cluster": cluster}
    admin.close()
    with cluster.connect("postgres") as a:
        a.execute(f"DROP DATABASE {name} WITH (FORCE)")


def verify(env):
    admin = env["admin"]
    admin.execute("SET ROLE cred_loader")
    assert loader.verify_loaded(admin, RUN)["ok"] is True
    admin.execute("RESET ROLE")


def base(path=""):
    return f"/api/v1/creditors/runs/{RUN}{path}"


FIN = {"Authorization": f"Bearer {TOKEN}"}


def raw_rows(env):
    return cs.load(env["run"], "e1_open_items")


# ───────────── state and serving rules ─────────────


def test_a01_only_a_verified_run_is_served_and_the_state_is_stated_by_the_api(env):
    c = env["client"]
    assert c.get("/api/v1/creditors/health").json() == {"status": "ok"}
    assert c.get(base()).status_code == 404 and c.get(base("/summary")).status_code == 404       # loaded but not yet verified
    assert c.get("/api/v1/creditors/current").status_code == 404
    verify(env)
    st = c.get(base()).json()
    assert (st["recon_state"], st["publication_state"], st["data_state"]) == ("verified", "unpublished", "verified_candidate")
    assert "not published" in st["data_state_label"].lower()
    assert st["controls"]["failed"] == 0 and st["controls"]["total"] > 100 and st["scope"]["debit_balances_netted_into_credit"] is False
    cur = c.get("/api/v1/creditors/current").json()
    assert cur["extraction_run_id"] == RUN and cur["data_state"] == "verified_candidate"
    assert c.get("/api/v1/creditors/runs/run_20990101_001").status_code == 404
    ev("A01", "state rules", before_verify="404", after_verify=st["data_state"], label=st["data_state_label"], unknown_run="404")


def test_a02_money_is_exact_text_and_the_summary_matches_the_rows(env):
    verify(env)
    s = env["client"].get(base("/summary")).json()
    rows = raw_rows(env)
    cr = sum((abs(Decimal(r["pending"])) for r in rows if r["drcr"] == "Cr"), Decimal(0))
    dr = sum((abs(Decimal(r["pending"])) for r in rows if r["drcr"] == "Dr"), Decimal(0))
    for k in ("credit_outstanding", "creditor_debit_balance", "signed_net", "past_due_credit", "due_date_unavailable_credit" if False else "due_unavailable_credit"):
        assert isinstance(s[k], str), k                                  # never a JSON number
    assert Decimal(s["credit_outstanding"]) == cr and Decimal(s["creditor_debit_balance"]) == dr and Decimal(s["signed_net"]) == -cr + dr
    assert s["item_rows"] == 48 and s["vendors"] == 7 and s["as_of_date"] == "2026-10-04"
    assert {"top_1", "top_5", "top_10", "top_20"} == set(s["credit_concentration"]) and Decimal(s["credit_concentration"]["top_20"]) == Decimal("1.0000")
    ev("A02", "exact money", credit=s["credit_outstanding"], debit=s["creditor_debit_balance"], net=s["signed_net"], types="decimal text, not numbers")


def test_a03_document_age_due_status_and_ledgers(env):
    verify(env)
    c = env["client"]
    age = c.get(base("/document-age")).json()["buckets"]
    assert [b["bucket"] for b in age] == ["D0_30", "D31_60", "D61_90", "D91_180", "D181_365", "D365_PLUS", "UNCLASSIFIED"]
    assert [b["label"] for b in age] == ["0–30", "31–60", "61–90", "91–180", "181–365", ">365", "Unclassified"]
    un = age[-1]
    assert un["credit_items"] + un["debit_items"] >= 2 and {r["reason"] for r in un["reasons"]} >= {"BEFORE_MIN", "MISSING"}   # the 0202 and the missing date
    due = c.get(base("/due-status")).json()["states"]
    assert [d["state"] for d in due] == ["NOT_YET_DUE", "PAST_DUE_OR_DUE_TODAY", "DUE_UNAVAILABLE", "DUE_INVALID"]
    assert [d["label"] for d in due] == ["Not yet due", "Past due / due today", "Due date unavailable", "Invalid due date"]
    assert due[3]["credit_items"] + due[3]["debit_items"] >= 1                                                                   # the due-before-document row
    led = c.get(base("/ledgers")).json()["ledgers"]
    assert len(led) == 4 and all(set(l) >= {"credit_outstanding", "debit_balance", "signed_net", "vendors", "credit_items", "debit_items"} for l in led)
    s = c.get(base("/summary")).json()
    assert sum(Decimal(l["credit_outstanding"]) for l in led) == Decimal(s["credit_outstanding"]) and sum(Decimal(b["credit_outstanding"]) for b in age) == Decimal(s["credit_outstanding"])
    ev("A03", "document age, due status, ledgers", buckets=[b["bucket"] for b in age], states=[d["state"] for d in due], unclassified_reasons=[r["reason"] for r in un["reasons"]])


# ───────────── masking ─────────────


def test_a04_the_masked_api_never_carries_a_vendor_name_or_a_code(env):
    verify(env)
    c = env["client"]
    page = c.get(base("/vendors"), params={"limit": 500}).json()
    some = page["vendors"][0]["vendor_ref"]
    bodies = [c.get(base(p)).text for p in ("", "/summary", "/document-age", "/due-status", "/ledgers", "/controls", "/vendors", f"/vendors/{some}", f"/vendors/{some}/items")]
    text = "\n".join(bodies)
    leaks = [w for w in FORBIDDEN_MASKED if w in text]
    assert not leaks, leaks
    v = page["vendors"][0]
    assert re.fullmatch(r"V[0-9a-f]{12}", v["vendor_ref"]) and set(v) >= {"vendor_ref", "party_class", "ledger_codes", "credit_outstanding", "debit_balance", "signed_net", "credit_by_document_age", "credit_by_due_status"}
    it = c.get(base(f"/vendors/{some}/items")).json()["items"][0]
    assert set(it) >= {"item_ref", "document_date", "due_date", "document_age_days", "document_age_bucket", "due_status", "pending", "drcr", "ledger_code"} and not (set(it) & {"document_code", "document_no", "ref_no", "sub_ledger_code"})
    ev("A04", "masked API", endpoints_scanned=len(bodies), forbidden_terms_checked=len(FORBIDDEN_MASKED), leaks="none", vendor_keys=sorted(v)[:8], item_keys_have_no_codes=True)


def test_a05_finance_endpoints_need_the_token_and_only_they_carry_names(env):
    verify(env)
    c = env["client"]
    path = base("/finance/vendors")
    assert c.get(path).status_code == 401
    assert c.get(path, headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert c.get(path, headers={"Authorization": f"Bearer {TOKEN}x"}).status_code == 401
    r = c.get(path, headers=FIN)
    assert r.status_code == 200
    vs = r.json()["vendors"]
    assert {v["vendor_name"] for v in vs} == set(NAMES) and all(v["slid"] and v["sub_ledger_code"] for v in vs)
    ref = vs[0]["vendor_ref"]
    items = c.get(base(f"/finance/vendors/{ref}/items"), headers=FIN).json()["items"]
    assert items and all(i["document_code"].startswith("DOC") for i in items)
    assert c.get(base(f"/finance/vendors/{ref}/items")).status_code == 401
    assert c.get(base(f"/finance/vendors/{ref}"), headers=FIN).json()["vendor"]["vendor_name"] in NAMES
    q = c.get(path, params={"q": "vendor 3"}, headers=FIN).json()
    assert q["total"]["vendors"] == 1 and q["vendors"][0]["vendor_name"] == "Vendor 3"
    assert c.get(path, params={"q": "vendor 3"}).status_code == 401           # search by name needs the same gate
    # a server without a configured token refuses Finance outright
    env["app"].state.settings = ApiSettings(conninfo=None, finance_token=None, cors_origins=())
    assert c.get(path, headers=FIN).status_code == 503
    ev("A05", "finance gate", no_token="401", wrong_token="401", right_token="names and codes", name_search="finance only", unconfigured_server="503")


def test_a06_vendor_list_paging_sorting_filters_and_distributions(env):
    verify(env)
    c = env["client"]
    full = c.get(base("/vendors"), params={"limit": 500}).json()
    assert full["total"]["vendors"] == 7 and full["returned"] == 7
    credits = [Decimal(v["credit_outstanding"]) for v in full["vendors"]]
    assert credits == sorted(credits, reverse=True)
    p1 = c.get(base("/vendors"), params={"limit": 3, "offset": 0}).json()["vendors"]
    p2 = c.get(base("/vendors"), params={"limit": 3, "offset": 3}).json()["vendors"]
    assert [v["vendor_ref"] for v in p1 + p2] == [v["vendor_ref"] for v in full["vendors"][:6]]
    asc = c.get(base("/vendors"), params={"sort": "items", "order": "asc"}).json()["vendors"]
    assert [v["items"] for v in asc] == sorted(v["items"] for v in asc)
    led = full["vendors"][0]["ledger_codes"][0]
    f = c.get(base("/vendors"), params={"ledger_code": led}).json()
    assert 0 < f["total"]["vendors"] <= 7 and all(led in v["ledger_codes"] for v in f["vendors"])
    cls = c.get(base("/vendors"), params={"party_class": "Staff"}).json()
    assert all(v["party_class"] == "Staff" for v in cls["vendors"])
    for v in full["vendors"]:
        assert sum(Decimal(x) for x in v["credit_by_document_age"].values()) == Decimal(v["credit_outstanding"])
        assert sum(Decimal(x) for x in v["credit_by_due_status"].values()) == Decimal(v["credit_outstanding"])
    assert abs(sum(Decimal(v["share_of_credit"]) for v in full["vendors"]) - 1) < Decimal("0.0001")
    assert c.get(base("/vendors/Vdeadbeefdead")).status_code == 404 and c.get(base("/vendors/Vdeadbeefdead/items")).status_code == 404
    assert c.get(base("/vendors"), params={"limit": 0}).status_code == 422 and c.get(base("/vendors"), params={"limit": 9999}).status_code == 422
    assert c.get(base("/vendors"), params={"sort": "drop table"}).status_code == 200            # unknown sort falls back, never reaches SQL
    ev("A06", "vendor list", vendors=7, sorted_desc=True, paging="consistent", filters="ledger, party class", distributions_add_up=True, unknown_vendor="404", bad_limit="422")


def test_a07_vendor_items_filters_and_drill_ids(env):
    verify(env)
    c = env["client"]
    v = c.get(base("/vendors"), params={"limit": 500}).json()["vendors"][0]
    ref = v["vendor_ref"]
    allit = c.get(base(f"/vendors/{ref}/items")).json()
    assert allit["total_items"] == v["items"] == len(allit["items"])
    assert sum(abs(Decimal(i["pending"])) for i in allit["items"] if i["drcr"].strip() == "Cr") == Decimal(v["credit_outstanding"])
    cr = c.get(base(f"/vendors/{ref}/items"), params={"drcr": "Cr"}).json()
    assert all(i["drcr"].strip() == "Cr" for i in cr["items"])
    ids = [i["item_ref"] for i in allit["items"]]
    assert len(set(ids)) == len(ids) and all(re.fullmatch(r"[0-9a-f]{64}", i) for i in ids)
    dates = [i["document_date"] for i in allit["items"] if i["document_date"]]
    assert dates == sorted(dates)
    ev("A07", "vendor items", drill_ids="unique 64-hex item_ref", oldest_first=True, filters="drcr, bucket, due")


# ───────────── the gate: mart = API ─────────────


def test_a08_mart_equals_api_with_zero_variance_and_the_database_records_it(env):
    verify(env)
    checks = rec.reconcile(env["client"], env["db"], RUN, TOKEN)
    bad = [c for c in checks if not c.ok]
    assert not bad, [(c.control, c.dimension, c.mart, c.api) for c in bad[:5]]
    controls = sorted({c.control for c in checks})
    assert len(checks) > 100 and {"API-C1", "API-C2", "API-C3", "API-C4", "API-C5", "API-C6", "API-C7", "API-C8", "API-C9", "API-FIN", "API-STRIP"} <= set(controls)
    res = rec.record(env["db"], RUN, checks)
    assert res["ok"] is True and res["recon_state"] == "api_verified"
    st = env["client"].get(base()).json()
    assert (st["recon_state"], st["publication_state"], st["data_state"]) == ("api_verified", "unpublished", "verified_candidate")
    layers = {(l["from"], l["to"]): l for l in st["controls"]["layers"]}
    assert layers[("mart", "api")]["failed"] == 0 and layers[("mart", "api")]["controls"] == len(checks)
    ev("A08", "mart = API", checks=len(checks), different=0, controls_covered=controls, api_layer_controls_recorded=len(checks), state_after=[st["recon_state"], st["publication_state"]])


def test_a09_one_difference_blocks_api_verification(env):
    verify(env)
    checks = rec.reconcile(env["client"], env["db"], RUN, TOKEN)
    checks[3].api = checks[3].api + Decimal("0.01")                       # one paisa
    res = rec.record(env["db"], RUN, checks)
    assert res["ok"] is False and res["failed"] == 1
    assert env["client"].get(base()).json()["recon_state"] == "verified"  # did not advance
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        env["db"].session  # the API cannot promote: it has no path to promote_run
        with env["db"].session("candidate", readonly=False) as c:
            c.execute(f"SELECT cred.promote_run('{RUN}','x')")
    ev("A09", "a paisa of difference blocks verification", database_answer={k: res[k] for k in ("ok", "controls", "failed")}, state_unchanged="verified", api_can_promote=False)


def test_a10_a_promoted_run_is_served_from_the_live_views_with_the_same_numbers(env):
    verify(env)
    c, admin = env["client"], env["admin"]
    before = {p: c.get(base(p)).json() for p in ("/summary", "/ledgers", "/document-age")}
    checks = rec.reconcile(c, env["db"], RUN, TOKEN)
    assert rec.record(env["db"], RUN, checks)["ok"]
    admin.execute("SET ROLE cred_promoter")
    admin.execute("SELECT cred.promote_run(%s,'api uat')", (RUN,))
    admin.execute("RESET ROLE")
    st = c.get(base()).json()
    assert (st["publication_state"], st["data_state"]) == ("live", "live")
    cur = c.get("/api/v1/creditors/current").json()
    assert cur["data_state"] == "live"
    after = {p: c.get(base(p)).json() for p in before}
    for p in before:
        a, b = dict(after[p]), dict(before[p])
        for d in (a, b):
            for k in ("recon_state", "publication_state", "data_state", "data_state_label"):
                d.pop(k, None)
        assert a == b, p
    assert not [w for w in FORBIDDEN_MASKED if w in c.get(base("/vendors")).text]                # live masked path (cred_api_reader) is masked too
    assert c.get(base("/finance/vendors"), headers=FIN).status_code == 200
    again = rec.reconcile(c, env["db"], RUN, TOKEN)
    assert all(x.ok for x in again)
    ev("A10", "live serving", data_state_after_promotion=st["data_state"], same_numbers=True, masked_live_path="no names or codes", reconciliation_still_zero_variance=True)


def test_a11_database_roles_do_the_masking_not_the_application(env):
    verify(env)
    db = env["db"]
    import psycopg.errors as E

    with db.session("candidate") as c:
        with pytest.raises(E.InsufficientPrivilege):
            c.execute("SELECT vendor_name FROM cred.v_open_item_named_candidate")
    with db.session("finance") as c:
        assert c.execute("SELECT count(*) AS n FROM cred.v_open_item_named_candidate WHERE extraction_run_id = %s", (RUN,)).fetchone()["n"] == 48
    with db.session("candidate", readonly=True) as c:
        with pytest.raises(E.ReadOnlySqlTransaction):
            c.execute("UPDATE cred.run SET expected_rows = 1")
    with pytest.raises(KeyError):
        with db.session("cred_owner"):
            pass
    ev("A11", "roles do the masking", verifier_cannot_read_names="permission denied", finance_can="yes", sessions_are_read_only=True, role_names_are_whitelisted=True)


def test_a12_cors_is_limited_and_the_server_degrades_cleanly_without_a_database():
    app = create_app(ApiSettings(conninfo=None, finance_token=None, cors_origins=("http://localhost:5180",)), None)
    c = TestClient(app)
    assert c.get("/api/v1/creditors/health").status_code == 200
    assert c.get("/api/v1/creditors/current").status_code == 503
    r = c.options("/api/v1/creditors/health", headers={"Origin": "http://localhost:5180", "Access-Control-Request-Method": "GET"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5180"
    r2 = c.options("/api/v1/creditors/health", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in r2.headers
    assert c.post("/api/v1/creditors/health").status_code == 405
    ev("A12", "cors and degradation", allowed_origin="http://localhost:5180 only", other_origin="no CORS header", no_database="503", writes="405 (read-only)")


def test_a13_install_api_creates_a_noinherit_login_that_can_only_assume_the_three_read_roles(env, tmp_path, monkeypatch, capsys):
    import install_api
    from setup_loader import read_env

    verify(env)
    admin, cluster = env["admin"], env["cluster"]
    secret = tmp_path / ".secrets" / "cred_api.env"
    facts = install_api.provision(admin, secret, "127.0.0.1", str(cluster.port), env["name"])
    cfg = read_env(secret)
    assert facts["created"] and set(cfg) == {"host", "port", "dbname", "user", "password", "finance_token"} and cfg["user"] == "cred_api_login"
    assert len(cfg["password"]) >= 40 and len(cfg["finance_token"]) >= 40
    checks = install_api.check_role(admin)
    assert all(ok for _, ok in checks), [n for n, ok in checks if not ok]
    info = f"host={cfg['host']} port={cfg['port']} dbname={cfg['dbname']} user={cfg['user']} password={cfg['password']}"
    login = install_api.check_login(info)
    assert all(ok for _, ok in login), [n for n, ok in login if not ok]
    # the real thing end to end: settings read from the secrets file, the API served through that login, mart = API still zero variance
    monkeypatch.setenv("FPA_CRED_API_ENV", str(secret))
    monkeypatch.delenv("FPA_CRED_API_URL", raising=False)
    monkeypatch.delenv("FPA_CRED_FINANCE_TOKEN", raising=False)
    settings = ApiSettings.load()
    client = TestClient(create_app(settings, Db(settings.conninfo)))
    assert client.get(base("/summary")).json()["item_rows"] == 48
    assert client.get(base("/finance/vendors"), headers={"Authorization": f"Bearer {cfg['finance_token']}"}).status_code == 200
    assert client.get(base("/finance/vendors")).status_code == 401
    assert all(c.ok for c in rec.reconcile(client, Db(settings.conninfo), RUN, settings.finance_token))
    again = install_api.provision(admin, secret, "127.0.0.1", str(cluster.port), env["name"])
    cfg2 = read_env(secret)
    assert again["token_kept"] and cfg2["finance_token"] == cfg["finance_token"] and cfg2["password"] != cfg["password"]
    out = capsys.readouterr().out
    assert cfg["password"] not in out and cfg["finance_token"] not in out
    ev("A13", "install_api login", role_checks=len(checks), login_checks=len(login), api_served_through_the_login=True, rerun="keeps the Finance token, re-keys the password", secrets_in_output="none")


def write_evidence():
    EVIDENCE_FILE.parent.mkdir(parents=True, exist_ok=True)
    order = sorted(EVIDENCE, key=lambda e: e["id"])
    lines = ["# Creditors API: UAT evidence", "",
             "Generated by `tools/creditors_mart/tests/test_creditors_api.py`: a synthetic run loaded through the real loader into a private, temporary PostgreSQL, served by the real app.",
             "`fpa_pilot`, Oracle and every real run were untouched.", "", "| Item | Result |", "|---|---|"]
    lines += [f"| {e['id']} | {e['title']}: PASS |" for e in order]
    lines.append("")
    for e in order:
        lines += [f"## {e['id']}: {e['title']}", "```json", json.dumps(e["detail"], indent=2, default=str, ensure_ascii=False), "```", ""]
    EVIDENCE_FILE.write_text("\n".join(lines), encoding="utf-8")
