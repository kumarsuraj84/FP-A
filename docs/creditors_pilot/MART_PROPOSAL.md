# Creditors pilot: mart design proposal (nothing has been created or loaded)

Status: design gate. No Postgres connection was made, no DDL was run, no row was loaded, no Oracle call, no frontend change.
The DDL below has **not been executed anywhere**; its syntax is validated on a scratch database as the first step after approval.
Input being loaded later: the passed run `run_20261004_006` (staging validation PASSED, 414 of 414 controls, ₹0.00 variance).

## Amendment 1 (approved after the scratch UAT): six roles, `cred_promoter`

Publication is separated from administration. `cred_owner` is a schema, migration and retention identity (it runs `purge_run` and `set_policy`) and no routine workflow uses it.

| Role | Purpose |
|---|---|
| `cred_owner` | schema, migrations, retention (`purge_run`), policy. Cannot promote or roll back. |
| `cred_loader` | ingest one run, record source/extract/mart controls, `verify_run` |
| `cred_verifier` | read candidate runs (masked), record API/UI-layer controls through functions |
| **`cred_promoter`** | `promote_run` and `demote_to` only, plus `v_run_status`, `v_promotion_history`, `v_control_result_any_run`, `v_live_run`. No fact access, no DDL, no purge, no vendor names, cannot bypass controls (eligibility is enforced inside `promote_run`). |
| `cred_api_reader` | masked live views only |
| `cred_finance_reader` | the same plus the named view |

Masking is stricter than first proposed and is approved: broad viewers receive no vendor name, document code, document number, reference number, SLID or SLCODE. They get `vendor_ref` (pseudonym), `item_ref` and safe analytical attributes.

## 1. Fit with the existing finance mart

`backend/app/mart/schema.sql` (schema `fin`, proposed, frozen with the backend branch) uses an idempotent *upsert with tombstones* model (decision D-12). The Creditors pilot needs the opposite: immutable, versioned runs that can be compared and rolled back. So:

- The pilot gets its **own schema `cred`**. `fin` is not touched. There is no foreign key between them.
- On approval, record **D-24**: "Creditors pilot uses immutable run-versioned snapshots; D-12 still governs the generic `fin` path." Source identity (D-17) is kept: `run.source_object` plus the row key identify the source row.
- Existing least-privilege conventions are reused: `fpa_migrator` owns DDL, the app never has DDL, extensions are an admin bootstrap (none needed here: `sha256()` is built in since PostgreSQL 11; the local server is 18.6).

## 2. Decisions frozen by this proposal (your six, mapped)

| # | Your decision | How the design enforces it |
|---|---|---|
| 1 | Immutable runs, previous good run stays live | Every load gets its own `extraction_run_id` and its own rows. A one-row pointer table `live_run` names the live run. A failed load never touches the pointer. |
| 2 | No `DELETE ... INSERT latest` | No delete or update path exists on fact tables (triggers reject both, for every role including the owner). History is append-only. |
| 3 | Exact money | `NUMERIC(24,4)`, no floating point anywhere. Observed data has at most 2 decimals and at most 8 integer digits, so there is wide headroom while staying paise-exact. Control values use `NUMERIC(30,4)`. |
| 4 | Preserve raw and derived | Raw fields are stored as extracted (AMOUNT, ADJUSTED, PENDING, DRCR, DUE_DATE_BASIS, the four dates as both `date` and the exact source text). Derived fields sit beside them. Nothing is overwritten with a cleaned value. |
| 5 | Vendor identity | `document_code`, `sub_ledger_code`, `source_row_key`, `row_fingerprint` are on the item. Vendor attributes live in a separate table and are never part of identity. |
| 6 | Promotion gate | `promote_run()` refuses unless every control passed, all required layers are present, counts match and the run is `loaded` (section 7). |

## 3. Schema (`cred`)

