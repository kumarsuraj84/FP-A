import json
from pathlib import Path

import pytest
from app import cli
from app.config import Settings
from app.discovery import cube_registry as cr
from app.discovery import runner, summary
from app.registry.resolver import apply_overlay, find, load_local_entries, load_seed

SEED = cli.SEED
SETTINGS = Settings(_env_file=None, oracle_user="RO_USER", oracle_odbc_dsn="MYDSN", oracle_password="hunter2-pw")
SITE_COLS = [("SITECODE", "VARCHAR2", "N"), ("GLCODE", "VARCHAR2", "N"), ("SLCODE", "VARCHAR2", "Y"), ("ENTRYDATE", "DATE", "N"),
             ("DEBIT", "NUMBER", "N"), ("CREDIT", "NUMBER", "N"), ("RELSTATUS", "VARCHAR2", "Y"), ("NARRATION", "VARCHAR2", "Y")]
OTS_COLS = [("GLCODE", "VARCHAR2", "N"), ("SLCODE", "VARCHAR2", "N"), ("DOCDATE", "DATE", "N"), ("DUEDATE", "DATE", "Y"), ("OUTAMT", "NUMBER", "N")]
LIST_ROWS = [{"CUBE_ID": "844", "CUBE_NAME": "SITE_REG", "TBL": "T$FINREGSITE_844", "CREATED_BY": "alice"},
             {"CUBE_ID": "5", "CUBE_NAME": "UNRELATED", "TBL": "X", "CREATED_BY": "bob"},
             {"CUBE_ID": "900", "CUBE_NAME": "FINOTSD", "TBL": "T$FINOTSD_900", "CREATED_BY": "carol"}]


class LiveFake:
    """Scripted stand-in for CityKart Oracle. Contains deliberately sensitive-looking sample values."""
    def __init__(self, est_rows=1000, priv=("CREATE SESSION",), fail=False):
        self.est_rows, self.priv, self.fail, self.calls, self.driver = est_rows, priv, fail, [], "odbc"

    def query(self, sql, params=None):
        if self.fail: raise RuntimeError("[ODBC] DSN=MYDSN;UID=RO_USER;PWD=hunter2-pw login failed")
        self.calls.append(" ".join(sql.split())); s = self.calls[-1]; p = params or {}
        if s.startswith("SELECT 1 AS ok"): return [{"OK": 1}]
        if "SELECT USER AS v" in s: return [{"V": "RO_USER"}]
        if "v$version" in s: return [{"V": "Oracle Database 19c"}]
        if "SYS_EXTRACT_UTC" in s: return [{"V": "2026-10-04 06:00:00"}]
        if "FROM session_privs" in s: return [{"PRIVILEGE": x} for x in self.priv]
        if "FROM all_synonyms" in s: return []
        if "FROM all_objects WHERE object_name = :n" in s: return [{"OWNER": "MISRETAIL", "OBJECT_NAME": "OLAP_DATACUBE_LIST", "OBJECT_TYPE": "TABLE"}]
        if "FROM all_objects WHERE object_name LIKE" in s:
            return [{"OWNER": "MISRETAIL", "OBJECT_NAME": "V_FINANCE_MOP_OUTPUT", "OBJECT_TYPE": "VIEW", "LAST_DDL_TIME": "2026-01-01"}] \
                if p["p"] == "V_FINANCE_MOP_OUTPUT" else []
        if "FROM all_objects WHERE owner" in s: return [{"OBJECT_TYPE": "TABLE"}]
        if "FROM all_views" in s: return [{"TEXT": "SELECT SITE, MOP FROM T$BILLCOLL"}]
        if "FROM all_dependencies" in s: return [{"REFERENCED_OWNER": "MISRETAIL", "REFERENCED_NAME": "CUBE$BILLCOLL", "REFERENCED_TYPE": "TABLE"}]
        if "FROM all_tab_columns" in s:
            name = p.get("t")
            cols = {"OLAP_DATACUBE_LIST": [(c, "VARCHAR2", "Y") for c in ("CUBE_ID", "CUBE_NAME", "TBL", "CREATED_BY")],
                    "T$FINREGSITE_844": SITE_COLS, "T$FINOTSD_900": OTS_COLS}.get(name, [("C", "VARCHAR2", "Y")])
            return [{"COLUMN_NAME": c, "DATA_TYPE": t, "DATA_LENGTH": 10, "DATA_PRECISION": None, "DATA_SCALE": None, "NULLABLE": n} for c, t, n in cols]
        if "FROM all_tables" in s: return [{"NUM_ROWS": self.est_rows if p.get("t") == "T$FINREGSITE_844" else 50, "LAST_ANALYZED": "2026-10-01"}]
        if "FROM all_constraints" in s: return [{"CNAME": "PK_SITE", "CTYPE": "P", "CSTATUS": "ENABLED", "CVALIDATED": "VALIDATED", "COL": "ENTRYNO", "POS": 1}]
        if "FROM all_indexes" in s: return []
        if "GROUP BY" in s: return [{"GRP": "RELEASED", "N": 90, "DEBIT": 9, "CREDIT": 9}, {"GRP": None, "N": 10, "DEBIT": 1, "CREDIT": 1}]
        if "COUNT(*) AS n, MIN(" in s:
            r = {"N": 100, "DMIN": "2026-04-01", "DMAX": "2026-10-02", "DEBIT": 1000, "CREDIT": 1000}
            r.update({f"D{i}": 7 + i for i in range(3)}); return r and [r]
        if "OLAP_DATACUBE_LIST" in s and "FETCH FIRST" in s: return [dict(r) for r in LIST_ROWS]
        if "FETCH FIRST 5 ROWS ONLY" in s or "FETCH FIRST" in s:
            return [{"SITECODE": "S1", "NARRATION": "PAID TO ACME VENDOR PRIVATE", "DEBIT": 123.45}]
        raise AssertionError(f"unscripted SQL: {s}")

    def data_queries(self): return [q for q in self.calls if runner.classify(q) != "METADATA"]


