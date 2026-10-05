# Sales source-certification register

Started 5 Oct 2026 (IST). Revision 2 (evening). One entry per claim in `SOURCE_CERTIFICATION_PLAN.md`. A verdict names the **stores, dates and measures** it covers. Acceptance rules are the plan's section 2.

**Current standing: nothing is fully certified.** This revision uses local evidence and definitions only. **No new Oracle query was run, and the SSRK-backed checks are on hold** pending resolution of the project's access rule (a bounded date window does not make the production load bounded, and it does not override the project restriction).

## 1. Evidence index

| Probe | Run | Kind | Seconds | Query hashes (first 10) |
|---|---|---|---|---|
| `sales_probe_04a` | `run_20261005_030` | dictionary views only | 6.2, 6.1, 6.1 | 2684d02b77, 9540c5708d, 03a97d33b4 |
| `sales_probe_04b` | `run_20261005_031` | POS cube only (MISRETAIL) | 26.7, 26.3, 42.5, 62.9, 42.6; 50.6 | d946fc604b, cd2650730e, 5a3bf62e8c, cf62f70544, 796333f977; b5da41706c |
| `sales_probe_04c` | `run_20261005_032` | POS cube only, freshness | 71.1, 58.7 | 5797db5c9d, 4ff76fa1c5 |

Exact SQL and literal parameters are in `tools/extraction_broker/packages.py` under the same package names; results are in the git-ignored inbox. Earlier probes are in `PHASE0_PROBE_LOG.md`.

**Terminology trap: "gross".** The cube column `GROSSAMT` is **not** the dictionary's "Gross Sales". The dictionary's Gross Sales is `NETAMT` (= `SL_V`, MRP net of all discount, tax-inclusive). The cube's `GROSSAMT` is basic value after returns and promotion, before bill-level discount (section 6). Wherever this register says "GROSSAMT" it means the cube column.

**Report dates are source-reported timestamps.** Their refresh semantics are not verified. A later report date (for example 25 Mar 2026 for the FY24-25 cube instance) is a **restatement risk**, not proof that historical values changed. It is recorded, not interpreted.

## 2. Reach of the POS cube (claim S8, cube only)

One-day totals, non-void:

| Date | Why chosen | Rows | Stores | Net | Instance (source-reported report date) |
|---|---|---|---|---|---|
| 24 Oct 2022 | Diwali 2022 | 26,254 | 93 | ₹1.60 Cr | 846 FY22-23 (2023-04-01) |
| 12 Nov 2023 | Diwali 2023 | 40,749 | 102 | ₹2.62 Cr | 857 FY23-24 (2024-04-15) |
| 1 Nov 2024 | Diwali 2024 | 52,193 | 124 | ₹3.19 Cr | 858 FY24-25 (2026-03-25) |
| 14 Mar 2025 | Holi 2025 | 13,034 | **69** | ₹0.75 Cr | 858 FY24-25 (2026-03-25) |
| 31 Mar 2025 | Eid-ul-Fitr 2025 | 52,819 | 137 | ₹2.84 Cr | 858 FY24-25 (2026-03-25) |

**Verdict: certified for existence of rows on these five dates only.** Not certified for completeness: Holi 2025 shows 69 stores against 137 at Eid, and the data cannot say whether the others were closed or missing. Reach before Oct 2022 and on other dates is untested. History stability (S6) is open.

## 3. Store identity: observed rows only (claims I1, I2, I4)

Scope: `CUBE$POSBILLSUMM`, non-void rows, 1 to 31 Aug 2026, instance 809 "SALES SUMMARY_26-27" (source-reported report date 2026-10-05), run `run_20261005_031`, query `m1`. This section is about the **rows that exist**.

| Check | Result within the tested rows |
|---|---|
| Rows tested | 6,046 non-void (store, day) pairs, **200 selling stores**, 31 days |
| Duplicate keys | **0** |
| Unmatched stores | **0**: all 200 store codes exist in `T_STORE_OPENING_DATE` (341 rows, unique key) |
| Join multiplication | None (one-to-one on a unique key) |
| Store type | All 200 have master status ACTIVE and no distribution-centre flag (the status is a current snapshot, not effective-dated) |
| Zero or negative net | **0** store-days with a zero or negative net |