```sql
CREATE SCHEMA cred AUTHORIZATION fpa_migrator;

-- one row per successfully loaded extraction; written once, never edited except `state` (via functions only)
CREATE TABLE cred.run (
  extraction_run_id      text PRIMARY KEY CHECK (extraction_run_id ~ '^run_[0-9]{8}_[0-9]{3}$'),
  as_of_date             date NOT NULL,                      -- the cube REPORT_DATE; one value per run
  package                text NOT NULL,
  contract_version       text NOT NULL,
  rules_version          text NOT NULL,
  hash_spec_version      text NOT NULL,
  rules                  jsonb NOT NULL,                     -- Document Age edges and the date validity window exactly as used
  source_object          text NOT NULL,
  scope_ledger_codes     text[] NOT NULL,
  manifest_sha256        char(64) NOT NULL UNIQUE,           -- the same extraction can never be loaded twice
  staging_report_sha256  char(64) NOT NULL,
  derived_parquet_sha256 char(64) NOT NULL,
  extract_started_at     timestamptz NOT NULL,               -- first pre-control
  extract_finished_at    timestamptz NOT NULL,               -- last post-control
  expected_rows          integer NOT NULL,                   -- from the source control, not from the data being loaded
  expected_identity_rows integer NOT NULL,
  loaded_at              timestamptz NOT NULL DEFAULT now(),
  loaded_by              text NOT NULL DEFAULT current_user,
  state                  text NOT NULL DEFAULT 'loaded' CHECK (state IN ('loaded','live','superseded','demoted')),
  UNIQUE (extraction_run_id, as_of_date)
);

-- vendor attributes per run, separate from the fact; the ONLY place vendor_name is stored
CREATE TABLE cred.vendor_snapshot (
  extraction_run_id  text NOT NULL REFERENCES cred.run,
  sub_ledger_code    text NOT NULL,
  slid               text,
  vendor_name        text,
  party_class        text,
  party_class_type   text,
  credit_days        integer,
  vendor_extinct     text,
  vendor_fingerprint char(64) NOT NULL CHECK (vendor_fingerprint ~ '^[0-9a-f]{64}$'),
  PRIMARY KEY (extraction_run_id, sub_ledger_code)
);

-- the fact: one row per open source item per run
CREATE TABLE cred.open_item (
  extraction_run_id     text NOT NULL,
  as_of_date            date NOT NULL,
  -- identity and change detection
  source_row_key        char(64) NOT NULL CHECK (source_row_key ~ '^[0-9a-f]{64}$'),
  identity_k1_signature char(64) NOT NULL CHECK (identity_k1_signature ~ '^[0-9a-f]{64}$'),   -- secondary control only
  row_fingerprint       char(64) NOT NULL CHECK (row_fingerprint ~ '^[0-9a-f]{64}$'),
  document_code         text NOT NULL,
  sub_ledger_code       text NOT NULL,
  -- raw source attributes (mutable, never overwritten)
  ledger_code           text NOT NULL,
  ledger_name           text,
  drcr                  char(2) NOT NULL CHECK (drcr IN ('Cr','Dr')),
  amount                numeric(24,4) NOT NULL,
  adjusted              numeric(24,4),
  pending               numeric(24,4) NOT NULL,
  document_no           text, document_type text, document_initial text, ref_no text, created_by_site text,
  due_date_basis        text,
  document_date date, due_date date, ref_date date, entry_date date,                    -- parsed; NULL only when missing or unparseable
  document_date_raw text, due_date_raw text, ref_date_raw text, entry_date_raw text,    -- exactly the text Oracle returned (keeps year 0202 etc.)
  -- derived (computed offline, rules_version recorded on the run)
  document_age_days     integer,
  document_age_bucket   text NOT NULL CHECK (document_age_bucket IN ('D0_30','D31_60','D61_90','D91_180','D181_365','D365_PLUS',
                          'UNCLASSIFIED_MISSING','UNCLASSIFIED_BEFORE_MIN','UNCLASSIFIED_AFTER_AS_OF','UNCLASSIFIED_UNPARSEABLE')),
  overdue_days          integer,
  due_status            text NOT NULL CHECK (due_status IN ('NOT_YET_DUE','PAST_DUE_OR_DUE_TODAY','DUE_UNAVAILABLE','DUE_INVALID')),
  date_quality_status   text NOT NULL CHECK (date_quality_status IN ('OK','MISSING','BEFORE_MIN','AFTER_AS_OF','UNPARSEABLE')),
  classification_status text NOT NULL CHECK (classification_status IN ('CREDIT_OUTSTANDING','CREDITOR_DEBIT_BALANCE_CLASSIFICATION_PENDING')),

  PRIMARY KEY (extraction_run_id, source_row_key),
  FOREIGN KEY (extraction_run_id, as_of_date) REFERENCES cred.run (extraction_run_id, as_of_date),
  FOREIGN KEY (extraction_run_id, sub_ledger_code) REFERENCES cred.vendor_snapshot (extraction_run_id, sub_ledger_code),
  UNIQUE (extraction_run_id, document_code, sub_ledger_code),          -- duplicate business key in a run is impossible
  UNIQUE (extraction_run_id, identity_k1_signature),
  CHECK (pending <> 0),
  CHECK ((drcr = 'Cr') = (pending < 0)),                               -- source sign convention
  CHECK (position('|' in document_code) = 0 AND position('|' in sub_ledger_code) = 0 AND document_code <> '' AND sub_ledger_code <> ''),
  -- the database re-derives the identity hashes, so a key that disagrees with its own identity parts cannot be stored
  CHECK (source_row_key = encode(sha256(convert_to('v1|' || document_code || '|' || sub_ledger_code, 'UTF8')), 'hex')),
  CHECK (identity_k1_signature = encode(sha256(convert_to('v1|' || document_code || '|' || ledger_code || '|' || sub_ledger_code || '|' || drcr, 'UTF8')), 'hex')),
  -- derived fields must agree with each other
  CHECK ((document_age_days IS NULL) = (document_age_bucket LIKE 'UNCLASSIFIED%')),
  CHECK ((document_age_bucket LIKE 'UNCLASSIFIED%') = (date_quality_status <> 'OK')),
  CHECK ((overdue_days IS NOT NULL) = (due_status = 'PAST_DUE_OR_DUE_TODAY')),
  CHECK ((classification_status = 'CREDIT_OUTSTANDING') = (drcr = 'Cr'))
);

-- every key in the four ledgers, open or settled: identity-stability evidence only; never feeds an exposure figure
CREATE TABLE cred.identity_snapshot (
  extraction_run_id text NOT NULL REFERENCES cred.run,
  source_row_key    char(64) NOT NULL CHECK (source_row_key ~ '^[0-9a-f]{64}$'),
  ledger_code       text NOT NULL,
  drcr              char(2) NOT NULL CHECK (drcr IN ('Cr','Dr')),
  pending           numeric(24,4) NOT NULL,
  entry_date_raw    text,
  PRIMARY KEY (extraction_run_id, source_row_key)
);

-- controls: the verdict is GENERATED, so it cannot be written or edited
CREATE TABLE cred.control_result (
  extraction_run_id text NOT NULL REFERENCES cred.run,
  control_id        text NOT NULL,                  -- C1..C12, M1..M12 (section 6)
  dimension         text NOT NULL,
  left_layer        text NOT NULL CHECK (left_layer  IN ('source','extract','mart','api','ui')),
  left_value        numeric(30,4) NOT NULL,
  right_layer       text NOT NULL CHECK (right_layer IN ('source','extract','mart','api','ui')),
  right_value       numeric(30,4) NOT NULL,
  variance          numeric(30,4) GENERATED ALWAYS AS (right_value - left_value) STORED,
  verdict           text GENERATED ALWAYS AS (CASE WHEN right_value = left_value THEN 'PASS' ELSE 'FAIL' END) STORED,
  recorded_at       timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (extraction_run_id, control_id, dimension, left_layer, right_layer)
);

-- loads that were refused: reasons and counts only, never row data or names
CREATE TABLE cred.load_rejection (
  rejection_id      bigserial PRIMARY KEY,
  extraction_run_id text NOT NULL,                   -- deliberately no FK: the run was not stored
  manifest_sha256   char(64),
  stage             text NOT NULL CHECK (stage IN ('precheck','staging_report','load','mart_controls','promotion')),
  reason            text NOT NULL,
  failed_controls   jsonb,
  attempted_at      timestamptz NOT NULL DEFAULT now(),
  attempted_by      text NOT NULL DEFAULT current_user
);

-- the live pointer (exactly one row) and the append-only promotion log
CREATE TABLE cred.live_run (
  singleton         boolean PRIMARY KEY DEFAULT true CHECK (singleton),
  extraction_run_id text NOT NULL REFERENCES cred.run,
  since             timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE cred.promotion (
  promotion_id      bigserial PRIMARY KEY,
  action            text NOT NULL CHECK (action IN ('promote','demote')),
  extraction_run_id text NOT NULL REFERENCES cred.run,
  previous_run_id   text REFERENCES cred.run,
  reason            text NOT NULL,
  at                timestamptz NOT NULL DEFAULT now(),
  by                text NOT NULL DEFAULT current_user
);
CREATE TABLE cred.policy (
  singleton         boolean PRIMARY KEY DEFAULT true CHECK (singleton),
  require_api_layer boolean NOT NULL DEFAULT true,   -- until the API layer is verified, nothing can be promoted
  changed_at        timestamptz NOT NULL DEFAULT now(),
  changed_by        text NOT NULL DEFAULT current_user
);
INSERT INTO cred.policy DEFAULT VALUES;
```

