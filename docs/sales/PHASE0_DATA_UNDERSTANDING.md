# Operations · Sales Comparison: Phase 0 Data Understanding Brief

Version 3, 5 Oct 2026 (IST). Supersedes versions 1 and 2.
Scope: understand the data, map sources to metrics, set a calculation contract, list what is unresolved. No extraction for loading, no mart, no cubes, no screens, no calendar implementation.

## Evidence labels

- **Dictionary**: from the MIS data dictionary or object metadata; the data itself was not queried.
- **Definition-read**: from the SQL text of a view or the source of a procedure, read through the dictionary. It tells us what the object is built to do, not that the data is right.
- **Sample-verified**: seen in a bounded live probe on named dates, months or objects. A sample check does **not** certify the whole history.
- **Unresolved**: not established. Listed in section 11.

## 1. How the evidence was gathered

- Route: Inventory Automation broker only, MISRETAIL only, inside the broker guard. The user authorised the route; it is **not** treated as a security exemption (section 10). The FP&A direct login (`backend/.env`) was used once, for `oracle-check` only, and no probe used it.
- Seven probes, 54 datasets, all completed: `sales_probe_01` (11), `02` (25), `03a` (6), `03b` (6), `03c` (4), `03d` (1), `03e` (1). Exact SQL, parameters, durations, row counts and guard hashes: [PHASE0_PROBE_LOG.md](PHASE0_PROBE_LOG.md). No guard rejection and no timeout at run time.
- **Invalid evidence:** `a11_pos_store_day` (probe 02) returned 0 rows because its filter was `ISVOID = 'N'` and the cube stores `'No'` / `'Yes'`. That result is a filter error, not zero activity. It was superseded by `c4_pos_store_day` (probe 03c). Also `c3_pos_rows_per_bill` returned 0 rows because bill numbers are null (finding, section 6).
- **Service coordination.** The finance session's `run_20261005_022` completed 14 of 14 before the follow-up began. Probes 03a to 03e ran between 16:18 and 16:28 IST with no `broker.py` process active and no other run starting in that window. Earlier, probe 02 (long scans) overlapped with the finance runs 020 and 021, which halted with timeouts; causation is not established.

- **Where the probe code lives (commit history, not rewritten).** `sales_probe_01` and `sales_probe_02` are inside commit `bf1c2e5`, a finance creditor-selections commit made by the other session: an earlier `git add tools` swept them in. That history is left intact because the branch is shared and unpushed. `sales_probe_03a` to `03e` are in their own commit `f869307`. `sales_probe_04a` to `04c` are in `a145383`. `sales_probe_05a`, `05c` and `05d` were swept into the other session's commit `74448e3`, and `05e` into `3f7cd30`, because `packages.py` is a shared file; that history is left intact. The sample prototype is `824c15d` and `de5d541`.
- **Reading the per-store-day average.** On the Sales page, sales per store-day with data (shown for custom periods) is a **coverage-dependent average**. If missing data changes which stores or days contribute, it can move without any change in trading. The page shows the coverage beside it and says it is not comparable-store growth.
- **Related documents:** festival review `FESTIVAL_REVIEW.md` (festival comparisons are in scope for Sales Comparison); next-stage plan `SOURCE_CERTIFICATION_PLAN.md`.

## 2. What the comparison tables really are

**Definition-read** (view text) and **sample-verified** (the table contents match the definition).

