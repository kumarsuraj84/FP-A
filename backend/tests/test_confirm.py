import json
import pytest
from app import cli
from app.discovery import cube_registry as cr
from app.discovery.profiler import Target, profile_light
from app.registry.evidence import EvidenceError, MACHINE_VERIFIED, OPERATOR_CONFIRMED, build_evidence
from app.registry.models import PhysicalObject, SEPARATE_OBJECT, SHARED_DISCRIMINATOR
from app.registry.resolver import apply_overlay, find, load_seed
from conftest import FakeOra

SEED = cli.SEED


class MetaOra:
    """Answers the confirm-time metadata lookups with synthetic data."""
    def __init__(self, objects, columns):
        self.objects, self.columns, self.calls = objects, columns, []
    def query(self, sql, params=None):
        self.calls.append(sql); s = " ".join(sql.split())
        if "FROM all_objects" in s:
            t = self.objects.get((params["o"], params["n"])); return [{"OBJECT_TYPE": t}] if t else []
        if "FROM all_tab_columns" in s:
            return [{"COLUMN_NAME": params["c"]}] if params["c"] in self.columns.get((params["o"], params["t"]), ()) else []
        raise AssertionError(f"unexpected SQL: {s}")


@pytest.fixture
def artifact(tmp_path):
    p = tmp_path / "cube_registry_discovery.json"
    p.write_text(json.dumps({"discovered_at": "2026-10-03T00:00:00+00:00", "list": {"rows": [
        {"CUBE_ID": "844", "TBL": "T$FINREGSITE_844", "NM": "SITE REG"},       # 0 full match for SITE_REG
        {"CUBE_ID": "777", "TBL": "CUBE$BILLCOLL", "NM": "SYN_MOP"},          # 1 MOP-like (synthetic)
        {"CUBE_ID": "844", "TBL": "SOMETHING_ELSE", "NM": "x"},               # 2 partial
        {"CUBE_ID": "1", "TBL": "UNRELATED", "NM": "y"}]}}))                  # 3 unrelated
    return str(p)


E844 = lambda: find(load_seed(SEED), "SITE_REG", "844")
OBJS = {("MISRETAIL", "T$FINREGSITE_844"): "TABLE", ("MISRETAIL", "CUBE$BILLCOLL"): "TABLE"}
COLS = {("MISRETAIL", "CUBE$BILLCOLL"): {"CUBENAME", "MOP"}}


def test_separate_confirmation(artifact):
    rec = cr.confirm_mapping(MetaOra(OBJS, COLS), E844(), "MISRETAIL", "T$FINREGSITE_844", evidence_file=artifact, evidence_row=0)
    assert rec["status"] == "CONFIRMED" and rec["physical"]["access_mode"] == SEPARATE_OBJECT
    assert rec["evidence"]["verification"] == MACHINE_VERIFIED and rec["evidence"]["artifact_sha256"]

def test_shared_confirmation_synthetic_example(artifact):
    entry = find(load_seed(SEED), "SITE_REG", "902")     # synthetic stand-in; real MOP mapping is NOT assumed
    ora = MetaOra(OBJS, COLS)
    rec = cr.confirm_mapping(ora, entry, "MISRETAIL", "CUBE$BILLCOLL", access_mode=SHARED_DISCRIMINATOR,
                             discriminator_column="CUBENAME", discriminator_value="SYN_MOP", evidence_file=artifact, evidence_row=1)
    p = rec["physical"]
    assert (p["access_mode"], p["discriminator_column"], p["discriminator_value"]) == (SHARED_DISCRIMINATOR, "CUBENAME", "SYN_MOP")
    assert all("COUNT(" not in q and "FETCH FIRST" not in q for q in ora.calls)     # metadata only, no table scan

def test_shared_without_discriminator_fails(artifact):
    with pytest.raises(ValueError): cr.confirm_mapping(MetaOra(OBJS, COLS), E844(), "MISRETAIL", "CUBE$BILLCOLL",
        access_mode=SHARED_DISCRIMINATOR, evidence_file=artifact, evidence_row=1)
    with pytest.raises(ValueError): cr.confirm_mapping(MetaOra(OBJS, COLS), E844(), "MISRETAIL", "CUBE$BILLCOLL",
        access_mode=SHARED_DISCRIMINATOR, discriminator_column="CUBENAME", evidence_file=artifact, evidence_row=1)

