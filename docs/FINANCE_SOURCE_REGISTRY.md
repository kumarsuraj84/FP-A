# Finance Source Registry
Seed: `config/source_registry_seed.csv`. Table: `fin.finance_source_registry`.
| source_type | cube_name | codes from brief | status |
|---|---|---|---|
| SITE_REG | CUBE$FINREGSITE | 687, 749, 805, 548, 874, 902, 844 (FY20-21..FY26-27) | UNVERIFIED |
| SITE_REG all-years | CUBE$FINREGSITE | ~877 | UNVERIFIED, **not seeded** |
| GL_REG / ALL_GL | CUBE$FINREG | ~901 / ~539 | UNVERIFIED, not seeded |
| MOP | CUBE$BILLCOLL | MOP_26_27 ~871 (cube name is CONFIRMED by data-model docs: `CUBENAME='MOP_<FY>'`) | UNVERIFIED code |
| TDS, PTC, BUDGET, FINOTSD, SERINV, SERORD | see brief | | UNVERIFIED, not seeded |
Only SITE_REG is seeded, per-year, because the brief gives codes and date windows. Observations to resolve live: FY23-24 code 548 is lower than neighbours (possible stale/odd copy); if 877 (all-years) is adopted for FY23-26, mark 548/874/902 `authoritative=false` — the overlap check will otherwise fail loudly. Date windows are the Apr–Mar FY (CONFIRMED convention); real min/max dates must come from discovery.
