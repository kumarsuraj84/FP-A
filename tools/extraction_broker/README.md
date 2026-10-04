# FP&A extraction broker

```
MISRETAIL DW → Inventory Automation SELECT-only extractor → Parquet + manifest → FP&A inbox
```

FP&A never connects to Oracle and never reads, copies, decrypts or logs a credential. The broker talks only to the
running Inventory Automation app on `localhost`, asks it to run guarded SELECTs on its own existing connection, and
copies the Parquet it produces into `data/inbox/run_<date>_<nnn>/` with a `manifest.json` that FP&A validates before
loading anything. The inbox is git-ignored (real data).

**Scope is MISRETAIL only.** SSRK is live production and out of scope; the guard rejects it, any other schema, and
`PUBLIC` synonyms (which resolve to SSRK objects).

## Commands (run with the system Python 3.11, which has pyarrow)

```
python tools/extraction_broker/broker.py plan   discovery_01        # guard report; sends nothing
python tools/extraction_broker/broker.py run    discovery_01        # backs up platform.db, then extracts
python tools/extraction_broker/broker.py run    discovery_01 --only d01_finance_objects,d04_columns
python tools/extraction_broker/broker.py verify data/inbox/run_YYYYMMDD_NNN
python tools/extraction_broker/analyze.py       data/inbox/run_YYYYMMDD_NNN   # structural report (UNVERIFIED)
python -m pytest tools/extraction_broker/tests -q
```

The Inventory Automation app must be running (`localhost:4001`).

## The guard (`guard.py`)

The app validates SQL only when a query is *saved*; its engine does not re-check at run time. So the broker checks
every statement first, and more strictly:

- single `SELECT`/`WITH`; no DML, DDL, PL/SQL, `EXECUTE`, locking, `FOR UPDATE`, `INTO`, packages (`DBMS_*`, `UTL_*`), db-links
- MISRETAIL only: metadata queries must restrict to owner `'MISRETAIL'`; data objects must be `MISRETAIL`-qualified
- every query must END with `FETCH FIRST n ROWS ONLY`, within a ceiling per kind (metadata 300k, sample 1k, extract 5M);
  an inner cap never stands in for a cap on the whole result
- an `extract` must be bounded by a date predicate and name its columns
- no blind `COUNT(*)` on finance objects: row estimates come from `ALL_TABLES` statistics

## What it changes in Inventory Automation

Only `queries`/run/audit rows for names starting `FPA__` (immutable, hash-suffixed). `platform.db` is backed up first
(SQLite online backup, integrity-checked). Existing queries, connections, schedules and behaviour are untouched.

## Manifest (`manifest.py`)

Per dataset: `dataset, kind, source_object, logical_source, copy_id, query_id, query_hash, extracted_at, row_count,
row_cap, min_date, max_date, file_name, file_size, sha256, status`. `status` is `ok`, `capped` (row cap reached: may be
incomplete), `failed`, `skipped`. `validate_manifest` checks presence, size, sha256, row counts and cap consistency;
missing dates stay `null`, never zero.
