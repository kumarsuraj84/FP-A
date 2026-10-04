# Creditors pilot: first real extract package. PROPOSAL (nothing has been run)

Status: proposal for review. No Oracle call, no extract, no mart load, no frontend change.
Frontend frozen at `9310b0a`. Broker branch: `feature/extraction-broker`.
Every statement below was checked against the broker guard offline (nothing sent anywhere).

## 1. Frozen inputs

| Item | Decision |
|---|---|
| Source object | `MISRETAIL."T$FINOTSD_533"` (cube OUTSTANDING), with LEFT JOINs to `MISRETAIL.LEDGER_MV` (ledger name) and `MISRETAIL.SUB_LEDGER_MV` (vendor attributes) |
| Scope | `LEDGER_CODE IN (1000000026 Apparels, 1000000024 for Expenses, 1000000092 GM, 1000000025 Non Trading)` |
| Open rows | `PENDING <> 0`, source sign preserved (Cr negative, Dr positive) |
| Excluded | TDS Payable, Sundry Debtors, Inter-Company, Vendor Advances |
| `as_of_date` | the cube `REPORT_DATE` carried in every row; exactly one distinct value required per run; `END_DATE` never used |
| Primary identity | `source_row_key = sha256("v1|" + DOCUMENT_CODE + "|" + SUB_LEDGER_CODE)` |
| Secondary signature | `identity_k1_signature = sha256("v1|" + DOCUMENT_CODE + "|" + LEDGER_CODE + "|" + SUB_LEDGER_CODE + "|" + DRCR)`, a uniqueness control only |
| Mutable (fingerprint, not identity) | LEDGER_CODE, DRCR, AMOUNT, ADJUSTED, PENDING and the dates / references listed in 6 |
| No ordinal | a duplicate key hard-fails the run |
| Terms | primary ageing dimension is **Document Age**, the other is **Due Status** |

## 2. Package `creditors_pilot_01`: datasets, in run order

One query at a time through the existing Inventory Automation broker, `FPA__` namespace, `platform.db` backed up first.

| # | Dataset | Role | Expected | Guard cap | Query hash |
|---|---|---|---|---|---|
| 1 | `c1_source_control_pre` | source control (ledger x DR/CR x Document Age x Due Status) | about 40 rows | 1000 | e40e50bbca |
| 2 | `c2_vendor_control_pre` | source control (distinct vendors: total, per ledger, per DR/CR) | about 15 rows | 100 | 0e7dd3b44f |
| 3 | `c3_snapshot_control_pre` | source control (row total, report dates, key uniqueness, nulls, join coverage) | 1 row | 2 | 1f67393682 |
| 4 | `e1_open_items` | **the extract**: one row per open source item | 12,233 rows | 50000 | 24c8d8d71e |
| 5 | `e2_identity_all_rows` | identity + PENDING for all rows in the four ledgers (stability evidence) | about 110,092 rows | 500000 | 4d00d19482 |
| 6-8 | `c1/c2/c3_*_post` | the same three controls again | same as 1-3 | same | same |

Run protocol (hard failures, run is rejected and nothing is published):
1. Pre controls, then extract, then post controls. Timestamps recorded for each step.
2. **Refresh race:** any difference between pre and post controls (rows, sums, report date, per-group values) rejects the run.
3. `e1` rows must equal the pre control; hitting the 50,000 row cap is a failure (`capped`).
4. Parquet and manifest validation exist already (sha256, size, row count, cap consistency).
5. All validation runs offline on the Parquet files; nothing here talks to Oracle after step 3.

## 3. Columns selected for the extract (`e1_open_items`)

Numbers and dates travel as exact text: `TO_CHAR(x, 'TM9')` for numbers and `TO_CHAR(d, 'YYYY-MM-DD')` for dates. This avoids binary-float rounding and is the only safe way to carry dates such as year 0202 (outside what a Parquet nanosecond timestamp can hold). The loader parses with exact decimals and fails on any value that does not match `^-?[0-9]+(\.[0-9]+)?$`.

| Group | Columns |
|---|---|
| Snapshot | as_of_date (from REPORT_DATE) |
| Identity parts | document_code, sub_ledger_code |
| Ledger | ledger_code, ledger_name |
| Vendor (SUB_LEDGER_MV) | slid, vendor_name, party_class (SL_CLASS), party_class_type, credit_days, vendor_extinct |
| Document | document_no, document_type, document_initial, document_date, due_date, due_date_basis, ref_no, ref_date, entry_date, created_by_site |
| Accounting | drcr, amount, adjusted, pending |

