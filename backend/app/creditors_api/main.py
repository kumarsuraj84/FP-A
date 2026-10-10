"""Run locally:   cd backend && python -m uvicorn app.creditors_api.main:app --host 127.0.0.1 --port 8081"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import ApiSettings
from .db import Db
from ..gold import db as gold
from .router import router
from ..cash_api.router import router as cash_router
from ..entry_api.router import router as entry_router
from ..pnl_api.router import router as pnl_router
from ..gold.ledger_entries import router as ledger_entries_router
from ..pnl_api.review_router import router as pnl_review_router
from ..mgmt.router import router as mgmt_router
from ..gold.related_party import router as related_party_router
from ..auth.router import router as auth_router
from ..adjustments.router import router as adjustments_router
from ..corrections.router import router as corrections_router
from ..inbox.router import router as inbox_router
from ..close.router import router as close_router
from ..mapping.router import router as mapping_router
from ..sourcefix.router import router as sourcefix_router
from ..auth.middleware import RequireSession


def create_app(settings: ApiSettings | None = None, db: Db | None = None) -> FastAPI:
    settings = settings or ApiSettings.load()
    app = FastAPI(title="CityKart Creditors API", version="1", description="Read-only. Candidate preview of a verified mart run, live after promotion.")
    app.state.settings = settings
    if db is None and gold.enabled():
        url = gold.database_url()
        db = gold.GoldDb(url) if url else None            # FPA_SOURCE=gold: read gold_fpa in the common Postgres as fpa_ro
        settings = settings.__class__(conninfo=url, finance_token=settings.finance_token, cors_origins=settings.cors_origins)
        app.state.settings = settings
    app.state.db = db if db is not None else (Db(settings.conninfo) if settings.conninfo else None)
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_methods=["GET"], allow_headers=["Authorization", "Content-Type"])
    app.add_middleware(RequireSession)      # FPA_REQUIRE_SESSION=1: every /api/v1 data route needs a signed-in session (off by default)
    app.include_router(router)
    app.include_router(cash_router)
    app.include_router(entry_router)
    app.include_router(ledger_entries_router)
    app.include_router(pnl_router)
    app.include_router(pnl_review_router)
    app.include_router(mgmt_router)
    app.include_router(related_party_router)
    app.include_router(auth_router)
    app.include_router(adjustments_router)
    app.include_router(corrections_router)
    app.include_router(inbox_router)
    app.include_router(close_router)
    app.include_router(mapping_router)
    app.include_router(sourcefix_router)
    return app


app = create_app()
