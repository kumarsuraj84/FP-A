# Decisions
D-1 Registry-driven source selection; three-layer double-count guard. D-2 Zero-tolerance reconciliation, explanations mandatory. D-3 Python ≥3.11 in code, 3.12 for deploy. D-4 Ageing buckets per brief; date basis undecided, no classification logic. D-5 No fabricated schemas/figures. D-6 Mart tables only when discovery justifies them. D-7 Feature branch only; no merge to main.
**D-8 (correction cycle)** Logical dataset and physical Oracle object are separate registry concepts; both separate-object and shared-discriminator architectures supported; physical names never derived from patterns; unresolved ⇒ BLOCKED.
**D-9** `OLAP_DATACUBE_LIST` drives cube resolution; mappings confirmed by an operator command with evidence, stored in a git-ignored overlay.
**D-10** Profiler: LIGHT default (≤1 scan), DEEP explicit (chunked null aggregates, ≤ ceil(cols/100) scans). Tests assert no per-column scans.
**D-11** Source-row identity (ingestion idempotency) is distinct from canonical finance identity (unknown, not implemented); fact uniqueness uses full source identity; no cross-copy dedupe.
**D-12** Staging is append-only snapshot history; promotion is idempotent upsert with tombstones for full-refresh scopes.
**D-13** Oracle read-only: SELECT-only grants are primary; SQL regex guard is secondary.
**D-14** Finance questions are deferred until database evidence is exhausted.
