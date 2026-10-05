# Sales source-certification register

Started 5 Oct 2026 (IST). Revision 2 (evening). One entry per claim in `SOURCE_CERTIFICATION_PLAN.md`. A verdict names the **stores, dates and measures** it covers. Acceptance rules are the plan's section 2.

**Current standing: nothing is fully certified.** This revision uses local evidence and definitions only. **No new Oracle query was run, and the SSRK-backed checks are on hold** pending resolution of the project's access rule (a bounded date window does not make the production load bounded, and it does not override the project restriction).

## 1. Evidence index

| Probe | Run | Kind | Seconds | Query hashes (first 10) |
|---|---|---|---|---|
| `sales_probe_04a` | `run_20261005_030` | dictionary views only | 6.2, 6.1, 6.1 | 2684d02b77, 9540c5708d, 03a97d33b4 |
| `sales_probe_04b` | `run_20261005_031` | POS cube only (MISRETAIL) | 26.7, 26.3, 42.5, 62.9, 42.6; 50.6 | d946fc604b, cd2650730e, 5a3bf62e8c, cf62f70544, 796333f977; b5da41706c |
| `sales_probe_04c` | `run_20261005_032` | POS cube only, freshness | 71.1, 58.7 | 5797db5c9d, 4ff76fa1c5 |
| `sales_probe_05a` | `run_20261005_036` | POS summary instance tables directly (MISRETAIL, no SSRK dependency) | 6.5, 10.1, 10.1 | df7734b7f3, 5166241ee6, 7945b075f3 |
| `sales_probe_05c` | `run_20261005_039` | POS summary instance tables directly (MISRETAIL, no SSRK dependency) | 10.5, 6.1, 6.1 | f7b4213187, 580647336f, 853f9c3085 |
| `sales_probe_05e` | `run_20261005_040` | POS summary instance tables directly (MISRETAIL, no SSRK dependency) | 6.2, 6.1 | af60606364, 5fab6148ec |
| `sales_probe_05d` | `run_20261005_041` | POS summary instance tables directly (MISRETAIL, no SSRK dependency) | 6.5, 6.1 | a9d28cc3e9, f88242aec2 |

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

## 6. Formula trace: gross, discount, extra tax, net (probes 05c and 05e, cube instances read directly)

Columns of `CUBE$POSBILLSUMM` (dictionary names). The dictionary's owner-confirmed rules: Gross Sales = `NETAMT` = MRP − discount, tax-inclusive; `DIS_V = PROMOAMT + DISCOUNTAMT`; validation identity `MRPAMT − SL_V = DIS_V`, with the note that a gap "flags a data or tax-handling issue". All recalculations below use **one instance** (809 for August; 196 and 809 separately for April), non-void rows, and the columns exactly as stored. **No formula was changed to force agreement.**

**August 2026, instance 809, 6,046 store-days.** Signed total / total absolute / maximum / store-days with any difference:

