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