| Item | Finding |
|---|---|
| Refresh | `PROC_T_SALES_COMPARISION` and `PROC_T_SALE_CONSOLIDATED` only truncate and reload four tables from `V_SALE_COMPARE_ABV_ASP`, `V_SALE_COMPARE_DAY_WISE`, `V_SALE_COMPARE_CONSOLIDATED`, `V_SALE_COMPARE_ASP_ABV`. They hold no comparison logic. |
| Period | `V_SALE_COMPARE_ABV_ASP` has the current month **typed into the SQL** as literals: this year 1–31 Oct 2026, last year Oct 2025, year before Oct 2024. Someone edits it each month (last changed 2026-10-01 18:10). That is why `ABV_ASP` and `DAY_WISE` hold October only. `CONSOLIDATED` holds Apr–Oct 2026 for 120 stores. |
| Store scope | Hard-wired to `T_STORE_COMPARE_120` (120 stores). A literal list of 28 store names decides the `YEAR_COMPARISON` flag (`26_vs_24` = 92 stores, `-` = 28). |
| Dates | Last-year dates come from `T_NEW_DATE_TWO_YEAR_COMP_20` (ABV_ASP and, through `V_COMPARE_TY_LY_LLY_DAY_V1`, DAY_WISE) and from `T_NEW_DATE_TWO_YEAR_COMP_ADHOC` (CONSOLIDATED and ASP_ABV). Not from `T_CALENDER_DATE_PLAN`. |
| Row duplicates | `ABV_ASP`: 4,200 rows but 3,720 distinct (store, day) pairs because the view unions a zero-valued footfall row per store-day with the sales row. Sums are safe; row counts are not store-day counts. (The cashback-filter join did not inflate sums: TY value equals `DAY_WISE` to ₹0.01 on 1 and 2 Oct.) |
| Future days | TY columns are zero for days after the as-of date while LY is populated. Zero here means "not yet happened". |
| `ABV_ASP` vs `DAY_WISE` | Equal to ₹0.01 on 1–2 Oct; differ ₹85,883 (0.6%) on 3 Oct and ₹310,535 (1.2%) on 4 Oct. **Explanation supported, not proven:** `ABV_ASP` reads live POS tables through `V_SALE_BUCKET_WISE`; `DAY_WISE` reads the materialised `T_CUSTOM_COGS` (dictionary notes a settlement lag of about 10 days). Different sources and refresh moments would differ on the newest days only, which matches. A direct test needs a daily `T_CUSTOM_COGS` scan, not run. |

**Conclusion:** the compare tables cannot be the certified source. They are monthly reporting snapshots with hand-edited periods and a fixed 120-store scope.

## 3. Date mappings: what exists, what is used, where they disagree

| Object | Rows | Read by | Coverage | Alignment |
|---|---|---|---|---|
| `T_NEW_DATE_TWO_YEAR_COMP_20` | 62 | `V_SALE_COMPARE_ABV_ASP`, `V_COMPARE_TY_LY_LLY_DAY_V1` and older views | TY 1–31 Oct 2026 ← 31 dates of Oct 2025 and 31 of Oct 2024; each date once, none null | Gaps to last year: 365 days ×19, 364 ×8, 367 ×4 (weekday shift 0 on 8, 1 on 19, 3 on 4). Mostly same calendar date with local swaps |
| `T_NEW_DATE_TWO_YEAR_COMP_ADHOC` | 428 | `V_COMPARE_TY_LY_LLY_CONSO`, `V_SALE_COMPARE_ASP_ABV` | TY 2026-04-01 to 2026-10-31 (214 dates), exactly one last-year and one year-before date each | Gaps to last year: 365 ×75, 364 ×68, 367 ×17, 357 ×16, others |
| `T_CALENDER_DATE_PLAN` | 455 | **No database object** | 2026-01-01 to 2027-03-31, no FY26-27 date missing, no last-year date reused | 302 of 455 weekday-aligned; festival-shifted stretches (gaps up to 395 days). Aligns Diwali 2026 (8 Nov) to Diwali 2025 (20 Oct) |
| `T_NEW_DATE_HOLI_TY_VS_LY` / `_LLY` | 62 / 62 | `V_COMPARE_HOLI` only | 2026-09-16 to 2026-11-16 | Named "Holi", holds the Diwali window. `_LLY` equals `T_NEW_DATE_TWO_YEAR_COMP_FEST` on all 62 dates |
| `T_NEW_DATE_TWO_YEAR_COMP_FEST` / `_FESTO` | 124 / 136 | Festival comparison views | 2026 window / 2025 window | Festival-stage alignment, two-year |
| `T_FESTIVAL_DATA`, `T_FESTIVAL_DETAIL` | 56 / 51 | not examined | 2018–2020 only | **Stale** list of holidays |
| `T_STORE_FESTIVAL_FILTER`, `T_STORE_COMPARE_FESTIVAL`, `T_BI_STORE_COMPARE_FESTIVE` | 164 / 89 / 105 | not examined | Store level | Store-group applicability exists; `T_STORE_OPENING_DATE.FESTIVAL_GROUPING` carries combined groups |
| `T_KEY_LODGER_EVENT` | 35 | n/a | n/a | **Not a calendar**: POS keystroke audit events |