**Verdict: passes within the tested rows** (identity of the 200 stores that appear). This says **nothing** about stores that have no rows, or about days a store has no row. Coverage is a separate question (section 4). The dashboard view's own key remains sample-verified on 3 days only (claim I6 is open).

## 4. Expected store-day coverage (separate from identity)

Expected: 200 observed stores × 31 days = 6,200 store-days. Present: 6,046. **Missing: 154.** Missing is recorded as missing, never as zero. The comparison below uses the master opening date, which is **itself unverified**, and **seven opening-date conflicts** show it is wrong for some stores.

**The seven conflicts** (store, master opening date, first observed sale): 412 (15 Aug, 6 Aug), 416 (15 Aug, 12 Aug), 417 (5 Sep, 24 Aug), 425 (8 Aug, 6 Aug), 436 (23 Aug, 22 Aug), 439 (16 Aug, 14 Aug), 443 (15 Aug, 7 Aug).

| Class | Store-days | Stores | Meaning |
|---|---|---|---|
| **Confirmed** (independent operational evidence) | **0** | none | No store opening or closure register was available |
| **Provisional**: before the master opening date, and the store has no sale before it | **43** | 399 (7), 407 (7), 411 (15), 428 (7), 438 (7) | Consistent with the master date, but that date is unverified |
| **Unexplained**: before the first observed sale, at a store whose master date sales contradict | **84** | 412 (5), 416 (11), 417 (23), 425 (5), 436 (21), 439 (13), 443 (6) | The master opening date cannot be relied on for these |
| **Unexplained**: between the first observed sale and the master opening date (inside the selling period) | **26** | 412 (8), 416 (2), 417 (7), 425 (1), 439 (1), 443 (7) | A store that sold, then has no row on a later day |
| **Unexplained**: on or after the master opening date | **1** | **343 on 31 Aug 2026** | No reason known |
| Total | **154** | | 43 provisional, 111 unexplained, 0 confirmed |

Also: **19** missing days fall strictly between a store's first and last observed sale, and 8 fall after a store's last observed sale in August (store 343's 31 Aug and store 417's 25 to 31 Aug).

**Store 343, 31 Aug 2026: status unknown.** It is neither zero sales nor a closure. Operational evidence (a store day-end or closure record) is needed.

**Earlier text corrected:** the previous revision said 153 of 154 gaps were "explained by opening dates". That is withdrawn. Given the seven conflicts, 111 are unexplained and 43 are provisional.

**Verdict on coverage: not certified.**

## 5. Trading dates, opening and closure (claim I5): not certified

**Sales absence is insufficient to establish closure.** A day without a row can mean a closed store, a trading store whose data is missing, or a data issue; the data cannot tell which. First and last observed sales are **evidence fields**, kept for investigation. They are **not certified operating dates** and must not drive eligibility.

Known facts:
- The master's opening date is contradicted by sales at 7 of 12 stores that opened in or near August.
- The master's `LAST_BILL_DATE` is a placeholder (2000-01-01 for all 200 selling stores), so it cannot show closure.
- There is no closure date field in the master.

Opening, closure and trading-day eligibility need **operational evidence** (an opening and closure register or a store-status history with dates). Until then eligibility rules use the evidence fields only as flags and show "unverified".

## 6. Formula trace: gross, discount, tax

Source columns of `CUBE$POSBILLSUMM` (names from the dictionary): `MRPAMT`, `BASICAMT`, `SALEAMT`, `RETURNAMT`, `PROMOAMT`, `GROSSAMT`, `ITEMDISCOUNTAMT`, `BILLDISCOUNTAMT`, `LPDISCOUNTAMT`, `TOTALDISCOUNTAMT`, `NETAMT`, `TAXABLEAMT`, `TAXAMT`, `EXTRATAXAMT`, `TAXPERCENT`, `BILLQTY`. The cube view is a union of year instances (dictionary). The dictionary's owner-confirmed rules: Gross Sales = `NETAMT` = MRP − discount, tax-inclusive; `DIS_V = PROMOAMT + DISCOUNTAMT`; validation identity **`MRPAMT − SL_V = DIS_V`**, with the note that a gap "flags a data or tax-handling issue".

What the data already collected shows (non-void, all in rupees; no transformation was changed to force a fit):

