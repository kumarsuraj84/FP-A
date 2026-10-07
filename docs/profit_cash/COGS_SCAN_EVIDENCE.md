# T_CUSTOM_COGS scan: evidence (aggregates only)

Run `run_20261007_001`, package `cogs_scan_01`: one SELECT-only aggregate pass over `MISRETAIL.T_CUSTOM_COGS` (about 104M rows, no index, no partition: a full scan, 79.8 s), site x month from 1 Apr 2025. 3,171 site-month rows. No row-level data, no names.

## What the table is

- Grain: site x barcode x bill date (this scan aggregates it). Columns used: `SL_V` (sales value), `TAXAMT`, `CUSTOM_COGS_V`, `CUSTOM_SL_Q`.
- **`SL_V` includes GST**: `SL_V - TAXAMT` equals the GL ledger "Sales - POS" (ex-GST) month by month (table below). `TAXAMT` is populated on every row of the scan.
- **COGS is stored next to the sale**, so gross margin per store and month is internally consistent: sales ex-GST less `CUSTOM_COGS_V`.
- Freshness: the newest bill date is 2026-10-06 (the scan ran on 7 Oct). No multi-day lag is visible in the newest month; completeness of the last few days is not proven.

## Tie-out to the general ledger (ex-GST, Cr)

| Month | T_CUSTOM_COGS SL_V - TAXAMT | GL "Sales - POS" | Difference |
|---|---|---|---|
| 2026-04 | 129.11 | 129.11 | -0.00 |
| 2026-05 | 129.56 | 129.53 | +0.03 |
| 2026-06 | 129.06 | 129.06 | -0.00 |
| 2026-07 | 96.96 | 96.94 | +0.02 |
| 2026-08 | 127.34 | 127.32 | +0.02 |

The April 2026 figure matches the GL exactly. The earlier 6.6 Cr April gap was against the POS summary cube (135.74 Cr taxable), not against this table: the cube is the outlier for April, not the GL.

## By month, all sites (Cr)

| Month | Sites | Sales incl GST | GST | Sales ex-GST | COGS | COGS % of ex-GST sales |
|---|---|---|---|---|---|---|
| 2025-04 | 137 | 93.21 | 5.90 | 87.30 | 57.02 | 65.3% |
| 2025-05 | 138 | 95.45 | 6.04 | 89.41 | 58.80 | 65.8% |
| 2025-06 | 143 | 93.39 | 5.86 | 87.54 | 57.46 | 65.6% |
| 2025-07 | 142 | 70.31 | 4.54 | 65.77 | 44.78 | 68.1% |
| 2025-08 | 147 | 81.61 | 5.14 | 76.47 | 57.62 | 75.3% |
| 2025-09 | 150 | 92.78 | 5.56 | 87.22 | 59.69 | 68.4% |
| 2025-10 | 155 | 125.86 | 7.40 | 118.46 | 77.17 | 65.1% |
| 2025-11 | 155 | 141.82 | 7.92 | 133.90 | 81.84 | 61.1% |
| 2025-12 | 154 | 124.73 | 6.95 | 117.77 | 72.41 | 61.5% |
| 2026-01 | 153 | 93.19 | 5.31 | 87.88 | 72.49 | 82.5% |
| 2026-02 | 163 | 93.26 | 5.48 | 87.79 | 57.81 | 65.8% |
| 2026-03 | 172 | 154.94 | 8.93 | 146.01 | 92.86 | 63.6% |
| 2026-04 | 174 | 137.09 | 7.99 | 129.11 | 81.69 | 63.3% |
| 2026-05 | 186 | 137.46 | 7.90 | 129.56 | 82.01 | 63.3% |
| 2026-06 | 188 | 136.97 | 7.91 | 129.06 | 83.04 | 64.3% |
| 2026-07 | 191 | 103.12 | 6.16 | 96.96 | 63.24 | 65.2% |
| 2026-08 | 201 | 135.18 | 7.85 | 127.34 | 91.92 | 72.2% |
| 2026-09 | 212 | 100.36 | 6.00 | 94.36 | 73.18 | 77.6% |
| 2026-10 | 210 | 18.80 | 1.17 | 17.63 | 11.18 | 63.4% |

## Flags for Finance

- COGS as a share of ex-GST sales is stable at 61-68 % in most months but jumps in **Aug 2025 (75 %), Jan 2026 (82 %), Aug 2026 (72 %) and Sep 2026 (78 %)** on this basis. Cause unknown (cost adjustments, stock corrections or timing of cost posting); the P&L must not smooth it away.
- The table's cost basis (when cost is struck, and any lag in settling it) is not documented: the table and its columns carry no comments.
- Sites in the table: 137 in Apr 2025 rising to 212 in Sep 2026; Oct 2026 is 6 days only.
