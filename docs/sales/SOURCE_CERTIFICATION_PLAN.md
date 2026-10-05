# Sales Comparison: source-certification plan

5 Oct 2026 (IST). Plan only. **No probe in this plan has been run, and none is authorised until you approve it.** It follows the Phase 0 brief (`PHASE0_DATA_UNDERSTANDING.md`) and the festival review (`FESTIVAL_REVIEW.md`).

## 1. What this stage decides

Whether four things can be called **certified** for a data-backed trial: **sales**, **units**, **store identity** and **comparison dates** (including the festival calendar).

**Out of scope, and staying unavailable:** Bills, ABV, UPB, the Bills → ABV bridge, comparable-store growth, department contribution, footfall, targets, margin. Each has a stated gate in section 8; none is certified by this plan.

A sample check never certifies a source. Every claim below is certified only on the evidence stated, over the period stated.

## 2. How a claim gets certified

Each claim has: an **id**, the exact **statement**, the **test** (a read-only broker probe: object, grain, window), an **acceptance rule** with its tolerance, the **evidence** to keep, and a **verdict**.

Verdicts: **Certified** · **Certified with stated tolerance** · **Not certified** · **Blocked** (needs a decision or access).

Evidence kept for every verdict: the run id, the query hash, the SQL text, the date window, the result and the reviewer, in one register file (`docs/sales/CERTIFICATION_REGISTER.md`), so a later reader can rerun it. Tolerances below are **proposals** for you to set.

## 3. Rules for running the tests

- **Route and guard:** Inventory Automation broker only, MISRETAIL only, within the broker guard, sequential. The FP&A direct login is never used.
- **Load policy.** Several source views read the live SSRK POS tables underneath, and the slowest earlier probes took 2 to 9 minutes. So: one month at a time, outside business hours, abort a query that passes 10 minutes, never start while a finance extract is running (check the inbox and the broker process first, and tell the other session), and never repeat a failed expensive query automatically.
- **Prefer the cheapest source that answers the question:** the POS cube copies and dictionary views before the SSRK-backed views.
- **No row-level customer data**; only totals by store and day.
- **Frozen windows:** test months are fixed up front so a rerun is comparable. Proposed: one ordinary month (Aug 2026), one festive month (Oct 2025), one with a high return share (Mar 2026 or the highest in the earlier monthly table).

## 4. Store identity (certify first; every other test depends on it)

| Id | Statement | Test | Acceptance (proposed) | Status now |
|---|---|---|---|---|
| I1 | `ADMSITE_CODE` is the store identifier and matches `T_STORE_OPENING_DATE.SITE_CODE` | For each test month, the list of distinct codes with sales (from the POS cube, not from `DISTINCT` on the view) is compared with the master | 100% of codes with sales exist in the master; unmatched codes listed and explained | Sample-verified on 3 days (206/206, 148/148, 207/207) |
| I2 | (store, day) is unique in the sales source | For each test month: rows against distinct (store, day) pairs from a grouped store-day list | Rows = distinct pairs; zero duplicates | Unique by definition; 1 day verified |
| I3 | The master's key is unique and a name is never used as a key | Master row count against distinct codes; list duplicate names | Codes unique; each duplicate name listed | Verified: 341/341; one duplicate name (`JGRxx`) |
| I4 | Every selling site is a store, not a distribution centre | Join selling codes to the master's DC and store-type flags | Zero DC sites with store sales, or each one explained | 0 on the sample day |
| I5 | Store attributes needed for comparison (opening date, status, region, festival group) are valid **as of each period** | The master is a current snapshot, not history. Capture a dated copy per run and compare with the previous copy; list changed stores | Decision on as-of versus current; every change in the test months explained | **Blocked**: needs your decision |
| I6 | The monthly distinct-count anomaly on the dashboard view is a query artifact | One two-day wrapped-distinct test on the view against the cube's store list for the same days | Same set of stores from both | Open; optional if I1 and I2 pass |

## 5. Sales

| Id | Statement | Test | Acceptance (proposed) | Status now |
|---|---|---|---|---|
| S1 | The dashboard view's `SL_V` equals the POS cube's non-void `NETAMT` at store-day level | For each test month, store-day totals from both sources, compared row by row | At least 99.9% of store-days equal to ₹1; every larger difference listed | Month level within 0.0013%; 202 of 206 stores exact on one day |
| S2 | The differences in S1 are explained by the view's own exclusions (divisions `FIXED ASSETS`, `NON-TRADING`, and items missing from the item master) | Measure the excluded amount where a source with item division exists inside MISRETAIL; otherwise record the exclusion as the definition and ask the owner to confirm it | Explained amount equals the difference, or the exclusion is accepted as the sales definition | Hypothesis only |
| S3 | `NETAMT` includes GST: taxable + tax = net | Month totals and store-day totals from the cube | Within ₹100 per month and ₹1 per store-day, differences listed | Verified for Aug and Sep 2026 monthly |
| S4 | `NETAMT` is after returns, promotion and discount | Identity `SALE + RETURNS − PROMO = GROSS` and `NET ≈ GROSS − DISCOUNT` per month | Gross identity within ₹1; discount residual within 0.01% and shown on the page | Gross identity verified; discount residual 0.004–0.011% unexplained |
| S5 | Void bills are excluded from the dashboard figure | The view has no void filter; show the mechanism (voided bills absent upstream, or removed by a join) without reading SSRK directly | Mechanism shown, or the 0.0013%-scale difference accepted with the reason recorded | Behaviour shown, mechanism unproven |
| S6 | History is stable: a closed month does not change when read again | Read the same closed month twice, a week apart | Identical totals, or each restatement explained | Not tested |
| S7 | The as-of date is the last complete day and today is never shown as complete | Latest business date in the source against the refresh time, for five consecutive days | Latest complete day identified every time; partial day flagged | Not tested |
| S8 | Earliest reliable date | Earliest date with a complete store-day set in the view and in the cube | Written down; reference dates before it show unavailable | View probed from 2025-04-01 only |

