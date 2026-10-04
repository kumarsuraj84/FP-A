# Liquidity & Working Capital Control: contract proposal `cash-wc-1.0` (for review, nothing built)

Status: **proposal**. No Cash extract, mart, API or frontend change has been made. Evidence: `DISCOVERY_FINDINGS.md` (runs 007 and 008).

## 1. What the page is

The current Cash page (Cash Today / 7d / 15d / 30d, bridge, forecast) is mock and implies a consolidated cash position and a forecast that no source supports yet. Version 1 becomes a **Liquidity & Working Capital Control** page. It shows only what is proven, and names what is not. It keeps its drill-origin, URL and layout machinery; the sections change, not the architecture. A bank position and a forecast can be added later without redesign.

## 2. Components

### Real in v1

| Component | Source | Definition | As-of rule |
|---|---|---|---|
| Creditor obligations | The **existing Creditors mart run** (no new Oracle extract) | Credit Outstanding; Past Due; Not Yet Due; Due Date Unavailable; >90 and >180 Document Age. Same definitions as `/creditors`. | The creditors run's as-of date. Shown with that run's data state. |
| Creditor debit balances | Creditors mart | Dr balances in the four creditor ledgers, **separate**, never netted, classification pending. | Same run. |
| Store cash held | `MISRETAIL.V_FINANCE_CASH_CUMLATIVE_BLNC` (till cash per store) | Sum of cumulative store cash balance on the as-of date; store count; stores with a negative balance; largest store; month-to-date Dr and Cr. | Latest date on or before the creditors/report as-of date with activity. Calendar-filled future rows (zero) are excluded. |
| Working-capital pressure from creditors | Derived from the two above, in the mart | Past Due creditors as a multiple of store cash held; Credit Outstanding vs store cash held. Stated as ratios of two real figures, **not** as liquidity or runway, because bank cash is absent. | Same as-of. |

### Candidates, each needs one bounded probe before it may enter the contract

| Component | Candidate | What the probe must settle |
|---|---|---|
| Bank and cash ledger position | FY26-27 GL register (`T$FINREGSITE_844` or `T$FINREG_901`): Opening entry + Dr − Cr per bank/cash ledger | Posted-only and date ≤ as-of; per-ledger opening, movement and unposted share; FY25-26 closing equals FY26-27 opening; treatment of the cash-credit account and of contra entries; pool/wallet accounts (Omni, Haeywa) as cash or receivable. |
| Receivables | Sundry Debtors in the outstanding cube: 687 open Dr items, 103.21 Cr; 2,405 open Cr items, 67.15 Cr | Debtor party identity, ageing and due rules; what the Cr items are; whether debtors belong in working capital v1. |
| Inventory | Not found | Stock ledger balances in the GL register; actual report date of the stock cube. |

### Explicitly unavailable in v1 (shown as "not available from current source", with the reason)

Bank balances; consolidated cash position; cash forecast (7/15/30 days); inventory working capital; receivables; vendor advances; payroll obligations; statutory obligations; capex commitments. Each is a labelled placeholder with its reason. None is shown as zero, and none is estimated.

## 3. Rules

- Credit, debit and net are never blended. Store cash is not bank cash and is never added to it.
- No figure on the page may come from the demo service. The page carries the same REAL DATA badge: `REAL DATA · Verified candidate · As of DD MMM YYYY`, driven by the API's `data_state`.
- Actual and forecast cash are different things and are never mixed. No forecast exists in v1.
- SSRK is out of scope. Oracle is reached only through the SELECT-only broker. FP&A never authenticates to Oracle, and never reads or copies the Inventory Automation credential.

## 4. Shared run model (all domains)

One table in a new `core` schema of `fpa_pilot`, written only by controlled functions: `domain`, `extraction_run_id`, `as_of_date`, `source_status`, `mart_status`, `api_status`, `publication_status`. Creditors is registered into it by a migration (its tables are not changed). Cash registers the same way. Every page then shows state and freshness from one place. This is a proposal for the second step; Cash v1 does not need it to ship, but it should land before Profitability.

## 5. Pipeline (same gates as Creditors)

1. Package `cash_wc_pilot_01`: source controls, then the store cash extract (one row per store per day, aggregated, no row-level personal data), then source controls again. Numbers and dates as exact text. A failed control halts the run.
2. Offline staging validation: hashes, row counts, store cash tie to the source control.
3. Mart `cash` schema in `fpa_pilot`: run-versioned immutable tables, the same role split (owner, loader, verifier, promoter, API reader), the same promotion gates. Creditor figures are **read from the creditors mart through a controlled view**, never re-extracted or copied by hand, and the cash run records which creditors run it used.
4. Reconcile source to extract to mart to API with zero variance.
5. API `/api/v1/cash/...`, masked store codes only. Store names only for Finance, as for vendors.
6. Frontend: only `/cash` changes, to the Liquidity & Working Capital Control page. Preview before promotion. Command Center and Profitability are untouched.

## 6. Decisions I need from you

1. Approve the v1 scope above (store cash + creditors real; bank, receivables, inventory behind probes; everything else unavailable).
2. Approve **one bounded probe** for bank/cash ledger position, receivables identity and inventory, before deciding whether bank enters v1 or v1.1. Recommendation: yes, because a derivable bank position would turn this into a real cash page quickly.
3. Confirm store cash held should be shown as **till cash only**, labelled as such.
4. Confirm the shared run model may land as its own migration after Cash v1.
