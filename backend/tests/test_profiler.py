import math
import pytest
from app.discovery import profiler as P
from app.registry.models import PhysicalObject, SHARED_DISCRIMINATOR

T = P.Target("MISRETAIL", "T$FINREGSITE_844")
def null_scans(o): return o.count(lambda s: s.startswith("SELECT COUNT(*) AS n, COUNT("))
def table_scans(o): return o.count(lambda s: "FROM \"MISRETAIL\"" in s)

def test_light_default_does_not_scan_for_counts(fake):
    o = fake(); p = P.profile_light(o, T)
    assert p["aggregates"] is None and p["estimated_rows"] == 1000
    assert table_scans(o) == 1        # only the bounded sample touches the table
    assert null_scans(o) == 0

def test_light_with_all_aggregates_is_one_scan_plus_sample(fake):
    o = fake(); p = P.profile_light(o, T, date_col="D", debit_col="DR", credit_col="CR", distinct_cols=("SITECODE", "GL"))
    assert table_scans(o) == 2        # 1 aggregate + 1 sample
    assert p["aggregates"]["DISTINCT_SITECODE"] == 7 and p["aggregates"]["DISTINCT_GL"] == 3
    assert null_scans(o) == 0

def test_light_query_budget(fake):
    o = fake(); P.profile_light(o, T, date_col="D", debit_col="DR", credit_col="CR", distinct_cols=("A", "B", "C"))
    assert len(o.calls) <= 5          # columns, stats, aggregate, sample

@pytest.mark.parametrize("ncols", [1, 36, 100, 101, 250])
def test_deep_null_profile_is_never_one_scan_per_column(fake, ncols):
    o = fake(ncols=ncols); p = P.profile_deep(o, T)
    expected = math.ceil(ncols / P.DEEP_NULL_CHUNK)
    assert null_scans(o) == expected and p["null_passes"] == expected
    if ncols > 3: assert null_scans(o) < ncols
    assert len(p["null_rate"]) == ncols

def test_deep_36_columns_is_single_null_pass(fake):
    o = fake(ncols=36); P.profile_deep(o, T); assert null_scans(o) == 1

def test_deep_null_rates_computed(fake):
    o = fake(ncols=3, total=200, nulls=50); p = P.profile_deep(o, T)
    assert p["null_rate"]["COL1"] == 0.25 and p["exact_rows"] == 200

def test_light_never_issues_null_counts(fake):
    o = fake(ncols=200); P.profile_light(o, T, exact_count=True); assert null_scans(o) == 0

def test_shared_discriminator_filter_is_bound_not_interpolated(fake):
    t = P.Target.from_physical(PhysicalObject("M", "T_ALL", "TABLE", SHARED_DISCRIMINATOR, "CUBE_ID", "844'; DROP"))
    o = fake(); P.profile_light(o, t, date_col="D")
    agg_sql, binds = [c for c in o.calls if "MIN(" in c[0]][0]
    assert ':disc' in agg_sql and "DROP" not in agg_sql and binds == {"disc": "844'; DROP"}

def test_separate_object_has_no_where(fake):
    o = fake(); P.profile_light(o, T, date_col="D")
    assert "WHERE" not in [c for c in o.calls if "MIN(" in c[0]][0][0]

def test_unsafe_column_names_rejected(fake):
    with pytest.raises(ValueError): P.profile_light(fake(), T, date_col='D"; DROP TABLE X--')
    with pytest.raises(ValueError): P.profile_light(fake(), T, sample_order_by="a b")

def test_sample_determinism_flag(fake):
    assert P.profile_light(fake(), T, sample_order_by="ENTRY_DATE")["sample_deterministic"] is True
    assert P.profile_light(fake(), T)["sample_deterministic"] is False

def test_all_generated_sql_passes_read_only_guard(fake):
    from app.oracle.client import assert_read_only
    o = fake(); P.profile_deep(o, T, date_col="D", debit_col="DR", credit_col="CR", distinct_cols=("A",), sample_order_by="D")
    for sql, _ in o.calls: assert_read_only(sql)