## 6. Units

| Id | Statement | Test | Acceptance (proposed) | Status now |
|---|---|---|---|---|
| U1 | `SL_Q` equals the cube's non-void `BILLQTY` at store-day level, with returns negative | Same store-day comparison as S1 | At least 99.9% of store-days equal; differences listed | 5 units apart on one day |
| U2 | The unit is a piece, and fractional quantities are understood | List item types behind non-integer quantities (monthly totals carry decimals) | Rule written: which items are measured, and how | Not examined |
| U3 | ASP = Sales ÷ Units is stable under returns | Recompute at store and total level; check no store has zero units with sales | Ratios recomputed from sums everywhere; zero-unit cases listed | Method fixed in code |

## 7. Comparison dates

| Id | Statement | Test | Acceptance (proposed) | Status now |
|---|---|---|---|---|
| D1 | Same-date and same-weekday rules are computed by us and are correct | Unit tests (exist for the rules, leap day and weekday); add year-boundary and first-day-of-fiscal-year cases | Tests green, reference dates shown on screen | Done for the prototype |
| D2 | Reference dates are only offered where history exists | History limit from S8 enforced; unsupported dates show unavailable | No comparison shown for a reference date before the earliest reliable date | Rule coded; limit to be confirmed |
| D3 | The MIS comparison convention (same month, nearly same dates) is understood and **not** adopted by default | Already documented | Documented | Done |
| D4 | Festival calendar: an approved, versioned table of festival occurrences, windows and applicable store groups | Build from the plan table's festival blocks and the store-group vocabulary; business approves each year's dates; reconcile with `FESTIVAL_GROUPING` and the filter table | Every occurrence approved and dated; store applicability reconciled; overlaps flagged | **Blocked**: festival list, windows, authoritative classification and maintainer need your decisions (`FESTIVAL_REVIEW.md` section 6) |
| D5 | Festival history is reachable | For each festival, check that the reference occurrence falls inside the earliest reliable date | Spring festivals (Holi, Eid-ul-Fitr) need Feb–Apr 2025; offered only if the source reaches it | Dashboard view starts 2025-04-01; bucket view untested |

## 8. What stays unavailable and the gate to lift each

| Measure | Gate |
|---|---|
| Bills, ABV, UPB, Bills → ABV bridge | A bill identifier shown unique per store and business date (including terminal or session reuse); your rule for purchase bills versus return documents counted separately; bills counted the same way in every source |
| Comparable-store growth | The cohort rule decided; opening dates, closures and trading coverage validated per store and period; the rule applied identically in both periods |
| Department contribution | A verified department-level history source and its reconciliation to store totals |
| Footfall and conversion | Coverage matching the sales cohort and dates |
| Targets, margin | Not examined |

## 9. Order of work and effort

1. **Decisions** (no probing): I5 as-of attributes; tolerances; test months; festival list and windows (D4); who maintains festival dates.
2. **Identity** I1–I4, I6 (cheapest, unlocks the rest).
3. **Sales** S1, S3, S4, then S2, S5; **Units** U1, U2.
4. **History and dates** S6–S8, D5.
5. **Festival calendar** D4 with business approval; read the festival views' text first (`FESTIVAL_REVIEW.md` section 7).
6. **Register and verdicts**, then review.

Estimate (probe time only): about 15 grouped queries per test month, mostly under 3 minutes on the cube and 5 to 10 minutes on the SSRK-backed view; roughly two to three hours across three months, run in off-hours blocks.

## 10. Exit criteria for the data-backed trial

The trial may start when: I1, I2 and I4 are **Certified**; S1, S3 and S4 are **Certified with stated tolerance**; U1 is **Certified**; S8 and D2 are in force; and every other claim has an explicit verdict. Festival comparison is added per festival once D4 and D5 pass for that festival. Bills, ABV, comparable-store growth and the real bridge stay unavailable until their own gates in section 8 are met.

## 11. Risks

- The residual (S2) may be unmeasurable inside MISRETAIL; the fallback is to accept the exclusion as part of the definition with the owner's sign-off.
- Heavy scans of SSRK-backed views can compete with finance extracts; the coordination rule in section 3 applies.
- The master is a snapshot, so past store status can be wrong for a closed or renamed store (I5).
- Festival dates are lunar and can move by a day; approval before publication is required.
