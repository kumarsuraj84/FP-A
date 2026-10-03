# CityKart FP&A / CFO Finance Operating System

SOURCE → TRUSTED FINANCE MART → RECONCILIATION → CFO KPI → DRILL-DOWN → EXCEPTION → ACTION

**Status: Stage 1 hardened (correction cycle 1). NO LIVE FINANCIAL DATA HAS YET BEEN VALIDATED — Oracle discovery is BLOCKED pending a SELECT-only account and network route.**
No CFO frontend is built. See `docs/STAGE1_REPORT.md`.

- `backend/` Python/FastAPI/SQLAlchemy foundation: read-only Oracle client, source registry, discovery profiler, ageing buckets, reconciliation framework, mart DDL (`backend/app/mart/schema.sql`)
- `config/source_registry_seed.csv` source registry seed (all UNVERIFIED)
- `docs/` architecture, registry, discovery runbook, mart, reconciliation, scope, gaps, decisions

Run: `cd backend && pip install -e .[dev] && pytest` · `python -m app.cli --help` (see `docs/DATA_DISCOVERY.md``
Secrets: env only (`.env.example`); `.env` is git-ignored. Oracle access is SELECT-only (code guard + must be a read-only DB account).
