import sys
import types
import pytest
from app import cli
from app.config import Settings
from app.oracle.client import OracleReadOnly, to_positional


def S(**kw): return Settings(_env_file=None, **kw)

def test_named_to_positional_in_order_and_repeats():
    sql, args = to_positional("SELECT 1 FROM t WHERE a = :x AND b = :y AND c = :x", {"x": 1, "y": 2})
    assert sql.count("?") == 3 and args == [1, 2, 1]
def test_binds_inside_literals_and_quoted_identifiers_untouched():
    sql, args = to_positional("""SELECT ':nope' AS a, "COL:x" FROM t WHERE k = :k""", {"k": 9})
    assert ":nope" in sql and '"COL:x"' in sql and args == [9] and sql.endswith("= ?")
def test_missing_or_unused_bind_is_an_error():
    with pytest.raises(ValueError, match="missing"): to_positional("SELECT :a FROM dual", {})
    with pytest.raises(ValueError, match="unused"): to_positional("SELECT 1 FROM dual", {"a": 1})
def test_no_params_passthrough():
    assert to_positional("SELECT 1 FROM dual", None) == ("SELECT 1 FROM dual", [])

def test_driver_selection():
    assert S(oracle_odbc_dsn="D").resolved_driver == "odbc" and S(oracle_odbc_dsn="D").oracle_configured
    assert S(oracle_dsn="h/s", oracle_user="u", oracle_password="p").resolved_driver == "oracledb"
    assert not S(oracle_dsn="h/s").oracle_configured and not S().oracle_configured
    assert S(oracle_odbc_dsn="D", oracle_dsn="h/s", oracle_user="u", oracle_password="p", oracle_driver="oracledb").resolved_driver == "oracledb"

class FakeCursor:
    description = [("ok",), ("n",)]
    def __init__(self, log): self.log = log
    def execute(self, sql, *args): self.log.append((sql, args))
    def fetchall(self): return [(1, 2)]

def install_fake_pyodbc(monkeypatch, log):
    class Conn:
        def cursor(self): return FakeCursor(log)
        def close(self): log.append("closed")
    mod = types.SimpleNamespace(connect=lambda cs, autocommit=False: (log.append(("connect", cs)), Conn())[1])
    monkeypatch.setitem(sys.modules, "pyodbc", mod)

def test_odbc_query_uses_positional_params_upper_keys_and_closes(monkeypatch):
    log = []; install_fake_pyodbc(monkeypatch, log)
    o = OracleReadOnly(S(oracle_odbc_dsn="MYDSN", oracle_user="u", oracle_password="p"))
    rows = o.query("SELECT 1 FROM all_objects WHERE owner = :o", {"o": "MISRETAIL"})
    assert rows == [{"OK": 1, "N": 2}]
    assert log[0] == ("connect", "DSN=MYDSN;UID=u;PWD=p") and log[1] == ("SELECT 1 FROM all_objects WHERE owner = ?", ("MISRETAIL",)) and log[-1] == "closed"

def test_odbc_dsn_only_has_no_credentials_in_string(monkeypatch):
    log = []; install_fake_pyodbc(monkeypatch, log)
    OracleReadOnly(S(oracle_odbc_dsn="MYDSN")).query("SELECT 1 FROM dual")
    assert log[0] == ("connect", "DSN=MYDSN")

def test_guard_still_applies_before_any_connection(monkeypatch):
    log = []; install_fake_pyodbc(monkeypatch, log)
    from app.oracle.client import UnsafeSQLError
    with pytest.raises(UnsafeSQLError): OracleReadOnly(S(oracle_odbc_dsn="D")).query("DELETE FROM t")
    assert log == []

def test_redaction_covers_odbc_strings():
    s = S(oracle_odbc_dsn="MYDSN", oracle_user="svc_ro", oracle_password="p@ss", oracle_odbc_connection_string="DSN=X;UID=a;PWD=zzz")
    out = cli.redact("[ODBC] DSN=MYDSN;UID=svc_ro;PWD=p@ss failed; DSN=X;UID=a;PWD=zzz", s)
    for leak in ("p@ss", "svc_ro", "zzz", "MYDSN"): assert leak not in out
