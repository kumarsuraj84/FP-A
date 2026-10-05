# Sales source-certification register

Started 5 Oct 2026 (IST). One entry per claim in `SOURCE_CERTIFICATION_PLAN.md`. A verdict names the **stores, dates and measures** it covers. Acceptance rules are the plan's section 2: keys, completeness (missing vs zero, freshness), three-level reconciliation, full difference reporting, residuals explained or explicitly accepted, and "99.9% within ₹1" as a diagnostic only.

**Current standing: nothing is fully certified yet.** Several key checks pass for the POS cube on one month; each is held back by a named open item.

## Evidence index

| Probe | Run | Kind | Queries | Seconds | Query hashes (first 10) |
|---|---|---|---|---|---|
| `sales_probe_04a` | `run_20261005_030` | dictionary views only | `f1_status`, `f2_dependencies`, `f3_view_text` | 6.2, 6.1, 6.1 | 2684d02b77, 9540c5708d, 03a97d33b4 |
| `sales_probe_04b` | `run_20261005_031` | POS cube only (MISRETAIL), no SSRK-backed view | `h1`–`h5` one-day totals; `m1_cube_store_day_aug26` | 26.7, 26.3, 42.5, 62.9, 42.6; 50.6 | d946fc604b, cd2650730e, 5a3bf62e8c, cf62f70544, 796333f977; b5da41706c |
| `sales_probe_04c` | `run_20261005_032` | POS cube only, freshness | `q1_cube_instance_aug26`, `q2_cube_instance_history_days` | 71.1, 58.7 | 5797db5c9d, 4ff76fa1c5 |

