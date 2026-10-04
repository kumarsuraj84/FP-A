import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import migrate  # noqa: E402


def test_prompt_builds_a_safe_connection_even_for_awkward_passwords(monkeypatch):
    monkeypatch.delenv("FPA_PG_ADMIN_URL", raising=False)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    answers = iter(["", "", "admin"])
    monkeypatch.setattr("builtins.input", lambda *_: next(answers))
    monkeypatch.setattr("getpass.getpass", lambda *_: "p@ss:w/rd %40")
    info = migrate.admin_conninfo()
    from psycopg.conninfo import conninfo_to_dict

    d = conninfo_to_dict(info)
    assert d["host"] == "localhost" and d["port"] == "5432" and d["user"] == "admin" and d["password"] == "p@ss:w/rd %40" and d["dbname"] == "postgres"
    assert migrate.with_database(info, "fpa_pilot").count("fpa_pilot") == 1


def test_no_prompt_without_a_terminal_and_urls_are_redacted(monkeypatch):
    monkeypatch.delenv("FPA_PG_ADMIN_URL", raising=False)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert migrate.admin_conninfo() is None
    assert "secret" not in migrate.redact("could not connect to postgresql://admin:secret@localhost:5432/postgres")
    monkeypatch.setenv("FPA_PG_ADMIN_URL", "postgresql://a:b@localhost/postgres")
    assert migrate.admin_conninfo() == "postgresql://a:b@localhost/postgres"


def test_protected_databases_are_refused():
    import pytest

    for name in ("fpa", "postgres", "template1"):
        with pytest.raises(SystemExit):
            migrate.create_database("host=localhost user=x", name)
