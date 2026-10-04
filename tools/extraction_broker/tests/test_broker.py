import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import guard  # noqa: E402
import manifest as mf  # noqa: E402
from packages import DISCOVERY_01, HEADER_COLUMNS, cube_copy_tables  # noqa: E402

CAP = " FETCH FIRST 100 ROWS ONLY"
META = "SELECT owner, object_name FROM all_objects WHERE owner = 'MISRETAIL'" + CAP


# ───────────── safety ─────────────


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO t VALUES (1)",
        "UPDATE t SET a = 1",
        "DELETE FROM t",
        "MERGE INTO t USING s ON (1=1) WHEN MATCHED THEN UPDATE SET a=1",
        "DROP TABLE t",
        "ALTER TABLE t ADD c NUMBER",
        "CREATE TABLE t (a NUMBER)",
        "TRUNCATE TABLE t",
        "GRANT SELECT ON t TO u",
        "BEGIN NULL; END;",
        "DECLARE x NUMBER; BEGIN NULL; END;",
        "CALL some_proc()",
        "EXECUTE IMMEDIATE 'x'",
        "SELECT dbms_random.value FROM all_objects WHERE owner = 'MISRETAIL'" + CAP,
        "SELECT utl_http.request('x') FROM all_objects WHERE owner = 'MISRETAIL'" + CAP,
        "SELECT * FROM all_objects WHERE owner = 'MISRETAIL' FOR UPDATE" + CAP,
        "LOCK TABLE t IN EXCLUSIVE MODE",
        "SELECT a INTO b FROM all_objects WHERE owner = 'MISRETAIL'" + CAP,
        "SELECT * FROM all_objects@remote_db WHERE owner = 'MISRETAIL'" + CAP,
        META + "; DROP TABLE t",
        META + "; " + META,
        "EXPLAIN PLAN FOR SELECT 1 FROM dual",
        "",
    ],
)
def test_guard_rejects_unsafe_statements(sql):
    with pytest.raises(guard.GuardError):
        guard.check(sql, "metadata")


def test_guard_ignores_keywords_inside_literals_and_column_names():
    ok = "SELECT owner, created, last_ddl_time, delete_rule FROM all_constraints WHERE owner = 'MISRETAIL' AND constraint_name = 'DELETE THIS UPDATE' " + CAP
    assert guard.check(ok, "metadata").row_cap == 100


# ───────────── scope: MISRETAIL only, SSRK is live production ─────────────


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT owner, object_name FROM all_objects WHERE owner = 'SSRK'" + CAP,
        "SELECT owner, object_name FROM all_objects WHERE owner IN ('MISRETAIL', 'SSRK')" + CAP,
        "SELECT owner, object_name FROM all_objects WHERE owner = 'MISRETAIL' OR owner = 'GINARCHIVE'" + CAP,
        "SELECT owner, object_name FROM all_objects WHERE owner = 'REPORT'" + CAP,
        "SELECT owner, object_name FROM all_objects WHERE owner = 'SYS'" + CAP,
        "SELECT owner, object_name FROM all_objects WHERE object_name = 'X' AND owner = 'ssrk'" + CAP,
    ],
)
def test_other_schemas_are_out_of_scope_even_inside_a_literal(sql):
    with pytest.raises(guard.GuardError, match="out of scope"):
        guard.check(sql, "metadata")


def test_a_metadata_query_must_name_misretail():
    with pytest.raises(guard.GuardError, match="restrict itself to owner 'MISRETAIL'"):
        guard.check("SELECT owner, object_name FROM all_objects" + CAP, "metadata")  # all owners: not allowed
    with pytest.raises(guard.GuardError, match="restrict itself"):
        guard.check("SELECT owner, object_name FROM all_objects WHERE object_type = 'TABLE'" + CAP, "metadata")


SAMPLE_OK = "SELECT cube_code FROM MISRETAIL.T$FINREGSITE_844 FETCH FIRST 5 ROWS ONLY"