Deliberately not extracted: NARRATION (free text, mutable, may name individuals), AGENTNAME / AGENT_ALIAS, the cube's precomputed day-count columns (`NO_OF_DAYS*`, which run to the fiscal year end), CUBE metadata, RELEASE_STATUS (always null), ADMOU_CODE. All vendor contact, address, tax and bank columns stay out; the guard already blocks them.

Vendor names can identify sole proprietors, so the extract stays in the git-ignored inbox. Access rules are needed before the mart exposes them.

The joins are LEFT joins and cannot multiply rows (SLCODE is unique in the vendor master, 13,191 of 13,191). The earlier probes returned identical totals with and without the joins. The pre control counts any row with no vendor or ledger match.

## 4. Derived fields (computed offline in staging; Oracle returns raw values)

An independent implementation of the same rules runs in Oracle inside `c1` as the source control, so a rule bug cannot hide behind itself.

**Document Age** from `as_of_date - DOCUMENT_DATE` in whole days:

| Condition | Value |
|---|---|
| document_date missing | `UNCLASSIFIED_MISSING` |
| before 2000-01-01 | `UNCLASSIFIED_BEFORE_2000` |
| after as_of_date | `UNCLASSIFIED_AFTER_AS_OF` |
| 0 to 30 | `D0_30` |
| 31 to 60 | `D31_60` |
| 61 to 90 | `D61_90` |
| 91 to 180 | `D91_180` |
| 181 to 365 (365 included) | `D181_365` |
| over 365 | `D365_PLUS` |

`document_age_days` is null when unclassified. `date_quality_status` is `OK`, `MISSING`, `BEFORE_2000`, `AFTER_AS_OF` or `UNPARSEABLE`. No date is clamped or corrected.

**Due Status** from stored `DUE_DATE` only (never derived from CREDIT_DAYS):

| Condition | Value |
|---|---|
| due_date missing | `DUE_UNAVAILABLE` |
| before 2000-01-01, after 2100-12-31, unparseable, or before document_date (when present) | `DUE_INVALID` |
| after as_of_date | `NOT_YET_DUE` |
| otherwise | `PAST_DUE_OR_DUE_TODAY`, with `overdue_days = as_of_date - due_date` (0 if due today) |

**`classification_status`**: `CREDIT_OUTSTANDING` for Cr, `CREDITOR_DEBIT_BALANCE_CLASSIFICATION_PENDING` for Dr. Never "vendor advance".

## 5. Identity and fingerprint

- `source_row_key`: exact UTF-8, no trimming or case change. The loader hard-fails if either part is null, empty, or contains `|`, so the encoding stays injective.
- Uniqueness is asserted three ways: the loader on `e1`, the Oracle source control (`COUNT(DISTINCT document_code || sub_ledger_code)` in `c3`), and the Postgres primary key.
- `identity_k1_signature` uniqueness is checked as a secondary control.
- `row_fingerprint = sha256("v1|" + fields)`. Fixed field order: ledger_code, drcr, amount, adjusted, pending, document_date, due_date, ref_no, ref_date, entry_date, document_no, document_type, document_initial, due_date_basis, created_by_site. Nulls encode as `~NULL~`. Numbers use normalised decimal text.
- `vendor_fingerprint` is separate: party_class, party_class_type, credit_days, vendor_extinct, vendor_name, slid.

## 6. Parquet schema

**Raw (`e1_open_items.parquet`, as extracted):** all columns above as strings (identity parts, text numbers and text dates exactly as Oracle returned them).

**Derived (`creditor_open_items.parquet`, written by staging, never by Oracle):**

| Column | Type |
|---|---|
| source_run_id, source_row_key, identity_k1_signature, row_fingerprint, vendor_fingerprint | string |
| as_of_date, document_date, due_date, ref_date, entry_date | date (nullable) plus a `*_raw` string |
| document_code, ledger_name, vendor_name, party_class, party_class_type, slid, document_no, document_type, document_initial, due_date_basis, ref_no, created_by_site, vendor_extinct | string |
| sub_ledger_code, ledger_code | string |
| credit_days | int (nullable) |
| drcr | string |
| amount, adjusted, pending | decimal(24,4), exact (null stays null) |
| document_age_days, overdue_days | int (nullable) |
| document_age_bucket, due_status, date_quality_status, classification_status | string |

