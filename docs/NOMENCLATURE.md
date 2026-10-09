# Nomenclature: portal term to finance MIS term

Source of the vocabulary: `Citykart MIS Format_Aug'26.xlsx` (sheets `P&L`, `P&L Ext`, `Stores`, `Store Cohorts`) and `P & L _New Version _FY27_Aug'26_updated.xlsx`, as read in `Aug26_Reconciliation/REVIEW_AND_PLAN.md` (sections 4 and 5).
The UI uses exactly these names. Code identifiers, API keys and `data-testid` values are NOT renamed (`revenue`, `gross_margin`, `opex`, `contribution` stay as they are in the JSON); only displayed text changed.
The single source in code is `frontend/src/lib/nomenclature.ts` (`T`, `GROUP_NAME`, `vintageLabel`) and, for the API, `backend/app/gold/pnl.py` (`GROUP_DISPLAY`, `MIS_LINE_OF_GROUP`).

## Basis

The Profitability page, its store workspace and its review tabs are the **books basis, before management adjustments** (the 1% shrinkage provision, gratuity, audit and CSR provisions, journals, the Citykart Ventures cost). Management adjustments live on the Management P&L page. The UI says: "Books basis, before management adjustments; see Management P&L."
The Command Center P&L tiles and hero bridge read the Management P&L API (book + adjustment = total) and say "includes management adjustments" where the adjustment is not zero. Last-year movements exist on the books basis only and are labelled so.

## Terms

| Portal term (old) | MIS term (new) | Definition | MIS source |
|---|---|---|---|
| Net sales ex-GST, Net sales | **Revenue from operations** | Credit less debit of group `01-Net Sales` at STORES sites, ex-GST | `P&L` row "Revenue from operations" |
| (Other income, lumped) | **Other operating income** | Group `02-Other Income`, all locations. Interest income and finance cost are separate and below EBITDA | `P&L` row "Other operating income" |
| (none) | **Total income** | Revenue from operations + Other operating income | `P&L` row "Total income" |
| COGS | **Material Cost** | COGS table (`T_CUSTOM_COGS`) for STORE sites, plus the COGS(Others) ledgers at STORES sites | `P&L` row "Material cost" |
| Other COGS items (books) | Other material cost items (books) | COGS(Others) ledgers (purchase discounts and the like) at STORES sites; the same ledgers at DC / HO sites are DC / HO cost | `Main Data Sheet`, group `02-COGS(Others)` |
| Gross margin (company) | **Material Margin** | Total income less Material Cost | `P&L` row "Material margin" |
| Gross margin (store) | **Gross Margin** | The same measure for one store. Finance abbreviates it RGM; the abbreviation is not used in the portal | `Stores` sheet, "RGM" |
| Store opex, Store operating expenses | **Store Expenses** | Rent, Employee Cost, Power and Fuel, Advertisement, Freight Forwarding, Other expenses at STORES-location sites only (STORE, VIRTUAL, EXTERNAL sites). DC and HO cost are separate lines | `P&L` rows "Total store expenses" |
| Contribution (company) | **Store EBITDA** | Material Margin less Store Expenses. Before DC cost, HO cost, interest income and finance cost | `P&L` row "Store EBITDA" |
| Contribution (one store) | **4-Wall EBITDA** | Gross Margin less Store Expenses for one store | `Stores` sheet, "4-Wall EBITDA" |
| (none) | **DC cost** | Every cost posting at a DC (warehouse) site, other income excluded | `P&L` row "DC cost" |
| (none) | **HO cost** | Every cost posting at an HO site, other income, interest income and finance cost excluded | `P&L` row "HO cost" |
| (none) | **Total Corporate Cost** | DC cost + HO cost | `P&L` row "Total corporate cost" |
| (none) | **Corporate EBITDA** | Store EBITDA less Total Corporate Cost | `P&L` row "Corporate EBITDA" |
| Contribution margin % | 4-Wall EBITDA % / Store EBITDA % | Percent of revenue (portal) or of total income (Management P&L) | `P&L` % block |
| Freight outward | **Freight Forwarding** | Group `08-Freight Outward` | `P&L` row "Freight forwarding" |
| 01-Rent | **Rent** | Group `01-Rent` | `P&L` row "Rent" |
| 02-Employee Cost | **Employee Cost** | Group `02-Employee Cost` | `P&L` row "Employee cost" |
| 03-Power and Fuel Expenses | **Power and Fuel** | Group `03-Power and Fuel Expenses` | `P&L` row "Power and fuel" |
| 07-Advertisement And Sales Promotion | **Advertisement** | Group `07-...` (was "Advertisement and sales promotion") | `P&L` row "Advertisement" |
| 09 Insurance, 10 Travelling & Conveyance, 11 Communication, 12 Repairs and Maintenance, 13 Packing, 14 Legal and Professional, 16 Miscellaneous, 17 Bank Charges, 20 Printing & Stationery | **Other expenses** (shown by their own names: Insurance, Travel and Conveyance, Communication, Repairs and Maintenance, Packing, Legal and Professional, Miscellaneous, Bank Charges, Printing and Stationery) | MIS rolls these nine groups into one line. The portal keeps them as separate lines, each tagged with `mis_line = Other expenses` | `P&L` row "Other expenses" |
| 05-Director remunaration | Director remuneration | Counted in Other expenses at STORES sites, in HO cost at HO | `Main Data Sheet`, group `05-` |
| Group display names with a numeric prefix | The MIS name without the prefix | The raw group code stays in the tooltip and in `group_label` | `SK-GRP` |
| Old store (`OLD STORE`) | **Same Store / LFL 120** | The 120 stores the site master calls OLD match the MIS LFL 120 cohort in count. The finance LFL tag itself is not in the sources | `Master` sheet, LFL tag |
| New store (`NEW STORE`) | **Non-LFL** | All other trading stores. NSO TY (stores opened this year) and Closed are not separately tagged in the sources | `Master` sheet, LFL tag |
| NSO TY | NSO TY | Stores opened this year (MIS tag). Not distinguishable in the sources; not shown | `Stores` sheet |
| Closed | Closed | MIS tag; the site master has `CLOSED` status (7 sites) | `Stores` sheet |
| Last year compare, last year | **LY** | Same months of the previous year | `P&L Ext` "LY" |
| Sales growth, growth vs last year | **Y-o-Y Growth** | Revenue growth against LY, complete months | `P&L` "Y-o-Y" |
| (none) | **SSSG** | Same-store sales growth, LFL stores. Cannot be reproduced from the sources today (needs the LFL tag); not shown | `P&L` "SSSG" |
| Plan, Budget | **AOP** | Annual operating plan. "AOP (budget): not available" for FY26-27; nothing is estimated | `Stores`, `P&L` "AOP" |
| Head office, depots | **HO**, **DC** | Location types from the management site rules | `mgmt_site_loc.csv`, `ALL DC COST` |
| Supplier-Apparels, Supplier-GM, Supplier-Expenses, Supplier-Non Trading | Same | Supplier classes as the data carries them (Creditors); not renamed | `Master` vendor class |

