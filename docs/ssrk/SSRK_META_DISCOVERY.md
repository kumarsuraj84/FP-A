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
