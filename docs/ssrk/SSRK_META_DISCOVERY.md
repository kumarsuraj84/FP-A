# SSRK metadata discovery (2026-10-07)

Source: broker package `ssrk_meta_probe_01`, run `run_20261007_008`, login `SSRK_RO` (read-only, verified by `login_access_probe_01`, run `run_20261007_007`).
**Metadata only**: `ALL_TABLES`, `ALL_VIEWS`, `ALL_TAB_COMMENTS`, `ALL_TAB_COLUMNS` for owner SSRK. Row counts are optimizer statistics (last analysed 25 Sep to 06 Oct 2026), never `COUNT(*)`. No data object was read. SSRK is live production.

## Inventory
- 1,991 tables (1,859 with statistics, 132 never analysed), 1,113 views, 70,978 columns, 126 commented objects.
- Heavy objects (estimated rows): `INVSTOCK` 442 M, `PSITE_POSBILLITEM` 257 M, `SALCSDET` 186 M, `PSITE_POSBILLMOP` 79 M, `PSITE_POSBILL` 74 M, `SALINVCHG_ITEM` 70 M, `SALINVDET` 36 M. Any query on these must be date-bound and partition-aware; none is a candidate for a first query.
- Large groups by prefix: `AUD2_*` 221 (audit copies), `PSITE_*` 167 (POS), `INT*` 121, `MIS*` 113, `TEMP*`/`STAGE*`/`STAGING*` about 220 (scratch: not finance sources). `MLOG$_*` snapshot logs show that MISRETAIL is a replica of SSRK masters.

## Finance transaction stack (the live source behind the MISRETAIL cubes)
| Object | Est. rows | Notes |
|---|---:|---|
| `FINPOST` | 8.07 M | Ledger postings: ENTCODE/ENTNO/ENTDT/ENTTYPE, DOCNO/DOCDT/DUEDT, GLCODE, SLCODE, DAMOUNT/CAMOUNT, ADJAMT, CHQ fields, TDS fields, RELEASE_STATUS, ADMSITE_CODE_OWNER, ECODE/TIME (maker), RELEASE_ECODE/RELEASE_TIME (releaser) |
| `FINCOSTTAG` | 7.95 M | Cost-centre split of postings (COSTCODE, ADMSITE_CODE, per entry) |
| `FINVCHMAIN` / `FINVCHDET` | 138 k / 172 k | Vouchers: header (VCHCODE, VCHNO, VCHDT, VCHTYPE, REFNO, NARTEXT, ENTRY_SOURCE) and lines (GL, SL, CHQ, PAYMENT_MODE, TDS) |
| `FINJRNMAIN` / `FINJRNDET` | 153 k / 324 k | Journals |
| `FINCHQMAIN` / `FINCHQDET` | 885 / 61 k | Cheque books and cheque status |
| `FINSL`, `FINSL_GL`, `FINSL_GL_SITE`, `FINSL_OU`, `FINSLOP` | 13 k to 60 k | Sub-ledger master, links to GL and site, opening balances |
| `FINGL`, `FINGL_SITE`, `FINGLOP`, `LEDGER_MV` | 576 to 113 k | Ledger master, site mapping, opening balances |
| `FINNAR` | 144 k | Narrations |
| `FINGLBUD` | 15 k | **Budget by GL, month code, sub-ledger and cost centre** (BUDDAMT/BUDCAMT, ACTDAMT/ACTCAMT). Budget is deferred, but a candidate source now exists. |
| `FINTDS_EXCEPTION`, `FINTAX_RANGE`, `GST_DOCNO_CHECK`, `TAX_RECALC_HISTORY` | 5 k to 73 k | Tax controls |

Purchase and sales documents: `PURINVMAIN/DET/CHG*` (131 k / 821 k), `PURORD*`, `PURSRV*`, `PURRT*`, `SALINVMAIN/DET/CHG*` (69 k / 36 M).

## Observations
- The finance tables carry the entry-level facts the Entry layer needs (maker, releaser, release status, document and cheque references) in one place, with far smaller sizes than POS or stock.
- Names such as `*_BKP_*`, `*_CHECK`, `*_DELETED`, `TEMP_*`, `TT2` are copies or scratch; they must not be treated as sources.
- 132 tables have no statistics: their size is unknown, so they need a metadata look before any query.

## Not yet done (each needs your go-ahead)
1. Compare SSRK finance tables to the MISRETAIL cubes already in use (row-estimate and column coverage, metadata only) to see what SSRK adds.
2. Index and partition metadata for `FINPOST`, `FINCOSTTAG`, `FINVCHMAIN` (`ALL_INDEXES`, `ALL_IND_COLUMNS`, `ALL_TAB_PARTITIONS`) to plan date-bound reads.
3. First bounded sample (single day, capped) of one finance table.

---

# Part 2: comparison with MISRETAIL, and index / partition plan (2026-10-07)

Runs: `run_20261007_009` (`ssrk_meta_probe_02`) and `run_20261007_010` (`misretail_visibility_probe_01`). Metadata only.

