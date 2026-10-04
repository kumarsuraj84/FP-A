"""Settings come from the environment or the git-ignored .secrets/cred_api.env. Secrets are never defaulted, printed or logged."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

SECRET_FILE = Path(__file__).resolve().parents[3] / ".secrets" / "cred_api.env"


def read_env_file(path: Path) -> dict:
    out = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return out


@dataclass(frozen=True)
class ApiSettings:
    conninfo: str | None
    finance_token: str | None
    cors_origins: tuple[str, ...]

    @staticmethod
    def load() -> "ApiSettings":
        from psycopg.conninfo import make_conninfo

        cfg = read_env_file(Path(os.environ.get("FPA_CRED_API_ENV", SECRET_FILE)))
        url = os.environ.get("FPA_CRED_API_URL")
        conninfo = url or (make_conninfo(host=cfg.get("host", "localhost"), port=cfg.get("port", "5432"), dbname=cfg.get("dbname", "fpa_pilot"),
                                         user=cfg["user"], password=cfg["password"]) if cfg.get("password") else None)
        token = os.environ.get("FPA_CRED_FINANCE_TOKEN") or cfg.get("finance_token")
        origins = tuple(o for o in os.environ.get("FPA_CRED_CORS", "http://localhost:5180,http://127.0.0.1:5180,http://localhost:5173,http://127.0.0.1:5173").split(",") if o)
        return ApiSettings(conninfo=conninfo, finance_token=token, cors_origins=origins)
