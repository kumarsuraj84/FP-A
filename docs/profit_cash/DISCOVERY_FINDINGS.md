# Profitability and Cash: source discovery findings (run_20261004_007)

Package `profit_cash_probe_01`, MISRETAIL only, through the Inventory Automation SELECT-only broker. 16 datasets, all guard-checked, 5 small masters and 11 capped aggregates. No row-level data. SSRK untouched. Nothing is decided here: this is evidence for the contracts.

## Decision table

| Domain | Candidate source | Coverage | Freshness | Grain | Major gap | Recommendation |
|---|---|---|---|---|---|---|
| Store sales | `V_CFO_DASHBOARD_SL_V` (SL_V, TAX_V, SL_Q, BILL_COUNT) | Apr 2025 to Oct 2026, every month | Current (4 days of Oct 2026) | ADMSITE_CODE x bill date | `ADMSITE_CODE` is unique per row within a month (distinct count = row count), so it does not behave like a store code. Whether SL_V is net of tax and returns is not proven. | **Needs a bounded probe** (site code vs store map, net/gross) before a contract. |
| COGS | `V_FINANCE_P_AND_L_COGS_DATA` (store, bill month, cost) and COGS_V in the dashboard view | Apr 2025 to Oct 2026 | Current | Store x month (137 to 209 stores a month) | The two COGS figures differ by up to 1.3 Cr a month (typically below 0.5 Cr). Store names, not codes. 209 stores vs 143 in the store map. | Usable. Pick one as the contract source and reconcile the other as a control. |
| GL register / Opex | `T$FINREGSITE_844` (site-wise GL register, FY26-27) | 1,093,369 rows, 312 sites, 387 GL codes, entry dates Apr to Dec 2026 | Report date 2026-10-04 | Site x GL x entry | Contains future-dated entries (to Dec 2026) and 27% unposted rows (release status). Needs Posted-only and date rules. 107 of 141 Income/Expense GLs map to a finance P&L group; the 34 unmapped are mostly purchases and stock transfers (handled via COGS) plus about 10 small opex ledgers. | **Primary route for FY26-27 store P&L.** Real modelling build, not a source hookup. |
| Finance P&L base | `T_FINANCE_P_AND_L_BASE_1_STORE` (+ budget, store map, grouping tables) | **0 rows from Apr 2025 on** | Appears stale | Ledger entry x location | Either stale or EXP_MTH is null for current rows: not yet distinguished. | One small follow-up probe (min/max of EXP_MTH, FY_YEAR list, END_DATE). Do not rely on it for FY26-27. |
| Budget | `T_FINANCE_P_AND_L_BUDGET` | FY25-26 only (Apr 2025 to Mar 2026), 270 stores, 29 AOP groups | Ends Mar 2026 | Store x month x group | No FY26-27 budget. 270 stores vs 143 in the store map: unexplained. Budget cube `CUBE$BUDGETANALYSIS` returned 0 rows. | **Not usable for the current year.** Needs the FY26-27 plan from Finance. |
| Cash / bank | `V_FINANCE_CASH_FLOW`, `T$BANKREG_561` | CASH_FLOW: 0 rows from Apr 2025; BANKREG: 2022 only | Stale | n/a | No current bank register. Bank/cash GLs are in the site GL register (10 bank/cash GLs present) but entries are movements; opening balances are not in the FY26-27 register. | Bank position needs an opening-balance source (prior-year registers or ledger master) before it can be real. |
| Store cash drawers | `V_FINANCE_CASH_CUMLATIVE_BLNC` | Apr 2026 onward, 209 stores | Current (Dr/Cr to Oct 2026; calendar-filled with zeros to Mar 2027) | Store x day | Till cash only, not bank. Cumulative balance column not yet read. | Real and usable as **store cash held**, kept separate from bank. |
| Working capital | Creditors: real (mart). Inventory: `CUBE$STKVAL`, `V_FINANCE_STOCK_MOVEMENT` (not yet probed). Receivables: `T$BILLCOLL`, `T$FINOTSD_533` debtor side (not yet probed). Vendor advances, statutory, payroll: no source found yet. | Creditors only | Creditors current | n/a | Only creditors is proven. | Cash room can be real for creditors obligations and store cash first; inventory and receivables need their own probes. |
| Hierarchy | `T_FINANCE_P_AND_L_STORE_MAP` (143 stores: state, status, same-store vintage), location map (192: store/HO/DC) | Current | n/a | Store | No Area, Cluster, Region or Zone anywhere in these tables. | Do not invent it. Use Store, State, Company until Finance supplies the mapping. |

