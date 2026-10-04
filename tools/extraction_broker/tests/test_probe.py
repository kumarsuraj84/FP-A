import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import guard  # noqa: E402
from packages import AGEING_PROBE_01, PACKAGES  # noqa: E402

TAIL = " FETCH FIRST 100 ROWS ONLY"


def test_master_kind_allows_small_reference_tables_with_named_columns_only():
    ok = "SELECT glcode, glname FROM MISRETAIL.LEDGER_MV" + TAIL
    assert guard.check(ok, "master").row_cap == 100
    with pytest.raises(guard.GuardError, match="name its columns"):
        guard.check("SELECT * FROM MISRETAIL.LEDGER_MV" + TAIL, "master")
    with pytest.raises(guard.GuardError, match="ceiling"):
        guard.check("SELECT glcode FROM MISRETAIL.LEDGER_MV FETCH FIRST 100001 ROWS ONLY", "master")
    with pytest.raises(guard.GuardError, match="MISRETAIL-qualified"):
        guard.check("SELECT glcode FROM LEDGER_MV" + TAIL, "master")
    with pytest.raises(guard.GuardError, match="out of scope"):
        guard.check("SELECT glcode FROM SSRK.FINGL" + TAIL, "master")


@pytest.mark.parametrize(
    "col",
    ["sl_billing_address", "addr", "billing_phone_1", "ph1", "email", "sl_billing_email_1", "mobile_no", "agent_mobile_no", "pan_no", "contact_person", "billing_fax", "customername", "customer_gstin_no", "pin"],
)
def test_personal_and_contact_columns_are_never_extracted(col):
    for kind, sql in (
        ("master", f"SELECT slcode, {col} FROM MISRETAIL.SUB_LEDGER_MV" + TAIL),
        ("sample", f"SELECT slcode, {col} FROM MISRETAIL.SUB_LEDGER_MV" + TAIL),
        ("extract", f"SELECT slcode, {col} FROM MISRETAIL.T1 WHERE d >= DATE '2026-01-01'" + TAIL),
    ):
        with pytest.raises(guard.GuardError, match="personal / contact data"):
            guard.check(sql, kind)


def test_business_columns_are_not_mistaken_for_personal_ones():
    ok = "SELECT slcode, slid, sl_name, sl_alias, credit_days, credit_limit, is_extinct FROM MISRETAIL.SUB_LEDGER_MV" + TAIL
    assert guard.check(ok, "master")


def test_the_probe_package_is_registered_and_passes_the_guard():
    assert "ageing_probe_01" in PACKAGES
    for d in AGEING_PROBE_01:
        c = guard.check(d.sql, d.kind)
        assert c.kind == d.kind


def test_every_probe_reads_only_the_533_cube_or_the_two_masters():
    for d in AGEING_PROBE_01:
        up = d.sql.upper()
        assert "SSRK" not in up and "PUBLIC" not in up and "FINPOST" not in up, d.name
        if d.kind == "master":
            assert ("MISRETAIL.LEDGER_MV" in up) != ("MISRETAIL.SUB_LEDGER_MV" in up), d.name
        else:
            assert up.count('MISRETAIL."T$FINOTSD_533"') >= 1 and "637" not in up, d.name
            assert "T$FINOTSD_637" not in up


def test_probes_are_bounded_aggregates_or_a_tiny_named_sample():
    kinds = {d.name: d.kind for d in AGEING_PROBE_01}
    sample = next(d for d in AGEING_PROBE_01 if d.name == "p08_sample_50")
    assert guard.check(sample.sql, "sample").row_cap == 50
    assert "*" not in sample.sql  # no wide SELECT *
    wanted = {
        "document_date", "due_date", "ref_date", "entry_date", "due_date_basis", "no_of_days_base_on_entry_date",
        "no_of_days_base_on_ref_date", "amount", "adjusted", "pending", "drcr", "ledger_code", "sub_ledger_code",
    }
    cols = {c.strip() for c in sample.sql.lower().split("select")[1].split(" from ")[0].split(",")}
    assert cols == wanted, "the sample contains exactly the requested columns"
    for d in AGEING_PROBE_01:
        if kinds[d.name] == "extract":
            assert "REPORT_DATE >= DATE" in d.sql.upper(), f"{d.name}: date-bounded"
    # single-row aggregates use cap 2 so a genuine 1-row result is 'ok', never 'capped'
    for name in ("p03_null_counts_and_ranges", "p05_day_count_consistency"):
        d = next(x for x in AGEING_PROBE_01 if x.name == name)
        assert guard.check(d.sql, d.kind).row_cap == 2


def test_the_probe_collects_the_evidence_the_questions_need():
    sql = {d.name: d.sql.lower() for d in AGEING_PROBE_01}
    assert "group by due_date_basis" in sql["p02_due_date_basis"]
    for c in ("document_date", "due_date", "ref_date", "entry_date"):
        assert f"count({c})" in sql["p03_null_counts_and_ranges"]
    assert "group by drcr" in sql["p04_drcr_distribution"]
    for c in ("no_of_days_base_on_entry_date", "no_of_days_base_on_ref_date"):
        assert c in sql["p03_null_counts_and_ranges"] and c in sql["p05_day_count_consistency"]
    # day-count columns are tested against both as-on dates and all four candidate dates
    assert sql["p05_day_count_consistency"].count("sum(case when") == 16
    assert "sub_ledger_code" in sql["p07_vendor_due_terms"] and "due_date_basis" in sql["p07_vendor_due_terms"]
    assert "credit_days" in sql["m02_sub_ledger_mv"] and "slcode" in sql["m02_sub_ledger_mv"] and "slid" in sql["m02_sub_ledger_mv"]
    # nothing in the masters can identify a person
    for d in AGEING_PROBE_01:
        if d.kind == "master":
            for bad in ("addr", "phone", "email", "mobile", "pan_no", "contact", "fax", "billing_"):
                assert bad not in d.sql.lower(), (d.name, bad)


def test_every_alias_fits_oracle_12_1s_30_character_identifier_limit():
    import re

    for d in AGEING_PROBE_01:
        for alias in re.findall(r"(?i)\bAS\s+([a-z_][a-z0-9_$#]*)", d.sql):
            assert len(alias) <= 30, f"{d.name}: alias '{alias}' is {len(alias)} characters"


def test_sampled_status_is_only_for_samples(tmp_path):
    import json

    import manifest as mf
    import pyarrow as pa
    import pyarrow.parquet as pq

    pq.write_table(pa.table({"A": [1, 2]}), tmp_path / "d.parquet")
    f = tmp_path / "d.parquet"
    e = {
        "dataset": "d", "kind": "sample", "source_object": "X", "logical_source": None, "copy_id": None, "query_id": 1,
        "query_hash": "a" * 64, "extracted_at": "t", "row_count": 2, "row_cap": 2, "min_date": None, "max_date": None,
        "file_name": "d.parquet", "file_size": f.stat().st_size, "sha256": mf.sha256_file(f), "status": "sampled",
    }
    m = {"run_id": "r", "package": "p", "created_at": "t", "broker_version": "1", "datasets": [e]}
    mf.write_manifest(tmp_path, m)
    v = mf.validate_manifest(tmp_path)
    assert v.ok and v.loadable == ["d"] and not v.warnings
    e["kind"] = "metadata"
    mf.write_manifest(tmp_path, m)
    assert any("only a 'sample' dataset" in x for x in mf.validate_manifest(tmp_path).errors)
    assert json.loads((tmp_path / "manifest.json").read_text())["datasets"][0]["status"] == "sampled"
