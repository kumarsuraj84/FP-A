# Gold source gaps - Entry / Voucher API

Module: `backend/app/gold/entry.py` (FPA_SOURCE=gold). The Entry API (`/api/v1/entries/...`) is served from `gold_fpa.voucher_lines`, `creditors_open_items`,
`cash_drawer_store`, `dim_site`, `control_totals`. Contract, routers and response shapes are unchanged. Run id is synthetic: `ENTRY-<yyyymmdd>`, live, verified.

## How each relation is built

| View | Source / rule |
|---|---|
| v_serving_run | as-of date from cash_drawer_store; cash run `CASH-yyyymmdd`, creditors run `GOLD-yyyymmdd`; coverage_from = min(entdt) |
| v_entry_header | one row per `entcode`; entry_ref = entcode; type = distinct `enttype` joined with `/` (PSC/PSD); status Posted / Unposted / Mixed |
| v_entry_line | one row per cost-tag line (`cost_tag_key`), line_no = row_number by cost_tag_key; sub_ledger_ref = V + md5 salt hash (same as creditors vendor_ref) |
| v_entry_line_text / v_entry_identity | narration, docno (reference_no), doc_date, raw slcode; entry_no = entno, else scheme_docno, docno, entcode |
| v_till_day | Cash Drawer 1000000008 by tag_site_code per day of current FY + synthetic opening day (FY start - 1) from cash_drawer_store.opening_balance + as-of row; reconciles to Store Till Cash exactly (238 stores) |
| v_creditor_bill_link | creditors_open_items.postcode -> voucher with entcode = document_code. Found: STRONG. Not found: NOT_LINKED (NO_MATCH, or REGISTER_COVERAGE_UNAVAILABLE if document_date < 2025-04-01) |
| v_control | control_totals(voucher_lines, month x ledger_type) vs recompute (rows, debit, credit) + till cumulative + bill-link rows |
| v_bank_entry | empty (no bank source) |

## Gaps and decisions needed

### From 01-Data Extraction
1. **Creditor / party-control lines are missing from voucher_lines.** No line with glcode 1000000024/25/26/92 exists, and Cash/Bank ledgers are absent too.
   Consequence: ~9% of recent vouchers are not balanced (e.g. 7,230 of 76,203 vouchers since Sep 2026), so `balanced=false` in the entry drill is a data gap, not a posting error.
   Needed: extract the full voucher (all legs, incl. sundry creditor, bank, cash) or a flag that marks the table as partial.
2. **Bank ledger master and bank lines** are not in gold_fpa. Bank ledgers and bank entries are empty (bank card and bank drill show nothing). Needed: bank ledger dimension + lines (ledger nature Bank/Cash).
3. **Entry history starts 2025-04-01** (coverage_from). Bills dated earlier return NOT_LINKED / REGISTER_COVERAGE_UNAVAILABLE (830 bills).
4. **Prepared / modified / released by and on, cheque no/date, reference date semantics, counter-ledgers** are not extracted: returned as NULL. `reference_no` = docno (else scheme_docno).
5. **cube_name** has no source: NULL.
6. **entno is NULL for many types** (journals, purchase vouchers). entry_no falls back to scheme_docno, docno, then entcode.
7. Till: `cash_drawer_store.opening_balance` is one number at FY start, so previous-FY Cash Drawer lines (available in voucher_lines from 2025-04-01) are not shown as days.
   Decision: opening is shown as one synthetic day (31 Mar). If Finance wants prior-FY days, extraction must give the true opening at the start of voucher_lines coverage (2025-04-01).

### Decisions for Finance
1. **Link status is never EXACT.** Without the creditor leg the bill amount cannot be corroborated against the entry (`entry_net_amount`, `amount_agrees` = NULL). All found links are STRONG (8,306 current FY).
   The earlier mart used EXACT only when the entry nets to the bill amount. Confirm STRONG is acceptable or supply the creditor leg.
2. **Entry identity = entcode.** Paired document types (PIC+PIM, PSC+PSD, CTC+CTM ...) share an entcode, so one voucher shows both codes. Confirm entcode is the voucher key (it is unique per creating site in the data).
3. **entry_ref is the entcode, not an opaque hash.** The masked endpoint therefore exposes the source entry code in the URL and body (an opaque hash would force a scan of 2.5M lines per drill). Confirm acceptable, or add an indexed hash column in extraction.
4. **Masking.** All gold sessions are the single read-only role fpa_ro; the entry/finance split is enforced only by the bearer-token gate on `/finance/entry/...` (narration and raw sub-ledger codes are returned only there).
5. **Till site_code is an integer** (as in cash.v_store_till), where the old mart returned text; the till list JSON shows `site_code` as a number.

### Performance (measured, 2.5M-row table)
- entry drill, creditor link, till days: under 1s. `/runs/{id}` (recomputes 229 control rows over all lines): about 5s. `/till/stores`: about 3-4s warm, up to 10s on a cold cache (the repository references the till view four times, so it is materialised per request).
  A materialised daily till table or an indexed voucher hash in extraction would remove this.