**Sample-verified disagreements** (computed from the full contents of each table):
- `_COMP_20` vs `T_CALENDER_DATE_PLAN`: agree on **0 of 31** October dates (for example 1 Oct 2026 maps to 1 Oct 2025 in `_COMP_20` and to 12 Sep 2025 in the plan).
- `_ADHOC` vs the plan: agree on **47 of 214** dates.
- Plan vs the Holi table: disagree on 28 of the 62 dates they share; the table the views use agrees with neither on those dates (it does not cover them, or maps elsewhere). **These 28 conflicts are therefore not part of the live comparison.**

**What this means:** there is no single authoritative last-year mapping. The MIS reports compare "same month, nearly the same dates"; a festival-aligned mapping exists but nothing reads it. Which convention CityKart wants is a **business decision**. A mapping table must be chosen and versioned by the new module, and every comparison must show the actual reference dates. "No gaps" in the plan table proves coverage, not correctness.

## 4. Sales measure: verified facts

All **sample-verified** on completed months and one day; the POS cube is `CUBE$POSBILLSUMM` (non-void rows), the dashboard view is `V_CFO_DASHBOARD_SL_V`.

| Question | Finding |
|---|---|
| GST | `NETAMT` includes GST: `TAXABLEAMT + TAXAMT = NETAMT` within ₹99 (Sep 2026) and ₹1,107 (Aug 2026) on ₹1,000–1,350 million. |
| Returns and promotion | `SALEAMT + RETURNS − PROMOAMT = GROSSAMT` to within ₹0.03 (Sep 2026) and ₹0.01 (Aug 2026). Returns are carried as negative amounts and are already inside the total. |
| Discount | `NETAMT ≈ GROSSAMT − DISCOUNT`, but not exactly: NET is higher by ₹37,890 (0.004%, Sep 2026) and ₹148,407 (0.011%, Aug 2026). Unexplained; discount treatment is certified only to that tolerance. |
| Cancelled (void) bills | **Two different statements, two different sources, reconciled here.** (1) *`V_CFO_DASHBOARD_SL_V` (definition-read):* its SQL contains **no void predicate**; it reads `SSRK.PSITE_POSBILL` and `PSITE_POSBILLITEM` directly. (2) *`CUBE$POSBILLSUMM` (sample-verified):* it carries an `ISVOID` flag; `'Yes'` rows are tiny (for example 1 row, −₹1,098 on 15 Sep 2026; ₹83,487 net in Apr 2025). *Reconciliation:* over whole months the dashboard total equals the cube's **non-void** total and not the total with voids (Apr 2025: view is ₹433 below non-void but ₹83,920 below non-void-plus-void; Sep 2026: ₹13,144 below versus ₹56,966 below). So the dashboard figure **behaves** as excluding voids. The mechanism is **unproven**: either voided bills are not in `PSITE_POSBILL`, or they are flagged in a way the view's joins drop. The single-day sample is not decisive on its own (the view is ₹290 below non-void and ₹808 below non-void-plus-void). Sales are not certified on this point until the mechanism is shown (U14). |
| Dashboard view vs POS cube, store level, 15 Sep 2026 | Same 206 stores. **202 of 206 stores equal to the paisa.** Four stores differ by ₹150, ₹70, ₹35 and ₹35 (total ₹290; cube higher). Cube tax is higher by ₹28.50 and quantity by 5. |
| Same, monthly | **Corrected 5 Oct evening.** For the two months first compared, the cube was higher by ₹433 (Apr 2025) and ₹13,144 (Sep 2026). Across all 19 months in hand, 17 differ by under 0.012%, but **April 2026 differs by +5.15% (₹7.07 crore)** and October 2026 (partial) by −0.17%. See `CERTIFICATION_REGISTER.md` section 8. |
| Cause of the residual | **Hypothesis, unproven:** the dashboard view drops lines from the divisions `FIXED ASSETS` and `NON-TRADING` and lines whose item is missing from `ITEM_MV` (a null division fails `NOT IN`). Sign (cube ≥ view) and tiny size are consistent. The excluded amounts were not measured. |
| Cost basis | The view's `COGS_V` uses `QTY × LAST_IN_RATE`, the **current** cost rate, not the cost at the time of sale. Not suitable for margin; `T_CUSTOM_COGS` is the margin source (out of trial scope). |