@pytest.fixture
def env(tmp_path):
    out = tmp_path / "gen"
    def load():
        e = load_seed(SEED) + load_local_entries(out / "local_entries.json")
        return apply_overlay(e, out / "registry_overlay.json")
    lines = []
    def go(gate, ora, **args):
        return runner.run_gate(gate, ora=ora, out=out, load_entries=load, args=args, echo=lines.append, settings=SETTINGS)
    return out, go, lines, load


def confirm(out, ora, copy, obj, row):
    entry = find(load_seed(SEED) + load_local_entries(out / "local_entries.json"), "SITE_REG" if copy == "844" else "OUTSTANDING", copy)
    rec = cr.confirm_mapping(ora, entry, "MISRETAIL", obj, evidence_file=str(out / "cube_registry_discovery.json"), evidence_row=row)
    p = out / "registry_overlay.json"; ov = json.loads(p.read_text()) if p.exists() else {}
    ov[entry.registry_key] = rec; p.write_text(json.dumps(ov))
    return rec


ROLES = dict(date_col="entrydate", debit_col="debit", credit_col="credit", site_col="sitecode", gl_col="glcode", sl_col="slcode", release_col="relstatus")


def test_gates_cannot_be_skipped(env):
    out, go, lines, _ = env; o = LiveFake()
    assert go(3, o) == 2 and "requires gate 2" in " ".join(lines)
    assert go(4, o) == 2 and o.calls == []             # nothing touched Oracle

def test_connection_failure_stops_and_redacts(env):
    out, go, lines, _ = env
    assert go(1, LiveFake(fail=True)) == 1
    txt = " ".join(lines)
    assert "STOP" in txt and "hunter2" not in txt and "RO_USER" not in txt and "MYDSN" not in txt
    assert runner.load_state(out)["completed_gates"] == []

