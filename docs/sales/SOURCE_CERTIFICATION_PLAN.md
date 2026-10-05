# Sales Comparison: source-certification plan

Revision 2, 5 Oct 2026 (IST). Supersedes revision 1. Follows the Phase 0 brief (`PHASE0_DATA_UNDERSTANDING.md`) and the festival review (`FESTIVAL_REVIEW.md`).

**State of work:** the festival-view metadata probe (`sales_probe_04a`, run `run_20261005_030`) has been read and is reflected here. No certification claim is yet certified. Data checks listed in section 9 are staged; which of them have run is recorded in `CERTIFICATION_REGISTER.md`.

## 1. What this stage decides

Whether four things can be called **certified** for a data-backed trial: **sales**, **units**, **store identity** and **comparison dates** (including the festival calendar). A certification names the **exact stores, dates and measures** it covers; anything outside that scope stays uncertified.

**Out of scope, and staying unavailable:** Bills, ABV, UPB, the Bills → ABV bridge, comparable-store growth, department contribution, footfall, targets, margin. Each has its own gate (section 8). A sample check never certifies a source.

## 2. Acceptance rules (apply to every numeric claim)

A claim passes only when **all** of these hold for its stated scope:

1. **Keys.** No unexplained duplicate keys, no unmatched stores and no join multiplication. Every exception is listed.
2. **Completeness.** Store-day coverage is counted. **Missing and zero are recorded separately** (a store-day with no row is not a zero). The source's freshness is recorded: the snapshot or refresh time and the latest complete business date.
3. **Reconciliation at three levels:** company total, store-day, and the merchandise totals that are available for that scope.
4. **Differences reported in full:** signed total difference, total absolute difference, maximum single difference, and a list of every exception (not only the large ones).
5. **Residuals.** Every residual is either **explained** (cause shown) or **explicitly accepted** in the register by a named approver, with the amount and the reason. A small percentage never certifies a residual by itself.
6. **"99.9% of store-days within ₹1" is a diagnostic statistic only.** It is reported but is never a pass criterion.

**Report dates** in the sources are treated as source-reported timestamps; refresh semantics are not verified, and a later timestamp is a restatement risk, not proof that values changed. **"Gross"** has two meanings: the cube column `GROSSAMT` (after returns and promotion, before bill-level discount) is not the dictionary's Gross Sales (`NETAMT`).

Verdicts: **Certified** (rules 1 to 6 met, no accepted residual) · **Certified with accepted residual** (residual named, amount, approver) · **Not certified** · **Blocked** (needs a decision or access).

Evidence kept for each verdict in `CERTIFICATION_REGISTER.md`: run id, query hash, exact SQL and parameters, duration, source snapshot, the result and the exception list.

## 3. Rules for running the tests

- **Route:** Inventory Automation broker only, MISRETAIL objects only, within the broker guard, sequential. The FP&A direct login is never used.
- **Coordination:** confirm the extraction service is idle (newest run folder complete, no `broker.py` process) and tell the other session before any heavy check; do not pause or cancel their runs.
- **Two classes of check.**
  - *MISRETAIL-native* (POS cube copies, small tables, dictionary views): no production exposure; run when the service is idle.
  - *SSRK-backed* (the dashboard view, the bucket view and other views that read the live POS tables underneath): each scan reads production tables indirectly. **These are on hold.** They need the user's explicit confirmation and a resolution of the project's access rule before they run, because the rule is that FP&A never queries SSRK. A bounded date window does not make the production load bounded and does not override that restriction. Until then only MISRETAIL-native and local checks proceed. They are narrow (a bounded window of days), sequential, off-hours, aborted past 10 minutes, and never repeated automatically.
- **No customer columns.** Only totals by store and day.
- **Frozen test windows:** an ordinary period, a festive period and a high-return period, fixed in advance so a rerun is comparable.

## 4. History by source and measure (reconciled)

The earlier statements "history starts September 2023" and "history starts April 2025" came from different places. They are reconciled here by source. **"April 2025" was my own query bound**, not a limit of any source.