Exact SQL and parameters (literal dates inside each statement) are in `tools/extraction_broker/packages.py` under the same package names. Raw results are in the git-ignored inbox under the run ids above. All queries ran sequentially through the Inventory Automation broker, MISRETAIL objects only, with no guard rejection and no timeout. The service was idle (no `broker.py` process, other session's latest run complete) before each run, and the other session was told before and after.

**Source snapshot.** August 2026 sales came from one cube instance: `CUBE$POSBILLSUMM` code 809 "SALES SUMMARY_26-27", window 2026-04-01 to 2027-03-31, **report date 2026-10-05**, 2,444,024 rows for the month (all void flags). The history dates came from frozen instances: FY22-23 (code 846, report date 2023-04-01), FY23-24 (857, 2024-04-15) and FY24-25 (858, **2026-03-25**).

## Reach of the POS cube (claim S8, cube only)

One-day totals, non-void:

| Date | Why chosen | Rows | Stores | Net |
|---|---|---|---|---|
| 24 Oct 2022 | Diwali 2022 | 26,254 | 93 | ₹1.60 Cr |
| 12 Nov 2023 | Diwali 2023 | 40,749 | 102 | ₹2.62 Cr |
| 1 Nov 2024 | Diwali 2024 | 52,193 | 124 | ₹3.19 Cr |
| 14 Mar 2025 | Holi 2025 | 13,034 | **69** | ₹0.75 Cr |
| 31 Mar 2025 | Eid-ul-Fitr 2025 | 52,819 | 137 | ₹2.84 Cr |

**Verdict: Certified for existence only, for these five dates.** The cube holds store-day sales on each. This does not certify completeness: Holi 2025 shows 69 stores against 137 at Eid, and the data cannot say whether the other stores were closed or are missing. That needs a store-level view of the festival day, so **completeness for festival days is not certified**. Reach before Oct 2022 and for other dates is untested. The FY24-25 instance was refreshed on 25 Mar 2026, a year after year-end, so history for that year may have been restated (claim S6 is open).

## I1, I2, I4: store identity, POS cube, 1 to 31 Aug 2026

Scope: `CUBE$POSBILLSUMM`, non-void rows, **200 selling stores**, 31 days, 6,046 store-day pairs (run `run_20261005_031`, `m1`).

| Rule | Result |
|---|---|
| Duplicate keys | **0** duplicates in 6,046 (store, day) pairs |
| Unmatched stores | **0**: all 200 selling store codes exist in `T_STORE_OPENING_DATE` (341 rows, unique keys) |
| Join multiplication | None (the master key is unique; join is one-to-one) |
| Store type | All 200 have status ACTIVE; **0** flagged as distribution centres |
| Zero versus missing | **0** store-days with a zero or negative net. **154 store-days missing** out of 6,200 expected (200 stores × 31 days) |
| Missing explained | 153 of 154 fall before the store's master opening date (12 stores opened in or after August) |
| **Unexplained missing** | **1: store 343 has no row on 31 Aug 2026** (opened 2025-08-21) |
| Freshness | Cube 809, report date 2026-10-05 |

Other findings that matter for the rules:
- **The master's opening date is not reliable as a trading start.** Seven of the 12 new stores sold **before** their master opening date (first sale against master date): store 412 on 6 Aug (15 Aug), 416 on 12 Aug (15 Aug), 417 on 24 Aug (5 Sep), 425 on 6 Aug (8 Aug), 436 on 22 Aug (23 Aug), 439 on 14 Aug (16 Aug), 443 on 7 Aug (15 Aug). Trading start must be derived from sales.
- **The master's `LAST_BILL_DATE` is a placeholder**: it is 2000-01-01 for all 200 selling stores. It cannot signal closures; closures must be derived from sales (last day with sales).

**Verdict: Not certified (one open exception).** Keys, matching and store type pass for this scope. The single unexplained missing store-day (store 343, 31 Aug 2026) must be explained or accepted by a named approver before I1, I2 and I4 can be marked Certified for the cube source and this month. The dashboard view's own store key remains sample-verified on 3 days only (claim I1 view side, I6).

## S3, S4: identities inside the cube, store-day, 1 to 31 Aug 2026

Non-void, 6,046 store-days; month totals: net ₹1,351,605,625.78, tax ₹78,451,609.94, taxable ₹1,273,155,122.90, quantity 6,513,455.367 (these equal the earlier monthly probe exactly).

| Claim | Signed total | Total absolute | Maximum | Store-days with a difference | Diagnostic: within ₹1 |
|---|---|---|---|---|---|
| S3: taxable + tax − net | ₹1,107.06 | ₹1,107.06 | ₹899.00 | **6** of 6,046 | 6,043 |
| S4a: sale + returns − promo − gross | ₹0.01 | ₹0.01 | ₹0.01 | **1** | 6,046 |
| S4b: gross − discount − net | −₹148,407.27 | ₹148,407.93 | −₹778.68 | **2,288** | 3,778 |

**S3 exceptions (all of them):** store 353 on 22 Aug ₹899.00 (net ₹166,826.82), on 6 Aug ₹99.00, on 27 Aug ₹109.00; store 266 on 2, 15 and 26 Aug ₹0.02 each. So ₹1,107.00 sits in three store-days of **one store (353)** and ₹0.06 is rounding at another.
**Verdict S3: Not certified.** The store 353 differences are unexplained.
**S4a verdict:** ₹0.01 on one store-day (store 314, 26 Aug) is rounding; **eligible for acceptance by a named approver**, not yet accepted.
**S4b verdict: Not certified.** The discount column does not reproduce net: the residual always has the same sign (net is higher than gross − discount), appears in 195 of 200 stores, and is not concentrated (the largest store, 407, is 4.3% of the total; the top ten stores 15.2%). Its size is 0.011% of the month, but a small percentage does not certify it. A systematic definition difference (a discount type counted in the discount column but not applied to net) is likely and must be explained or explicitly accepted.

## Claims not yet tested

| Claim | Why | What it needs |
|---|---|---|
| S1 dashboard view = cube, store-day | The view side is SSRK-backed | The user's explicit confirmation, then a bounded window (proposed 1 to 15 Aug 2026) |
| U1 quantity, store-day | Same | Same |
| S2, S5 | Mechanism not shown | Owner confirmation of the view's exclusions; mechanism for voids |
| S6, S7 | Not tested | A second read a week later; five consecutive days |
| I5 store attributes | Findings above | Decision: derive trading start and closure from sales, not from the master's opening and last-bill fields |
| I6 monthly distinct anomaly | SSRK-backed | Optional |
| D4, D5 festival calendar | Business decisions | Plan section 10 |

## Readiness verdict (revised)

- **Certified now:** nothing in full.
- **Certified for existence only:** POS cube store-day sales on five named dates (24 Oct 2022, 12 Nov 2023, 1 Nov 2024, 14 Mar 2025, 31 Mar 2025).
- **Passing but held by one open item:** store identity (I1, I2, I4) for the POS cube, 200 stores, 1 to 31 Aug 2026, non-void net, tax and quantity; held by the unexplained store 343 store-day on 31 Aug.
- **Not certified:** S3 (store 353), S4b (systematic discount residual); S1 and U1 not yet tested.
- **Still unavailable:** Bills, ABV, UPB, the real bridge, comparable-store growth, department contribution, footfall, targets, margin, festival-stage comparison.
- **Prototype:** unchanged; every real figure on it is sample data.