def test_data_objects_must_be_misretail_qualified_and_public_synonyms_are_rejected():
    assert guard.check(SAMPLE_OK, "sample").row_cap == 5
    assert guard.check('SELECT a FROM MISRETAIL."T$X_1" FETCH FIRST 5 ROWS ONLY', "sample")
    with pytest.raises(guard.GuardError, match="MISRETAIL-qualified"):
        guard.check("SELECT cube_code FROM T$FINREGSITE_844 FETCH FIRST 5 ROWS ONLY", "sample")  # could resolve via a synonym
    with pytest.raises(guard.GuardError, match="out of scope"):
        guard.check("SELECT postcode FROM PUBLIC.FINPOST FETCH FIRST 5 ROWS ONLY", "sample")
    with pytest.raises(guard.GuardError, match="out of scope"):
        guard.check("SELECT postcode FROM SSRK.FINPOST FETCH FIRST 5 ROWS ONLY", "sample")
    with pytest.raises(guard.GuardError, match="MISRETAIL-qualified"):
        guard.check("SELECT a FROM MISRETAIL.T1 t JOIN other_table o ON o.id = t.id FETCH FIRST 5 ROWS ONLY", "sample")


# ───────────── performance: the cap is the OUTERMOST final clause ─────────────


def test_every_query_needs_a_trailing_hard_row_cap_within_its_ceiling():
    with pytest.raises(guard.GuardError, match="END with a hard row cap"):
        guard.check("SELECT owner FROM all_objects WHERE owner = 'MISRETAIL'", "metadata")
    with pytest.raises(guard.GuardError, match="END with a hard row cap"):
        guard.check("SELECT owner FROM all_objects WHERE owner = 'MISRETAIL' AND ROWNUM <= 50", "metadata")  # ROWNUM is no longer enough
    with pytest.raises(guard.GuardError, match="ceiling"):
        guard.check("SELECT owner FROM all_objects WHERE owner = 'MISRETAIL' FETCH FIRST 9999999 ROWS ONLY", "metadata")
    assert guard.check(META, "metadata").row_cap == 100


def test_an_inner_cap_cannot_stand_in_for_a_cap_on_the_whole_result():
    # one row per branch is fine, but without a final cap the UNION itself is unbounded
    inner_only = (
        "SELECT * FROM (SELECT a FROM MISRETAIL.T1 FETCH FIRST 1 ROWS ONLY) UNION ALL "
        "SELECT * FROM (SELECT a FROM MISRETAIL.T2 FETCH FIRST 1 ROWS ONLY)"
    )
    with pytest.raises(guard.GuardError, match="END with a hard row cap"):
        guard.check(inner_only, "sample")
    wrapped = f"SELECT * FROM ({inner_only}) FETCH FIRST 500 ROWS ONLY"
    assert guard.check(wrapped, "sample").row_cap == 500  # the outermost cap is what counts, not the inner 1s
    too_big = f"SELECT * FROM ({inner_only}) FETCH FIRST 5000 ROWS ONLY"
    with pytest.raises(guard.GuardError, match="ceiling"):
        guard.check(too_big, "sample")


def test_kinds_are_enforced():
    with pytest.raises(guard.GuardError, match="dictionary"):
        guard.check("SELECT a FROM MISRETAIL.my_table" + CAP, "metadata")
    with pytest.raises(guard.GuardError, match="data objects"):
        guard.check(META, "sample")
    with pytest.raises(guard.GuardError, match="unknown query kind"):
        guard.check(META, "bulk")
    with pytest.raises(guard.GuardError, match="ceiling"):
        guard.check("SELECT a FROM MISRETAIL.my_table FETCH FIRST 5000 ROWS ONLY", "sample")