## 1. SSRK vs MISRETAIL
- **No table name is shared.** MISRETAIL holds 83 tables, all `T_*` report/summary tables (largest: `T_AUTO_BRCD_REQ_V7` 145 M, `T_CUSTOM_COGS` 104 M, customer-segment tables 21 to 24 M, `T_SALE_COMPARE_CONSOLIDATED` 16 M, `T_DASHBOARD_SL_V` 13 M). It has no views and no synonyms. So MISRETAIL is a derived reporting layer, not a mirror of the SSRK finance tables, and nothing in SSRK can be matched to it by name.
- SSRK's own `MLOG$_*` snapshot logs (masters such as `FINGL`, `FINSL`, `ADMSITE`, `INVITEM`) show SSRK masters are replicated outward; the finance transaction tables (`FINPOST` and the rest) are not among them.
- **Visibility finding (needs action).** With the new login the MISRETAIL schema shows only those 83 `T_*` tables (all VALID). **The finance registers and cubes the existing pipelines read (`T$FINREGSITE_877`, `T$FINREGSITE_844`, the outstanding cube and the other `T$*` objects) are not visible** to `SSRK_RO` (`ALL_OBJECTS`/`ALL_TABLES` show only objects the login may select). The Creditors, Cash, Entry and P&L extracts will therefore fail at the readiness gate until the role is granted SELECT on those objects, or the old grants are restored. `T_CUSTOM_COGS` is visible.
- Consequence for the P&L: the books side (the `T$FINREGSITE` registers) can be re-created from SSRK `FINPOST` (+ `FINGL`, `FINGL_SITE`, `FINSL`) only after a reconciliation against the existing, verified runs; nothing is switched automatically.

## 2. Indexes, keys and partitions of the SSRK finance tables
- **No partitioning** on any of the 17 tables checked (no partition keys, no partitions). Every table has a primary key.
- **`FINPOST` (8.07 M rows)**: primary key `POSTCODE` (numeric surrogate); single-column indexes on `ENTTYPE`, `GLCODE`, `SLCODE`, `YCODE`, `ADMSITE_CODE_OWNER`, `REF_ADMSITE_CODE`, `RELEASE_STATUS`, `ECODE`, `RELEASE_ECODE`, `DOCNO`, `SCHEME_DOCNO`; composite `(ENTCODE, ENTTYPE)`. **There is no index on `ENTDT` or `DOCDT`**, so a bare date predicate is a full scan.
- **`FINCOSTTAG` (7.95 M)**: primary key `CODE`; unique composite `(ENTCODE, GLCODE, SLCODE, ADMSITE_CODE, POSTCODE, REF_ADMSITE_CODE)`; single-column indexes on `COSTCODE`, `ENTTYPE`, `GLCODE`, `SLCODE`, `YCODE`, `POSTCODE`, `ADMSITE_CODE`. No date column at all (the date is on the posting).
- **`FINVCHMAIN` / `FINVCHDET` / `FINJRNMAIN` / `FINJRNDET`**: primary keys on `VCHCODE` / `JRNCODE` / `CODE`; unique `(VCHCODE, GLCODE, SLCODE)` on voucher lines; no date index (`VCHDT`).
- **`FINGLBUD`**: unique `(GLCODE, COSTCODE, SLCODE, MCODE, ADMOU_CODE)` plus single-column indexes.
- **`FINCHQDET`**: unique `(BOOKCODE, CHQNO)` and `(GLCODE, CHQNO)`.

## How to read these tables cheaply (proposal, not yet run)
1. Bound by **financial year first**: `YCODE` is indexed on `FINPOST`, `FINCOSTTAG`, `FINVCHMAIN`, `FINVCHDET` and `FINJRNDET`. Add the exact `ENTDT` / `VCHDT` window on top, and cap the rows.
2. Find the **`POSTCODE` range** for a month once (a bounded probe by `YCODE`), then read `FINPOST` and `FINCOSTTAG` by `POSTCODE BETWEEN` (primary key and indexed): this avoids repeated full scans of 8 M rows.
3. Join `FINCOSTTAG` to `FINPOST` by `POSTCODE` (both indexed), never by `ENTNO`/`ENTDT` text.
4. Run one query at a time, off business peaks if possible, and keep every statement under the broker timeout.

---

# Part 3: SSRK range probe (2026-10-07, 16:24)

Runs `run_20261007_011` (`ssrk_range_probe_01`: financial-year master + `MIN/MAX(POSTCODE)` from the primary-key index) and `run_20261007_012` (`ssrk_range_probe_02`: 40 single-row primary-key lookups). No posting was scanned.

- `ADMYEAR` (83 rows): `YCODE` 50 = FY 25-26 (2025-04-01 to 2026-03-31), **`YCODE` 51 = FY 26-27** (2026-04-01 to 2027-03-31).
- `FINPOST.POSTCODE` runs 1,112,747,022 to 1,133,985,088 and is **monotonic with the entry date** at all 40 sample points (2016-01-20 up to 2026-10-07). It is therefore a usable range key.
- Month windows (approximate, from the sample): FY 26-27 starts between `POSTCODE` 1,131,262,259 (2026-03-30) and 1,131,807,157 (2026-05-08); about 2.5 M of the 8.07 M postings belong to FY 26-27. Exact month boundaries come from a second, narrower lookup, not from interpolation.
- The `POSTCODE` ranges are only an access path. The reads still carry `YCODE` and the exact `ENTDT` window as the real predicates, and every figure still has to reconcile to the verified MISRETAIL runs before anything is used.

