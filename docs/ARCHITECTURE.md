# Architecture
> **NO LIVE FINANCIAL DATA HAS YET BEEN VALIDATED.** Everything below is design plus code tested on synthetic fixtures.

Oracle/Ginesys (read-only, source of truth) → discovery + ingestion (registry-driven, lineage-stamped) → PostgreSQL `fin` schema (append-only staging → typed facts) → calculation/control layer → FastAPI → React. The frontend never touches Oracle.

## Oracle safety model
- **PRIMARY control (required, outside this code): the Oracle account is SELECT-only.** No CREATE/ALTER/INSERT/UPDATE/DELETE/MERGE/EXECUTE grants are needed for discovery or ingestion. A SELECT can still invoke a function with side effects, so only the grant set is a real boundary. Ask the DBA for a dedicated read-only user and, ideally, no EXECUTE on packages.
- **SECONDARY control (this code):** `app/oracle/client.py` rejects non-SELECT/multi-statement/FOR UPDATE SQL, all identifiers go through `app/identifiers.py` (strict regex + quoting), values are bind variables. This is a regex guard — never treat it as the security boundary (a test pins that `select pkg.fn() from dual` passes the guard).
- No mutation is ever run against Oracle.

## Logical vs physical source model
A *logical* dataset (SITE_REG, GL_REG, MOP, OUTSTANDING) maps to a Ginesys *logical cube* (e.g. `CUBE$FINREGSITE`) with a *copy id*. The *physical* Oracle object (owner, name, type) and its addressing mode — **SEPARATE_OBJECT** (own table/view per copy) or **SHARED_DISCRIMINATOR** (shared object + column=value) — are separate fields, `NULL` until live metadata confirms them. Code obtains a table only through `SourceEntry.require_physical()`, which raises unless status is CONFIRMED. No physical name is ever built from a pattern.

## Identity
- **Source-row identity** = (source_system, source_owner, physical object [+discriminator], copy_id, row_key). Used for ingestion idempotency only.
- **Canonical finance transaction identity** = UNKNOWN (to be derived from live discovery). Reserved column `canonical_txn_key`; no cross-copy dedupe exists or is permitted before it is defined.
- Double-count guards: registry overlap check (code), GiST exclusion constraint (Postgres), source-identity UNIQUE on facts.

## Ingestion semantics
Staging = append-only snapshot history (one row per source-row identity × extract batch; same batch resubmitted is a no-op). Promotion = deterministic idempotent upsert by source-row identity (row-hash change → update; unchanged → no-op; full-refresh scopes tombstone missing rows via `source_deleted_at`, revive if they return). Reference implementation + tests: `app/ingest/`.

Auth/RBAC and `fin.config_audit` are architected, not implemented. Python ≥3.11 (sandbox 3.11), deploy on 3.12.
