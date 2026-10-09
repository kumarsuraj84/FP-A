# Management (MIS) P&L configuration

The data files here hold real finance numbers and are git-ignored (`*.csv`, `*.json`); only this README and `*.example.*` are committed.
Regenerate them with `python tools/mgmt/seed_from_workbook.py --pl <P&L workbook> --mis <MIS workbook> [--gold]` (needs openpyxl).

| File | Purpose |
|---|---|
| `mgmt_ledger_map.csv` | ledger -> management group (finance SK-GRP). Overrides the gold `fin_group`. Flags ledgers gold leaves UNMAPPED (source `workbook;gold_unmapped`). Finance decisions: Gratuity -> Employee Cost, Professional Charges -> Legal, NOTICE PAY RECOVERY -> Employee Cost (the workbook has it under Other Income; 0.46 lakh, immaterial). `EXCLUDED` = inventory flow, kept out of the P&L. |
| `mgmt_site_loc.csv` | site-level location override (CKSPL-ISD is HO in the MIS). Default rule: STORE, VIRTUAL, EXTERNAL -> STORES; HEAD_OFFICE -> HO; WAREHOUSE, WAREHOUSE_OTHER -> DC. |
| `adjustments.csv` | the adjustments register. Columns: id, month, mis_line (P&L line key), location_type, amount_cr, kind (provision, manual_journal, income_adjustment, reclass, stopgap_entity, one_time, elimination), rule, owner, status (confirmed, proposed, stopgap, in_books = memo only), source, note, entity (SUBCO or HOLDCO), counterparty, counterparty_entity. |
| `mis_published.csv` | the published MIS monthly values by line, used only by the reconciliation. |
| `mis_overrides.csv` | hard-coded values in the MIS sheet that the portal does not copy: portal minus MIS that they explain. |
| `rules.json` | tolerances and rule parameters (defaults are in `backend/app/mgmt/config.py`). |

Rules computed by the engine, not stored: COGS correction (1.0% of store net sales every month from 2026-04), COGS bifurcation (purchase / early-payment discounts booked at DC and HO are charged to stores), advertisement movement HO/DC to stores (from 2026-08; earlier months are explicit register rows), fixed monthly provisions continued after the last register month (status proposed, always provisional; `include_proposed=false` removes them), SIS income as a true-up of the booked Business Auxiliary Service ledger.

Entities: SUBCO = Citykart Stores (CKSPL, gold entity RETAIL); HOLDCO = Citykart Ventures (CKVPL-* warehouses, CRPL-HO, gold entity VENTURES). When gold carries an `entity` column it is used, and a month in which gold already holds HoldCo postings suppresses the workbook stop-gap rows for that month. Intercompany eliminations are not invented: `elimination` rows are empty until finance or a gold table (`gold_fpa.mgmt_eliminations`) provides them.