# (Withdrawn 2026-10-07) Grant request for the DBA
The user confirmed the MISRETAIL `T$` registers are temporary tables and are not needed; the source of truth is the live SSRK tables. No grant is required. The text below is kept only as a record.
The pipelines read these MISRETAIL objects, which `SSRK_RO` cannot currently see: `MAS$FINGL`, `T$FINREGSITE_844`, `T$FINREGSITE_877`, `T$FINREG_901`, `T$FINREG_886`, `T$FINOTSD_533`, `T_FINANCE_P_AND_L_STORE_MAP`, `T_FINANCE_P_AND_L_BUDGET`, `T_FINANCE_P_AND_L_BASE_*`, `T_STORE_OPENING_DATE` (and the cash / entry cubes if they are other `T$` objects). Grant `SELECT` on each to role `SSRK_READ_ONLY`; nothing else.

---

# Part 4: one-day SSRK sample, 2026-10-06 (16:50)

Runs `run_20261007_013` (`ssrk_range_probe_03`, finer key-to-date grid) and `run_20261007_014` (`ssrk_day_sample_01`). Every statement was guard-checked, capped and run one at a time; the data stays in the git-ignored inbox, only aggregates are written here.

- **Access path worked**: `FINPOST.POSTCODE >= 1133929721` with the `ENTDT` window `[2026-10-06, 2026-10-07)`. The key is not strictly monotonic (back-dated entries exist: e.g. a posting dated 2026-10-02 sits at a later key than some dated 2026-10-06), so the date window, not the key, is the real predicate. The day's postings occupy keys 1,133,947,121 to 1,133,985,353, inside the window; each of the four queries took about 6 s.
- **FINPOST for the day**: 8,101 postings, 3,062 distinct entries, 57 ledgers, 35 owner sites and 223 reference sites, all `YCODE` 51, all dated 2026-10-06. **Debit = credit = ₹325,025,033.76 (difference 0.00).**
- **Release status**: `P` (posted) 4,658 postings, `U` (unposted) 3,443. This is the Posted / Unposted split already used in the P&L.
- **Entry types** (31 type / status combinations): mostly `TIA` (3,264), `CSM` (1,468, unposted), `PJN` (1,612, unposted), `CTM`, `PIM`, `CTC`, `JDT`, `PIC`, `PRM` and others.
- **FINCOSTTAG**: 7,683 rows covering 7,486 of the 8,101 postings (the rest carry no cost-centre split); the cost-tag debit and credit totals (₹27.77 Cr, ₹26.81 Cr) differ because only some postings are tagged.
- **Not reconciled yet**: the MISRETAIL registers are not visible to `SSRK_RO` (grant pending), so this day could not be compared with the register. The comparison is the gate before any SSRK figure feeds a page: re-sample a day that exists in a verified run (for example 2026-10-05) after the grant, and compare posting-by-posting and by ledger.
- Tooling note: the broker marks a one-row aggregate with `FETCH FIRST 1 ROWS ONLY` as "capped" (`d2_totals`). The row is complete (8,101 postings, matching `d1`); the warning is a false positive of the cap check on cap = 1.

---

# Part 5: live-table review (2026-10-07, 17:00)

Direction from the user: the MISRETAIL `T`/`T$` objects are temporary tables; review the live SSRK tables. The user's schema-browser screenshots (filter `*fin*`) confirm the finance family: `FINPOST`, `FINCOSTTAG`, `FINVCHMAIN/DET/DN`, `FINJRN*`, `FINSL*`, `FINGL*`, `FINGLBUD`, `FINTAG`, `FINTAG_SITEWISE(_ADJ)`, `FINENTTYPE`, `FINENTGRP`, `FINCOST`, `FINDOC_AGE_SLAB`, `FINTDS*`, `FINTAX*`, plus `GLOBAL_FIN_BALANCESHEET`, `GLOBAL_FIN_CASH_FLOW`, `GLOBAL_FIN_DOC_ADJ/POST` (global/working tables, not sources) and many `*_BKP`, `*_24_02`, `*_CHECK`, `*_DELETED`, `AUD2_*` copies (ignored). New masters worth reading: `FINENTTYPE` / `FINENTGRP` (entry-type codes such as TIA, CSM, PJN) and `FINCOST` (cost-centre master).

