import pytest
from app.identifiers import ident, quote
from app.oracle.client import assert_read_only, UnsafeSQLError

@pytest.mark.parametrize("sql", ["SELECT 1 FROM dual", "with a as (select 1 x from dual) select * from a",
                                 "select 'DELETE me' from dual", "select created from all_objects"])
def test_allows_reads(sql): assert_read_only(sql)

@pytest.mark.parametrize("sql", ["DELETE FROM t", "update t set a=1", "select 1 from dual; drop table t",
                                 "select * from t for update", "begin null; end;", "ALTER TABLE t ADD x NUMBER",
                                 "select 1 from dual /* x */ ; delete from t", "MERGE INTO t USING s ON (1=1) WHEN MATCHED THEN UPDATE SET a=1",
                                 "insert into t values (1)", "select 1 from dual where 1 = (call f())"])
def test_blocks_writes(sql):
    with pytest.raises(UnsafeSQLError): assert_read_only(sql)

def test_guard_is_secondary_documented():
    # A SELECT can still call a function with side effects; only a SELECT-only grant stops that.
    # This test pins the limitation so nobody mistakes the regex for the security boundary.
    assert_read_only("select some_pkg.side_effect_fn() from dual")

@pytest.mark.parametrize("good", ["T$FINREGSITE_844", "MISRETAIL", "A_B#1"])
def test_ident_accepts(good): assert ident(good) == good
@pytest.mark.parametrize("bad", ['x"; drop', "a b", "1abc", "", "a;b", "a--b", 'a"b', None])
def test_ident_rejects(bad):
    with pytest.raises(ValueError): ident(bad)
def test_quote(): assert quote("T$X") == '"T$X"'