def test_gate1_flags_write_capable_account(env):
    out, go, lines, _ = env
    assert go(1, LiveFake(priv=("CREATE SESSION", "DELETE ANY TABLE"))) == 0
    assert "WRITE_CAPABLE_PRIVILEGES_PRESENT" in " ".join(lines) and "WARNING" in " ".join(lines)
    assert go(1, LiveFake()) == 0 and "APPEARS_READ_ONLY" in " ".join(lines)

def test_gate2_does_not_auto_confirm_and_stops(env):
    out, go, lines, _ = env; o = LiveFake()
    assert go(1, o) == 0 and go(2, o) == 0
    assert (out / "cube_registry_discovery.json").exists() and (out / "pnl_definitions.json").exists()
    assert not (out / "registry_overlay.json").exists()            # operator must confirm
    assert "never auto-confirmed" in " ".join(lines)
    assert all(runner.classify(q) == "METADATA" or "OLAP_DATACUBE_LIST" in q for q in o.calls)

def test_gate3_blocked_until_site_reg_confirmed(env):
    out, go, lines, _ = env; o = LiveFake()
    go(1, o); go(2, o); n = len(o.calls)
    assert go(3, o) == 2 and "BLOCKED" in " ".join(lines) and len(o.calls) == n      # no Oracle query at all

def prepared(env, o=None):
    out, go, lines, _ = env; o = o or LiveFake()
    go(1, o); go(2, o); confirm(out, o, "844", "T$FINREGSITE_844", 0); assert go(3, o) == 0
    return o

def test_gate3_metadata_only(env):
    out, go, lines, _ = env; o = LiveFake(); before = len(o.calls)
    prepared(env, o)
    assert o.data_queries() == [] or all("OLAP_DATACUBE_LIST" in q for q in o.data_queries())
    assert (out / "object_T_FINREGSITE_844.json").exists() or any(p.name.startswith("object_") for p in out.iterdir())
    assert any(p.name.startswith("keys_") for p in out.iterdir())

def test_gate4_requires_explicit_roles_and_valid_columns(env):
    out, go, lines, _ = env; o = prepared(env); n = len(o.data_queries())
    assert go(4, o) == 1 and "explicit column roles" in " ".join(lines)
    assert go(4, o, **{**ROLES, "debit_col": "NOPE"}) == 1 and "not a column" in " ".join(lines)
    assert len(o.data_queries()) == n            # nothing scanned

def test_gate4_light_profile_one_aggregate_one_sample_no_null_scans(env):
    out, go, lines, _ = env; o = prepared(env); base = len(o.data_queries())
    assert go(4, o, **ROLES) == 0
    new = o.data_queries()[base:]
    assert len(new) == 2 and sum("COUNT(*) AS n, MIN(" in q for q in new) == 1 and sum("FETCH FIRST 5 ROWS ONLY" in q for q in new) == 1
    assert not any("COUNT(\"" in q for q in new)               # no per-column null counting (DEEP mode)
    nm = next(p for p in out.iterdir() if p.name.startswith("profile_light_"))
    assert "sample_rows" not in nm.read_text()
    local = next(p for p in out.iterdir() if p.name.startswith("LOCAL_ONLY_"))
    d = json.loads(local.read_text()); assert "DO NOT SHARE" in d["WARNING"] and d["sample_rows"][0]["NARRATION"]

def test_gate4_stops_on_large_table_unless_allowed(env):
    out, go, lines, _ = env; o = prepared(env, LiveFake(est_rows=50_000_000)); base = len(o.data_queries())
    assert go(4, o, **ROLES) == 2 and "STOP" in " ".join(lines) and len(o.data_queries()) == base
    assert go(4, o, **ROLES, allow_large=True) == 0

