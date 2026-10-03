# Architecture
Oracle/Ginesys (read-only, source of truth) → ingestion (registry-driven, lineage-stamped) → PostgreSQL `fin` schema (staging → typed facts) → calculation/control layer (ageing, exceptions) → FastAPI → React. The frontend never touches Oracle.
- CONFIRMED (design): Oracle access only via `app/oracle/client.py`, which rejects non-SELECT/multi-statement/FOR UPDATE SQL. The DB user must independently be read-only.
- Source choice is by registry + date window, never by hardcoded cube code.
- Double-count safeguards: (1) `validate_no_double_coverage` in code, (2) GiST exclusion constraint in Postgres, (3) `UNIQUE(source_object, source_row_key)` on facts.
- Auth/RBAC and config audit (`fin.config_audit`) are architected, not implemented yet.
- Python: sandbox has 3.11; code is 3.11-compatible and targets 3.12 (DECISION D-3).