Run `run_20261007_015` (`ssrk_logic_probe_01`, metadata) and `run_20261007_016` (`ssrk_masters_01`, small masters plus sales headers):
- **No stored dependency leads from SSRK to the MISRETAIL `T_*` tables** (no program or view references `T_CUSTOM_COGS`), so how COGS is built there cannot be read from the dictionary; COGS has to be defined from the SSRK sources.
- **`ADMSITE` (457 sites)**: 300 POS sites. `STORE_SIZE` is filled for only 106 sites, `STORE_STARTDT` for 180, `STORE_CLOSEDT` for 5. This is **weaker than `T_STORE_OPENING_DATE`, which gave area for 234 sites**, so `ADMSITE` does not close the area gap by itself; the two should be compared before choosing a source.
- **`FINGL` (577 rows) and `FINGRP` (115 rows)** read cleanly (ledger name, group, type; group tree with parent and sequence): enough to rebuild the Major Group, Group, Ledger hierarchy from the live masters.
- **`SALCSMAIN` (consignment-sale headers) is the daily consolidated sale document**: one document per site per day (202 sites on 2026-10-06, all `RELEASE_STATUS` U, net ₹3.00 Cr), monthly net ₹70 to 155 Cr. `NETAMT` is the sales value; `EXTAXAMT` is a small separate figure. **`SITE_COSTAMT` is 0 on every header, so COGS is not at header level**: it sits on the lines (`SALCSDET`: `SITE_COSTAMT`, `SITE_COSTRATE`, `COSTRATE`, 186 M rows). Whether header net equals GL "Sales - POS" (with or without GST) is not established yet.
- Reading `SALCSDET` is the expensive step (about 130 k lines per day). If pursued it must go by `CSCODE` range for one day at a time, never a month scan.

## Correction (2026-10-07, 17:00): COGS stays on `T_CUSTOM_COGS`
The user clarified that `MISRETAIL.T_CUSTOM_COGS` is a custom table built specifically for COGS calculation: it is the COGS source and is not rebuilt from `SALCSDET`. It is visible to `SSRK_RO` (104 M rows) and the P&L already uses it. The `SALCSMAIN` / `SALCSDET` findings above are therefore background only. What changes with the live-table direction is the **books side** (ledger postings): `FINPOST` + `FINGL` / `FINGRP` + `ADMSITE`, in place of the temporary `T$FINREGSITE_*` registers, with a month-by-site-by-ledger reconciliation against the verified P&L run before use.

---

# Part 6: live books (SSRK `FINPOST` + `FINCOSTTAG`) reconciled to the verified P&L run (2026-10-07, 17:10)

Runs `run_20261007_017` / `_018` (April 2026, two site-dimension tests) and `run_20261007_019` (May to October 2026). Package code: `tools/extraction_broker/ssrk_books.py`. Compared with `run_20261007_005` (`g_YYYY_MM`, the books taken from the `T$FINREGSITE` registers earlier on 07 Oct).

**Query shape (one per month, about 6 to 10 s each):** `FINPOST p JOIN FINGL g (TYPE in E, I) JOIN FINCOSTTAG c ON c.POSTCODE = p.POSTCODE`, `p.YCODE = 51`, `p.POSTCODE >=` a lower bound about two weeks before the month, exact `ENTDT` month; grouped by `c.ADMSITE_CODE`, ledger, entry type and release status. The money is taken from the cost-tag split (`c.DAMOUNT` / `c.CAMOUNT`).

**Findings**
- **The register's site is the cost-tag site (`FINCOSTTAG.ADMSITE_CODE`)**, not `FINPOST.ADMSITE_CODE_OWNER` or `REF_ADMSITE_CODE` (those matched only 594 and 3,582 of 9,697 April keys). Using the cost tag, April matches **9,695 of 9,697 site / ledger / entry-type / status keys exactly** (debit, credit and line count), with identical totals: debit ₹1,696,303,337.77, credit ₹2,494,487,657.37, 55,374 lines. The two other keys differ only in release status (`Unposted` in the register, `Posted` live; ₹1.10 in total): the entries were released after the register was taken.
- **Postings with no cost tag: none** for P&L ledgers in April (0 rows).
- **May to August** (live against the morning register): 11,440 of 11,441, 10,651 of 10,651, 10,936 of 10,937 and 11,942 of 11,957 keys exact; month-total differences are at most ₹0.50, except July (one line, debit ₹68,333 lower live). These look like entries edited or removed after the register snapshot; that is an inference, not proven.
- **September and October** differ more (September +₹1.72 Cr debit, +843 lines; October +₹9.85 Cr debit, +703 lines): consistent with late September postings and the current month's postings made since the register snapshot (October is still being posted), again an inference.
- **Entry types** decode through `FINENTTYPE` (62 rows) and `FINENTGRP` (6 rows), for example CSM / CSD = Retail Sale, CTC / CTD / CTM = Consignment / Stock Transfer, JDJ = Journal; `FINCOST` is empty (0 rows).

**Conclusion:** the live SSRK finance tables reproduce the verified books to the rupee wherever no posting has changed since the snapshot, so the books side of the P&L can be sourced from them. Not done yet: FY 25-26 months (`YCODE` 50), staging and loading as a new run, and a same-moment comparison (the registers are no longer to be used, so drift can only be explained by re-running twice).

---

# Part 7: the MIS cubes seen from SSRK (2026-10-07, 17:20)

Runs `run_20261007_020` (`ssrk_cube_probe_01`, metadata only; plus the earlier `s1_tables` / `s4_columns`).

