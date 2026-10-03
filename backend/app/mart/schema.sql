-- PROPOSED finance mart (PostgreSQL). Column names for source fields are UNVERIFIED
-- until DATA_DISCOVERY is run against live Oracle. Lineage columns are mandatory.
CREATE SCHEMA IF NOT EXISTS fin;

CREATE TABLE fin.finance_source_registry (
  id BIGSERIAL PRIMARY KEY,
  source_type TEXT NOT NULL, cube_name TEXT NOT NULL, cube_code TEXT NOT NULL,
  financial_year TEXT, date_from DATE NOT NULL, date_to DATE NOT NULL,
  is_current BOOLEAN NOT NULL DEFAULT FALSE, is_auto_refresh BOOLEAN NOT NULL DEFAULT FALSE,
  last_refresh_at TIMESTAMPTZ, status TEXT NOT NULL DEFAULT 'UNVERIFIED',
  authoritative BOOLEAN NOT NULL DEFAULT TRUE,
  UNIQUE (source_type, cube_name, cube_code),
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

-- Immutable raw staging: append-only, one row per source row, with lineage.
CREATE TABLE fin.stg_finance_entry (
  stg_id BIGSERIAL PRIMARY KEY,
  source_system TEXT NOT NULL DEFAULT 'ORACLE_GINESYS',
  source_object TEXT NOT NULL, source_cube_code TEXT NOT NULL, source_financial_year TEXT,
  source_row_key TEXT NOT NULL,            -- natural identifier(s) from source (UNVERIFIED which columns)
  extract_batch_id UUID NOT NULL, extracted_at TIMESTAMPTZ NOT NULL, loaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  payload JSONB NOT NULL,
  UNIQUE (source_object, source_cube_code, source_row_key, extract_batch_id)
);

-- Typed fact (shape follows the CUBE$FINREGSITE field list in the brief; verify against live).
CREATE TABLE fin.fact_finance_entry (
  entry_id BIGSERIAL PRIMARY KEY,
  site_code TEXT, entry_glcode TEXT, entry_slcode TEXT, entry_no TEXT,
  entry_date DATE NOT NULL, entry_type TEXT, narration TEXT,
  debit NUMERIC(20,2) NOT NULL DEFAULT 0, credit NUMERIC(20,2) NOT NULL DEFAULT 0,
  release_status TEXT,
  source_system TEXT NOT NULL, source_object TEXT NOT NULL, source_cube_code TEXT NOT NULL,
  source_financial_year TEXT, source_row_key TEXT NOT NULL,
  extract_batch_id UUID NOT NULL, extracted_at TIMESTAMPTZ NOT NULL, loaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (source_object, source_row_key)   -- idempotent reload; second guard against double counting
);
CREATE INDEX ON fin.fact_finance_entry (entry_date, site_code);
CREATE INDEX ON fin.fact_finance_entry (entry_glcode, entry_slcode);

CREATE TABLE fin.recon_run (
  id BIGSERIAL PRIMARY KEY, run_at TIMESTAMPTZ NOT NULL DEFAULT now(), scope TEXT NOT NULL,
  check_name TEXT NOT NULL, source_value NUMERIC(24,2) NOT NULL, mart_value NUMERIC(24,2) NOT NULL,
  kpi_value NUMERIC(24,2), explanation TEXT, passed BOOLEAN NOT NULL
);
-- Further tables (dim_*, fact_creditor_outstanding, fact_vendor_advance, fact_cash_bank, ...)
-- are deliberately NOT created until discovery shows the source can support them.
