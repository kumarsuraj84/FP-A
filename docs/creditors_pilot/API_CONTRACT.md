# Creditors API contract (v1)

Read-only. Serves ONE verified mart run: a **candidate** (unpublished, reconciled) now, **live** after promotion. Code: `backend/app/creditors_api/`.
Run locally: `cd backend && python -m uvicorn app.creditors_api.main:app --host 127.0.0.1 --port 8081`.

## Rules

- **Money is exact decimal text** (`"4043757678.4100"`), never a JSON number. The UI converts for display only.
- **The API states the data state; the UI never infers it.** `data_state` is `verified_candidate` (reconciled, not published), `live`, `superseded` or `withdrawn`. A run that is only `loaded` (not verified) is not served: 404.
- **Masking is enforced by the database.** Each request runs as exactly one of `cred_verifier` (candidate, masked), `cred_api_reader` (live, masked) or `cred_finance_reader` (named). The masked routes cannot return a vendor name, SLCODE, SLID, document code, document number, reference number or credit days, because the role cannot read them.
- **Finance routes** (`/finance/...`) need `Authorization: Bearer <token>` (401 without it, 503 if the server has no token configured). They add vendor name, `slid`, `sub_ledger_code`, `credit_days`, and on items `document_code`, `document_no`, `document_initial`, `ref_no`, `ref_date`, `created_by_site`.
- **Credit, debit and net are never blended.** Every figure is `credit_outstanding` (sum of absolute Cr), `creditor_debit_balance` / `debit_balance` (sum of absolute Dr, classification pending) and `signed_net`, separately.
- Document Age and Due Status are separate dimensions.

## Endpoints (prefix `/api/v1/creditors`)

| Route | Returns |
|---|---|
| `GET /health` | `{status}` (no database) |
| `GET /current` | the live run if any, else the newest verified candidate: run header |
| `GET /candidates` | `{runs: [run header]}` |
| `GET /runs/{run}` | status: run header, `expected_rows`, control tallies per layer (`source→extract`, `extract→mart`, `mart→api`), `scope` |
| `GET /runs/{run}/summary` | run header + `item_rows`, `vendors`, `credit_items`, `debit_items`, `credit_outstanding`, `creditor_debit_balance`, `signed_net`, `past_due_credit` (+`_items`), `due_unavailable_credit` (+`_items`), `over_90_credit`, `over_180_credit` (+`_items`), `credit_vendors`, `debit_vendors`, `credit_concentration` {top_1, top_5, top_10, top_20} |
| `GET /runs/{run}/document-age` | `buckets`: `D0_30, D31_60, D61_90, D91_180, D181_365, D365_PLUS, UNCLASSIFIED` (labels `0–30 … >365`, `Unclassified`), each with credit/debit items and amounts and net; `UNCLASSIFIED` carries `reasons` |
| `GET /runs/{run}/due-status` | `states`: `NOT_YET_DUE`, `PAST_DUE_OR_DUE_TODAY`, `DUE_UNAVAILABLE`, `DUE_INVALID` with labels, credit/debit items and amounts and net |
| `GET /runs/{run}/ledgers` | one entry per creditor ledger: credit and debit items and amounts, net, vendors (total, credit, debit), past due and due-unavailable credit |
| `GET /runs/{run}/controls` | tallies per layer and the failing controls |
| `GET /runs/{run}/vendors` | `total` {vendors, credit_outstanding, debit_balance, signed_net} and `vendors[]`: `vendor_ref`, `party_class`, `party_class_type`, `ledger_codes`, items, credit/debit amounts, net, `past_due_credit`, `due_unavailable_credit`, `oldest_credit_age_days`, `share_of_credit`, `credit_by_document_age`, `credit_by_due_status`. Query: `ledger_code`, `party_class`, `sort` (`credit_outstanding`, `debit_balance`, `net`, `items`, `past_due`, `due_unavailable`, `oldest`), `order`, `limit` (1-500), `offset` |
| `GET /runs/{run}/vendors/{vendor_ref}` | one vendor (same fields) |
| `GET /runs/{run}/vendors/{vendor_ref}/items` | open items: `item_ref` (drill id), `ledger_code`, `ledger_name`, `drcr`, `amount`, `adjusted`, `pending`, dates, `document_age_days`, `document_age_bucket`, `overdue_days`, `due_status`, `date_quality_status`, `classification_status`. Query: `drcr`, `bucket`, `due`, `limit` (1-2000), `offset`. Oldest document first |
| `GET /runs/{run}/finance/vendors` (+ `/{ref}`, `/{ref}/items`) | the same with names and codes; `q` searches vendor name |

## The mart = API gate

`cd backend && python -m app.creditors_api.reconcile <run> [--record]` reads every endpoint, every vendor and every open item through the API and compares them with the mart (differently shaped SQL), exactly. `--record` writes the results as `mart→api` controls through the verifier's function and asks the database to advance the run to `api_verified` (still unpublished). One difference blocks it.
