-- PROPOSED finance mart (PostgreSQL). Column names for source fields are UNVERIFIED
-- until DATA_DISCOVERY is run against live Oracle. Lineage columns are mandatory.
CREATE SCHEMA IF NOT EXISTS fin;

CREATE TABLE fin.finance_source_registry (
  id BIGSERIAL PRIMARY KEY,
  source_type TEXT NOT NULL, logical_cube_name TEXT NOT NULL, copy_id TEXT NOT NULL,
  physical_owner TEXT, physical_object TEXT, physical_object_type TEXT,   -- NULL until CONFIRMED from live metadata
  access_mode TEXT, discriminator_column TEXT, discriminator_value TEXT, physical_hint TEXT,
  financial_year TEXT, date_from DATE NOT NULL, date_to DATE NOT NULL,
  is_current BOOLEAN NOT NULL DEFAULT FALSE, is_auto_refresh BOOLEAN NOT NULL DEFAULT FALSE,
  last_refresh_at TIMESTAMPTZ, status TEXT NOT NULL DEFAULT 'UNVERIFIED',
  authoritative BOOLEAN NOT NULL DEFAULT TRUE,
  UNIQUE (source_type, logical_cube_name, copy_id),
  CHECK (status <> 'CONFIRMED' OR (physical_owner IS NOT NULL AND physical_object IS NOT NULL)),
  CHECK (date_from <= date_to)
);
-- DB-level double-coverage safeguard: no two authoritative live sources of one type may overlap.
CREATE EXTENSION IF NOT EXISTS btree_gist;
ALTER TABLE fin.finance_source_registry ADD CONSTRAINT no_double_coverage
  EXCLUDE USING gist (source_type WITH =, daterange(date_from, date_to, '[]') WITH &&)
  WHERE (authoritative AND status <> 'RETIRED');

CREATE TABLE fin.config_audit (
  id BIGSERIAL PRIMARY KEY, changed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  changed_by TEXT NOT NULL, table_name TEXT NOT NULL, row_pk TEXT NOT NULL,
  old_value JSONB, new_value JSONB
);

-- STAGING = append-only snapshot history. Identity of a source row = (system, owner, physical object, copy, row key).
-- Same batch re-submitted -> no-op (ON CONFLICT DO NOTHING). Different batches of the same row are all retained.
CREATE TABLE fin.stg_finance_entry (
  stg_id BIGSERIAL PRIMARY KEY,
  source_system TEXT NOT NULL DEFAULT 'ORACLE_GINESYS',
  source_owner TEXT NOT NULL, source_object TEXT NOT NULL,     -- source_object = PhysicalObject.identity
  source_copy_id TEXT NOT NULL, source_financial_year TEXT,
  source_row_key TEXT NOT NULL,
  extract_batch_id UUID NOT NULL, extracted_at TIMESTAMPTZ NOT NULL, loaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  row_hash TEXT NOT NULL, payload JSONB NOT NULL,
  UNIQUE (source_system, source_owner, source_object, source_copy_id, source_row_key, extract_batch_id)
);

-- FACT = typed, ONE row per source-row identity (idempotent promotion: INSERT .. ON CONFLICT (identity) DO UPDATE
-- when row_hash differs; rows missing from a full-refresh batch of the same physical scope get source_deleted_at set).
-- This is NOT a canonical finance-transaction key: the same row key in two annual copies stays two facts.
-- canonical_txn_key is reserved (NULL) until live discovery establishes the real business key; no cross-copy dedupe before then.
CREATE TABLE fin.fact_finance_entry (
  entry_id BIGSERIAL PRIMARY KEY,
  site_code TEXT, entry_glcode TEXT, entry_slcode TEXT, entry_no TEXT,
  entry_date DATE NOT NULL, entry_type TEXT, narration TEXT,
  debit NUMERIC(20,2) NOT NULL DEFAULT 0, credit NUMERIC(20,2) NOT NULL DEFAULT 0,
  release_status TEXT,
  source_system TEXT NOT NULL, source_owner TEXT NOT NULL, source_object TEXT NOT NULL,
  source_copy_id TEXT NOT NULL, source_financial_year TEXT, source_row_key TEXT NOT NULL,
  row_hash TEXT NOT NULL, canonical_txn_key TEXT,
  extract_batch_id UUID NOT NULL, extracted_at TIMESTAMPTZ NOT NULL, loaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  source_deleted_at TIMESTAMPTZ,
  UNIQUE (source_system, source_owner, source_object, source_copy_id, source_row_key)
);
CREATE INDEX ON fin.fact_finance_entry (entry_date, site_code) WHERE source_deleted_at IS NULL;
CREATE INDEX ON fin.fact_finance_entry (entry_glcode, entry_slcode) WHERE source_deleted_at IS NULL;

CREATE TABLE fin.recon_run (
  id BIGSERIAL PRIMARY KEY, run_at TIMESTAMPTZ NOT NULL DEFAULT now(), scope TEXT NOT NULL,
  check_name TEXT NOT NULL, source_value NUMERIC(24,2) NOT NULL, mart_value NUMERIC(24,2) NOT NULL,
  kpi_value NUMERIC(24,2), explanation TEXT, passed BOOLEAN NOT NULL
);
-- Further tables (dim_*, fact_creditor_outstanding, fact_vendor_advance, fact_cash_bank, ...)
-- are deliberately NOT created until discovery shows the source can support them.