## 5. Store key

- **Intended key:** `ADMSITE_CODE` is the store identifier (`PSITE_POSBILL.ADMSITE_CODE`). The view groups by `(ADMSITE_CODE, BILLDATE)`, so **(store, day)** is the row identifier **by definition** (definition-read).
- **Sample-verified:** 15 Sep 2026: 206 rows, 206 distinct codes, all 206 in `T_STORE_OPENING_DATE` (341 rows, 341 distinct `SITE_CODE`, no null: no join multiplication), all ACTIVE, none flagged DC. The POS cube returned the same 206 sites. 15 Sep 2025: 148 rows, all in the master. 30 Sep 2026: 207 rows, all in the master. Stores selling grew by 58 year on year.
- **Name is not a key:** `T_STORE_OPENING_DATE.STORE_NAME` has a duplicate (`JGRxx`), and the compare tables and bucket view key on **name**. Joins must go through code.
- **What contradicted the key, stated exactly:** a monthly query on the dashboard view returned `COUNT(DISTINCT ADMSITE_CODE)` equal to `COUNT(*)` (for example 6,127 for Sep 2026). A monthly distinct count above the daily count is normal, but a distinct count of **store codes** cannot exceed the 341 codes in the master, and it contradicts the cube, which shows 209 distinct sites for the same month. The most likely cause is a query-shape artifact in that view, not a changing code. This was **not retested** (a retest costs several minutes of scanning production tables underneath). Rule: never take distinct counts from that view; count stores from the master or the cube.

## 6. Bills

| Source | Finding |
|---|---|
| `CUBE$POSBILLSUMM` | `BILLNO` is **null on every row** (0 of 70,098 non-void rows on 15 Sep 2026; 0 of 40,807 on 15 Sep 2025). The cube is a bill-by-tax-slab summary (70,098 rows for 52,114 bills, about 1.34 rows per bill). It **cannot count bills**. |
| `V_CFO_DASHBOARD_SL_V.BILL_COUNT` | `COUNT(DISTINCT BILLNO)` per (site, day). Definition-read. |
| `V_SALE_BUCKET_WISE` (bucket view behind `ABV_ASP`) | A bill is `(STORE_NAME, BILLDATE, BILLNO)` summed over its lines, put in a value bucket (including `NEGATIVE SALE`), then counted. Valid; history from 2023-09-01 by its text. Definition-read. |
| Agreement of the two counters | **Sample-verified, 15 Sep 2026:** 52,114 bills in both, **0 differences across 206 stores**, value identical (₹35,877,752.88). |
| Return bills | **1,522 of the 52,114 bills (2.9%) are return ("negative sale") bills and count as bills.** ABV computed from this count mixes returns with sales. |
| Voids | The bill views have no void predicate; totals behave as if voids are excluded (section 4, U14). Whether voided bills are counted as bills is unproven. |
| Invalid views | `V_DAYWISE_BILLCUT` and `V_SALE_COMPARE_BILL_CUT` are INVALID; see section 9. |

The two counters agree but read the **same** bill-number field, so the agreement is internal consistency, not independent proof. The remaining questions cannot be answered inside MISRETAIL: whether the same bill number can appear on two terminals or sessions of one store on one day (the MIS merges them), and how cancelled/returned bills should count. The raw bill table is in SSRK, which FP&A may not query. **No bill identity is certified.**

## 7. Source-to-metric map