**Manifest v2** (existing per-dataset keys stay): `manifest_version`, `contract_version = creditors-pilot-1.0`, `rules_version`, `as_of_date`, `scope` (source object, ledger codes, predicate text), per-dataset `role` (control_pre / extract / identity / control_post) and `query_hash`, `protocol` (step timestamps), `source_controls_pre` and `source_controls_post` (digests and full values), `expected_rows`, `hash_spec_version`. The validator, never the broker, writes a separate `validation_report.json` (every control, expected, actual, variance, verdict).

## 7. Reconciliation controls (₹0.00 tolerance, exact decimals)

Layers: **S** Oracle control query, **E** extract Parquet, **M** Postgres mart, **A** API, **U** UI (automated browser test reading rendered figures against the API payload; display rounding allowed only when raw values match exactly).

| # | Control | Dimensions | S | E | M | A | U |
|---|---|---|---|---|---|---|---|
| C1 | Row count | total, ledger x DR/CR | c1 | e1 | mart | API | UI |
| C2 | Credit exposure (sum of abs of Cr) | total, ledger | c1 | e1 | mart | API | UI |
| C3 | Debit balances (sum of abs of Dr) | total, ledger | c1 | e1 | mart | API | UI |
| C4 | Signed net | total, ledger | c1 | e1 | mart | API | UI |
| C5 | Document Age exposure | bucket x DR/CR; buckets sum to total | c1 (Oracle rules) | staging (Python rules) | mart | API | UI |
| C6 | Unclassified Document Age | rows and amount by date_quality_status | c1 | e1 | mart | API | UI |
| C7 | Due Status exposure | four states; states sum to total | c1 | e1 | mart | API | UI |
| C8 | Vendor count | distinct SLCODE: total, per ledger, per DR/CR | c2 | e1 | mart | API | UI |
| C9 | Ledger totals | ledger x DR/CR (rows and exposure) | c1 | e1 | mart | API | UI |
| C10 | Key integrity | distinct key = rows; K1 signature unique; no nulls | c3 | e1 | PK | n/a | n/a |
| C11 | File integrity | row count, sha256 vs manifest | n/a | manifest | load log | n/a | n/a |
| C12 | As-of | exactly one report date; the same `as_of_date` in every layer; no `CURRENT_DATE` in staging, API or React | c3 | e1 | mart | API | UI |

Two more gates: **pre = post** on all source controls, and **source = extract = mart = API = UI** on every row above. Any non-zero unexplained variance blocks publishing: the mart run is not promoted, and the UI shows "Reconciliation failed" instead of numbers.

**Baseline already observed twice (runs 002 and 004 agree exactly)** for the open scope: 12,233 rows; absolute ₹5,160,808,843.98; signed ₹-2,926,706,512.84; credit ₹4,043,757,678.41 (8,982 rows); debit ₹1,117,051,165.57 (3,251 rows). The first extract is expected to reproduce these to the paisa unless the cube has refreshed.

## 8. Proposed Postgres schema (design only, not created)