| Step | Result |
|---|---|
| `SALEAMT + RETURNAMT = BASICAMT` | **Exact** every month (returns are negative) |
| `BASICAMT − PROMOAMT = GROSSAMT` | Within ₹0.01 to ₹0.12 a month in May–Oct 2026; **April 2026 is off by −₹8,214.84** |
| `GROSSAMT − TOTALDISCOUNTAMT = NETAMT` | **Does not hold**: `NETAMT` is higher, every month, store-day sign always the same |
| The dictionary's own identity `MRPAMT − NETAMT = PROMOAMT + DISCOUNT` | **Fails by the same amount** as the line above (Sep 2026: −₹37,905.52 against −₹37,889.55) |
| `TAXABLEAMT + TAXAMT = NETAMT` | Holds except as listed in section 7 |

**Discount residual R = GROSSAMT − DISCOUNT − NETAMT, by month** (signed; negative = net is higher): Apr 2026 −₹683,953; May −₹540,363; Jun −₹360,138; Jul −₹340,154; Aug −₹148,407; Sep −₹37,890; Oct (partial) −₹6,318. The residual is **not stable: it falls steadily over the months**, from 2.17% of the discount in April to 0.16% in October.

**August 2026, store-day level (6,046 store-days):** R is negative on 2,268, zero on 3,758 and positive on 20. It is **zero on every one of the 7 store-days with no promotion**, and it appears on days both with and without returns (2,249 of 5,959 days with returns, 39 of 87 without), so it is not explained by returns alone. Correlation of |R| with the discount is weak (0.26) and with returns weaker (0.12). Median R is 2.3% of that store-day's discount, 90th percentile 11.3%, maximum 495%.

**Reading (hypothesis, not a finding):** the discount column appears to contain amounts that did not reduce the net value, or the net is adjusted later. The falling pattern suggests the difference is linked to something that changes over time (for example later adjustments or a change in how discounts are recorded) rather than to isolated bad rows. Hypotheses to test, not conclusions: `TOTALDISCOUNTAMT` double-counts part of `PROMOAMT`; a discount component is excluded from `NETAMT`; the cube is rebuilt from different snapshots of the item and bill tables. **What local analysis cannot settle:** the component columns (`ITEMDISCOUNTAMT`, `BILLDISCOUNTAMT`, `LPDISCOUNTAMT`, `EXTRATAXAMT`), null counts per column, and the instance each row came from were not collected.

## 7. Tax identity exceptions (claim S3): not certified

Six store-days of 6,046 (August 2026):

| Store | Day | Difference (taxable + tax − net) | Net | Effective tax rate that day |
|---|---|---|---|---|
| 353 | 22 Aug | **₹899.00** | ₹166,826.82 | 6.26% |
| 353 | 6 Aug | **₹99.00** | ₹156,825.60 | 6.31% |
| 353 | 27 Aug | **₹109.00** | ₹384,845.20 | 5.65% |
| 266 | 2, 15, 26 Aug | ₹0.02 each | ₹364,919–₹503,617 | 5.96–6.40% |

Signed total ₹1,107.06, total absolute ₹1,107.06, maximum ₹899.00. Store 353's three differences are **whole rupees**, which fits a fixed-amount item such as an extra charge or manual adjustment rather than a tax calculation, but this is unproven (`EXTRATAXAMT` was not collected). The store 266 differences are rounding candidates. Effective tax rates across store-days range from 5.04% to 17.94% with a median of 6.16%; the wide upper range is itself a flag to explain (a store-day with unusual tax mix or an adjustment). **Not certified.**

## 8. Dashboard view against the cube, by month (claim S1, all 19 months already collected)

Cube non-void `NETAMT` less view `SL_V`:

