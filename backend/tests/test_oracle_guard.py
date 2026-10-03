import pytest
from app.oracle.client import assert_read_only, UnsafeSQLError

@pytest.mark.parametrize("sql", ["SELECT 1 FROM dual", "with a as (select 1 x from dual) select * from a",
                                 "select 'DELETE me' from dual"])
def test_allows_reads(sql): assert_read_only(sql)

@pytest.mark.parametrize("sql", ["DELETE FROM t", "update t set a=1", "select 1 from dual; drop table t",
                                 "select * from t for update", "begin null; end;", "ALTER TABLE t ADD x NUMBER",
                                 "select 1 from dual /* x */ ; delete from t"])
def test_blocks_writes(sql):
    with pytest.raises(UnsafeSQLError): assert_read_only(sql)