Immutability (applies to every role, including the owner):

```sql
CREATE FUNCTION cred.deny_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF current_setting('cred.retention', true) = 'on' AND TG_OP = 'DELETE' THEN RETURN OLD; END IF;   -- only cred.purge_run() sets this
  RAISE EXCEPTION '% on cred.% is not allowed: runs are immutable', TG_OP, TG_TABLE_NAME;
END $$;
CREATE TRIGGER no_mutation BEFORE UPDATE OR DELETE ON cred.open_item        FOR EACH ROW EXECUTE FUNCTION cred.deny_mutation();
-- the same trigger on vendor_snapshot, identity_snapshot, control_result, promotion, load_rejection
-- run: UPDATE allowed only when nothing but `state` changes (checked in the trigger), DELETE only via cred.purge_run()
```

## 4. Roles, grants and vendor-name handling

| Role | Can do | Cannot do |
|---|---|---|
| `fpa_migrator` | owns the schema and functions; applies DDL | runtime access from the app |
| `fpa_loader` | `INSERT` on the six load tables (one transaction per run); `EXECUTE cred.promote_run / demote_to`; `SELECT` on its own run for controls | any `UPDATE` / `DELETE`; DDL |
| `fpa_verifier` | `SELECT` on the run-parameterised views and `INSERT` api/ui layer rows into `control_result` | the live pointer, base tables |
| `fpa_api_reader` | `SELECT` on `v_live_run`, `v_open_item`, `v_exposure_summary`, `v_vendor_counts`, `v_live_controls` | base tables, `vendor_name`, `v_open_item_named` |
| `fpa_finance_reader` | the above plus `v_open_item_named` | writes |