| Identity | Signed | Total absolute | Max | Store-days with a difference | Status |
|---|---|---|---|---|---|
| `SALEAMT + RETURNAMT = BASICAMT` | 0.00 | 0.00 | 0.00 | 0 | Exact |
| `BASICAMT − PROMOAMT = GROSSAMT` | 0.01 | 0.01 | 0.01 (store 314, 26 Aug) | 1 | Rounding candidate |
| `ITEMDISCOUNTAMT + BILLDISCOUNTAMT + LPDISCOUNTAMT = TOTALDISCOUNTAMT` | 0.00 | 0.00 | 0.00 | 0 | Exact: TOTALDISCOUNTAMT is the sum of the three components |
| `GROSSAMT − TOTALDISCOUNTAMT = NETAMT` (the earlier identity) | −148,407.27 | 148,407.93 | −778.68 (store 407, 11 Aug) | 2,288 | **Does not hold** |
| **`GROSSAMT − TOTALDISCOUNTAMT + EXTRATAXAMT = NETAMT`** | **0.59** | **0.59** | **0.03** | **38** | **Holds to rounding**: 6,046 of 6,046 within ₹1 (diagnostic) |
| `MRPAMT − NETAMT = PROMOAMT + TOTALDISCOUNTAMT` (the dictionary's identity) | −148,155.26 | 148,265.78 | −778.68 | 2,292 | Fails; equals the extra tax less ₹252 (`MRPAMT − BASICAMT` = ₹252.00) |
| `TAXABLEAMT + TAXAMT = NETAMT` | 1,107.06 | 1,107.06 | 899.00 (store 353, 22 Aug) | 6 | Fails on six store-days (section 7) |
| `TAXABLEAMT + TAXAMT + EXTRATAXAMT = NETAMT` | 149,514.92 | 149,514.92 | 927.35 | 2,270 | Fails: `EXTRATAXAMT` is **not** an addition to taxable + tax |

**Finding: the "discount residual" is `EXTRATAXAMT`.** For August the sum of `EXTRATAXAMT` is ₹148,407.86 and the residual it explains is ₹148,407.27; the remaining ₹0.59 is spread over 38 store-days at no more than ₹0.03 each. On every store-day where the residual is non-zero, `EXTRATAXAMT` is non-zero (2,268 of 2,268 negative residuals; 20 positive ones are rounding), and there are no negative `EXTRATAXAMT` values. By tax slab (non-void, August): the extra tax sits **only in the 18% GST slab** (₹148,407.86); the 0%, 5% and 12% slabs carry none. So `NETAMT` includes it, and `taxable + tax` already equals `NETAMT` (the extra tax is inside the taxable/tax split, not on top).

**What this settles and what it does not.** Numerically, `NETAMT = GROSSAMT − TOTALDISCOUNTAMT + EXTRATAXAMT` for August 2026 in instance 809. That explains why the discount looked over-stated. It does **not** by itself establish what `EXTRATAXAMT` means in business terms (the name and the 18%-only pattern suggest a tax adjustment on discounted prices, but that is an inference); the owner's definition is still needed. It also does not prove the identity for other months.

**April 2026 (probe 05e), per instance, no union:**

| Identity | Instance 196 (1–3 Apr, 117,389 rows) | Instance 809 (30 days, 2,108,769 rows) |
|---|---|---|
| `SALE + RETURNS = BASIC` | 0.00 | 0.00 |
| `BASIC − PROMO = GROSS` | −300.54 | −7,914.30 |
| `ITEM + BILL + LP = TOTALDISC` | 0.00 | 0.00 |
| `GROSS − TOTALDISC − NET` | −32,628.35 (extra tax 27,908.83) | −651,324.80 (extra tax 615,124.74) |
| `GROSS − TOTALDISC + EXTRATAX − NET` | **−4,719.52** | **−36,200.06** |
| `TAXABLE + TAX − NET` | 0.00 | 0.18 |

In April the extra tax explains 94% of the residual in instance 809 but **₹36,200.06 remains unexplained** (0.0026% of April's net), and the gross chain is off by ₹7,914.30. The earlier "April gross identity off by ₹8,214.84" was the union of both instances. So the extra-tax identity is verified for August only; April has an open remainder. May to July were not recomputed.

**Null treatment (probe 05c, instance 809, August).** Of 2,443,910 non-void rows, the only column with NULLs is `LPDISCOUNTAMT`: NULL on 2,378,536 rows (97.3%), and its non-null values sum to 0. On 75 store-days every `LPDISCOUNTAMT` is NULL, so the store-day sum is NULL; the recalculation treats it as 0 and reports that count. All other amount columns are non-null on every non-void row. The 114 void rows have NULL `LPDISCOUNTAMT` on all rows.

**Terminology.** The cube's `GROSSAMT` is basic value after returns and promotion, **not** the dictionary's Gross Sales (`NETAMT`).

**Verdict S4:** `SALE + RETURNS = BASIC` exact; `BASIC − PROMO = GROSS` fits to rounding in August; `TOTALDISC` is the sum of its components; **the net identity holds to rounding in August 2026 when `EXTRATAXAMT` is included**. Not certified for other months; April 2026 leaves ₹36,200.06 open; the business meaning of `EXTRATAXAMT` needs the owner.

## 7. Tax identity exceptions (claim S3), August 2026

Six store-days of 6,046 (instance 809, non-void):

| Store | Day | Difference (taxable + tax − net) | Where it sits |
|---|---|---|---|
| 353 | 22 Aug | **₹899.00** | GST 5% slab rows only; the 0%, 12% and 18% slabs that day reconcile to 0.00 |
| 353 | 6 Aug | **₹99.00** | GST 5% slab rows only |
| 353 | 27 Aug | **₹109.00** | GST 5% slab rows only |
| 266 | 2, 15, 26 Aug | ₹0.02 each | rounding candidates |

Store 353's differences are **whole rupees confined to its 5% slab**, on three days out of 31, and `EXTRATAXAMT` is zero in that slab, so the extra tax does not explain them. They are not tax-calculation rounding (too large, and exact rupees). Possible sources, none established: a bill-level round-off or manual adjustment carried in net but not in the taxable/tax split, or a charge posted to the wrong slab. Telling these apart needs bill-level data, which this cube does not hold. Store 353 also shows a constant ₹28.35 of extra tax each day in the 18% slab, which is unrelated.
Month totals by slab: 5% slab ₹1,107.00 (all of it store 353), 18% slab ₹0.06 (the store 266 rounding), the other slabs 0.00.
Effective tax rates across store-days range from 5.04% to 17.94% (median 6.16%); the upper range is a mix effect of the 18% slab, not an identity failure.

**Verdict S3: not certified.** Store 353's ₹1,107.00 is unexplained. The ₹0.06 at store 266 stays a rounding candidate pending the rounding policy.

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

**Correction of an earlier statement.** The Phase 0 brief said the two sources agree within 0.0013%. That was true only for the two months I had compared. Across 19 months, 17 differ by under 0.012%, but **April 2026 differs by 5.15% (₹7.07 crore, 314,700 units)** and the partial month October 2026 by −0.17%. This was the most important item in the register; it is explained below.

**April 2026 overlap: measured (probe 05a, run `run_20261005_036`, cube-only, no SSRK dependency).** The cube view depends only on eight MISRETAIL tables (dictionary dependencies) and is **exactly the sum of its instance tables**: the three April-relevant instances add to ₹1,441,510,119.49, equal to the view's April total to the paisa. I queried the instance tables directly and never summed them silently.

| Instance | Intended period | Actual April coverage | Source-reported timestamp | Non-void rows | Net | Units |
|---|---|---|---|---|---|---|
| 196 "POS_SUMM_MTD" | 1–30 Apr 2026 | **1–3 Apr only** (3 Apr is a partial day: 3,362 rows against 64,079 in instance 809) | report date 2026-04-03 | 117,389 | ₹70,645,272.67 | 314,629 |
| 809 "SALES SUMMARY_26-27" | 1 Apr 2026 – 31 Mar 2027 | 1–30 Apr (30 days) | report date 2026-10-05 | 2,108,769 | ₹1,370,864,846.82 | 5,720,623.753 |
| 750 "SALES SUMMARY_25-26" | 1 Apr 2025 – 31 Mar 2026 | none | n/a | 0 | 0 | 0 |

- **Duplicate coverage, not separate slices.** Instances 196 and 809 both hold 1, 2 and 3 April. On 1 and 2 April the two snapshots agree closely but not exactly (rows 57,809 against 57,807 and 56,218 against 56,218; net differs by ₹1,551 and ₹1,546 in opposite directions), consistent with the same days read at different times. 3 April in instance 196 is a partial day.
- **Instance 196 explains the April difference.** The cube view minus the dashboard view for April is ₹70,656,553.67 and 314,700 units. Instance 196 alone is ₹70,645,272.67 (99.984% of the sales difference) and 314,629 units (99.977%). Instance 809 alone differs from the dashboard view by only ₹11,281 and 71 units, in line with other months (for example May 2026: ₹8,317 and 45 units).
- **Finding: the cube view double counts 1 to 3 April 2026**, because it unions a stale month-to-date snapshot with the full-year instance. Before this is fixed at the source, the cube view must not be used for April 2026.

**Proposed instance-selection rule (for approval; nothing was summed, deduplicated by value, or chosen by "latest" alone):**
1. Read each business date from **exactly one** instance table, never from the union view.
2. An instance is **eligible** for a date only if its window contains the date **and** its source-reported report date is later than that date (the snapshot was taken after the day ended).
3. If more than one instance is eligible, prefer the **financial-year instance** over a month-to-date or stub instance. This rule is stated by type, not by recency; the report date is a check, not the selector.
4. If after rule 3 more than one instance is still eligible, or none is, the date is an **exception**: it is listed and the date shows unavailable. It is never resolved by summing, by keeping the larger value, or by choosing the latest.
5. A per-day check (count of instances with rows for the day) runs with every certification window and its result is recorded.

Applied to April 2026 this selects instance 809 for all thirty days and excludes instance 196. Other months showed no comparable difference (17 of 19 within 0.012%), but that is a monthly total, not a per-day instance count; the per-day check has been run only for April 2026.

**Verdict S1: not certified.** The view side at store-day level has not been tested (SSRK-backed, on hold). The April 2026 difference is now explained (instance 196 duplicates 1–3 April) but the cube view is not usable for that month until the selection rule is applied. The partial October 2026 difference (−0.17%) and the slightly larger Nov–Dec 2025 differences are not yet investigated.

## 9. Rounding

A ₹0.01 difference occurs on one store-day in the gross identity (store 314, 26 Aug 2026) and ₹0.02 on three store-days in the tax identity (store 266). These are **rounding candidates**. They are recorded, not accepted. A rounding policy (what size, which identities, who approves) is to be defined with Finance, then applied uniformly.

## 10. Status of each claim

| Claim | Status |
|---|---|
| S8 reach (cube) | Existence certified on five dates only; completeness not certified |
| I1, I2, I4 observed rows (cube, Aug 2026) | **Passes within the tested rows** |
| Coverage (Aug 2026) | **Not certified**: 0 confirmed, 43 provisional, 111 unexplained; store 343, 31 Aug **unknown** |
| I5 trading dates | **Not certified**: needs operational evidence |
| S1 view vs cube | **Not certified**: April 2026 difference **explained** (duplicate coverage from instance 196, 99.98%); view side not tested; Oct 2026 partial and Nov–Dec 2025 not investigated |
| Cube instance selection | Rule proposed (section 8); per-day instance count run for April 2026 only |
| S3 tax identity | **Not certified**: store 353, ₹1,107.00 in the 5% slab on three days, unexplained |
| S4 chain and net identity (Aug 2026, instance 809) | `SALE + RETURNS = BASIC` exact; `BASIC − PROMO = GROSS` rounding; **`NET = GROSS − TOTALDISC + EXTRATAX` holds to ₹0.59 total (max ₹0.03)**. Business meaning of `EXTRATAXAMT` unconfirmed. April 2026 leaves ₹36,200.06; other months not recomputed |
| Rounding | Candidates: ₹0.01 (store 314), ₹0.02 ×3 (store 266), ₹0.59 over 38 store-days. A policy with Finance is needed; none accepted |
| U1, S5, S6, S7, I6 | Not tested |
| D4, D5 festival calendar | Business decisions |

## 11. Readiness verdict (revised again)

- **Certified in full:** nothing.
- **Certified for existence only:** POS cube store-day rows on five named dates (24 Oct 2022, 12 Nov 2023, 1 Nov 2024, 14 Mar 2025, 31 Mar 2025).
- **Passing within tested rows, coverage unresolved:** store identity for 200 stores, 1 to 31 Aug 2026, non-void, instance 809.
- **Reconciles to rounding (identity only, not yet certified):** the net identity for August 2026 in instance 809 with `EXTRATAXAMT`; `SALE + RETURNS = BASIC` and `TOTALDISC` = its components.
- **Explained, rule awaiting approval:** the April 2026 cube-versus-view difference (duplicate coverage from instance 196).
- **Not certified:** coverage, trading dates, view-versus-cube store-day reconciliation, store 353 tax differences, April 2026 net-identity remainder, other months' identities.
- **Still unavailable:** Bills, ABV, UPB, the real bridge, comparable-store growth, department contribution, footfall, targets, margin, festival-stage comparison.
- **Prototype:** available for design review; every figure on it is sample data.
