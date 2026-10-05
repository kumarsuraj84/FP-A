"""entry_pilot_01 source readiness: the cheap pre-check that runs before any extract. No Oracle, no service."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import broker  # noqa: E402
import guard  # noqa: E402
import packages  # noqa: E402
import readiness as rd  # noqa: E402

GOOD_REG = {"register_rows": 1_000_000.0, "register_report_date": "2026-10-05"}
GOOD_CUBE = {"cube_report_date": "2026-10-05"}


def test_ready_when_non_empty_dated_and_equal_to_the_cube():
    assert rd.assess(GOOD_REG, GOOD_CUBE, None) == (True, "ready")


@pytest.mark.parametrize("reg,cube,reason", [
    ({"register_rows": 0.0, "register_report_date": None}, GOOD_CUBE, rd.EMPTY),
    ({"register_rows": None, "register_report_date": None}, GOOD_CUBE, rd.EMPTY),
    ({"register_rows": 5.0, "register_report_date": None}, GOOD_CUBE, rd.DATE_UNAVAILABLE),
    (GOOD_REG, {"cube_report_date": None}, rd.CUBE_DATE_UNAVAILABLE),
    ({**GOOD_REG, "register_report_date": "2026-10-04"}, GOOD_CUBE, rd.MISMATCH),
    (None, GOOD_CUBE, rd.PROBE_FAILED),
    (GOOD_REG, None, rd.PROBE_FAILED),
])
def test_each_failure_has_its_own_clean_reason(reg, cube, reason):
    assert rd.assess(reg, cube, None) == (False, reason)


def test_a_collapse_against_the_last_good_snapshot_is_a_refresh_in_progress():
    base = {"register_rows": 1_000_000}
    assert rd.assess({**GOOD_REG, "register_rows": 400_000.0}, GOOD_CUBE, base) == (False, rd.COLLAPSED)
    assert rd.assess({**GOOD_REG, "register_rows": 600_000.0}, GOOD_CUBE, base)[0]      # ordinary variation passes
    assert rd.assess({**GOOD_REG, "register_rows": 10.0}, GOOD_CUBE, None)[0]            # no baseline yet: the three checks alone decide


def test_the_baseline_only_ratchets_up(tmp_path):
    f = tmp_path / "b.json"
    rd.record_baseline(f, 900, "2026-10-05")
    rd.record_baseline(f, 100, "2026-10-06")
    assert rd.load_baseline(f)["register_rows"] == 900
    rd.record_baseline(f, 1200, "2026-10-07")
    assert rd.load_baseline(f)["register_rows"] == 1200
    assert rd.load_baseline(tmp_path / "missing.json") is None


def test_probe_queries_are_guarded_misretail_only_and_tiny():
    for d in packages.ENTRY_READINESS:
        c = guard.check(d.sql, d.kind)
        assert c.row_cap <= 5 and "SSRK" not in d.sql.upper() and "PUBLIC" not in d.sql.upper()
        for obj in re.findall(r"(?i)\b(?:from|join)\s+([\w$#\".]+)", d.sql):
            assert obj.upper().startswith("MISRETAIL."), obj


def _stub(monkeypatch, tmp_path, answers):
    monkeypatch.setattr(broker, "INBOX", tmp_path / "inbox")
    monkeypatch.setattr(broker, "BASELINE", tmp_path / "inbox" / ".b.json")
    (tmp_path / "inbox").mkdir()
    monkeypatch.setattr(broker, "find_oracle_connection", lambda: 1)
    monkeypatch.setattr(broker, "backup_platform_db", lambda: tmp_path / "backup.db")
    it = iter(answers)
    monkeypatch.setattr(broker, "_probe", lambda conn_id, d: next(it))
    monkeypatch.setattr(broker, "ensure_query", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no extract query may be created")))


@pytest.mark.parametrize("answers,reason", [
    ([{"register_rows": 0.0, "register_report_date": None}, GOOD_CUBE], "register empty"),
    ([GOOD_REG, None], "readiness probe did not complete"),
    ([{**GOOD_REG, "register_report_date": "2026-10-04"}, GOOD_CUBE], "snapshot mismatch"),
])
def test_a_source_that_is_not_ready_creates_no_run_folder_and_extracts_nothing(monkeypatch, tmp_path, capsys, answers, reason):
    packages.configure_entry("2026-10-05")
    _stub(monkeypatch, tmp_path, answers)
    assert broker.cmd_run("entry_pilot_01", None) == 3
    out = capsys.readouterr().out
    assert f"SOURCE_NOT_READY — {reason}" in out
    assert list((tmp_path / "inbox").glob("run_*")) == []


def test_a_ready_source_proceeds_to_the_run_and_records_the_baseline(monkeypatch, tmp_path):
    packages.configure_entry("2026-10-05")
    _stub(monkeypatch, tmp_path, [GOOD_REG, GOOD_CUBE])
    with pytest.raises(AssertionError, match="no extract query"):          # the stub stops the first real dataset: the run DID start
        broker.cmd_run("entry_pilot_01", None)
    assert rd.load_baseline(tmp_path / "inbox" / ".b.json")["register_rows"] == 1_000_000
    assert len(list((tmp_path / "inbox").glob("run_*"))) == 1
