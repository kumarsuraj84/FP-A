"""Run locally:   cd backend && python -m uvicorn app.creditors_api.main:app --host 127.0.0.1 --port 8081"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import ApiSettings
from .db import Db
from .router import router
from ..cash_api.router import router as cash_router
from ..entry_api.router import router as entry_router


def create_app(settings: ApiSettings | None = None, db: Db | None = None) -> FastAPI:
    settings = settings or ApiSettings.load()
    app = FastAPI(title="CityKart Creditors API", version="1", description="Read-only. Candidate preview of a verified mart run, live after promotion.")
    app.state.settings = settings
    app.state.db = db if db is not None else (Db(settings.conninfo) if settings.conninfo else None)
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_methods=["GET"], allow_headers=["Authorization", "Content-Type"])
    app.include_router(router)
    app.include_router(cash_router)
    app.include_router(entry_router)
    return app


app = create_app()