def test_an_extract_must_be_date_bounded_and_name_its_columns():
    unbounded = "SELECT a, b FROM MISRETAIL.fin_t FETCH FIRST 1000 ROWS ONLY"
    with pytest.raises(guard.GuardError, match="bounded"):
        guard.check(unbounded, "extract")
    star = "SELECT * FROM MISRETAIL.fin_t WHERE voucher_date >= DATE '2026-04-01' FETCH FIRST 1000 ROWS ONLY"
    with pytest.raises(guard.GuardError, match="name its columns"):
        guard.check(star, "extract")
    good = "SELECT a, b FROM MISRETAIL.fin_t WHERE voucher_date >= DATE '2026-04-01' AND voucher_date < DATE '2026-05-01' FETCH FIRST 1000 ROWS ONLY"
    assert guard.check(good, "extract").kind == "extract"
    assert guard.check("SELECT a FROM MISRETAIL.fin_t WHERE d BETWEEN :d1 AND :d2 FETCH FIRST 10 ROWS ONLY", "extract")


def test_query_hash_ignores_whitespace_comments_and_case():
    a = guard.query_hash("SELECT  owner\nFROM all_objects -- note\n FETCH FIRST 5 ROWS ONLY;")
    b = guard.query_hash("select owner from ALL_OBJECTS /* x */ fetch first 5 rows only")
    assert a == b and len(a) == 64
    assert a != guard.query_hash("select owner from all_tables fetch first 5 rows only")


# ───────────── the package ─────────────


def test_the_whole_discovery_package_passes_the_guard_and_never_leaves_misretail():
    for d in DISCOVERY_01:
        if d.sql:
            c = guard.check(d.sql, d.kind)
            assert c.kind == "metadata"
            up = d.sql.upper()
            assert "SSRK" not in up and "GINARCHIVE" not in up and "PUBLIC" not in up, d.name
            assert "'MISRETAIL'" in up, d.name
            assert "count(" not in d.sql.lower(), f"{d.name}: no COUNT on finance objects"
    assert [d.name for d in DISCOVERY_01 if d.sql is None] == ["d12_cube_copy_headers"]
    assert not any("owners_overview" in d.name or "registry" in d.name for d in DISCOVERY_01)


def _prev(tables, with_header=True):
    objs = [{"OWNER": "MISRETAIL", "OBJECT_NAME": t, "OBJECT_TYPE": "TABLE"} for t in tables]
    cols = []
    for t in tables:
        for c in HEADER_COLUMNS if with_header else ("SEQ",):
            cols.append({"OWNER": "MISRETAIL", "TABLE_NAME": t, "COLUMN_NAME": c})
    return {"d01_finance_objects": objs, "d04_columns": cols}


def test_cube_header_query_is_built_from_the_warehouse_catalog_and_still_guarded():
    d = next(x for x in DISCOVERY_01 if x.name == "d12_cube_copy_headers")
    sql = d.build(_prev(["T$FINREGSITE_844", "T$FINOTSD_637", "T$BILLCOLL_871"]))
    assert guard.check(sql, "sample").row_cap == 500
    assert sql.count("FETCH FIRST 1 ROWS ONLY") == 3  # one row per copy
    assert 'MISRETAIL."T$FINREGSITE_844"' in sql and "SSRK" not in sql
    assert "COUNT" not in sql.upper()


def test_cube_header_query_only_covers_cube_copies_that_expose_the_header_columns():
    prev = _prev(["T$FINREGSITE_844"])
    prev["d01_finance_objects"] += [
        {"OWNER": "MISRETAIL", "OBJECT_NAME": "T_FINANCE_MOP_OUTPUT", "OBJECT_TYPE": "TABLE"},  # not a cube copy
        {"OWNER": "MISRETAIL", "OBJECT_NAME": "T$FINREGSITE_0", "OBJECT_TYPE": "TABLE"},  # a copy, but no columns known
        {"OWNER": "MISRETAIL", "OBJECT_NAME": "CUBE$FINREGSITE", "OBJECT_TYPE": "VIEW"},
        {"OWNER": "SSRK", "OBJECT_NAME": "T$FINREGSITE_999", "OBJECT_TYPE": "TABLE"},  # other schema: ignored
    ]
    assert cube_copy_tables(prev) == ["T$FINREGSITE_844"]