Vendor names (approved for the local extract and mart):
- Stored **only** in `cred.vendor_snapshot.vendor_name`. They are not in `open_item`, `control_result`, `run`, `load_rejection`, the manifest, validation reports or any log.
- `v_open_item` (default API view) has no name column: it exposes `slid`, `party_class`, `credit_days` and the codes, so broader viewers get a restricted, still usable view. `v_open_item_named` adds `vendor_name` and is granted only to Finance, CFO and Admin roles.
- The loader uses bulk `COPY` and logs counts only. On the loader and API roles, statement and parameter logging is switched off (`log_statement = none` per role, `log_parameter_max_length = 0`) so a server log cannot capture names. A test asserts the loader writes no vendor name to its own log or reports.
- No name ever appears in screenshots meant for sharing or in any demo hosting. This stays a standing rule.
- Retention drops names with their run (section 11).

## 5. Load procedure (first load stops at state `loaded`)

Input: `data/inbox/<run>/staging/creditor_open_items.parquet`, `creditor_identity_snapshot.parquet`, `validation_report.json`, `manifest.json`.

Pre-checks (no database write; a failure is recorded in `load_rejection` at stage `precheck` / `staging_report`):
1. The manifest validates and every dataset is `ok`; the staging report verdict is `PASSED`; hashes in the manifest and report match the files on disk.
2. The run id is not already loaded. The same `manifest_sha256` under the same id is a no-op that reports "already loaded"; a different hash under an existing id is refused.

