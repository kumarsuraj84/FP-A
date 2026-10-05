# Sales Comparison: festival comparisons, review of what already exists

5 Oct 2026 (IST). Request: Sales Comparison must also compare festival periods (Holi, Durga Puja, Eid, Diwali, Chhath and so on), and any existing festival reports should be reviewed first.

**Basis:** evidence already collected in Phase 0 (object metadata, the full contents of the small date and store tables, view dependencies). **No new Oracle query was run for this review.** The text of the festival views has not been read yet.

Labels: **table-read** = seen in the actual table contents; **dictionary** = object metadata only; **inference** = my reading of the evidence, to be confirmed by the business. Festival dates quoted from outside the tables are public-calendar dates as I know them and are **inference**.

## 1. Headline findings

1. **The business already classifies stores by festival** (table-read). `T_STORE_OPENING_DATE.FESTIVAL_GROUPING` uses the same vocabulary you gave: DIWALI, HOLI, EID, PUJA, CHHATH, plus BIHU. Of 209 active stores, 101 carry a festival group and 108 carry none.
2. **A festival-aligned last-year plan exists, but nothing reads it** (table-read + dependency check). `T_CALENDER_DATE_PLAN` (455 rows, Jan 2026 to Mar 2027, created 9 Jun 2026) pairs every current date with a different last-year date, one-to-one. Its shifted stretches line up with the festivals in section 4. No database object references it.
3. **The monthly comparison tables are not festival-aligned** (definition-read + table-read). For October 2026 the `ABV_ASP` and `DAY_WISE` tables compare October with October. The Diwali mapping table pairs Diwali 2026 (8 Nov) with Diwali 2025 (20 Oct), so the two Octobers have **different festival exposure**. That is a plausible reason for a gap between this year and last year in those tables; it is **not a measured finding**. Measuring it would need a day-by-day comparison against the festival-aligned mapping, which has not been done. Whole-month totals there should not be read as growth.
4. **Festival windows are overwritten, not kept** (table-read). Tables named "Holi" (`T_NEW_DATE_HOLI_TY_VS_LY` / `_LLY`) currently hold the Diwali 2026 window; `T_NEW_DATE_TWO_YEAR_COMP_FEST` was last replaced 15 Sep 2026. Earlier festivals' windows (Holi 2026, Eid 2026) are not stored anywhere I can see. Festival history therefore has to be rebuilt and kept by the new module.
5. **A naming defect in the holiday list** (table-read): in `T_FESTIVAL_DETAIL`, the column `PRIOR_DATE_15_DAYS` is **14** days before the festival in all 51 rows; `PRIOR_DATE_20_DAYS` is 20. The existing lead-time convention is therefore about 14 and 20 days, whatever the label says.
6. **Two store classifications for festivals disagree** (table-read). `FESTIVAL_GROUPING` and `T_STORE_FESTIVAL_FILTER` (Holi and Eid with PEAK tiers) give different counts: Holi 54 vs 53 stores, Eid 67 vs 34. They serve different purposes (peak tiers), but the authoritative one must be chosen.
7. **History depth: corrected.** I earlier said the dashboard view "starts on 1 Apr 2025". That was **my own query bound**, not a limit of the view: its SQL reaches back to 1 Jul 2020 (definition-read), the bucket view's to 1 Sep 2023, and the POS cube has year instances from FY22-23 (cube registry). What is true is that **none of these were tested for earlier dates**, so Holi and Eid-ul-Fitr 2026 against 2025 (Feb–Apr 2025) remain unproven until checked source by source. See `SOURCE_CERTIFICATION_PLAN.md` section 4 for the reconciliation.
8. **The current festival report is a typed-in seasonal calendar** (definition-read, probe 04a). `V_PDC_SALE_COMPARE_PART_1` (changed 16 Sep 2026, valid) splits Sep–Nov 2026 into four **contiguous** phases, all typed into the SQL: Shradh 26 Sep–10 Oct, Pooja 11–20 Oct, Diwali 21 Oct–8 Nov, Chhath 9–16 Nov. It compares 16 Sep–16 Nov 2026 with 28 Aug–28 Oct 2025 and 20 Sep–20 Nov 2023 through `T_NEW_DATE_TWO_YEAR_COMP_FEST`, for a typed list of 74 stores labelled `26_vs_23`. "PDC" fits Puja–Diwali–Chhath, though the name is not documented. Future days are not cut off (the as-of limit is commented out).
9. **Five of the eleven festival views are INVALID** (status, probe 04a): `V_COMPARE_HOLI`, `V_COMPARE_HOLI_2019`, `V_COMPARE_TY_LY_LLY_FESTIVAL`, `V_SALE_COMPARISION_FESTIVAL` and `V_WEEKLY_SL_FESTIVAL_WISE`. The valid ones are `V_PDC_SALE_COMPARE_PART_1` / `_2`, `V_COMPARE_TY_LY_LLY_FEST_GV`, `V_FOOTFALL_HOLI_COMPARE`, `V_COMPARE_TY_LY_LLY_DAY_V1` and `V_COMPARE_TY_LY_LLY_CONSO`. Several valid ones still carry stale typed windows (the footfall view: Mar–Apr 2025; `FEST_GV`: 2022–2024 dates).
10. **Festival reports read SSRK underneath** (dependency check): `V_COMPARE_HOLI`, `..._FESTIVAL`, `..._FEST_GV`, `..._CONSO` and `V_PDC_SALE_COMPARE_PART_2` reference `SSRK.INVSTOCK` / `INVITEM`; `V_PDC_SALE_COMPARE_PART_1` reads the bucket view, which reads the live POS tables. They are not a source of record for the new module.