def test_cube_header_builder_fails_safe_and_ignores_hostile_names():
    d = next(x for x in DISCOVERY_01 if x.name == "d12_cube_copy_headers")
    with pytest.raises(LookupError):
        d.build({"d01_finance_objects": [], "d04_columns": []})
    with pytest.raises(LookupError):
        d.build(_prev(["T$FINREGSITE_1; DROP TABLE x"]))  # does not match the cube-copy name pattern
    with pytest.raises(LookupError):
        d.build(_prev(["T$FINREGSITE_844"], with_header=False))


def test_a_large_estate_is_capped_at_80_probe_tables():
    assert len(cube_copy_tables(_prev([f"T$FINOTSD_{i}" for i in range(300)]))) == 80


# ───────────── manifest ─────────────


def _run(tmp_path, rows=3, cap=100, status="ok"):
    import pyarrow as pa
    import pyarrow.parquet as pq

    pq.write_table(pa.table({"OWNER": ["A"] * rows}), tmp_path / "d.parquet")
    f = tmp_path / "d.parquet"
    entry = {
        "dataset": "d", "kind": "metadata", "source_object": "ALL_OBJECTS", "logical_source": None, "copy_id": None,
        "query_id": 1, "query_hash": "a" * 64, "extracted_at": "2026-10-04T00:00:00+00:00", "row_count": rows,
        "row_cap": cap, "min_date": None, "max_date": None, "file_name": "d.parquet", "file_size": f.stat().st_size,
        "sha256": mf.sha256_file(f), "status": status,
    }
    m = {"run_id": "r", "package": "p", "created_at": "t", "broker_version": "1", "datasets": [entry]}
    mf.write_manifest(tmp_path, m)
    return m, entry


def test_a_good_run_validates(tmp_path):
    _run(tmp_path)
    v = mf.validate_manifest(tmp_path)
    assert v.ok and v.loadable == ["d"]


def test_tampering_and_inconsistency_are_caught(tmp_path):
    m, e = _run(tmp_path)
    (tmp_path / "d.parquet").write_bytes((tmp_path / "d.parquet").read_bytes() + b"x")
    assert not mf.validate_manifest(tmp_path).ok  # size / hash differ

    m, e = _run(tmp_path)
    e["row_count"] = 4
    mf.write_manifest(tmp_path, m)
    assert any("manifest says 4 rows" in x for x in mf.validate_manifest(tmp_path).errors)

    m, e = _run(tmp_path)
    e["file_name"] = "../outside.parquet"
    mf.write_manifest(tmp_path, m)
    assert any("plain file name" in x for x in mf.validate_manifest(tmp_path).errors)

    m, e = _run(tmp_path)
    del e["query_hash"]
    mf.write_manifest(tmp_path, m)
    assert any("missing keys" in x for x in mf.validate_manifest(tmp_path).errors)

    assert not mf.validate_manifest(tmp_path / "nowhere").ok


def test_a_capped_run_is_loadable_but_flagged_and_ok_cannot_hide_a_cap_hit(tmp_path):
    _run(tmp_path, rows=3, cap=3, status="capped")
    v = mf.validate_manifest(tmp_path)
    assert v.ok and any("row cap reached" in w for w in v.warnings)
    _run(tmp_path, rows=3, cap=3, status="ok")
    assert any("should be 'capped'" in x for x in mf.validate_manifest(tmp_path).errors)


def test_failed_datasets_are_never_loadable_and_empty_is_not_missing(tmp_path):
    m, e = _run(tmp_path)
    e["status"] = "failed"
    mf.write_manifest(tmp_path, m)
    v = mf.validate_manifest(tmp_path)
    assert v.loadable == [] and any("not loadable" in w for w in v.warnings)
    _run(tmp_path, rows=0)
    v = mf.validate_manifest(tmp_path)
    assert v.ok and any("zero rows" in w for w in v.warnings)
    assert json.loads((tmp_path / "manifest.json").read_text())["datasets"][0]["min_date"] is None