One transaction (`BEGIN` ... `COMMIT`), bulk `COPY` from the Parquet:
3. Insert `run` (`state = 'loaded'` is only set at commit by the transaction's success), `vendor_snapshot` (distinct vendor per run; a vendor with conflicting attributes within the run fails control M6), `open_item`, `identity_snapshot`.
4. Insert the source to extract controls taken from the validated report (re-derived from the Parquet, not trusted from the report file alone), then compute extract to mart controls in SQL (section 6) and insert them.
5. If **any** control or constraint fails: `ROLLBACK`. Nothing is stored. The loader then writes one `load_rejection` row (stage, reason and failed control ids and counts only) in a separate transaction.
6. `COMMIT` only when every control passed. The run is visible in the base tables but is **not live**: promotion is a separate gate.

Because of the single transaction there are no half-loaded runs and no cleanup step.

## 6. Mart controls

Source to extract controls come from `validation_report.json` (C1–C12, 414 rows in the first run). New **mart** controls, each stored as `control_result` rows (left = extract, right = mart) at ₹0.00 / zero-row tolerance:

| Id | Control | Failure means |
|---|---|---|
| M-C1…C9 | every C1–C9 dimension recomputed in SQL: rows, credit, debit, signed, bucket × Dr/Cr, Unclassified by reason, Due Status, ledger × Dr/Cr, vendors | the mart differs from the extract |
| M1 | `count(*)` = `expected_rows` from the source control | rows lost or added |
| M2 | **duplicate business key within the run** = 0 (`GROUP BY document_code, sub_ledger_code HAVING count(*) > 1`) | your first extra control |
| M3 | **same `source_row_key` with conflicting identity attributes** = 0 (more than one distinct `(document_code, sub_ledger_code)` per key) | your second extra control |
| M4 | rows whose key or K1 signature is not re-derivable from the identity parts = 0 | key corruption (also enforced by CHECK) |
| M5 | duplicate K1 signature = 0 | secondary uniqueness |
| M6 | vendor attribute conflicts within a run = 0; items without a vendor row = 0 | broken vendor link |
| M7 | sign or open-state violations (`Cr` positive, `pending = 0`) = 0 | wrong source scope |
| M8 | `identity_snapshot` open keys = `open_item` keys; row count = `expected_identity_rows` | e1 / e2 disagree |
| M9 | single `as_of_date` in every table and equal to `run.as_of_date` | mixed snapshots |
| M10 | derived-field consistency violations = 0 (age/quality/overdue/classification) | rule bug |
| M11 | `scale(pending) <= 2` count (informational, never a gate) | sub-paise values appearing |
| M12 | row counts of the loaded tables equal the Parquet row counts | partial COPY |

API-layer rows (`left = mart`, `right = api`) are added by `fpa_verifier` before promotion; UI-layer rows (`api` to `ui`) after promotion.

## 7. Promotion, the live pointer and rollback

```sql
CREATE FUNCTION cred.promote_run(p_run text, p_reason text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = cred, pg_temp AS $$
DECLARE r cred.run%ROWTYPE; prev text; prev_asof date; fails int; n bigint;
BEGIN
  SELECT * INTO r FROM cred.run WHERE extraction_run_id = p_run FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'run % does not exist', p_run; END IF;
  IF r.state <> 'loaded' THEN RAISE EXCEPTION 'run % is % and cannot be promoted', p_run, r.state; END IF;
  SELECT count(*) INTO fails FROM cred.control_result WHERE extraction_run_id = p_run AND verdict <> 'PASS';
  IF fails > 0 THEN RAISE EXCEPTION 'run %: % control(s) failed', p_run, fails; END IF;
  -- every required layer must have recorded passing controls
  IF NOT EXISTS (SELECT 1 FROM cred.control_result WHERE extraction_run_id = p_run AND left_layer = 'source'  AND right_layer = 'extract')
     OR NOT EXISTS (SELECT 1 FROM cred.control_result WHERE extraction_run_id = p_run AND left_layer = 'extract' AND right_layer = 'mart')
  THEN RAISE EXCEPTION 'run %: source/extract/mart controls are missing', p_run; END IF;
  IF (SELECT require_api_layer FROM cred.policy) AND NOT EXISTS
     (SELECT 1 FROM cred.control_result WHERE extraction_run_id = p_run AND left_layer = 'mart' AND right_layer = 'api')
  THEN RAISE EXCEPTION 'run %: API-layer controls are missing', p_run; END IF;
  SELECT count(*) INTO n FROM cred.open_item WHERE extraction_run_id = p_run;
  IF n <> r.expected_rows THEN RAISE EXCEPTION 'run %: % rows loaded, % expected', p_run, n, r.expected_rows; END IF;
  SELECT l.extraction_run_id, x.as_of_date INTO prev, prev_asof FROM cred.live_run l JOIN cred.run x USING (extraction_run_id);
  IF prev IS NOT NULL AND r.as_of_date < prev_asof THEN RAISE EXCEPTION 'older as_of_date than the live run: use demote_to'; END IF;
  INSERT INTO cred.live_run (extraction_run_id) VALUES (p_run)
    ON CONFLICT (singleton) DO UPDATE SET extraction_run_id = EXCLUDED.extraction_run_id, since = now();
  IF prev IS NOT NULL THEN UPDATE cred.run SET state = 'superseded' WHERE extraction_run_id = prev; END IF;
  UPDATE cred.run SET state = 'live' WHERE extraction_run_id = p_run;
  INSERT INTO cred.promotion (action, extraction_run_id, previous_run_id, reason) VALUES ('promote', p_run, prev, p_reason);
END $$;
```

- **Gate:** state `loaded`; zero failed controls; source, extract, mart (and, while `require_api_layer`, API) controls all present; loaded rows equal the source-control count; not older than the live run. The default policy `require_api_layer = true` means **the first run cannot be promoted until the API layer exists**, which matches your "do not connect the frontend yet".
- **Nothing partial:** the promotion is one transaction, so the pointer, the state change and the log row land together or not at all.
- **Rollback:** `cred.demote_to(p_previous_run, p_reason)` moves the pointer back to an earlier run that was `live` before and is still retained, marks the withdrawn run `demoted` (it can never be promoted again), and logs it. No row is deleted. A failed load needs no rollback beyond the transaction; the previous run was never touched.
- **UI layer (decision needed when the UI connects):** UI checks run after promotion; a failure triggers an automatic `demote_to` the previous run. The alternative is a candidate preview in the UI before promotion. Not decided now.

## 8. Failure behaviour

| Situation | Outcome |
|---|---|
| Pre or post source control differ (cube refreshed) | rejected at staging; never reaches the database |
| Duplicate business key, key conflict, key not re-derivable | CHECK / UNIQUE violation or M2–M4: transaction rolled back, `load_rejection` row |
| Any C or M control with non-zero variance | rolled back, rejection row listing control ids and counts |
| Cap hit, capped or failed dataset | rejected at staging |
| Same manifest loaded again | no-op, "already loaded" |
| Same run id with different content | refused |
| Promotion with failing or missing controls | `promote_run` raises; pointer unchanged |
| Process killed mid-load | transaction never commits; nothing stored |
| New run fails | the previous live run stays live, untouched |

## 9. API-facing views

All views read through `live_run`, so the API can only ever see the one promoted run.

| View | Rows | Notes |
|---|---|---|
| `cred.v_live_run` | 1 | as-of date, run id, rules and contract versions, counts: the figures the UI header needs |
| `cred.v_open_item` | open items | all item columns plus `slid`, `party_class`, `party_class_type`, `credit_days`, `vendor_extinct`; **no vendor name** |
| `cred.v_open_item_named` | open items | the same plus `vendor_name`; Finance, CFO, Admin only |
| `cred.v_exposure_summary` | grouped | ledger × Dr/Cr × Document Age × Due Status × party class: rows, credit exposure, debit balance, signed net as separate measures (never one netted figure) |
| `cred.v_vendor_counts` | grouped | distinct vendors: total, per ledger, per Dr/Cr (not additive, so computed in the view) |
| `cred.v_live_controls` | controls | the live run's controls, so the API and UI can display and re-check reconciliation |
| `cred.v_open_item_any_run` and `cred.v_exposure_summary_any_run` | by run id | `fpa_verifier` only, for API-layer checks before promotion |

Measures stay split: **credit outstanding**, **creditor debit balance (classification pending)** and **signed net**. No view returns one blended "creditors" number. Top-strip semantics and the presentation of Document Age versus Due Status are deliberately **not frozen here**; they wait for the API contract review.

## 10. Indexes

Primary keys already give `(run, source_row_key)`. Added, all leading with the run id:

```sql
CREATE INDEX ON cred.open_item (extraction_run_id, ledger_code, drcr);
CREATE INDEX ON cred.open_item (extraction_run_id, document_age_bucket, drcr);
CREATE INDEX ON cred.open_item (extraction_run_id, due_status, drcr);
CREATE INDEX ON cred.open_item (extraction_run_id, sub_ledger_code);          -- vendor drill (also the FK)
CREATE INDEX ON cred.vendor_snapshot (extraction_run_id, party_class);
CREATE INDEX ON cred.control_result (extraction_run_id, verdict) WHERE verdict <> 'PASS';
CREATE INDEX ON cred.promotion (extraction_run_id, at DESC);
```

Sizing: about 12,233 item rows per run (roughly 7 MB) and 110,092 identity rows (roughly 13 MB). Daily runs are about 2.6 GB a year for items, so no partitioning is needed. Revisit if rows pass 50 million. `ANALYZE` runs after every load.

## 11. Retention

| Data | Kept |
|---|---|
| `run`, `open_item`, `vendor_snapshot`, `control_result` | every run for 13 months; then month-end and fiscal-year-end runs indefinitely; the live run and the last promoted run are never purged |
| `identity_snapshot` | the latest 14 runs plus month-end runs; stability evidence only |
| `promotion`, `load_rejection` | 24 months (small) |
| Parquet and manifest archives | not in the database; kept at least as long as the item data, with sha256 recorded on the run |

Purging is by whole run through `cred.purge_run()` (the only code path that may delete; it sets the retention flag, checks the run is neither live nor the last promoted, and logs). Purging a run also removes the vendor names stored with it. Numbers are proposals for your approval.

## 12. The first load, after approval (stops again)

1. A DBA (or you) provisions the roles and an empty database or schema. Passwords are never in the repository. I do not have DDL rights and will not use them.
2. Apply the DDL on a **scratch** database first to validate syntax and constraints, with tests against synthetic data (every failure case in section 8).
3. Apply to the pilot database with `fpa_migrator`.
4. Load `run_20261004_006` as `fpa_loader`: one transaction, controls as above.
5. Report the mart controls (row counts, credit, debit, signed net, ledger, Document Age, Due Status, vendors, key checks M1–M12). The run stays state `loaded`, not live, with no API and no frontend connection.

## 13. Decisions I need from you

1. **Which PostgreSQL database hosts the pilot mart?** A server is running locally (PostgreSQL 18.6) and `backend/.env` has a `DATABASE_URL`; I have not connected or read its value. Please confirm the database and who creates the roles.
2. **Role set** from section 4 (loader, verifier, API reader, Finance reader) and the per-role logging settings.
3. **Policy default `require_api_layer = true`**, meaning the first run cannot be promoted until API-layer controls exist.
4. **Retention numbers** in section 11.
5. **Masking rule** for non-authorised viewers: no name, but the SLID, party class and codes stay visible.
6. **UI-layer verification** (post-promotion with automatic demotion, or a candidate preview): can wait until the UI connects.