## Other facts worth knowing

- Sales (dashboard view), April to September 2026: about 750 Cr; COGS about 476 Cr by the same view. FY26-27 monthly sales run 100 to 137 Cr (July and September are lower).
- 133 of the 145 ledger names in the finance ledger map match the GL master by name; 12 do not.
- The finance group map (145 rows, 5 major groups) does not join to the 22 distinct group labels in the ledger map, so the group hierarchy needs reconciling.
- Store map: 126 active, 17 closed.

## Proposed next probes (bounded, not run)

1. `T_FINANCE_P_AND_L_BASE_1_STORE`: min and max of EXP_MTH, END_DATE, FY_YEAR list, null counts.
2. Dashboard sales view: ADMSITE_CODE against site codes in the store map and the GL register; sales gross vs net of tax and returns.
3. Bank and cash GLs: opening-balance sources in the ledger master or prior-year registers.
4. Inventory and receivables candidates (stock value cube, debtor side of the outstanding cube).

---

# Follow-up probe results (run_20261004_008, profit_cash_probe_02)

11 datasets, 10 loaded. One failed (`i1_stock_movement_by_period`: the view raised an ODBC error). Aggregates only, MISRETAIL only.

## Profitability

| Question | Answer |
|---|---|
| Is the finance P&L base stale? | **Yes, confirmed.** It holds only FY23-24 and FY24-25; the last month is Feb 2025 (last prepared 6 Feb 2025). No nulls: it simply stops. Do not use it for FY26-27. |
| What is one `ADMSITE_CODE`? | A real site code. One row per site per day (196 to 207 sites a day); every code is in the GL register's site list. Only 120 of them are in the store map, and only 143 of the register's 312 sites are in the store map, so the store map is incomplete for current trading sites. |
| What does dashboard `SL_V` measure? | **Net bill amount: after returns, promotions and discounts, and including GST.** For May, Jun, Jul, Aug and Sep 2026 it equals the POS cube `NETAMT` to the paisa (e.g. Aug 135.16 Cr). Net = taxable + tax (May: 129.53 + 7.90). |
| What is the ex-tax revenue? | POS `TAXABLE` equals the GL ledger "Sales - POS" (credit minus debit) to the paisa for May to Aug (129.53, 129.06, 96.94, 127.32 Cr). Revenue for P&L should be ex-GST taxable value, which the GL confirms. |
| Where does it not tie? | **April 2026**: POS net 144.15 Cr vs dashboard 137.09 Cr (7.06 Cr apart), and POS taxable 135.74 Cr vs GL 129.11 Cr (6.6 Cr apart). Needs Finance's explanation (late bills, restatement, or a stale dashboard month). September ties within 0.03 Cr (GL still unposted). |
| Posting status | The current month is **unposted** in the GL (Sep and Oct "Sales - POS" are Unposted). A current-month P&L from the GL is provisional until posted. |
| Void bills | Negligible (about 0.01 Cr a month). |
| Other sales ledgers | Sales - Customer is small (0.1 to 1.4 Cr a month). No postings on Online Sales, Sales Return, Sales Manual, Sales - Service this FY. Returns sit inside the POS bills. |
| The 12 unmatched P&L ledger names | 3 naming differences (Bond Retention, Auditor remuneration, Office Expense_), 3 near-aliases to confirm (Advertisement Expenses, Foreign Travelling Expense (E) and (T)), 4 not in the GL master (AMC CHARGES_AIR-CONDITIONER, Annual Maintenance Charges, Laptop Repair, Subscription Fee (Software)), 2 that are group labels rather than ledgers ("02-COGS(Correction)", "02-COGS(Product)"). The ledger map's group labels also differ from the budget table's. |
| Payment-mode (tender) sales view | Returned 0 rows from April 2026: stale, not usable as a cross-check. |

**Profitability read:** revenue is now well defined (ex-GST taxable, tied to the books). COGS is usable. The blockers are the unexplained April gap, the incomplete store map, the missing FY26-27 plan, and the ledger-to-group mapping gaps. Closer to a contract than before, but not yet.

## Cash and working capital