```sql
CREATE SCHEMA creditors_stg; CREATE SCHEMA creditors_mart;

CREATE TABLE creditors_stg.run (
  run_id text PRIMARY KEY, as_of_date date NOT NULL, contract_version text NOT NULL, rules_version text NOT NULL,
  manifest_sha256 text NOT NULL, loaded_at timestamptz NOT NULL DEFAULT now(),
  recon_status text NOT NULL CHECK (recon_status IN ('pending','passed','failed')),
  published boolean NOT NULL DEFAULT false);

CREATE TABLE creditors_stg.open_item_raw (       -- exactly what Oracle returned, as text
  run_id text NOT NULL REFERENCES creditors_stg.run, source_row_key text NOT NULL, payload jsonb NOT NULL,
  PRIMARY KEY (run_id, source_row_key));

CREATE TABLE creditors_mart.open_item (
  run_id text NOT NULL REFERENCES creditors_stg.run, source_row_key text NOT NULL, identity_k1_signature text NOT NULL,
  row_fingerprint text NOT NULL, vendor_fingerprint text NOT NULL, as_of_date date NOT NULL,
  document_code text NOT NULL, sub_ledger_code text NOT NULL, ledger_code text NOT NULL, ledger_name text,
  slid text, vendor_name text, party_class text, party_class_type text, credit_days int, vendor_extinct text,
  document_no text, document_type text, document_initial text, due_date_basis text, ref_no text, created_by_site text,
  document_date date, due_date date, ref_date date, entry_date date,
  drcr char(2) NOT NULL, amount numeric(24,4) NOT NULL, adjusted numeric(24,4), pending numeric(24,4) NOT NULL,
  document_age_days int, document_age_bucket text NOT NULL, overdue_days int,
  due_status text NOT NULL, date_quality_status text NOT NULL, classification_status text NOT NULL,
  PRIMARY KEY (run_id, source_row_key),
  UNIQUE (run_id, identity_k1_signature),
  CHECK (pending <> 0));

CREATE TABLE creditors_mart.identity_snapshot (   -- from e2: every key in the four ledgers, open or settled
  run_id text NOT NULL, source_row_key text NOT NULL, ledger_code text, drcr char(2), pending numeric(24,4), entry_date date,
  PRIMARY KEY (run_id, source_row_key));

CREATE TABLE creditors_mart.control_result (
  run_id text NOT NULL, control_id text NOT NULL, dimension text NOT NULL, layer text NOT NULL,
  expected numeric(30,4), actual numeric(30,4), variance numeric(30,4) GENERATED ALWAYS AS (actual - expected) STORED,
  verdict text NOT NULL, PRIMARY KEY (run_id, control_id, dimension, layer));

CREATE TABLE creditors_mart.item_movement (        -- stability evidence between two runs
  from_run_id text NOT NULL, to_run_id text NOT NULL, source_row_key text NOT NULL, movement text NOT NULL, detail jsonb,
  PRIMARY KEY (from_run_id, to_run_id, source_row_key));

CREATE VIEW creditors_mart.open_item_current AS      -- the API reads only this: latest published, fully reconciled run
  SELECT i.* FROM creditors_mart.open_item i JOIN creditors_stg.run r USING (run_id)
  WHERE r.published AND r.run_id = (SELECT run_id FROM creditors_stg.run WHERE published ORDER BY as_of_date DESC, loaded_at DESC LIMIT 1);
```
Runs are immutable and kept, so any as-of can be reconstructed. A run is published only if every control passed. The API gets only a read-only role on `open_item_current` and `control_result`.

## 9. Stability checks (the one thing the snapshot could not prove)

**Check 1, same-day repeat.** Run the full package a second time. Expected: identical key set, identical fingerprints, identical controls, all movements `persisted_unchanged`. Any difference means the extraction is not deterministic and blocks the pilot. If a cube refresh happened in between, it is reported and the run counts as check 2.

**Check 2, next cube refresh.** Compare the new run with the previous one using `e2` (all rows, open and settled) so every disappearance can be explained:

| Movement | Meaning | Explained? |
|---|---|---|
| `persisted_unchanged` | same key, same fingerprint | yes |
| `persisted_changed` | same key, fingerprint differs; field-level diff counted (PENDING / ADJUSTED expected; `LEDGER_CODE` / `DRCR` drift reported separately) | yes, except identity-attribute drift is flagged |
| `settled` | key now present with PENDING = 0 | yes |
| `new_posting` | new open key with `ENTRY_DATE` after the previous as-of date | yes |
| `reopened` | was settled, now open | reported |
| `vanished` | open before, absent from all rows now | **no** |
| `new_backdated` | new open key absent from the earlier all-rows snapshot and `ENTRY_DATE` on or before the previous as-of date | **no**, until classified (for example moved into scope by a ledger reclass) |

**Unexplained churn = `vanished` + `new_backdated` + duplicate-key violations. The gate is 0.** If the key proves unstable, K1 or an ordinal is revisited with this evidence, not before.

## 10. After approval: implementation order (not started)

1. `creditors_pilot_01` in `packages.py` with the tested SQL, plus guard, SQL-versus-Python rule equivalence, hash determinism and fixture-loader tests.
2. `broker.py plan` (dry run) for the review.
3. Staging transform and validator: Parquet to derived Parquet and `validation_report.json`, offline.
4. First controlled run (about 70 seconds, 8 queries), validation report reviewed with you.
5. Check 1; the mart load only after your review of the validation report.

