# Finance Source Registry
> **NO LIVE FINANCIAL DATA HAS YET BEEN VALIDATED.** All entries are UNVERIFIED; none has a physical object.

Seed: `config/source_registry_seed.csv`. Table: `fin.finance_source_registry`. Local discovery evidence: `reports/generated/registry_overlay.json` (git-ignored), merged at runtime.

| Field group | Fields |
|---|---|
| Logical | source_type, logical_cube_name (e.g. `CUBE$FINREGSITE`), copy_id (opaque; **not chronological**) |
| Coverage | financial_year, date_from/date_to, is_current, is_auto_refresh, last_refresh_at |
| Physical (NULL until CONFIRMED) | physical_owner, physical_object, physical_object_type, access_mode (SEPARATE_OBJECT / SHARED_DISCRIMINATOR), discriminator column/value |
| Control | status (UNVERIFIED/CONFIRMED/BLOCKED/RETIRED), authoritative, physical_hint |

`physical_hint` is a prior-documentation *candidate* used only to check existence in `ALL_OBJECTS` during discovery. Hints exist only for the two documented examples (`MISRETAIL.T$FINREGSITE_844`, `…_902`); other copies have none rather than a guessed pattern.

## Seeded (UNVERIFIED): SITE_REG / CUBE$FINREGSITE
copy ids 687, 749, 805, 548, 874, 902, 844 ↔ FY20-21…FY26-27. Date windows are the Apr–Mar FY convention (CONFIRMED convention), real coverage comes from discovery. Copy ids carry no ordering meaning.
Not seeded until discovery: all-years SITE_REG (~877), GL_REG/ALL_GL, MOP (~871), TDS, PTC, BUDGET, FINOTSD, SERINV, SERORD. If an all-years copy is adopted for a span, the per-year copies in that span must be marked `authoritative=false`; the overlap check fails loudly otherwise.

## Resolution workflow (live)
`discover-cube-registry` → locates `OLAP_DATACUBE_LIST` (ALL_OBJECTS/ALL_SYNONYMS) → inspects its columns (not assumed) → captures finance-related rows (all rows if ≤5000 else pattern-filtered, bounded) → existence-checks hints → writes evidence JSON. Operator reviews, then `registry-confirm` per copy (re-checks `ALL_OBJECTS`, requires an evidence reference). Only then does `profile-source` work for that copy.