| Source | Defined reach | What was actually tested | Usable for |
|---|---|---|---|
| `V_CFO_DASHBOARD_SL_V` | From 2020-07-01 (SQL text) | Months from Apr 2025 only (my bound); single days 15 Sep 2025 and 2026 | Sales, units, tax, store-day bill count (if bill rule settles). Earlier reach **untested** |
| `V_SALE_BUCKET_WISE` | From 2023-09-01 (SQL text) | One day (15 Sep 2026) | Bill counts by bucket. Earlier reach untested |
| `V_DAYWISE_BILLCUT` | From 2018-01-01 (SQL text) | None | **INVALID**: unusable |
| `CUBE$POSBILLSUMM` (MISRETAIL) | Year instances FY22-23 to FY26-27, plus stub instances for 2015–16 (cube registry, dictionary-derived) | Apr 2025 to Oct 2026 monthly | Sales, tax, quantity (no bill number). Earlier years **to be tested** (section 9, H-checks) |
| `T_CUSTOM_COGS` | 104M rows | Not probed | Margin (out of scope) |
| `T_SALE_COMPARE_ABV_ASP`, `_DAY_WISE` | Current month only, by design (month typed into the SQL) | Whole table | Not a history source |
| `T_SALE_COMPARE_CONSOLIDATED` | FY26-27 (Apr–Oct 2026 found) | Whole table | Not a history source |
| `T_STORE_WISE_DAY_SALE` | 1–4 Oct 2026 only | Whole table | Not a history source |

**Festival history, three different things that must not be confused:**
- **Stale festival occurrences:** `T_FESTIVAL_DATA` / `_DETAIL` hold 2018–2020 only; several festival views have typed windows from 2019–2024 (Holi 2019/2022, Diwali-season 2022–2024, a Mar–Apr 2025 footfall window).
- **Overwritten comparison windows:** the date-mapping tables hold only the window of the festival last run (the "Holi" tables and `T_NEW_DATE_TWO_YEAR_COMP_FEST` currently hold the Diwali 2026 window). Earlier windows were replaced.
- **No retained historical mappings:** I found no table that keeps the mapping for Holi 2026, Eid 2026 or earlier years. Only the one-year plan table (`T_CALENDER_DATE_PLAN`, 2026 to Mar 2027) records them, and it is used by nothing.

Whether older **raw** sales exist is a separate question from whether older **mappings** exist: the cube registry suggests raw history from Apr 2022; mappings for those years would have to be rebuilt.

## 5. Store identity (certify first)

