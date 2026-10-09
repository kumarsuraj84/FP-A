# P&L on gold_fpa: source gaps and decisions needed

Implemented in `backend/app/gold/pnl.py` (FPA_SOURCE=gold). One synthetic run `PNL-<latest month>` (live, verified); `as_of_date` = latest voucher entry date, `cogs_last_bill_date` = latest COGS bill.

## Columns with no source in gold_fpa (returned NULL / empty)

| Relation.column | Returned | Effect | Needed |
|---|---|---|---|
| `v_serving_run.aligned_days`, `ly_aligned_month` | NULL | No day-aligned last-year window; the review pages fall back to complete months only for a partial current month (current month is Oct, partial) | Daily COGS (bill-date level, or "first N days" per site-month) in extraction, then a day-aligned GL from `voucher_lines` |
| `v_gl_aligned` (all columns) | empty | as above (GL side could be built from voucher_lines, but COGS early part cannot) | as above |
| `v_cogs_site_month.sl_v_early`, `tax_early`, `cogs_early`, `sl_q_early` | NULL | as above | daily COGS |
| `v_site.st_type`, `store_grade` | NULL | not shown/used by the current screens | store grade / ST type in dim_site if wanted |
| `v_site.store_current_status` (vintage) | derived: `dim_site.store_type` ('OLD STORE' / 'NEW STORE'; '-' becomes NULL) | assumption: old mart's vintage = same/new store | Finance to confirm definition and any cut-off date |
| `v_site.area` | `dim_site.area`, 0 becomes NULL | 6 active-store sites without area (JVC, AAC, KDR, BRN, SAH, DLT) are left out of PSF | area master fix; no area history, so a single current area is applied to every month (store resized/refitted earlier is mis-stated) |
| `v_store_month_effective_area.closing_date` | derived from `dim_site.last_bill_date` for CLOSED / IN-ACTIVE stores (same rule as pl_stage) | the real closing date is not held | closing date in dim_site |
| `v_sales_tieout`, `v_cogs_site_month.sl_v` | `sl_v` rebuilt as `net_sales_ex_gst + tax_amt` | gold stores no gross SL_V; 14 site-months have NULL `tax_amt`, treated as 0 | confirm tax_amt NULL = 0 |
| `v_serving_run` run-model fields (manifest hashes, `expected_*`) | `expected_gl_rows/cogs_rows/sites` = current table row counts; `tolerance_rupees` 0.01 | cosmetic: no load manifest in gold | none |
| `v_control` | source = `gold_fpa.control_totals`, extract = recompute from `pnl_store_month` / `cogs_store_month` (209 controls, all PASS) | no `mart` or `api` layer, and no source-to-GL tie to Oracle totals beyond what control_totals holds | optional: control totals for aligned window |

## Budget

`gold_fpa.budget_ledger_month` is NOT wired: its month mapping is unreliable and the API serves budget as null by design (`BUDGET_NOTE`). Finance must confirm the month mapping before any budget column is added.

## Items needing a Finance / extraction decision

1. Section mapping is the fixed table from `tools/extraction_broker/pl_stage.py` (`SECTION_OF_GROUP`). Any new `fin_group` not in it silently becomes UNMAPPED (visible in the excluded list, never in a total).
2. UNMAPPED is large: about -5.49 bn net Apr-Oct 2026 across 35 ledgers (expense ledgers not in the finance group map: purchases, etc.). It is correctly excluded from every total but the Finance mapping should be completed.
3. "Sales - POS" is identified by ledger NAME (`glname`), as in the old mart; `SALES MANUAL` (also Net Sales) is revenue but does not make a site a "store".
4. The store set = sites with a "Sales - POS" posting; stores in `dim_site` with status UPCOMING_STORE appear only in the effective-area view.
5. Sales tie-out tolerance is 1000 rupees as in the old loader. Sep-2026 shows 3 untied site-months (largest about 0.93 m): books vs COGS table, a data point for Finance, not hidden.
6. `as_of_date` comes from `max(voucher_lines.entdt)` (today); the gold load has no explicit "books cut-off" field. The running month is therefore partial/provisional (unposted entries are in `all` basis).
7. Performance: each request re-evaluates the views (no materialisation): about 2 s per call, `summary` 7-13 s. If too slow, ask for materialised `pnl_gl_site_month` and `v_store_month_effective_area` tables in gold_fpa.
8. `review_router` is not included by `app/creditors_api/main.py` (only `pnl_router`), so the review endpoints (/pivot, /comparison, /expenses, /heatmap, /peers, /exceptions/*, /quality) return 404 on the stock app. They were verified by mounting the router in a scratch harness; mounting needs a one-line change to main.py.