- SSRK holds about 100 cube **template** tables `MIS_CUBE$*` (finance: `FINREGSITE`, `FINREG`, `FINREGSL`, `FINOTSD`, `BANKREG`, `BUDGETANALYSIS`, `FINTDS`; sales: `POSBILLSUMM`, `POSBILLDET`, `RETAILSALE`, `COMPANYSALE`, `POSDSR`; purchase, stock, production and others). **They are empty (0 rows)**: each carries the run columns `CUBE_CODE`, `CUBENAME`, `CREATOR`, `REPORT_DATE`, `START_DATE`, `END_DATE` and the report fields. A cube run for a chosen period is produced by the application (it is what created the `T$FINREGSITE_<n>` copies in MISRETAIL, the temporary tables); the code that generates it is not visible to `SSRK_RO` (only 9 stored programs are visible, none related to cubes) and a read-only login must not run it.
- **So a cube for a period is reproduced from the live base tables, not requested.** This is already proven for one: `MIS_CUBE$FINREGSITE` equals `FINPOST` joined to `FINCOSTTAG` (site = cost-tag site) and `FINENTTYPE` (short / long type), release status P / U, debit / credit from the cost-tag split (Part 6: April exact, the other months within snapshot drift). The template columns are the specification to follow.
- Definitions of the cubes already used by the pipelines, to be rebuilt the same way and each reconciled to its verified run before use:

| Cube (template) | Used by | Live source to rebuild from |
|---|---|---|
| `FINREGSITE` | P&L books, Entry | `FINPOST` + `FINCOSTTAG` + `FINGL` + `FINENTTYPE` (done for P&L ledgers) |
| `FINOTSD` (outstanding by document: due date, amount, adjusted, pending, DR/CR, sub-ledger) | Creditors | `FINPOST` (`DUEDT`, `DAMOUNT` / `CAMOUNT`, `ADJAMT`) + `FINSL` + `FINTAG` |
| `BANKREG` (bank voucher: GL, SL, cheque, balance) | Cash / bank | `FINVCHMAIN` / `FINVCHDET` / `FINPOST` for bank ledgers |
| `POSBILLSUMM` (bill header: qty, MRP, discounts, net, tax) | Sales / till | `PSITE_POSBILL` (note: the template carries customer name, mobile and e-mail columns, which are never read) |
| `BUDGETANALYSIS` (budget vs actual by ledger, site, month) | Budget (deferred) | `FINGLBUD` |

---

# Part 8: the outstanding cube (`FINOTSD`) rebuilt from live `FINPOST` (2026-10-07, 17:40)

Runs `run_20261007_021` (`ssrk_otsd_probe_01`: 300 sampled documents) and `run_20261007_022` (`ssrk_otsd_open_01`: every open item of the four creditor ledgers). Code: `tools/extraction_broker/ssrk_otsd.py`. Compared with the verified Creditors run `run_20261005_012` (cube snapshot of 05 Oct, 12,275 open items).

**Mapping proved on the sample (300 documents, 332 cube items; all 300 found):**
- cube `DOCUMENT_CODE` = `FINPOST.ENTCODE`; `SUB_LEDGER_CODE` = `SLCODE`; `LEDGER_CODE` = `GLCODE`; `DOCUMENT_NO` / dates = `ENTNO` or `DOCNO` / `ENTDT`, `DOCDT`, `DUEDT`.
- cube `AMOUNT` = `DAMOUNT - CAMOUNT` (credit items negative); cube `ADJUSTED` = `FINPOST.ADJAMT` (empty in the cube when 0); cube `PENDING` = `AMOUNT - ADJAMT` for a debit item and `AMOUNT + ADJAMT` for a credit item; an item is open when `ABS(DAMOUNT - CAMOUNT) <> ADJAMT`.
- Result: 287 of 332 items agree exactly (amount, adjusted, pending). **All 45 others are items that live are MORE settled than on 05 Oct** (live adjusted is higher, pending nearer zero): none is a logic difference.

**Full set (live today against the 05 Oct snapshot):**
- Live open keys 12,220 against 12,275 in the cube; 11,628 in both (10,690 identical), 647 only in the cube (settled since), 592 only live (275 dated on or before 05 Oct but posted after the snapshot, 317 entered after it), 938 in both with pending changed.
- Net pending: cube **-₹295.10 Cr**, live **-₹270.13 Cr** (difference +₹24.97 Cr). By ledger: Apparels (`1000000026`) -₹212.82 Cr live against -₹213.02 Cr; GM (`1000000092`) -₹43.05 Cr against -₹47.49 Cr; Non-Trading (`1000000025`) -₹2.63 Cr against -₹2.39 Cr; **Expenses (`1000000024`) -₹11.64 Cr against -₹32.20 Cr**, where +₹18.83 Cr comes from newly entered debit items (entry types PIM, JMD, PSM, PRM, VDP, PDM) and ₹0.67 Cr from items settled since.
- The two days between the snapshot and now (06 and 07 Oct) are enough to explain item-level differences, but **not proven to explain the size of the Expenses-ledger movement**. This is why the position cannot be called reconciled.

