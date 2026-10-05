# Drill-to-entry contract `drill-1.0` (proposal, for review; nothing extracted or built)

Evidence: `DISCOVERY_FINDINGS.md` (voucher_probe_01 and voucher_probe_03). Rule: **every figure drills to the deepest level that is proven for its source, and never further.**
One accounting-entry layer, three proven source bridges, one canonical entry identity.

## 1. One entry identity, one entry layer

Canonical identity: **`(site, entry_type, entry_no)`** (the register's SITECODE, ENTRY_TYPE_SHORT, ENTRY_NO). `entry_no` alone repeats across sites and types, so it is never used alone. The API and UI use an opaque `entry_ref` (a hash of the identity); the identity itself is shown only in the Finance view.

New schema `entry` (migration 005, same discipline as `cred` and `cash`: immutable run-versioned snapshots, controlled functions, separate verify and publication states, no UPDATE or DELETE):

| Table | Holds |
|---|---|
| `entry.run` | one snapshot of the site register: source object, **register report date**, extract times, expected counts, hashes, `recon_state`, `publication_state` |
| `entry.entry_header` | one row per entry: `entry_ref`, site, type (short and long), entry number, entry date, release state, created-by site, line count, total Dr, total Cr |
| `entry.entry_line` | every line of every extracted entry, **all lines of a multi-line entry**: line number, ledger code and name, sub-ledger (pseudonymous ref for masked use), Dr, Cr, release status, source cube |
| `entry.entry_line_text` (Finance only) | narration, reference number and date, cheque number and date, counter-ledgers, prepared by/on, last modified by/on, released by/on |
| `entry.creditor_bill_link` | per open creditor bill: `link_status`, `key_used`, matched `entry_ref` (null unless Exact), `amount_agrees`, `coverage` note |
| `entry.till_day` | per store per day: Dr, Cr, cumulative balance as served by the till view (for the cumulative-day control) |
| views | `cash_drawer_entry_link` (Cash Drawer lines by store and day) and `bank_entry_link` (bank/cash ledger lines by ledger, release status and date) are views over `entry_line`: no second copy of any line |

The entry run joins the shared run model (`core.v_domain_run`, domain `entries`). **Lineage:** every link row carries the domain run it belongs to (creditors run, cash run) and the entry run it points into. The API refuses to serve a drill where the two as-of dates disagree (`register_report_date` must equal the domain run's as-of date, except the till, whose balance date is stated and must be on or before it). A drill can never silently land on another snapshot.

## 2. The three bridges

| Bridge | Source link | Status values | Coverage |
|---|---|---|---|
| `creditor_bill_link` | ledger + sub-ledger + `DOCUMENT_NO = ENTRY_NO`, materialised in the mart | `EXACT` (one distinct entry identity, amount-corroborated), `AMBIGUOUS` (several; **never auto-selected**, listed with the count), `NOT_LINKED` | FY26-27: 10,239 of 10,239 Exact. FY23-24 to FY25-26: 1,565 of 1,599 Exact, 34 `NOT_LINKED` (kept as such, not investigated). Items older than April 2023: `NOT_LINKED` with reason **"source register coverage unavailable"**, a distinct reason, not a generic failure. |
| Cash Drawer | the till view equals the register ledger "Cash Drawer" to the paisa | n/a (an exact identity, proven) | all stores, all days to the till date, posted and unposted |
| `bank_entry_link` | bank and cash ledger lines are the position itself | n/a (exact by construction) | the 10 ledgers with entries (24 have none) |

## 3. Drill paths and what each level must equal

**Store Till Cash:** card → store (209) → day → accounting entry → all entry lines → "No verified attachment source available".
**Bank review card:** card → ledger → posted / unposted split → entries → all entry lines.
**Creditors:** card → breakdown (ledger, Document Age, Due Status) → vendor list → vendor → open bills (already built) → bill → entry (link status shown) → all entry lines.

Every list shows its parent figure, the sum of its rows and an explicit `reconciles` flag (the API computes it; the UI shows a red failure state, never a quiet mismatch).

## 4. Controls (all must be green before any drill UI is switched on)

| # | Control | Where enforced |
|---|---|---|
| E1 | The extracted entry lines equal the Oracle source control: line count and exact Dr/Cr per selection, pre and post (refresh race rejected) | extract, staging |
| E2 | **Full multi-line vouchers:** for every entry, the extracted line count equals the source line count (histogram by line count plus a per-entry hash of the line set) | staging, loader |
| E3 | Every extracted entry balances: total Dr = total Cr across all its lines | staging, mart check |
| E4 | Every `EXACT` creditor link resolves to exactly one canonical identity, and that entry exists in `entry_header` | mart check |
| E5 | No `AMBIGUOUS` link has an `entry_ref`; no code path picks a winner | mart check, API test |
| E6 | `NOT_LINKED` stays visible: the link count by status equals the open-item count of the creditors run | mart control |
| E7 | Bank: posted and unposted entry-line sums per ledger equal the review card's posted and unposted figures exactly, and future-dated lines are excluded and shown separately | mart control, API gate |
| E8 | Till: for every store and day, **cumulative balance recomputed from all Cash Drawer lines up to that day (including the Opening line) equals the till view's cumulative balance**; day Dr/Cr equal the sum of that day's lines; Σ stores on the till date equals the Store Till Cash card | mart control (the cumulative-day reconciliation) |
| E9 | Creditors: for an `EXACT` bill, the entry's net amount for that ledger and sub-ledger equals the bill amount (already 100% in the probe) | mart control |
| E10 | Parent = Σ children at every level of every path | API gate (mart = API, per level) |
| E11 | No drill crosses run or as-of context | API, UI test |
| E12 | Masked responses contain no narration, reference, cheque field, preparer or releaser, entry number or sub-ledger code; Finance routes need the bearer token | API test (role-enforced in the database) |

## 5. Bounded entry-level extract, package `entry_pilot_01` (design only)

Row-level, but only the entries the three pages already show, and only through the guarded broker (SELECT-only, MISRETAIL, capped, date-bounded, exact text). Scalar source controls are computed in Oracle in a different shape before and after.

| Dataset | Selection | Size estimate |
|---|---|---|
| `h1_creditor_entries` | all lines of every entry that carries an open creditor bill (FY26-27 site register, then the all-years register for older bills) | ~9–10k entries, ~15–50k lines |
| `h2_bank_entries` | all lines of every entry that touches a bank or cash ledger, to the register report date, future-dated entries flagged | ~8.5k entries, ~20k lines |
| `h3_till_entries` | all lines of every entry that touches the "Cash Drawer" ledger, to the till date | ~165k entries, ~490k lines (retail sales average 6.7 lines, POS journals 2) |
| `l1_creditor_links` | per open bill: key used and the distinct matched entry identities (identifiers only) | 12,233 rows |
| `l2_till_day` | the till view per store per day (the cumulative-day control's right-hand side) | ~38,900 rows |
| `c*_pre / c*_post` | line counts and exact Dr/Cr per selection, in a different grouping | scalars |

Total about 0.6 million lines: far inside the 5M cap. Narration, references, cheque fields and preparer/releaser names go to `entry_line_text` only. **Narration is free text and can contain personal data** (names, phone numbers). The extract guard only checks column names, so the loader keeps it in the Finance-only table, the masked API never reads that table, and the UAT proves it.

## 6. API and UI

- `GET /api/v1/entries/{entry_run}/entries/{entry_ref}` masked: type, date, release state, lines with ledger names and amounts, link status. `/finance/...`: adds entry number, reference, cheque fields, narration, preparer and releaser.
- Domain drills: `/cash/runs/{run}/till/stores`, `/till/stores/{site}/days`, `/till/stores/{site}/days/{date}/entries`; `/cash/runs/{run}/bank-ledgers/{code}/entries?status=posted|unposted`; `/creditors/runs/{run}/items/{item_ref}/entry`. Each returns the parent value, the child sum and `reconciles`.
- One shared Entry page. Link-status chip (Exact / Ambiguous / Not linked, with the reason). The attachment area reads **"No verified attachment source available"** (never an empty box). Breadcrumbs and the header keep the run and as-of date through the drill.
- A card whose deepest verified level is shallower says so ("Deepest verified level: bill").

## 7. Build order (each step reviewed before the next)

1. Migration 005 (`entry` schema, roles, views, `core.v_domain_run` learns `entries`): an admin step for you, as before.
2. `entry_pilot_01` package, guard tests, staging validator with E1 to E3, loader with E4 to E9, scratch UAT.
3. Real extract and load; verified, unpublished.
4. Entry API and the mart = API gate with E10 to E12.
5. UI: **bank drill first**, then Store Till Cash, then Creditors; each with a real-data review and screenshots at both sizes.

## 8. Decisions I need

1. Approve the `entry` schema and the shared structure above.
2. Confirm narration, reference, cheque fields and preparer/releaser are Finance-only, in a separate table the masked role cannot read.
3. Approve running `entry_pilot_01` through the broker after the staging validator and loader are tested (the extract is row-level, about 0.6M lines).
4. Confirm that items older than April 2023 stay at bill level with "source register coverage unavailable".
