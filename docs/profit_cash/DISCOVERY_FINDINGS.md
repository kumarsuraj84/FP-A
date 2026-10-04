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