## 2. Existing festival objects

| Object | Holds | Last changed | Notes |
|---|---|---|---|
| `V_COMPARE_TY_LY_LLY_FESTIVAL` | store-item level TY / LY / LLY sales, quantity, tax, COGS, discount by `FINAL_DATE` and `WEEK_NO` | 2026-03-30 | Reads `T_NEW_DATE_TWO_YEAR_COMP_FEST`. Dictionary |
| `V_COMPARE_TY_LY_LLY_FEST_GV` | same 26-column shape | 2026-07-27 | "GV" not explained. Dictionary |
| `V_SALE_COMPARISION_FESTIVAL` | adds store attributes, `FESTIVAL_GROUPING`, `TY_STATUS` / `LY_STATUS`, `DAY` | 2024-10-15 | Reads the `_FEST` mapping and `T_STORE_COMPARE`. Dictionary |
| `V_COMPARE_HOLI`, `V_COMPARE_HOLI_2019` | TY / LY by item | 2026-03-30 | `V_COMPARE_HOLI` reads the Holi/Diwali window table. Dictionary |
| `V_FOOTFALL_HOLI_COMPARE` | store, date, TY / LY net footfall | 2025-04-07 | Footfall for festival windows. Dictionary |
| `V_PDC_SALE_COMPARE_PART_1` / `_2` | bills, value, quantity TY / LY / LLY with `FESTIVE_FILTER` | not read | "PDC" not explained. Dictionary |
| `V_WEEKLY_SL_FESTIVAL_WISE`, `T_WEEKLY_SL_FESTIVAL_WISE` | weekly sales and stock by `FESTIVAL_TAG` (6.05M rows) | 2026-03-19 | Weekly, not daily. Dictionary |
| `T_NEW_DATE_TWO_YEAR_COMP_FEST` / `_FESTO` | old-date to new-date pairs with `WEEK_NO` (124 / 136 rows) | 2026-09-15 / 2025-10-13 | Two-year festival alignment. Table-read |
| `T_NEW_DATE_HOLI_TY_VS_LY` / `_LLY` | date pairs, 62 rows each | 2026-09-22 | Named Holi, hold the Diwali window. Table-read |
| `T_CALENDER_DATE_PLAN` | current date to last-year date, 455 rows | 2026-06-09 | Unused by any object. Table-read |
| `T_FESTIVAL_DATA`, `T_FESTIVAL_DETAIL` | Diwali and Chhath day flags; 17 named holidays with lead dates | 2019 | 2018–2020 only. Stale. Table-read |
| `T_STORE_FESTIVAL_FILTER` | 164 stores: HOLI 20, PEAK_HOLI 25, EID 12, PEAK_EID 14, HOLI_&_EID 3, PEAK_HOLI_&_EID 5, none 85 | 2026-03-16 | All 164 are active stores. Table-read |
| `T_STORE_COMPARE_FESTIVAL`, `T_BI_STORE_COMPARE_FESTIVE` | festival-comparison store eligibility (89) and comparison-year flags (105) | 2024-03-29 / 2023-10-04 | Older conventions. Table-read |
| `T_MAMJ25_FESTIVAL_STORE` | 126 stores with Holi, Eid and Bihu flags | 2025-02-28 | One-off for spring 2025. Dictionary |
| `V_AUTO_*_FESTIVAL` (4 views), `T_ALLOC_AUTO_FESTIVE_LISTING` | festive stock allocation and listing | 2024 / 2020 | Merchandising planning, not Sales Comparison. Dictionary |

The festival views' SQL has **not** been read, so how each one defines its windows is not yet known.

## 3. Which stores take part in which festival (table-read, active stores)

| Festival group | Active stores | Where |
|---|---|---|
| Eid | 67 | UP 31, Bihar 24, Assam 6, Odisha 2, Jharkhand 2, CH 1 |
| Diwali | 54 | UP 50, Bihar 2, CH 1, MP 1 |
| Holi | 54 | UP 50, Bihar 2, CH 1, MP 1 |
| Chhath | 24 | Bihar 24 |
| Puja | 23 | Bihar 12, Assam 6, Odisha 2, Jharkhand 2, Tripura 1 |
| Bihu | 7 | Assam 6, Tripura 1 |
| No group | 108 | — |