def test_separate_with_discriminator_fails(artifact):
    with pytest.raises(ValueError): cr.confirm_mapping(MetaOra(OBJS, COLS), E844(), "MISRETAIL", "T$FINREGSITE_844",
        discriminator_column="CUBENAME", discriminator_value="X", evidence_file=artifact, evidence_row=0)

def test_discriminator_column_must_exist(artifact):
    with pytest.raises(LookupError, match="discriminator column"):
        cr.confirm_mapping(MetaOra(OBJS, COLS), E844(), "MISRETAIL", "CUBE$BILLCOLL", access_mode=SHARED_DISCRIMINATOR,
                           discriminator_column="NOPE", discriminator_value="SYN_MOP", evidence_file=artifact, evidence_row=1)

def test_missing_object_fails(artifact):
    with pytest.raises(LookupError): cr.confirm_mapping(MetaOra({}, {}), E844(), "MISRETAIL", "GHOST", evidence_file=artifact, evidence_row=0)

def test_overlay_round_trip_preserves_shared_mode(artifact, tmp_path):
    entry = find(load_seed(SEED), "SITE_REG", "902")
    rec = cr.confirm_mapping(MetaOra(OBJS, COLS), entry, "MISRETAIL", "CUBE$BILLCOLL", access_mode=SHARED_DISCRIMINATOR,
                             discriminator_column="CUBENAME", discriminator_value="SYN_MOP", evidence_file=artifact, evidence_row=1)
    ov = tmp_path / "ov.json"; ov.write_text(json.dumps({entry.registry_key: rec}))
    back = find(apply_overlay(load_seed(SEED), ov), "SITE_REG", "902")
    p = back.require_physical()
    assert isinstance(p, PhysicalObject) and p.access_mode == SHARED_DISCRIMINATOR
    assert (p.discriminator_column, p.discriminator_value) == ("CUBENAME", "SYN_MOP")

def test_overlay_round_trip_preserves_separate_mode(artifact, tmp_path):
    rec = cr.confirm_mapping(MetaOra(OBJS, COLS), E844(), "MISRETAIL", "T$FINREGSITE_844", evidence_file=artifact, evidence_row=0)
    ov = tmp_path / "ov.json"; ov.write_text(json.dumps({E844().registry_key: rec}))
    p = find(apply_overlay(load_seed(SEED), ov), "SITE_REG", "844").require_physical()
    assert p.access_mode == SEPARATE_OBJECT and p.discriminator_column is None

def test_shared_discriminator_value_stays_a_bind_variable_when_profiling(artifact, tmp_path):
    entry = find(load_seed(SEED), "SITE_REG", "902")
    rec = cr.confirm_mapping(MetaOra(OBJS, COLS), entry, "MISRETAIL", "CUBE$BILLCOLL", access_mode=SHARED_DISCRIMINATOR,
                             discriminator_column="CUBENAME", discriminator_value="SYN_MOP' OR '1'='1", evidence_file=artifact, evidence_row=1)
    ov = tmp_path / "ov.json"; ov.write_text(json.dumps({entry.registry_key: rec}))
    t = Target.from_physical(find(apply_overlay(load_seed(SEED), ov), "SITE_REG", "902").require_physical())
    o = FakeOra(); profile_light(o, t, date_col="D")
    sql, binds = [c for c in o.calls if "MIN(" in c[0]][0]
    assert ":disc" in sql and "OR '1'='1" not in sql and binds == {"disc": "SYN_MOP' OR '1'='1"}

# ---- evidence ----
def ev(artifact, row, **kw):
    base = dict(registry_key="SITE_REG|CUBE$FINREGSITE|844", copy_id="844", owner="MISRETAIL", object_name="T$FINREGSITE_844",
                access_mode=SEPARATE_OBJECT, discriminator_column=None, discriminator_value=None); base.update(kw)
    return build_evidence(artifact, row, **base)

def test_evidence_full_match_is_machine_verified(artifact):
    e = ev(artifact, 0)
    assert e["verification"] == MACHINE_VERIFIED and e["notes"] == [] and e["evidence_row_snapshot"]["TBL"] == "T$FINREGSITE_844"
    assert e["artifact_discovered_at"] and len(e["artifact_sha256"]) == 64 and e["confirmed_at"]
