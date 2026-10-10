"""Connections to the app database `fpa_app`. The app login (fpa_workflow_app) has SELECT / INSERT and explicit UPDATE on projection tables only; it owns nothing."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import psycopg
from psycopg.rows import dict_row

ENV = Path(__file__).resolve().parents[2] / ".env"


def env() -> dict[str, str]:
    out = {}
    for line in ENV.read_text(encoding="utf-8-sig").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def app_connection() -> psycopg.Connection:
    e = env()
    u = urlparse(e["DATABASE_URL"])
    return psycopg.connect(host=u.hostname, port=u.port or 5432, dbname="fpa_app", user="fpa_workflow_app", password=e["FPA_WORKFLOW_PASSWORD"], row_factory=dict_row)