**What would prove it:** reconstruct the position as of 05 Oct from live data instead of comparing today's with it: take postings created up to the snapshot (`ECODE` / `TIME` on the posting) and subtract only the adjustments recorded up to that time (`FINTAG`: `POSTCODE1`, `POSTCODE2`, `AMOUNT`, `TIME`). First check whether `FINPOST.ADJAMT` equals the sum of `FINTAG` amounts for the posting. If the reconstructed 05 Oct position equals the cube's 12,275 items and ₹-295.10 Cr, the rebuild is exact.

---

# Part 9: point-in-time reconstruction of the creditors position (2026-10-07, 20:50)

Runs `run_20261007_023` (`ssrk_fintag_probe_01`), `_024` (rule A), `_025` (rule B), `_026` (rule C, four times), `_027` (rule C, four later times). Code: `tools/extraction_broker/ssrk_otsd.py`. Target: the 05 Oct cube snapshot in the verified Creditors run `run_20261005_012` (12,275 open items, net pending -₹295.0955 Cr).

**`FINTAG` is the adjustment ledger.** `FINPOST.ADJAMT` equals the sum of `FINTAG.AMOUNT` over both sides (`POSTCODE1`, `POSTCODE2`) for 529 of 532 sampled postings; each `FINTAG` row carries the time of the adjustment (`TIME`). The three that differ show `ADJAMT` changing without a `FINTAG` row (round-off style adjustments).