## 11. Open items that need your decision

1. Approve extracting vendor names into the local extract, and the access rule for the mart (section 3).
2. Cap policy: 50,000 for `e1` (about 4x headroom) and 500,000 for `e2` (about 4.5x). Both are far above the current 12,233 and 110,092 rows.
3. `e2` (110,092 rows) is for stability evidence only and never feeds the mart's exposure figures. Confirm you want it in every run.
4. Document Age bucket boundaries as written (365 in 181-365, 0 in 0-30) and the 2000 to 2100 validity window for dates.
5. Treatment of the 11 non-supplier classes inside the ledgers (Staff, Landlord, SIS, TDS, Transporter, Others): included and flagged by `party_class` in this proposal.

## Appendix: proposed SQL (guard-checked offline)

#### `c1_source_control_pre`
```sql
SELECT TO_CHAR(ledger_code, 'TM9') AS ledger_code, drcr, doc_age_bucket, due_status, COUNT(*) AS item_rows, TO_CHAR(SUM(ABS(pending)), 'TM9') AS abs_pending, TO_CHAR(SUM(pending), 'TM9') AS signed_pending FROM (SELECT o.ledger_code AS ledger_code, o.drcr AS drcr, o.pending AS pending, CASE WHEN o.document_date IS NULL THEN 'UNCLASSIFIED_MISSING' WHEN o.document_date < DATE '2000-01-01' THEN 'UNCLASSIFIED_BEFORE_2000' WHEN TRUNC(o.document_date) > TRUNC(o.report_date) THEN 'UNCLASSIFIED_AFTER_AS_OF' WHEN TRUNC(o.report_date) - TRUNC(o.document_date) <= 30 THEN 'D0_30' WHEN TRUNC(o.report_date) - TRUNC(o.document_date) <= 60 THEN 'D31_60' WHEN TRUNC(o.report_date) - TRUNC(o.document_date) <= 90 THEN 'D61_90' WHEN TRUNC(o.report_date) - TRUNC(o.document_date) <= 180 THEN 'D91_180' WHEN TRUNC(o.report_date) - TRUNC(o.document_date) <= 365 THEN 'D181_365' ELSE 'D365_PLUS' END AS doc_age_bucket, CASE WHEN o.due_date IS NULL THEN 'DUE_UNAVAILABLE' WHEN o.due_date < DATE '2000-01-01' OR o.due_date > DATE '2100-12-31' OR o.due_date < o.document_date THEN 'DUE_INVALID' WHEN TRUNC(o.due_date) > TRUNC(o.report_date) THEN 'NOT_YET_DUE' ELSE 'PAST_DUE_OR_DUE_TODAY' END AS due_status FROM MISRETAIL."T$FINOTSD_533" o WHERE o.report_date >= DATE '2026-01-01' AND o.ledger_code IN (1000000026, 1000000024, 1000000092, 1000000025) AND o.pending <> 0) GROUP BY ledger_code, drcr, doc_age_bucket, due_status ORDER BY ledger_code, drcr, doc_age_bucket, due_status FETCH FIRST 1000 ROWS ONLY
```

#### `c2_vendor_control_pre`
```sql
SELECT GROUPING(o.ledger_code) AS g_ledger, GROUPING(o.drcr) AS g_drcr, TO_CHAR(o.ledger_code, 'TM9') AS ledger_code, o.drcr AS drcr, COUNT(DISTINCT o.sub_ledger_code) AS vendors, COUNT(*) AS item_rows FROM MISRETAIL."T$FINOTSD_533" o WHERE o.report_date >= DATE '2026-01-01' AND o.ledger_code IN (1000000026, 1000000024, 1000000092, 1000000025) AND o.pending <> 0 GROUP BY GROUPING SETS ((), (o.ledger_code), (o.drcr), (o.ledger_code, o.drcr)) ORDER BY g_ledger, g_drcr, ledger_code, drcr FETCH FIRST 100 ROWS ONLY
```