| Month | Difference | % | Quantity difference |
|---|---|---|---|
| Apr 2025 | +₹433 | 0.0000% | 7 |
| May 2025 | +₹426 | 0.0000% | 7 |
| Jun 2025 | +₹1,868 | 0.0002% | 16 |
| Jul 2025 | +₹696 | 0.0001% | 15 |
| Aug 2025 | +₹1,008 | 0.0001% | 12 |
| Sep 2025 | +₹2,868 | 0.0003% | 18 |
| Oct 2025 | +₹4,422 | 0.0004% | 35 |
| Nov 2025 | +₹94,433 | 0.0067% | 327 |
| Dec 2025 | +₹148,126 | 0.0119% | 448 |
| Jan 2026 | +₹44,095 | 0.0047% | 149 |
| Feb 2026 | +₹10,646 | 0.0011% | 58 |
| Mar 2026 | +₹20,263 | 0.0013% | 90 |
| **Apr 2026** | **+₹70,656,554** | **5.1542%** | **314,700** |
| May 2026 | +₹8,317 | 0.0006% | 45 |
| Jun 2026 | +₹21,273 | 0.0016% | 117 |
| Jul 2026 | +₹14,676 | 0.0014% | 90 |
| Aug 2026 | +₹13,427 | 0.0010% | 124 |
| Sep 2026 | +₹13,144 | 0.0013% | 95 |
| Oct 2026 (partial month) | −₹215,999 | −0.1676% | −949 |

**Correction of an earlier statement.** The Phase 0 brief said the two sources agree within 0.0013%. That was true only for the two months I had compared. Across 19 months, 17 differ by under 0.012%, but **April 2026 differs by 5.15% (₹7.07 crore, 314,700 units)** and the partial month October 2026 by −0.17%. This is the most important open item in the register.

**Hypothesis for April 2026 (unproven):** the cube registry lists two overlapping instances for April 2026, code 196 "POS_SUMM_MTD" (a live month-to-date copy, window 2026-04-01 to 2026-04-30, last refreshed 2026-04-03) and code 809 "SALES SUMMARY_26-27" (the full year). If the cube view unions both, early-April rows would count twice; the size is about 1.5 days of April sales, which is consistent. The registry is a dictionary snapshot and may be out of date. **Until this is explained, no cube-based total for April 2026 can be used, and the cube's role as the reconciliation reference is qualified.** Other months are not affected on this evidence, but that has not been shown row by row.

**Verdict S1: not certified.** The view side at store-day level has not been tested (SSRK-backed, on hold), and the monthly comparison shows an unexplained 5.15% difference in one month.

## 9. Rounding

A ₹0.01 difference occurs on one store-day in the gross identity (store 314, 26 Aug 2026) and ₹0.02 on three store-days in the tax identity (store 266). These are **rounding candidates**. They are recorded, not accepted. A rounding policy (what size, which identities, who approves) is to be defined with Finance, then applied uniformly.

## 10. Status of each claim

| Claim | Status |
|---|---|
| S8 reach (cube) | Existence certified on five dates only; completeness not certified |
| I1, I2, I4 observed rows (cube, Aug 2026) | **Passes within the tested rows** |
| Coverage (Aug 2026) | **Not certified**: 0 confirmed, 43 provisional, 111 unexplained; store 343, 31 Aug **unknown** |
| I5 trading dates | **Not certified**: needs operational evidence |
| S1 view vs cube | **Not certified**: April 2026 +5.15% unexplained; view side not tested |
| S3 tax identity | **Not certified**: store 353 (₹1,107.00 in three store-days) |
| S4a basic/gross chain | `SALEAMT + RETURNAMT = BASICAMT` exact; `BASICAMT − PROMOAMT = GROSSAMT` fits except April 2026 (−₹8,214.84); rounding candidates unaccepted |
| S4b discount | **Not certified**: systematic, falling over time, owners' own identity fails by the same amount |
| U1, S5, S6, S7, I6 | Not tested |
| D4, D5 festival calendar | Business decisions |

## 11. Readiness verdict (revised)

- **Certified in full:** nothing.
- **Certified for existence only:** POS cube store-day rows on five named dates (24 Oct 2022, 12 Nov 2023, 1 Nov 2024, 14 Mar 2025, 31 Mar 2025).
- **Passing within tested rows, with coverage unresolved:** store identity for 200 stores, 1 to 31 Aug 2026, non-void net, tax and quantity, POS cube.
- **Not certified:** coverage, trading dates, view-versus-cube reconciliation (April 2026 anomaly), tax identity, discount identity.
- **Still unavailable:** Bills, ABV, UPB, the real bridge, comparable-store growth, department contribution, footfall, targets, margin, festival-stage comparison.
- **Prototype:** available for design review; every figure on it is sample data.