**Rules tried** (position as of a moment T = postings created before T, minus adjustments made before T):
- **A** (FINTAG only): 13,850 items, 1,581 too many. Rejected: about 900 old items settled by adjustments that `FINTAG` does not show.
- **B** (`ADJAMT` as now when the posting's last-access time is before T): 616 items missing. Rejected: `LAST_ACCESS_TIME` is not updated by adjustments, so it cannot date them.
- **C (accepted)**: use the `FINTAG` adjustments made before T when the `FINTAG` total agrees with `FINPOST.ADJAMT`; otherwise (legacy or round-off adjustments) use `ADJAMT`.

**Result for rule C, T between 04 Oct 18:00 and 05 Oct 06:00 (identical in that whole window):**
- 12,329 open items against 12,275 in the cube; **12,249 in both, 12,220 of them exactly equal** (amount and pending) = **99.8% of the cube's items**; 26 only in the cube; 80 only in the reconstruction.
- **Net pending -₹295.5292 Cr against -₹295.0955 Cr: a difference of ₹0.43 Cr (0.15%)**, compared with ₹24.97 Cr when today's live position is compared with the snapshot (Part 8).
- Earlier or later T fits worse (T = 04 Oct 00:00: 12,178 exact and ₹1.99 Cr off; T = 05 Oct 12:00: 12,210 exact and ₹4.66 Cr off; T from 05 Oct 18:00: about 240 cube items missing). So the cube snapshot was taken in the early hours of 05 Oct, and the Part 8 gap was genuinely two days of activity (items settled and entered on 05 to 07 Oct), not a difference in logic.
- Not yet explained: the 106 items (about 0.9%) that differ, 80 open in the reconstruction but not in the cube and 26 the other way. The likely cause is adjustments whose `FINTAG` time is the voucher time rather than the moment of adjustment; that is an inference, to be tested on those items.

**Conclusion:** the creditors outstanding position can be sourced from the live SSRK tables with an explicit as-of moment, reproducing the verified run to 99.8% of items and 0.15% of value, and the remaining differences are small and identifiable. Not switched: no page reads this yet.

---

# Part 10: the 106 residual items classified, and the live Creditors extract built (2026-10-07, 21:10)

Runs `run_20261007_028` (residual detail), `_029` (rule D), `_030` (`V_FIN` sample), `_031`/`_032` (vendor and class masters), `_033` (first live extract, not loaded), `_034` (live extract, `creditors_live_01`).

## Classification of the reconstruction residual (rule C at 05 Oct 00:00: 80 only-live, 26 only-cube, 29 differing)
- **65 of the 80 only-live items**: a `FINTAG` row that settles the item exists but is timed on 05, 06 or 07 Oct (for example 2026-10-07 10:12), and the amount of those late rows equals exactly the amount the reconstruction was missing, yet the cube of 05 Oct already counted the item settled. So `FINTAG.TIME` is not always the time of the adjustment: it is refreshed when the adjusting voucher is saved again. This is an inference from the match of amounts; it means point-in-time reconstruction from `FINTAG` can never be exact for vouchers edited later. 15 further only-live items show no late `FINTAG` row: `ADJAMT` was lowered after 05 Oct (an adjustment was undone), which cannot be rebuilt either.
- **26 only-cube items**: in 16 the `FINTAG` total before the snapshot equals the cube's ADJUSTED exactly; `FINPOST.ADJAMT` was topped up afterwards by a small round-off adjustment (for example 102,386 against 102,384), so rule C wrongly fell back to `ADJAMT`. Rule D (accept `FINTAG` when `ADJAMT` exceeds it by at most a round-off tolerance) cuts only-cube from 26 to 19 and raises exact items from 12,220 to 12,227; not adopted for the live extract because the live extract needs no history.
- **29 differing items**: the same two causes (adjustments or edits dated after the snapshot).
- **Conclusion:** the 0.9% residual is explained by edits and un-adjustments after the snapshot; none points to a wrong rule.

## Consequence for the build: no history logic
The live tables hold only the current position, so the live extract reads it as it is now (`FINPOST.ADJAMT`, exact by construction) and each daily run is an immutable snapshot; history comes from keeping the runs, not from reconstructing them.

## `creditors_live_01` (code: `tools/extraction_broker/creditors_live.py`)
- Same eight datasets, columns and controls as the verified pilot: the pilot's own SQL is pointed at an inline view that rebuilds the cube's rows from SSRK (`FINPOST`, `FINGL`, `FINSL`, `ADMCLS`, `V_FIN`, `ADMSITE`). `--as-of` is required and must be today (the live source cannot give a past day); the broker records the extraction moment.
- Field mapping checked on the 11,604 items present in both the 05 Oct cube run and the live run: ledger, vendor, class, credit days, document number, due-date basis, creating site and Dr/Cr agree on **all 11,604**; document type and initial agree on all after a seven-pair label dictionary read off those items (V_FIN says "Voucher (AR/AP)", the cube "AR/AP Voucher", and so on; every pair maps one-to-one); the rest differ only for the few hundred items whose amounts or dates changed after 05 Oct.
- Staging (`creditors_stage.py`, now accepting `creditors_live_01`) passed all 408 controls with no failure: source controls before and after the extract identical, identity unique, Dr/Cr and sign rules, and the independent Oracle-side age and due classification equal to the offline one. The loader (`loader.py`) now accepts the package and records which package a run came from.
- Live position at extraction: 12,169 open items, net pending -₹271.79 Cr.

---

# Part 11: Cash from live tables, discovery (2026-10-07, 22:30)

Run `run_20261007_035` (`cash_live_probe_01`, code `tools/extraction_broker/cash_live_probe.py`). The Cash run `run_20261005_013` has two parts, assessed separately.

**Bank and cash ledger book figures (34 ledgers): rebuildable.**
- The 34 ledgers of the verified run are all in `SSRK.FINGL`, and the bank / cash split is explicit there: `TYPE = A` with `SRCTYPE = B` (Bank Account group, 28 ledgers) or `SRCTYPE = C` (Cash-in-hand group, 6 ledgers), with `EXT` for extinct. The cube's "nature" is this classification.
- Opening balances are in `FINGLOP` (`GLCODE`, `YCODE`, `OPDAMT`, `OPCAMT`): 19 rows for these ledgers across FY 25-26 (`YCODE` 50) and FY 26-27 (51), for example CASH IN HAND(STORES) 96,995 Dr opening in FY 26-27 against 133,624 in FY 25-26.
- Posted, unposted and future-dated movement comes from `FINPOST` (GL register) and from `FINPOST` + `FINCOSTTAG` (site register), as for the P&L books.
- Not yet built or reconciled.

**Store till cash (209 stores, 1.49 Cr on 4 Oct): NOT rebuildable from the finance postings.**
- The verified figure comes from the MISRETAIL view `V_FINANCE_CASH_CUMLATIVE_BLNC` (store x day debit, credit, cumulative balance). Its definition is not visible now (MISRETAIL views are not readable by `SSRK_RO`) and was not captured by any earlier discovery run.
- The finance postings do not contain it: the till ledger CASH IN HAND(STORES) (`1114925459`) has only **17 posting rows** in FY 26-27 to 04 Oct (all at one owner site) and **no cost-tag rows**, against 209 stores with year-to-date till debits and credits in the view.
- So the till figure is derived outside the postings, most likely from the point-of-sale settlement tables (`PSITE_POSSTLM` 300 k, `PSITE_POSSTLMDETAIL` 2.5 M, `PSITE_POSSTLMOTH`, `PSITE_POSBILLMOP` 79 M with cash tender per bill, `PSITE_DAY_STLM_ACC/OTH`). That is an inference; the cash-drawer rule (what counts as cash taken, what as banked or settled, and how the running balance is built) has to come from Finance or from the view's author before any live rebuild.

---

# Part 12: the 34 bank and cash ledgers rebuilt from live tables (2026-10-07, 22:50)

Runs `run_20261007_036` (`cash_bank_live_01`, code `tools/extraction_broker/cash_bank_live.py`), `_037` / `_038` (two small probes on one ledger). Checker: `tools/extraction_broker/cash_bank_live_check.py`. Reference: the verified Cash run `run_20261005_013` (05 Oct).

**Build.** The Cash pilot's own position SQL for the three registers is pointed at inline views over SSRK: ledgers from `FINGL` (type A, srctype B bank or C cash), the opening row from `FINGLOP`, movement from `FINPOST` with entry-type names from `FINENTTYPE`, release status P / U, site = the owner site. As-of must be today. Store till cash is not included (rule unknown, Part 11).

**Result (live at 07 Oct, report date 2026-10-07):**
- 34 ledgers in each register, 10 with entries; posted Dr 9,014,872,007.92, Cr 9,177,037,123.13; unposted Dr 147,285,265.43, Cr 254,257,599.97. The bank control is identical before and after the extract.
- **Against the verified 05 Oct run: the opening is identical for all 34 ledgers, and every figure (opening, posted, unposted, future, contra) is identical for 29 of 34.** The five that differ are the ledgers that moved between 05 and 07 Oct (CASH IN HAND(STORES) unposted credit 24,349 to 24,860; AXIS BANK-8218, AXIS BANK-7647, OMNI CARD POOL and AXIS CC 1797 posted and unposted figures, as postings were made and released), consistent with two days of activity.
- The site register and the GL register agree on every figure: all 34 ledgers sit on a single site (the original cube showed the same), so this tie is weak by construction.
- The ledger figures add up to the source control to the paisa.

**One hard tie fails, and it is a real finding, not a pipeline error:** the FY 25-26 closing of **AXIS BANK-8218 (CKSPL)** (`1114927514`) is ₹26,117,493.60 on the live postings, but its FY 26-27 opening in `FINGLOP` is ₹23,573,789.60: a difference of **₹2,543,704.00**. The cause: five FY 25-26 postings (dated on or before 31 Mar 2026, ₹2,543,704.00 Dr in total) were **created in July 2026**, after the year-end carry-forward of openings, so the opening was not updated. The verified 05 Oct run did not see them because its prior-year register (`T$FINREG_886`) predates July; its closing (₹23,573,789.90 before unposted, ₹23,573,789.60 with unposted) matched the opening. Finance should confirm whether the FY 26-27 opening of this ledger needs re-carrying, or whether those five entries belong in FY 26-27.

**Not done:** the live bank/cash figures are not loaded into the Cash mart (the Cash schema, loader and API require the till datasets; making the till optional is a separate change that needs a decision), and no page reads them.

---

# Part 13: store till cash and the POS day-end cash summary (2026-10-08, 10:50)

Runs `run_20261008_002` (`till_probe_01`), `_003` (`till_probe_02`), `_004` (`till_probe_03`, one store). Every table SSRK-qualified; settlement aggregates only. Reference: the verified Cash run `run_20261005_013` (store till rows of 04 Oct).

**What the store till is.** The physical cash held in each store's till: cash taken from customers, less what the store then banks or pays out. Verified Cash run, 209 stores on 04 Oct: sum of the cumulative store balances **₹3.25 Cr (32,493,887.21)** = FYTD debit ₹373.09 Cr less FYTD credit ₹369.84 Cr. (An earlier discovery note quoted ₹1.49 Cr for the same date; the verified run's own store rows add up to ₹3.25 Cr, which is the figure to use.)