| Component | Finding |
|---|---|
| Store cash held | `V_FINANCE_CASH_CUMLATIVE_BLNC`: 209 stores, **1.49 Cr in total on 4 Oct 2026**, no negative stores, largest store 0.04 Cr. (1.94 Cr on 31 Aug, 1.36 Cr on 30 Sep.) Real and usable. |
| Bank and cash ledgers | **A source exists after all.** The FY26-27 GL register carries **Opening** entries (voucher type "Opening") plus movements for the bank and cash ledgers, so balance = opening + Dr − Cr is derivable inside one register. Only 10 of the 35 bank/cash ledgers have entries. Caveats: the probe did not split Posted/Unposted or cap the date, entry types include contra (net zero), one account is a cash-credit facility (AXIS CC A/C 1797), and there is no bank statement here to reconcile. Raw FY26-27 bank/cash net is Cr 16.6 Cr, which must not be read as a position until posted-only and as-of rules are applied. **Needs one bounded probe**: per-ledger opening, posted movement to the as-of date, and unposted share; and the FY25-26 closing against the FY26-27 opening. |
| Receivables | Sundry Debtors (ledger 1000000014) in the outstanding cube, as of 4 Oct 2026: **687 open Dr items, 103.21 Cr**; 2,405 open Cr items, 67.15 Cr (customer credits/advances; not netted). The subsidiary debtor ledger has no open items. A real candidate. |
| Inventory | Not found yet. The stock-movement view errored; the stock value cube returned no rows for September 2026 onward. Next: the stock ledgers in the GL register and the stock cube's actual report date. |
| Creditors | Real (mart). |
| Payroll, statutory, vendor advances, capex | No source probed. Stay explicitly unavailable. |

---

# Final Cash probe (run_20261004_009, cash_wc_probe_02)

14 datasets, 12 loaded. Failed: `b1_debtors_foundation` (ODBC error, to be retried with a simpler shape) and `c6_stock_movement_retry` (`V_FINANCE_STOCK_MOVEMENT` is an invalid view: ORA-04063). Aggregates only.

## A. Bank and cash ledgers (10 of 34 have any entries; 24 have none)

Convention check: **passes.** The FY25-26 closing at 31 Mar 2026 (Opening + posted Dr − posted Cr) equals the FY26-27 Opening entry, ledger by ledger (total 3.44 Cr; e.g. AXIS 8218: 2.357 = 2.357). Opening is Dr − Cr, Dr positive for these asset ledgers. The two registers agree on every posted figure to the paisa (same posted Dr, Cr, last posted date). They differ only in unposted items, because their report dates differ by one day (GL register 3 Oct, site register 4 Oct). Contra vouchers net to zero. Future-dated entries (to 31 Dec 2026) net to zero and are excluded from every position.

| As of | Opening 1 Apr | Posted Dr | Posted Cr | **Posted closing** | Unposted Dr | Unposted Cr | **Including unposted** |
|---|---|---|---|---|---|---|---|
| 4 Oct 2026 (site register) | 3.44 Cr | 755.87 Cr | 839.15 Cr | **−79.84 Cr** | 125.0 Cr | 50.2 Cr | **−5.07 Cr** |
| 3 Oct 2026 (GL register) | 3.44 Cr | 755.87 Cr | 839.15 Cr | −79.84 Cr | 112.5 Cr | 49.2 Cr | −16.57 Cr |

One ledger drives it: **AXIS BANK-8218 (CKSPL)**: opening +2.36 Cr, posted closing **−83.45 Cr**, including unposted −5.64 Cr (4 Oct). Last posted entry 30 Sep, last entry date 31 Dec (future-dated). AXIS BANK-7647: +0.70 Cr posted, +0.43 Cr including unposted. Omni card pool: +2.91 Cr posted, +0.11 Cr including unposted. The rest are nil or negligible. Store cash in hand (ledger): 0.02 Cr.

**Verdict: not defensible as "Bank balance as of 4 Oct 2026".** Posted-only is minus 79.84 Cr, because about 125 Cr of net debits (mainly receipts) are still unposted; adding them gives minus 5.07 Cr, still negative, and no bank statement or reconciliation (BRS) is available to say whether that is a real overdraft or a posting lag. The two figures differ by 75 Cr, so neither can be headlined. What can be stated: a ledger book position with the posted and unposted figures side by side, labelled provisional.

Finance questions: is AXIS 8218 an overdraft or collection account that is expected to run negative; what is the usual posting lag for bank receipts; are Omni and Haeywa pool accounts cash or receivables; is a bank reconciliation available and from where.

## B. Receivables (Sundry Debtors, ledger 1000000014; the subsidiary debtor ledger has no open items)