| Metric | Source for a trial | Evidence | Status |
|---|---|---|---|
| Sales (incl. GST) | `V_CFO_DASHBOARD_SL_V.SL_V` (its SQL reaches 2020-07-01; tested only from 2025-04-01 by my query bound), reconciled to the POS cube | sample-verified | conditional |
| Sales ex-GST | `SL_V − TAX_V` | sample-verified (₹99–1,107 a month) | conditional |
| Units | `SL_Q` | sample-verified totals; quantity differs by 5 on the sample day | conditional |
| Bills | `BILL_COUNT` / bucket view | definition-read; two counters agree on one day | **unavailable** until the bill rule is set |
| ABV, UPB | Derived from bills | — | **unavailable** |
| ASP | Sales ÷ Units | derived; returns lower units | conditional |
| Bills → ABV bridge | — | — | **unavailable** |
| Store contribution | Dashboard view by store-day, store attributes from the master via code | sample-verified key | conditional |
| Department contribution | not yet identified | compare tables are one month and 120 stores | **unavailable** |
| Comparable stores | master plus rule | rule undecided (120 vs more than 6 months vs AOP cohort) | **unavailable** |
| Same calendar date | Our own rule from history (this date − 1 year), reference dates shown | reach per source being certified; see the plan, section 4 | conditional |
| Same weekday | Our own 364-day rule, reference dates shown | as above | conditional |
| Custom period | Any two periods, day counts shown | as above | conditional |
| Festival-stage comparison | A versioned festival mapping owned by the new module | mappings disagree; business decision needed | **unavailable** |
| Footfall, conversion | `ABV_ASP` footfall counters | current month, 120 stores, zero-filled on sales rows | **unavailable** |
| Targets | `T_STORE_SALE_TARGET` | not probed | **unavailable** |
| Gross margin | `T_CUSTOM_COGS` | out of scope; view cost is current rate | **unavailable** |

**History limits (corrected, 5 Oct evening):** earlier text here said the dashboard view starts in April 2025. That was **my own query bound**, not a limit of the view. The view's SQL reaches 1 Jul 2020, the bucket view's 1 Sep 2023, and the POS cube has year instances from FY22-23 (cube registry). What was actually tested is only April 2025 onward, so earlier reach is **untested** for every source. The reconciliation by source and measure is in `SOURCE_CERTIFICATION_PLAN.md` section 4. Unsupported reference dates must show **unavailable**, never zero.

## 8. Calculation contract (proposal, not approved)

- **Calendar** April–March. As-of date = last complete business day.
- **Headline sales** = `SL_V`, labelled "Sales (incl. GST)" and kept **provisional** until the open reconciliation items in `CERTIFICATION_REGISTER.md` are explained (the April 2026 cube difference of +5.15%, the tax-identity exceptions at store 353, and the discount residual) and a rounding policy exists. Ex-GST = `SL_V − TAX_V`, documented separately.
- **Bills, ABV, UPB, the Bills → ABV bridge** show an explicit **unavailable** state, with the reason, until a bill identity and counting rule are agreed (section 6). When agreed, bridge order is shown on screen: Bills effect = (Bills_cur − Bills_ref) × ABV_ref; ABV effect = (ABV_cur − ABV_ref) × Bills_cur; the two must sum to the sales difference, otherwise the bridge shows unavailable. Extend to Bills → UPB → ASP only after units are independently verified.
- **Ratios** recomputed from summed components, never averaged.
- **Missing vs zero:** no source row = "no data". Future days are not zero. A closed or not-yet-open store-day is "not trading".
- **Periods:** same calendar date and same weekday computed by us from history; custom period with unequal day counts shown; festival-stage only after the mapping decision. Reference dates are always displayed. Leap day: handled by the mapping rule, tested explicitly.
- **Comparable stores:** All / Comparable / New. Not decided; the AOP SSSG cohort is not reused until its period and rules are confirmed.
- **Controls:** source totals before and after extraction; extract = mart = API; every drill reconciles to its parent; mart reconciles to the dashboard view and to the POS cube at store-day level on sample days; no figure is certified from a sample alone.

## 9. INVALID views

| View | Status | Last changed | Depends on | In the refresh path? |
|---|---|---|---|---|
| `V_DAYWISE_BILLCUT` | INVALID | 2026-03-30 | `ITEM_MV`, `SSRK.PSITE_POSBILL`, `SSRK.PSITE_POSBILLITEM`, `T_STORE_OPENING_DATE` | **No** |
| `V_SALE_COMPARE_BILL_CUT` | INVALID | 2024-10-15 | `V_DAYWISE_BILLCUT` (invalid), `T_STORE_COMPARE`, `T_STORE_OPENING_DATE`, `V_DUMMY_REMOVE` (valid) | **No** |