**Where it lives in SSRK.** `PSITE_POSSTLMDETAIL` joined to `PSITE_POSSTLM` (one settlement per store per day, `STLMFOR` = the day, `STATUS` C closed / U unsettled / O open) holds a **`CashSummary`** block for payment mode 112 (Cash), per store per day:
- sub-type `Opening`: the day's opening cash (37,191 store-days this year, sum of daily openings ₹564.27 Cr, which is about ₹1.5 lakh per store-day, the same scale as the till balances);
- sub-type `POS Bill`: cash from bills (₹368.26 Cr this year to 04 Oct, 35,044 lines);
- sub-type `PTC Head`: cash paid out of the till (-₹368.97 Cr, 115,310 lines): **Cash/CMS Deposit (banking) -₹365.05 Cr** and petty-cash heads such as staff welfare, repairs, loading, printing, conveyance.
So till movement = POS Bill less PTC Head, and a store's balance is its running cash.

**Test against the verified till, store by store** (209 stores in common; the 213 live stores include four not in the verified run: sites 299, 437, 457, 469; store names, `ADMSITE.SHRTNAME`, equal for all 209):
- POS Bill is **close to, but not equal to**, the verified FYTD debit (for example site 43: ₹24,284,571 verified against ₹24,057,195 settlement, +0.9%; in total ₹373.09 Cr against ₹368.26 Cr, +1.3%); -PTC Head is close to the verified FYTD credit (site 43: ₹24,110,451 against ₹24,078,277; total ₹369.84 Cr against ₹368.97 Cr). Exact equality holds for only 1 store on FYTD and 60 on month to date.
- So the settlement cash summary is the right family, but the verified view adds something further on the debit side (and a little on the credit side) that this extract does not reproduce. The bill-level cash lines (`PSITE_POSBILLMOP`, mode type CSH) do not explain it: for site 43 their `BASEAMT` nets to -₹21,082 (change given back) and `BASETENDER` holds sentinel values, so the cash tender cannot simply be summed. Reading that 79 M-row table by date needs the `(ADMSITE_CODE, billdate)` index and one store takes about 30 s, so it is not a candidate for a network-wide scan.
- **No rule has been guessed or added to close the gap.**

**What is needed to finish it:** the definition of the extra debit and credit in the verified view `V_FINANCE_CASH_CUMLATIVE_BLNC` (for example other cash receipts, refunds or timing of unsettled days), from its author or from Finance. Until then the live till stays unavailable and the verified till (05 Oct run) is the only till figure.