- Customers only in practice: **643 open Dr items, 35 sub-ledgers, 101.32 Cr**; 2,351 open Cr items, 27 sub-ledgers, 65.23 Cr. Small amounts under party class "SIS" (about 1.8 Cr each side) and "Supplier-Non Trading" (0.14 Cr each side). These are not retail customers.
- Dr is almost all **Sale Service Invoice (SS): 623 items, 102.25 Cr.**
- Cr is **AR/AP Voucher (VP): 2,309 items, 26.91 Cr; AR/AP Journal (IJ): 47 items, 37.42 Cr; Credit Journal (CN): 48 items, 2.82 Cr.** Receipts on account and journals, not classified as advances or credits. Not netted against Dr.
- Due dates: Dr 488 items (100.82 Cr) have a due date that has been reached; 199 items (2.40 Cr) have none. **Every Cr item has no due date.**
- Not established (b1 failed): documents and sub-ledger identity counts, date-field population for document/entry/ref dates, and whether PENDING = AMOUNT − ADJUSTED. Needs a retried, simpler probe before a contract.

## C. Inventory: no credible current valuation source. Stop.

- GL: "Closing Stock - FG (B/S)" holds an Opening entry of **265.96 Cr on 1 Apr 2026** (the year-end closing) and no movement since. The other stock ledgers have no entries. This is a year-end accounting figure, not current stock.
- Stock cubes (`CUBE$STKAGE`, `CUBE$STKVAL`, `CUBE$SITESTOCK`): no rows since 2026-01 (stale or not refreshed).
- `V_FINANCE_STOCK_MOVEMENT`: invalid view.
- `T_STK_REPORT_FINAL_OUTPUT_NEW`: store x article stock rows by month, but the totals are not a point-in-time position (Mar 2026: 15.7 Cr at stock value; Sep 2026: 152.8 Cr summed over the month's rows) and bear no relation to the 265.96 Cr in the books. Its valuation basis cannot be established; value at MRP is about 2x the stock value. Not usable.
- Retail price or MRP is not used to reconstruct inventory value, per your rule. Inventory stays **unavailable**.

---

# Receivables retry (receivables_probe_01: runs 010 and 011)

Sundry Debtors (ledger 1000000014) in the OUTSTANDING cube (`T$FINOTSD_533`, report date 2026-10-04), open rows (PENDING <> 0). Aggregates only. The first attempt failed on one wide query; the retry split it into small ones. A broker bug (an Oracle error text the Windows console could not encode killed the run) was fixed and tested.

| Question | Answer |
|---|---|
| Identity | Dr: 687 rows, 685 document codes, 41 sub-ledgers. Cr: 2,405 rows, 2,384 document codes, 35 sub-ledgers. |
| Candidate stable key | **(DOCUMENT_CODE, SUB_LEDGER_CODE) is unique over all 3,092 open rows** (also with Dr/Cr, also with REF_NO). Same key as the creditors pilot. No nulls in document code, sub-ledger or Dr/Cr. REF_NO is 84% null, so it cannot be part of the key. |
| Sign convention | **Same as creditors**: Dr positive, Cr negative, in both AMOUNT and PENDING. |
| PENDING semantics | **Same as creditors**: PENDING = sign(AMOUNT) x (|AMOUNT| − |ADJUSTED|) holds on 100% of rows (687 of 687 Dr, 2,405 of 2,405 Cr). ADJUSTED is null on most rows (645 of 687 Dr, 2,397 of 2,405 Cr). The simple `AMOUNT − ADJUSTED` form holds on only 646 Dr rows and 2,397 Cr rows, so the absolute-difference form is the rule. |
| Totals | Dr: 103.214 Cr (AMOUNT 103.77, ADJUSTED −0.553). Cr: 67.147 Cr absolute (AMOUNT −67.311, ADJUSTED 0.164). Not netted. |
| Date population | DOCUMENT_DATE and ENTRY_DATE are present on every row. REF_DATE: 486 of 687 Dr, 1 of 2,405 Cr. DUE_DATE: **488 of 687 Dr (71%), 1 of 2,405 Cr.** |
| Date quality | Dr document dates reach back to an impossible year (0202-01-01): a date outside any valid window, which the creditors rule (technical window 2000 to 2100) would hold as unclassified, not guess. Stored due-date basis: Dr 617 rows "Document Date" (418 with a due date inside the window) and 70 "Entry Date" (all in window). No due date before its document date. |
| Business identity | Customers (35 Dr sub-ledgers, 27 Cr) plus small SIS and non-trading supplier balances, as found earlier. Dr is almost entirely Sale Service Invoices. |

**Read:** receivables behave exactly like creditors at the cube level, so a `receivables-pilot-1.0` contract can reuse the creditors rules (Document Age and Due Status as separate dimensions, due-date unavailable reported not estimated, Dr and Cr never netted, Cr side unclassified). No extract or mart has been built.
