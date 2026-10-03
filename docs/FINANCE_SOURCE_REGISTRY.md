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

## Confirming a mapping (structured evidence)
```
registry-confirm SITE_REG --copy 844 --object MISRETAIL.<OBJECT> --evidence-file reports/generated/cube_registry_discovery.json --evidence-row <N>
registry-confirm <TYPE> --copy <ID> --object OWNER.<SHARED_OBJECT> --access-mode shared --discriminator-column <COL> --discriminator-value <VAL> --evidence-file ... --evidence-row N
```
- `--access-mode separate` (default): discriminator args are rejected. `shared`: both discriminator args required.
- Metadata-only Oracle checks: object exists in `ALL_OBJECTS`; for shared, the discriminator column exists in `ALL_TAB_COLUMNS`. The object is never scanned to save a mapping.
- Evidence is structured, not free text: artifact path + sha256 + discovery timestamp, 0-based row index and a snapshot of that row, registry key, owner/object/access mode/discriminator, confirmed_by/at.
- `verification`: **MACHINE_VERIFIED** only if the evidence row contains, as exact cell values, the copy id AND the object name (and the discriminator value for shared mode). OLAP_DATACUBE_LIST's columns are unknown, so this is a generic cell match, not a field mapping. **OPERATOR_CONFIRMED** if the row only partly matches (gaps listed in `notes`). A row mentioning neither copy id nor object, a missing file/row, or a wrong-shaped file is rejected.
- Two registry entries cannot claim the same physical source (owner + object + discriminator).
- Which cubes are shared-vs-separate is an open fact: CityKart docs say `CUBE$BILLCOLL` is shared (`CUBENAME='MOP_<FY>'`), `SITE_REG` copies are described as separate objects. Neither mapping is assumed; the MOP example above is a placeholder.

## Resolution workflow (live)
`discover-cube-registry` → locates `OLAP_DATACUBE_LIST` (ALL_OBJECTS/ALL_SYNONYMS) → inspects its columns (not assumed) → captures finance-related rows (all rows if ≤5000 else pattern-filtered, bounded) → existence-checks hints → writes evidence JSON. Operator reviews, then `registry-confirm` per copy (see above). Only then does `profile-source` work for that copy.