The dictionary records **no compile errors** for either (`ALL_ERRORS` returned no rows), so the cause is unknown; invalidation after a dependent change is the usual reason but that is an inference. Nothing was compiled or repaired. The four tables the refresh procedures load come from views that are all VALID with valid dependencies, so the invalid views do not by themselves make those tables unreliable. They remove `V_DAYWISE_BILLCUT` as a bill source.

## 10. Broker governance

- **Known from code:** the broker guard (`guard.py`) enforces one SELECT, no DML/DDL/PL/SQL/locking/packages/db links/INTO, MISRETAIL-qualified objects, metadata queries restricted to owner MISRETAIL, a row cap on every query, a date bound and named columns on extracts, and a PII column-name check. `platform.db` is backed up before each run. FP&A queries use the `FPA__` prefix.
- **Known limitation:** Inventory Automation validates SQL when a query is saved; its engine does not re-check. The guard is the main control on our side.
- **Unresolved:** the Oracle account Inventory Automation uses. The broker never reads its connection details, by design. Whether it is read-only needs DBA or operator evidence; broker behaviour does not prove database privileges.
- **FP&A's own login is separate and unused:** `oracle-check` on `backend/.env` returned `WRITE_CAPABLE_PRIVILEGES_PRESENT` (schema owner, about 170 write-capable privileges). A dedicated read-only user is still the pending remedy.
- **Indirect SSRK exposure:** several MISRETAIL views read `SSRK.PSITE_POSBILL`, `SSRK.PSITE_POSBILLITEM` and `SSRK.INVSTOCK` underneath. The broker queries only MISRETAIL objects, but scanning those views reads production tables (the slowest probes took 2–9 minutes). Keep such scans few, narrow and off peak hours; prefer materialised copies for a trial.

## 11. Unresolved-issues register

| # | Issue | Status after follow-up | Needed to close | Blocks |
|---|---|---|---|---|
| U1 | Which mapping drives the comparison | **Resolved:** `_COMP_20` (ABV_ASP, DAY_WISE) and `_ADHOC` (CONSOLIDATED). The plan table has no readers. The 28 plan-vs-Holi conflicts are not in the live comparison | — | — |
| U1b | Which mapping convention CityKart wants: same month nearly same date vs festival-stage | Open, business decision. The three tables disagree materially (0 of 31, 47 of 214) | Owner decision; then a versioned mapping in the new module | Festival and LY mapping |
| U2 | Store key | **Largely resolved:** identity and store-day grain by definition; master join 1:1 on three sample dates. The monthly distinct-count anomaly is explained as a probable query artifact but not retested | Optional retest with a wrapped distinct on two days | Wording only |
| U3 | Bill identity and counting rule | Open. Cube cannot count; two MIS counters agree on one day; return bills count as bills (2.9%); terminal/session uniqueness untestable in MISRETAIL | Owner/IA ruling on (store, day, bill number) uniqueness and on return and cancelled bills; or approval to read the raw bill table | Bills, ABV, UPB, bridge |
| U4 | Dashboard vs POS residual | Narrowed to four stores and ₹290 on the sample day (202 of 206 exact). Cause hypothesised (excluded divisions and items without master match), not measured | Measure excluded divisions and unmatched items for those four stores (needs item-level data) | Dropping "provisional" |
| U5 | `ABV_ASP` vs `DAY_WISE` differences | Explanation supported (different sources and refresh moments), not proven | Daily comparison against `T_CUSTOM_COGS` | Using either for reconciliation |
| U6 | History | Compare tables: October only (CONSOLIDATED Apr–Oct, 120 stores). Dashboard view reaches 2020-07-01 by definition but was tested only from Apr 2025 (my bound). Year-before reach is untested | Single-day reach checks per source (certification plan, stage 2 and 3) | LY/LLY beyond the above |
| U7 | Comparable-store rule | Open. 120-store list is a fixed table; more than 6 months is a dictionary rule; AOP cohort unconfirmed | Owner decision | Comparable growth |
| U8 | INVALID views | Not in the refresh path; cause unknown; not repaired | DBA | Confidence only |
| U9 | Extraction account privileges | No evidence | DBA/operator statement | Governance sign-off |
| U10 | Department and item history | Not probed | `ITEM_MV` join design after U3 | Department contribution |
| U11 | Discount tolerance | NET differs from GROSS − DISCOUNT by 0.004–0.011% | Accept or explain | "Sales" certification |
| U12 | SSRK exposure through views | Documented | Scan policy and off-peak window | — |
| U13 | Closed and new stores in comparisons | Not tested | Validate opening dates, closures and trading coverage per store and period | Comparable cohort |
| U14 | Void mechanism: view SQL has no void filter, yet totals behave as non-void | Behaviour shown over months; mechanism unproven | Show how voided bills are kept out (source table or join) without querying SSRK directly, or accept with the tolerance stated | "Sales" certification |
| U15 | Technical bill identifier incl. terminal/session reuse | Open (section 6) | Verify identifier before certifying Bills or ABV | Bills, ABV |

