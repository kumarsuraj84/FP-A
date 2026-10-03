import json
import pytest
from app import cli
from app.registry.models import PhysicalUnresolvedError
from conftest import FakeOra

def test_registry_status_prints_unverified(capsys):
    assert cli.main(["registry-status"]) == 0
    out = capsys.readouterr().out
    assert "UNVERIFIED" in out and "physical=-" in out and "CONFIRMED" not in out.split("NOTE")[0]

def test_oracle_commands_blocked_without_credentials(monkeypatch, capsys):
    for k in ("ORACLE_DSN", "ORACLE_USER", "ORACLE_PASSWORD"): monkeypatch.delenv(k, raising=False)
    monkeypatch.chdir("/tmp")
    assert cli.main(["oracle-check"]) == 2 and "BLOCKED" in capsys.readouterr().out

def test_profile_source_refuses_unconfirmed_mapping(capsys):
    rc = cli.main(["profile-source", "SITE_REG", "--copy", "844"], ora_factory=FakeOra)
    out = capsys.readouterr().out
    assert rc == 1 and "no CONFIRMED physical object" in out

def test_redaction(monkeypatch):
    monkeypatch.setenv("ORACLE_PASSWORD", "s3cr3t!"); monkeypatch.setenv("ORACLE_DSN", "dbhost:1521/svc")
    msg = cli.redact("ORA-12541 connecting dbhost:1521/svc password=s3cr3t! failed")
    assert "s3cr3t" not in msg and "dbhost" not in msg

def test_discover_object_with_explicit_object_is_metadata_only(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "OUT_DIR", tmp_path); monkeypatch.setattr(cli, "ROOT", tmp_path.parent)
    o = FakeOra()
    monkeypatch.setattr(cli, "_ora", lambda s, f=None: o)
    monkeypatch.setattr(cli, "_emit", lambda n, d: (tmp_path / f"{n}.json").write_text(json.dumps(d, default=str)))
    assert cli.main(["discover-object", "SITE_REG", "--copy", "844", "--object", "MISRETAIL.T$FINREGSITE_844"]) == 0
    assert all("COUNT(" not in s and "FETCH FIRST" not in s for s, _ in o.calls)   # no table scan, no row read
    assert "UNVERIFIED" in (tmp_path / "object_T$FINREGSITE_844.json").read_text()