## Grouping (what the numbers use)

* Ledger group: `config/mgmt/mgmt_ledger_map.csv` replaces the gold finance group for every ledger listed there (read once at API start-up; a missing file means no override). It supplies a group for the 20 ledgers gold leaves unmapped and re-groups the 3 conflicts (Gratuity to Employee Cost, Professional Charges to Legal and Professional, Notice Pay Recovery to Employee Cost). Stock-transfer and purchase ledgers are `EXCLUDED` (inventory flow): they are counted apart, not as "needs a group".
* Location: STORES, DC or HO per site, from the site kind (STORE, VIRTUAL, EXTERNAL = STORES; HEAD_OFFICE = HO; WAREHOUSE, WAREHOUSE_OTHER = DC) with `config/mgmt/mgmt_site_loc.csv` overriding (CKSPL-ISD is HO).
* Entity: the Profitability API reads the RETAIL entity only (Citykart Stores). Citykart Ventures is on the Management P&L page.
* Not in Profitability, on the Management P&L: the 1% COGS correction (shrinkage provision), COGS bifurcation, gratuity, audit and CSR provisions, HO incentive, advertisement movement to stores, SIS income, one-time items, DC / HO apportionment to stores.

## Terms that could not be mapped

* **SSSG, NSO TY**: no LFL flag or opening cohort in the gold sources; the labels exist in the vocabulary but no figure is shown.
* **Closed** as a store type: only the site-master status `CLOSED` exists (no closing-date cohort).
* **Supplier classes**: the Creditors data does not carry the MIS class names as a field the portal reads; shown as the data has them.
* **RGM**: deliberately not introduced in the UI (Gross Margin at store level).
* **AOP by store and month**: no budget source (issue 13 of the review plan).
