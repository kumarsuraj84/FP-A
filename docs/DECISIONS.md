# Decisions
D-1 Registry-driven source selection; three-layer double-count guard. D-2 Zero-tolerance reconciliation, explanations mandatory. D-3 Python ≥3.11 in code, 3.12 for deploy. D-4 Ageing buckets per brief; date basis undecided, no classification logic. D-5 No fabricated schemas/figures. D-6 Mart tables only when discovery justifies them. D-7 Feature branch only; no merge to main.
**D-8 (correction cycle)** Logical dataset and physical Oracle object are separate registry concepts; both separate-object and shared-discriminator architectures supported; physical names never derived from patterns; unresolved ⇒ BLOCKED.
**D-9** `OLAP_DATACUBE_LIST` drives cube resolution; mappings confirmed by an operator command with evidence, stored in a git-ignored overlay.
**D-10** Profiler: LIGHT default (≤1 scan), DEEP explicit (chunked null aggregates, ≤ ceil(cols/100) scans). Tests assert no per-column scans.
**D-11** Source-row identity (ingestion idempotency) is distinct from canonical finance identity (unknown, not implemented); fact uniqueness uses full source identity; no cross-copy dedupe.
**D-12** Staging is append-only snapshot history; promotion is idempotent upsert with tombstones for full-refresh scopes.
**D-13** Oracle read-only: SELECT-only grants are primary; SQL regex guard is secondary.
**D-14** Finance questions are deferred until database evidence is exhausted.
**D-15 (patch 2)** `registry-confirm` supports both architectures end to end; shared mode verifies the discriminator column in `ALL_TAB_COLUMNS`, never scans the object; overlay round-trips the mode.
**D-16** Mapping evidence is structured (artifact path+sha256, row index+snapshot, physical identity, who/when) with an honest MACHINE_VERIFIED vs OPERATOR_CONFIRMED distinction.
**D-17** Source identity = owner / object NAME / copy id / discriminator column / discriminator value / row key, `''` sentinel for none; `display_name` is a label only. Chosen over a combined string so staging, facts and tombstone scopes share one definition.
**D-18** `btree_gist` is an admin bootstrap prerequisite (`bootstrap_admin.sql`); `schema.sql` fails fast if missing and never creates extensions. Overlap constraint retained.
**D-19** Oracle connectivity supports ODBC (pyodbc, the existing CityKart extraction pattern) as well as oracledb thin, behind the same read-only guard; ODBC bind conversion is strict and tested without a database.
**D-20** Execution model: live Oracle discovery runs on a CityKart-network PC; cloud Claude does code + GitHub only.
**D-21** `discovery-run-01` is a gated orchestrator: one gate per invocation, no auto-confirmation, no DEEP mode, no ingestion; it regenerates a whitelist-built sanitized summary after every gate, and logs every query (text, kind, seconds; never bind values).
**D-22** Key discovery is metadata-only and advisory (STRONG/WEAK/NO_METADATA_KEY); the final source_row_key is a human decision after review.
**D-23** `profile-group`: exactly one dimension, one aggregate scan, max 100 groups; intended for code-like columns because group labels are returned verbatim.