def test_evidence_partial_match_is_operator_confirmed_with_notes(artifact):
    e = ev(artifact, 2)
    assert e["verification"] == OPERATOR_CONFIRMED and any("object name" in n for n in e["notes"])
def test_evidence_unrelated_row_rejected(artifact):
    with pytest.raises(EvidenceError, match="neither"): ev(artifact, 3)
def test_evidence_row_out_of_range_and_negative(artifact):
    for r in (4, -1, 99):
        with pytest.raises(EvidenceError, match="out of range"): ev(artifact, r)
def test_evidence_missing_file(tmp_path):
    with pytest.raises(EvidenceError, match="not found"): ev(tmp_path / "nope.json", 0)
def test_evidence_wrong_shape(tmp_path):
    p = tmp_path / "x.json"; p.write_text('{"foo": 1}')
    with pytest.raises(EvidenceError, match="not a cube_registry_discovery"): ev(p, 0)
def test_shared_mode_missing_discriminator_value_in_row_downgrades(artifact):
    e = ev(artifact, 1, copy_id="777", object_name="CUBE$BILLCOLL", access_mode=SHARED_DISCRIMINATOR,
           discriminator_column="CUBENAME", discriminator_value="NOT_IN_ROW")
    assert e["verification"] == OPERATOR_CONFIRMED and any("discriminator" in n for n in e["notes"])
def test_evidence_never_claims_machine_verified_when_unchecked(artifact):
    assert ev(artifact, 2)["verification"] != MACHINE_VERIFIED

def test_two_entries_cannot_claim_same_physical_source():
    phys = {"owner": "M", "object_name": "T", "discriminator_column": None, "discriminator_value": None}
    with pytest.raises(ValueError, match="already maps"): cr.assert_not_already_mapped({"A": {"physical": phys}}, "B", phys)
    cr.assert_not_already_mapped({"A": {"physical": phys}}, "A", phys)      # re-confirming itself is fine

# ---- CLI end to end (no Oracle, synthetic) ----
def test_cli_registry_confirm_shared_end_to_end(tmp_path, monkeypatch, artifact, capsys):
    monkeypatch.setattr(cli, "OUT_DIR", tmp_path); monkeypatch.setattr(cli, "OVERLAY", tmp_path / "registry_overlay.json")
    monkeypatch.setattr(cli, "_ora", lambda s, f=None: MetaOra(OBJS, COLS))
    rc = cli.main(["registry-confirm", "SITE_REG", "--copy", "902", "--object", "MISRETAIL.CUBE$BILLCOLL", "--access-mode", "shared",
                   "--discriminator-column", "cubename", "--discriminator-value", "SYN_MOP", "--evidence-file", artifact, "--evidence-row", "1"])
    out = capsys.readouterr().out
    assert rc == 0 and "CONFIRMED (" in out, out
    saved = json.loads((tmp_path / "registry_overlay.json").read_text())["SITE_REG|CUBE$FINREGSITE|902"]
    assert saved["physical"]["discriminator_column"] == "CUBENAME" and saved["evidence"]["evidence_row_index"] == 1

def test_cli_rejects_discriminator_in_separate_mode(tmp_path, monkeypatch, artifact, capsys):
    monkeypatch.setattr(cli, "OUT_DIR", tmp_path); monkeypatch.setattr(cli, "OVERLAY", tmp_path / "registry_overlay.json")
    monkeypatch.setattr(cli, "_ora", lambda s, f=None: MetaOra(OBJS, COLS))
    rc = cli.main(["registry-confirm", "SITE_REG", "--copy", "844", "--object", "MISRETAIL.T$FINREGSITE_844",
                   "--discriminator-column", "X", "--discriminator-value", "Y", "--evidence-file", artifact, "--evidence-row", "0"])
    assert rc == 1 and "must not carry discriminator" in capsys.readouterr().out and not (tmp_path / "registry_overlay.json").exists()

def test_cli_requires_structured_evidence(capsys):
    with pytest.raises(SystemExit): cli.main(["registry-confirm", "SITE_REG", "--copy", "844", "--object", "A.B", "--evidence", "free text"])