def test_gate5_release_groups_then_outstanding_pending_then_complete(env):
    out, go, lines, load = env; o = prepared(env); go(4, o, **ROLES)
    assert go(5, o) == 3                                      # OUTSTANDING not mapped yet
    st = runner.load_state(out); assert st["release_group_done"] and 5 not in st["completed_gates"]
    assert st["outstanding_candidates"][0]["row_index"] == 2
    # operator adds and confirms OUTSTANDING (never done by the runner)
    cli_args = cli.build_parser().parse_args(["registry-add", "--source-type", "OUTSTANDING", "--logical-cube", "CUBE$FINOTSD",
        "--copy-id", "900", "--date-from", "2026-04-01", "--date-to", "2027-03-31", "--current"])
    (out / "local_entries.json").write_text(json.dumps([{"source_type": "OUTSTANDING", "logical_cube_name": "CUBE$FINOTSD", "copy_id": "900",
        "financial_year": "FY26-27", "date_from": "2026-04-01", "date_to": "2027-03-31", "is_current": True}]))
    confirm(out, o, "900", "T$FINOTSD_900", 2)
    groups_before = sum("GROUP BY" in q for q in o.calls)
    assert go(5, o) == 0
    assert sum("GROUP BY" in q for q in o.calls) == groups_before            # release aggregate not repeated
    assert 5 in runner.load_state(out)["completed_gates"]

def test_summary_is_sanitized(env):
    out, go, lines, load = env; o = prepared(env); go(4, o, **ROLES); go(5, o)
    text = (out / summary.SUMMARY_NAME).read_text()
    for leak in ("PAID TO ACME VENDOR PRIVATE", "alice", "bob", "carol", "hunter2", "RO_USER", "MYDSN", "sample_rows", "NARRATION\": \"PAID"):
        assert leak not in text, leak
    s = json.loads(text)
    assert "CREATED_BY" in s["cube_registry"]["redacted_columns"] and all("CREATED_BY" not in r for r in s["cube_registry"]["finance_related_rows"])
    assert [r["CUBE_NAME"] for r in s["cube_registry"]["finance_related_rows"]] == ["SITE_REG", "FINOTSD"]     # finance rows only
    assert s["site_reg"]["light_profile"]["aggregates"]["N"] == 100 and s["site_reg"]["release_status_groups"]["groups"][0]["GRP"] == "RELEASED"
    assert s["site_reg"]["key_candidates"]["recommendation"] and s["environment"]["version"].startswith("Oracle")
    assert "user" not in s["environment"] and "local_only" not in text.lower()
    assert s["finance_reporting_objects"][0]["depends_on"][0]["REFERENCED_NAME"] == "CUBE$BILLCOLL"
    assert s["data_queries_executed"] and all(q["kind"] != "METADATA" for q in s["data_queries_executed"])

def test_summary_rewritten_after_every_gate(env):
    out, go, lines, _ = env; o = LiveFake(); go(1, o)
    assert json.loads((out / summary.SUMMARY_NAME).read_text())["gates_completed"] == [1]
    go(2, o); assert json.loads((out / summary.SUMMARY_NAME).read_text())["gates_completed"] == [1, 2]

def test_next_gate_progression(env):
    out, go, lines, _ = env; assert runner.next_gate(out) == 1
    go(1, LiveFake()); assert runner.next_gate(out) == 2

def test_registry_add_rejects_overlap_and_rolls_back(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "OUT_DIR", tmp_path); monkeypatch.setattr(cli, "OVERLAY", tmp_path / "registry_overlay.json")
    ok = ["registry-add", "--source-type", "OUTSTANDING", "--logical-cube", "CUBE$FINOTSD", "--copy-id", "900",
          "--date-from", "2026-04-01", "--date-to", "2027-03-31"]
    assert cli.main(ok) == 0
    assert cli.main(["registry-add", "--source-type", "SITE_REG", "--logical-cube", "CUBE$FINREGSITE", "--copy-id", "ZZ",
                     "--date-from", "2026-04-01", "--date-to", "2026-12-31"]) == 1       # overlaps seeded FY26-27 coverage
    assert len(json.loads((tmp_path / "local_entries.json").read_text())) == 1          # rolled back
