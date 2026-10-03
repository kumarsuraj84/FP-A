"""Read-only Oracle access. Defence in depth: the SQL guard rejects anything that
is not a single SELECT/WITH statement; the DB account must ALSO be read-only."""
import re
from typing import Any, Sequence

from app.config import Settings

_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|merge|drop|alter|create|truncate|grant|revoke|"
    r"execute|exec|call|begin|declare|commit|rollback|lock|rename|comment)\b",
    re.IGNORECASE,
)


class UnsafeSQLError(ValueError):
    pass


def assert_read_only(sql: str) -> str:
    stripped = re.sub(r"--[^\n]*|/\*.*?\*/", " ", sql, flags=re.S).strip().rstrip(";").strip()
    if ";" in stripped:
        raise UnsafeSQLError("multiple statements are not allowed")
    if not re.match(r"(?is)^(select|with)\b", stripped):
        raise UnsafeSQLError("only SELECT/WITH statements are allowed")
    # strip string literals before keyword scan so e.g. 'DELETE' in a literal is fine
    no_literals = re.sub(r"'(?:[^']|'')*'", "''", stripped)
    m = _FORBIDDEN.search(no_literals)
    if m:
        raise UnsafeSQLError(f"forbidden keyword: {m.group(1)}")
    if re.search(r"(?i)\bfor\s+update\b", no_literals):
        raise UnsafeSQLError("FOR UPDATE is not allowed")
    return sql


_BIND = re.compile(r"""'(?:[^']|'')*'|"(?:[^"])*"|:([A-Za-z_][A-Za-z0-9_]*)""")


def to_positional(sql: str, params: dict[str, Any] | None) -> tuple[str, list]:
    """ODBC takes positional `?`. Convert :name binds (outside string literals / quoted identifiers)
    to `?`, in order of appearance, repeating a value when a name repeats. Strict: every bind needs
    a value and every supplied value must be used, so a typo can never silently change a query."""
    params = params or {}
    names: list[str] = []

    def sub(m):
        if m.group(1) is None:
            return m.group(0)
        names.append(m.group(1))
        return "?"

    out = _BIND.sub(sub, sql)
    missing = [n for n in names if n not in params]
    if missing:
        raise ValueError(f"missing bind values: {sorted(set(missing))}")
    unused = set(params) - set(names)
    if unused:
        raise ValueError(f"unused bind values: {sorted(unused)}")
    return out, [params[n] for n in names]


class OracleReadOnly:
    """Executes guarded SELECTs over ODBC (pyodbc) or oracledb thin. Result rows are dicts with
    UPPER-CASE keys regardless of driver."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()
        if not self.settings.oracle_configured:
            raise RuntimeError("Oracle not configured: set ORACLE_ODBC_DSN (ODBC) or ORACLE_DSN/ORACLE_USER/ORACLE_PASSWORD")
        self.driver = self.settings.resolved_driver

    def _odbc_connection_string(self) -> str:
        s = self.settings
        if s.oracle_odbc_connection_string:
            return s.oracle_odbc_connection_string.get_secret_value()
        parts = [f"DSN={s.oracle_odbc_dsn}"]
        if s.oracle_user:
            parts.append(f"UID={s.oracle_user}")
        if s.oracle_password:
            parts.append(f"PWD={s.oracle_password.get_secret_value()}")
        return ";".join(parts)

    def query(self, sql: str, params: dict[str, Any] | None = None) -> list[dict]:
        assert_read_only(sql)
        if self.driver == "odbc":
            import pyodbc  # lazy: tests and oracledb users don't need it

            text, args = to_positional(sql, params)
            conn = pyodbc.connect(self._odbc_connection_string(), autocommit=False)
            try:
                cur = conn.cursor()
                cur.execute(text, *args)
                cols = [d[0].upper() for d in cur.description]
                return [dict(zip(cols, r)) for r in cur.fetchall()]
            finally:
                conn.close()
        import oracledb

        s = self.settings
        with oracledb.connect(user=s.oracle_user, password=s.oracle_password.get_secret_value(), dsn=s.oracle_dsn) as conn:
            conn.autocommit = False
            with conn.cursor() as cur:
                cur.execute(sql, params or {})
                cols = [d[0].upper() for d in cur.description]
                return [dict(zip(cols, r)) for r in cur.fetchall()]
