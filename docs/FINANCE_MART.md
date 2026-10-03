# Finance Mart (PROPOSED)
> **NO LIVE FINANCIAL DATA HAS YET BEEN VALIDATED.** Column names for source fields follow the brief and are UNVERIFIED.

DDL `backend/app/mart/schema.sql`: registry (logical + physical columns, GiST no-double-coverage), `config_audit`, `stg_finance_entry`, `fact_finance_entry`, `recon_run`.

- **Source identity convention (same in Python, staging, fact, tombstone scope):** source_system, source_owner, source_object (object NAME only), source_copy_id, source_discriminator_column, source_discriminator_value (`''` when unused, never NULL), source_row_key.
- **Staging = append-only snapshot history.** UNIQUE (identity…, source_row_key, extract_batch_id). Resubmitting a batch is a no-op; every distinct extract of a row is retained with `row_hash`.
- **Fact = idempotent, one row per source-row identity.** UNIQUE (identity…, source_row_key). Promotion upserts by identity (update only if `row_hash` changed); a full-refresh batch tombstones same-scope rows it no longer contains (`source_deleted_at`); all totals/indexes exclude tombstones. The old key `(source_object, source_row_key)` was removed as insufficient.
- **Source-row identity ≠ canonical transaction identity.** `canonical_txn_key` is reserved/NULL. The same row key in different annual copies is two facts; cross-copy dedupe is forbidden until a real business key is proven from live data. Two shared-object sources with different discriminator values are different sources. Overlapping coverage is prevented at the registry level instead (one authoritative source per type × period).
- Deferred until discovery supports them: dimensions, creditor/advance/unreconciled/cash/budget/P&L/MOP/TDS/petty-cash/service/commitment facts.
- Ageing buckets exist (`app/ageing`), basis-agnostic. No creditor or advance classification exists.
