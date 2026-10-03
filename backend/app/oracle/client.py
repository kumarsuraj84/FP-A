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


class OracleReadOnly:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()
        if not self.settings.oracle_configured:
            raise RuntimeError("Oracle not configured: set ORACLE_DSN/ORACLE_USER/ORACLE_PASSWORD")

    def query(self, sql: str, params: dict[str, Any] | Sequence[Any] | None = None) -> list[dict]:
        import oracledb  # imported lazily so tests run without a driver/network

        assert_read_only(sql)
        s = self.settings
        with oracledb.connect(user=s.oracle_user, password=s.oracle_password.get_secret_value(), dsn=s.oracle_dsn) as conn:
            conn.autocommit = False
            with conn.cursor() as cur:
                cur.execute(sql, params or {})
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, r)) for r in cur.fetchall()]