Groups combine: DIWALI,EID,HOLI 32; DIWALI,HOLI 22; CHHATH,EID 14; PUJA,EID 14; CHHATH 10; BIHU,PUJA,EID 7; PUJA 2. A festival comparison therefore applies to a subset of stores, and a store can take part in several festivals.

## 4. What the plan table's shifted stretches suggest (inference)

`T_CALENDER_DATE_PLAN` is mostly 364/365 days apart, but 62 separate stretches differ (205 of its 455 days). The blocks below are consistent with festival-first alignment; the table does not name the festivals, so this is my reading.

| Current dates (2026) | Mapped to (2025) | Length | Consistent with |
|---|---|---|---|
| 19 Feb to 4 Mar | 1 Mar to 14 Mar | 14 days | Holi (about 4 Mar 2026 vs 14 Mar 2025), D−13 to D |
| 14 Mar to 20 Mar | 25 Mar to 31 Mar | 7 days | Eid-ul-Fitr (about 21 Mar 2026 vs 31 Mar 2025), D−7 to D−1 |
| 21 May to 27 May | 1 Jun to 7 Jun | 7 days | Bakrid (about 27 May 2026 vs 7 Jun 2025) |
| 25 Aug to 28 Aug | 6 Aug to 9 Aug | 4 days | Raksha Bandhan (28 Aug 2026 vs 9 Aug 2025) |
| 17 Oct to 20 Oct | 29 Sep to 2 Oct | 4 days | Durga Puja / Dussehra (about 20 Oct 2026 vs 2 Oct 2025) |
| 26 Sep to 16 Nov (Puja stretch inside) | 7 Sep to 28 Oct | about 7 weeks | Diwali (8 Nov 2026 vs 20 Oct 2025) from about D−43, ending with Chhath (about 15–16 Nov 2026 vs 27–28 Oct 2025) |

The days between the festival blocks are filled so that **every last-year day is used exactly once**. That fill is arbitrary (for example 8 to 25 Sep 2026 map to 4 to 21 Nov 2025). The plan is therefore a sound starting point **inside** festival windows only, and must not be used as a general date mapping.

## 5. Design implications (proposal, not decisions)

1. **Model a festival occurrence, not a table per festival.** Festival, year, key date(s), window (D−a to D+b), applicable store groups, approval status and version. Compare occurrence to occurrence by relative day (D−k with D−k). Last year's and the year before's occurrence are looked up, not computed.
2. **Elapsed-window rule.** While a festival is in progress, compare only the same number of elapsed days and flag the window as incomplete.
3. **Applicability from the store master**, reconciled with the filter table's peak tiers. A store counts in a festival comparison only if it takes part in that festival and was open and trading in both occurrences.
4. **Overlaps.** Durga Puja, Dussehra, Diwali and Chhath sit within about six weeks of each other. Windows will overlap, so each festival is its own view and the screen flags overlap days; totals across festivals are never added.
5. **Lunar dates are maintained by the business each year**, with edit and approval before publication. Eid can move by a day with the moon sighting.
6. **Default lead times:** the existing convention is about 14 and 20 days before. The earlier proposal of D−20 to D+7 is consistent; the final windows are a business decision.
7. **Reuse versus rebuild:** reuse the plan table's festival blocks as a seed for 2026, and the grouping vocabulary; rebuild the history and keep versions, because the existing tables overwrite.
8. **Source for sales:** use the store-day sales source from the certification plan with our own windows, not the item-level festival views.
9. **The allocation `V_AUTO_*_FESTIVAL` views belong to Merchandising**, not to this report.

## 6. Questions for the business

1. Which festivals first, and which are separate (Dussehra and Durga Puja, Diwali and Chhath, Eid-ul-Fitr and Bakrid, Bihu)?
2. The window before and after each festival.
3. Which store classification is authoritative: `FESTIVAL_GROUPING` or the filter table with PEAK tiers, and what does PEAK mean?
4. Who maintains and approves each year's festival dates?
5. How far back must festival comparisons go? Spring 2026 festivals need Feb–Apr 2025 daily data that the tested source does not hold.
6. What "GV" and "PDC" stand for, and whether those reports are still used.

## 7. Follow-up status

- **Done (probe 04a, run `run_20261005_030`, metadata only):** status, dependencies and text of 11 festival and comparison views (findings 8 to 10 above).
- **Still open:** the distinct `FESTIVAL_TAG` values and week range in `T_WEEKLY_SL_FESTIVAL_WISE` (one small grouped query; the view over it is INVALID, so this is low priority), and the earliest dates per source (see the plan).
- **Design proposal** (order, anchors, D−21 to D+7 windows, equal-elapsed rule, owners and approvers, store classifications not chosen automatically) is in `SOURCE_CERTIFICATION_PLAN.md` section 10.

## 8. Effect on the prototype

None yet. Festival-stage comparison stays **unavailable** on the Sales Comparison page, with the reason. Once the festival list and windows are agreed, a festival mode can be added to the sample prototype first (sample festival calendar, applicability by store group, elapsed-window flag) before any real data is connected.