| Id | Statement | Test | Pass rule | Status |
|---|---|---|---|---|
| I1 | The sales source's store code matches the master's `SITE_CODE` (**identity of the rows that exist; coverage is claim C1, separate**) | For each test window, the store codes with sales (from the cube's own store list) against the master | Rules 1–2: every selling code is in the master; unmatched codes listed and explained | Sample-verified on 3 days; cube-side check in section 9 |
| I2 | (store, day) is unique in each source (**observed rows only**) | Rows against distinct (store, day) pairs over the test window | Zero duplicate keys; any duplicate listed | Unique by definition; 1 day verified |
| I3 | The master key is unique; names are never used as keys | Master rows against distinct codes; duplicate names listed | Codes unique; each duplicate name listed and excluded from name joins | Verified: 341/341; one duplicate name |
| I4 | Every selling site is a store | Selling codes against the DC and store-type flags | Zero DC sites with store sales, or each explained | 0 on one day |
| I5 | Store attributes and trading dates | **Default view:** today's hierarchy (region, cluster, state) applied to **both** periods. **Eligibility** (open, closed, trading) needs **effective-dated opening, closure and trading status from an authoritative record**. **Sales absence is insufficient to establish closure**; first and last observed sales are evidence fields for investigation, not certified operating dates. Where no dated record exists, the status shows **unavailable** and eligibility flags show "unverified". A historical-hierarchy mode stays separate and unavailable until a dated history exists | Every status used for eligibility has a dated source; every store whose status changed in the window is listed; sales-derived dates appear only as flags | **Not certified.** Master `LAST_BILL_DATE` is a placeholder (2000-01-01), there is no closure field, and sales contradict the master opening date for 7 of 12 new stores. **Needs operational evidence** |
| I6 | The monthly distinct-count anomaly on the dashboard view is a query artifact | Compare the view's store list for two days with the cube's | Same set of stores. This is an SSRK-backed check | Open; optional if I1 and I2 pass |
| C1 | Expected store-day coverage: every store-day that should have sales has a row, and each missing one is classified | For each test window: expected store-days (from a **dated** trading record) against present; missing listed by store and day, classified confirmed / provisional / unexplained / unknown | Rules 1–2: zero unexplained missing store-days, or each accepted by a named approver. Missing is never counted as zero and never assumed to be a closure | Aug 2026: 154 missing: 0 confirmed, 43 provisional, 111 unexplained; store 343 on 31 Aug **unknown**. **Not certified** |

## 6. Sales

| Id | Statement | Test | Pass rule | Status |
|---|---|---|---|---|
| S1 | The dashboard view's `SL_V` equals the cube's non-void `NETAMT` | Store-day totals from both sources over the test window (view side is SSRK-backed) | Rules 1–6. Report: signed total difference, total absolute difference, maximum difference, every store-day exception. Diagnostic only: the share within ₹1 | 17 of 19 months differ by under 0.012%; **April 2026 differs by +5.15% (₹7.07 crore)** and October 2026 (partial) by −0.17%. One day: 202 of 206 stores exact. **Not certified** |
| S2 | The S1 differences come from the view's exclusions (divisions `FIXED ASSETS`, `NON-TRADING`; items missing from the item master) | Measure the excluded amount where a MISRETAIL source with item division exists; else record the exclusion as the sales definition and ask the owner to confirm it | The residual is explained and equals the S1 difference, or is explicitly accepted with a named approver | Hypothesis only |
| S3 | `NETAMT` includes GST: taxable + tax = net | Cube store-day totals over the test window | Rules 1–6; residual listed per store-day | Monthly: within ₹99 to ₹1,107 on ₹1,000–1,350 million. Not certified at store-day |
| S4 | `NETAMT` is after returns, promotion and discount | Identities `SALE + RETURNS − PROMO = GROSS` and `NET ≈ GROSS − DISCOUNT` per store-day | Gross identity exact to the rupee at store-day; the discount residual (0.004–0.011% at month level) explained or explicitly accepted | Gross identity verified at month level; discount residual unexplained |
| S5 | Void bills are excluded from the dashboard figure | The view has no void filter; show the mechanism without reading SSRK directly | Mechanism shown, or the difference accepted with a named approver | Behaviour shown, mechanism unproven |
| S6 | A closed month does not change when read again | Read the same closed month twice, a week apart | Identical, or each restatement listed | Not tested |
| S7 | As-of date = last complete day; today is never complete | Latest business date against the refresh time on five consecutive days | Recorded each day | Not tested |
| S8 | Earliest reliable date, per source | Single-day checks at chosen dates (section 9) | Written down per source (section 4); reference dates before it show unavailable | In progress |

## 7. Units and comparison dates

| Id | Statement | Test | Pass rule |
|---|---|---|---|
| U1 | `SL_Q` equals the cube's non-void `BILLQTY`, returns negative | Same store-day comparison as S1 | Rules 1–6; differences listed |
| U2 | The unit is a piece, and fractional quantities are understood | List item types behind non-integer quantities | Rule written down |
| U3 | ASP = Sales ÷ Units, recomputed from sums | Check no store has zero units with sales | Zero-unit cases listed |
| D1 | Same-date and same-weekday rules are computed by us | Unit tests incl. leap day, weekday, year boundary, fiscal-year start | Tests green; reference dates shown on screen |
| D2 | A reference date is offered only where the source reaches it | Earliest reliable date per source (S8) | No comparison for an unreached date |
| D3 | The MIS's same-month convention is not the default | Documented | Done |
| D4 | Festival calendar (section 10) | Approved, versioned table; reconciled with the store classifications | See section 10 |
| D5 | Festival history is reachable | Reference occurrence inside the earliest reliable date, per source | Offered only if the source reaches it |

## 8. What stays unavailable and the gate to lift each

| Measure | Gate |
|---|---|
| Bills, ABV, UPB, Bills → ABV bridge | A bill identifier shown unique per store and business date (including terminal or session reuse); the rule for purchase bills versus return documents counted separately; the same counting in every source |
| Comparable-store growth | The cohort rule decided; opening dates, closures and trading coverage validated per store and period; the same rule in both periods |
| Department contribution | A verified department-level history source reconciled to store totals |
| Footfall and conversion | Coverage matching the sales cohort and dates |
| Targets, margin | Not examined |

## 9. Staged checks

**Stage 1: metadata (done).** `sales_probe_04a`: status, dependencies and text of 11 festival and comparison views. Result in `FESTIVAL_REVIEW.md`.

**Stage 2: MISRETAIL-native cube checks (narrow, no production exposure; may run when idle). DONE 5 Oct: `sales_probe_04b` and `04c`, results in `CERTIFICATION_REGISTER.md`.**
- *H-checks:* one-day totals on the POS cube at chosen dates to find how far back usable store-day sales go: Diwali 2022 (24 Oct), Diwali 2023 (12 Nov), Diwali 2024 (1 Nov), Holi 2025 (14 Mar), Eid-ul-Fitr 2025 (31 Mar). Records rows, stores, void split and net per day.
- *Store-day listing for 1–31 Aug 2026* from the cube: gives the cube side of S1, S3, S4, U1 and the store lists for I1, I2, I4.

**Stage 3: SSRK-backed checks. ON HOLD pending the project's access rule and the user's explicit confirmation.**
- The dashboard view's store-day totals for a bounded window (proposed 1–15 Aug 2026, about 5 minutes) for the view side of S1, U1, I1, I2, I6.
- Single-day dashboard-view checks at two earlier dates to test its reach for Holi/Eid 2025 and a festive day in 2024 (S8, D5).

**Stage 4: register and verdicts.** Every verdict names the stores, dates and measures it covers.

## 10. Festival design (proposal, for approval)

**Order:** Diwali, Durga Puja / Dussehra and Chhath first; then Holi; then Eid-ul-Fitr and Eid-ul-Adha, **as separate festivals**. Bihu later, if wanted.

**Two models to choose between, both found in practice:**
- *Anchored windows* (proposed default): each festival has an anchor day and a configurable window **D−21 to D+7**. Windows can overlap (Puja, Diwali and Chhath sit within about six weeks), so each festival is its own view and overlap days are flagged. Festival totals are never added.
- *Season phases* (what the current MIS report `V_PDC_SALE_COMPARE_PART_1` does): contiguous, non-overlapping phases of one season. For 2026 it uses Shradh 26 Sep–10 Oct, Pooja 11–20 Oct, Diwali 21 Oct–8 Nov and Chhath 9–16 Nov, all typed into the SQL, compared with 2025 and 2023 through `T_NEW_DATE_TWO_YEAR_COMP_FEST`. Offered as a second view for the Puja–Diwali–Chhath season.

**Anchors for multi-day events (proposed; the business confirms):**

| Festival | Anchor day | Note |
|---|---|---|
| Diwali | the main Lakshmi Puja day | Dhanteras to Bhai Dooj are sub-markers inside the window |
| Durga Puja | Maha Ashtami | Applies to the Puja store group |
| Dussehra | Vijayadashami | Separate anchor; applies to the Diwali/Holi group stores in UP and Bihar |
| Chhath | the evening-offering (Sandhya Arghya) day | Four-day festival; the window spans all four days |
| Holi | Holi day (the day after Holika Dahan) | |
| Eid-ul-Fitr | Eid day | Moon-sighting can move it by a day; editable before publication |
| Eid-ul-Adha | Eid day | Same |

**Equal-elapsed-window rule.** A festival in progress compares days D−21 up to the as-of date with the same offsets last year, flags the window as incomplete, and never compares a partial current window with a full past one. Past festivals compare the full window.

**Store applicability.** Neither store classification is chosen automatically. The documented differences: `T_STORE_OPENING_DATE.FESTIVAL_GROUPING` (six tags; 101 of 209 active stores tagged), `T_STORE_FESTIVAL_FILTER` (Holi and Eid with peak tiers; 164 stores), `T_MAMJ25_FESTIVAL_STORE` (126 stores, spring 2025), `T_STORE_COMPARE_FESTIVAL` (89 eligible), and the store lists typed into the views (74 stores for the Puja–Diwali–Chhath report, 28 excluded stores in the comparison tables, `T_STORE_COMPARE_120`). They overlap and conflict. Regional applicability and each store's participation need business approval.

**Roles (proposed arrangement; the business confirms).** *Retail Operations* maintains the festival windows and store applicability. *Finance* approves the calculation treatment (how windows are compared and totalled). A **named business approver** confirms each year's festival dates and regional relevance before publication. Store-level overrides are logged with a reason, a date and the approver. **Every festival date is verified against an authoritative source** (a named calendar source, recorded with the verifier) before publication, because Holi, Eid, Durga Puja and Chhath follow lunar calendars.

**Legacy report rules are not approvals.** The current festival report's four phases (Shradh, Pooja, Diwali, Chhath) and its typed list of 74 stores are **legacy report rules**. They are not approved festival anchors and not comparable-store eligibility, and they are not reused as such.

**Wording correction.** I earlier said October's last-year columns are "inflated by Diwali". That is a plausible explanation, not a measured finding: October 2026 and October 2025 have **different festival exposure** (Diwali falls on 8 Nov 2026 and 20 Oct 2025). The measurement would be a day-by-day comparison against the festival-aligned mapping, which has not been done.

## 11. Exit criteria for the data-backed trial

The trial may start for a named scope (stores, dates, measures) when: I1, I2 and I4 are **Certified** for that scope; S1, S3 and S4 are **Certified** or **Certified with accepted residual**; U1 is **Certified**; S8 and D2 are in force; every other claim has an explicit verdict. Each festival is added when D4 and D5 pass for it. Bills, ABV, comparable-store growth and the real bridge stay unavailable until their own gates pass.

## 12. Risks

- The S1 residual may be unmeasurable inside MISRETAIL; the fallback is acceptance by a named approver with the amount recorded.
- SSRK-backed scans compete with finance extracts and read production tables; they run only with explicit confirmation and coordination.
- The master is a current snapshot with no closure date field (I5).
- Festival dates are lunar; approval before publication is required.
- Typed windows in existing views are stale or overwritten; none of them should be reused as a source of record.

## 13. Blocker-resolution plan

| Blocker | What local analysis has settled | What is still needed | Class of need |
|---|---|---|---|
| April 2026: cube is +5.15% above the dashboard view | **Explained (probe 05a):** instance 196 duplicates 1–3 Apr 2026 and accounts for 99.98% of the sales and unit difference. Instance-selection rule proposed (register section 8) | Approval of the rule; a per-day instance count for every certification window; source owner informed of the duplicate | Decision + MISRETAIL-native query |
| Discount residual (₹148,408 in Aug; ₹683,953 in Apr) | **Explained for August (probe 05c):** it is `EXTRATAXAMT` (₹148,407.86, 18% slab only); `NET = GROSS − TOTALDISC + EXTRATAX` to ₹0.59. April 2026 instance 809 leaves ₹36,200.06 | The owner's definition of `EXTRATAXAMT`; the same recomputation for the other months; the April remainder | Owner definition + MISRETAIL-native query |
| Store 353 tax differences (₹899, ₹99, ₹109) | **Localised (probe 05d):** whole rupees in the 5% GST slab only, three days of 31; extra tax is zero in that slab | Bill-level data for those days (not in the cube) or the store's own explanation | Operational evidence / authorised source access |
| Missing store-days (111 unexplained, store 343 unknown) | Classified; master opening dates contradicted at 7 stores | Dated opening and closure register; day-end records for store 343 | **Operational evidence** |
| Trading dates and eligibility (I5) | Sales cannot establish closure; master fields unusable | An authoritative dated store-status record | **Operational evidence** |
| View side of S1, U1 | Nothing yet | Store-day totals from the dashboard view for a bounded window | **Authorised source access** (SSRK-backed; on hold) |
| Void mechanism (S5) | Behaviour shown, view has no void filter | How voided bills stay out of the view | **Owner explanation or authorised source access** |
| Rounding | Candidates found (₹0.01, ₹0.02) | A policy with Finance | Decision |
| Festival calendar (D4, D5) | Legacy report rules documented; store classifications compared | Festival list, windows, anchors, owners, authoritative date source | Business decisions |
| Bills, ABV, comparable-store growth | Gates written | Bill identifier evidence, owner rulings, cohort rule | Separate gates |