## 12. Readiness verdict

Two separate questions:

**A. Labelled sample-data design (prototype of the screens): ready to start, with conditions.** The measures, the comparison choices and the unavailable states are defined well enough to design against. Rules for the design: every number is labelled sample data; Bills, ABV, UPB, the bridge, department contribution, comparable stores, festival comparison, footfall and targets appear in their **unavailable** state with the reason; reference dates are always shown; "Sales (incl. GST)" carries a provisional badge. It does not start until you say so.

**B. Data-backed trial: not ready.** Blocked by U3 (no certified bill identity or counting rule), U1b (no agreed last-year mapping convention), U7 (no comparable-store rule) and the open governance items (U9). Sales, ex-GST sales, units, ASP, store contribution and same-date, same-weekday and custom-period comparison are **conditional** (usable once the residual wording is accepted and history limits are enforced). 

Smallest next steps that need decisions rather than more probing: the bill rule (U3), the mapping convention (U1b), the comparable-store rule (U7).

## 12b. Decisions recorded (5 Oct 2026, from the user's review)

1. **Bills:** propose **separate purchase-bill and return-document counts** (the MIS counts return bills as bills, 2.9% on the sample day). Verify the technical identifier, including terminal reuse, before certifying Bills or ABV.
2. **Comparison:** same dates, same weekdays and custom periods are separate, selectable modes. Festival-stage comparison is added later. The manual October mapping used by the MIS tables is **not** the default.
3. **Comparable stores:** a fixed cohort eligible in both periods. Validate opening dates, closures and trading coverage before accepting the 120-store list or the AOP cohort.
4. **Design:** start the labelled sample-data prototype now; unsupported real metrics show unavailable states. Further Oracle probes wait.
5. **Festivals (added later the same day):** Sales Comparison will also compare festival periods (Holi, Durga Puja, Eid, Diwali, Chhath and others). Existing festival reports were reviewed in `FESTIVAL_REVIEW.md`. Festival-stage comparison stays unavailable until its calendar is agreed.

## 13. Finance entry-layer pending state (recorded, not changed)

- `HEAD` of `feature/profit-cash-discovery`: `01b013b`, committed 15:30:49 IST: till drill ends at the store-day; Cash Drawer POS-line selection and post-extract histogram removed; migration `006_entry_till_day_only.sql`, API and tests updated. **Migration 006 is a file; whether it is applied to `fpa_pilot` is not confirmed** (the database administrator applies it, run by the user).
- Uncommitted: `tools/extraction_broker/packages.py` (the sales probes added in this phase; no entry changes) and three regenerated evidence docs (`docs/creditors_pilot/MART_SCRATCH_UAT_EVIDENCE.md`, `docs/profit_cash/CASH_MART_UAT_EVIDENCE.md`, `docs/profit_cash/ENTRY_MART_UAT_EVIDENCE.md`). Untracked: root log files and `docs/sales/`.
- 05 Oct entry extract: `run_20261005_014` (old package, halted), `015` (timeout), `016` (stopped by me after four datasets), `020` (new package, halted at `c1_totals_post`), `021` (halted at `c1_totals_pre`), `022` (new package, **completed 14 of 14**, started by the other session; **not staged or loaded**). Runs 023–027 belong to this Phase 0 work.
- Creditors `run_20261005_012` and Cash `run_20261005_013`: api_verified, unpublished, unchanged. Nothing promoted.