#### `c3_snapshot_control_pre`
```sql
SELECT COUNT(*) AS item_rows, COUNT(DISTINCT o.report_date) AS report_dates, TO_CHAR(MIN(o.report_date), 'YYYY-MM-DD') AS min_as_of, TO_CHAR(MAX(o.report_date), 'YYYY-MM-DD') AS max_as_of, COUNT(DISTINCT o.document_code || '|' || TO_CHAR(o.sub_ledger_code)) AS distinct_identity_keys, COUNT(DISTINCT o.document_code || '|' || TO_CHAR(o.ledger_code) || '|' || TO_CHAR(o.sub_ledger_code) || '|' || o.drcr) AS distinct_k1_keys, SUM(CASE WHEN o.document_code IS NULL OR o.sub_ledger_code IS NULL THEN 1 ELSE 0 END) AS null_identity_rows, SUM(CASE WHEN o.document_date IS NULL THEN 1 ELSE 0 END) AS null_document_date_rows, SUM(CASE WHEN o.due_date IS NULL THEN 1 ELSE 0 END) AS null_due_date_rows, SUM(CASE WHEN s.slcode IS NULL THEN 1 ELSE 0 END) AS rows_without_vendor_master, SUM(CASE WHEN l.glcode IS NULL THEN 1 ELSE 0 END) AS rows_without_ledger_master FROM MISRETAIL."T$FINOTSD_533" o LEFT JOIN MISRETAIL.LEDGER_MV l ON l.glcode = o.ledger_code LEFT JOIN MISRETAIL.SUB_LEDGER_MV s ON s.slcode = o.sub_ledger_code WHERE o.report_date >= DATE '2026-01-01' AND o.ledger_code IN (1000000026, 1000000024, 1000000092, 1000000025) AND o.pending <> 0 FETCH FIRST 2 ROWS ONLY
```

#### `e1_open_items`
```sql
SELECT TO_CHAR(o.report_date, 'YYYY-MM-DD') AS as_of_date, o.document_code AS document_code, TO_CHAR(o.sub_ledger_code, 'TM9') AS sub_ledger_code, TO_CHAR(o.ledger_code, 'TM9') AS ledger_code, l.glname AS ledger_name, s.slid AS slid, s.sl_name AS vendor_name, s.sl_class AS party_class, s.sl_class_type AS party_class_type, TO_CHAR(s.credit_days, 'TM9') AS credit_days, s.is_extinct AS vendor_extinct, o.document_no AS document_no, o.document_type AS document_type, o.document_initial AS document_initial, TO_CHAR(o.document_date, 'YYYY-MM-DD') AS document_date, TO_CHAR(o.due_date, 'YYYY-MM-DD') AS due_date, o.due_date_basis AS due_date_basis, o.ref_no AS ref_no, TO_CHAR(o.ref_date, 'YYYY-MM-DD') AS ref_date, TO_CHAR(o.entry_date, 'YYYY-MM-DD') AS entry_date, o.drcr AS drcr, TO_CHAR(o.amount, 'TM9') AS amount, TO_CHAR(o.adjusted, 'TM9') AS adjusted, TO_CHAR(o.pending, 'TM9') AS pending, o.created_by_site AS created_by_site FROM MISRETAIL."T$FINOTSD_533" o LEFT JOIN MISRETAIL.LEDGER_MV l ON l.glcode = o.ledger_code LEFT JOIN MISRETAIL.SUB_LEDGER_MV s ON s.slcode = o.sub_ledger_code WHERE o.report_date >= DATE '2026-01-01' AND o.ledger_code IN (1000000026, 1000000024, 1000000092, 1000000025) AND o.pending <> 0 ORDER BY o.document_code, o.sub_ledger_code FETCH FIRST 50000 ROWS ONLY
```

#### `e2_identity_all_rows`
```sql
SELECT o.document_code AS document_code, TO_CHAR(o.sub_ledger_code, 'TM9') AS sub_ledger_code, TO_CHAR(o.ledger_code, 'TM9') AS ledger_code, o.drcr AS drcr, TO_CHAR(o.pending, 'TM9') AS pending, TO_CHAR(o.entry_date, 'YYYY-MM-DD') AS entry_date, TO_CHAR(o.report_date, 'YYYY-MM-DD') AS as_of_date FROM MISRETAIL."T$FINOTSD_533" o WHERE o.report_date >= DATE '2026-01-01' AND o.ledger_code IN (1000000026, 1000000024, 1000000092, 1000000025) ORDER BY o.document_code, o.sub_ledger_code FETCH FIRST 500000 ROWS ONLY
```

`c1`, `c2` and `c3` appear once; the `_post` datasets reuse exactly the same text.
