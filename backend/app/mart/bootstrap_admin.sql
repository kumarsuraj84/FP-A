-- ONE-TIME, run by a DB ADMIN (superuser or a role allowed to CREATE EXTENSION) BEFORE app migrations.
-- The application role does not need, and should not have, CREATE EXTENSION privilege.
CREATE EXTENSION IF NOT EXISTS btree_gist;   -- required by fin.finance_source_registry.no_double_coverage
-- Suggested least-privilege roles (names illustrative):
--   CREATE ROLE fpa_migrator LOGIN;  GRANT CREATE ON DATABASE fpa TO fpa_migrator;   -- applies schema.sql
--   CREATE ROLE fpa_app      LOGIN;  -- runtime: SELECT/INSERT/UPDATE on fin.* only, no DDL
