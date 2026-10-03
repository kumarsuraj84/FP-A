import pytest
from app.discovery import keys as K
from app.discovery import profiler as P
from app.discovery.runner import classify
from app.oracle.client import assert_read_only
from app.registry.models import PhysicalObject, SHARED_DISCRIMINATOR


class KeyOra:
    def __init__(self, cons=(), idx=(), cols=(("A", "N"), ("B", "N")), otype="TABLE"):
        self.cons, self.idx, self.cols, self.otype, self.calls = cons, idx, cols, otype, []
    def query(self, sql, params=None):
        self.calls.append(sql); s = " ".join(sql.split())
        if "FROM all_objects" in s: return [{"OBJECT_TYPE": self.otype}] if self.otype else []
        if "FROM all_tab_columns" in s: return [{"COLUMN_NAME": c, "NULLABLE": n} for c, n in self.cols]
        if "FROM all_constraints" in s: return list(self.cons)
        if "FROM all_indexes" in s: return list(self.idx)
        raise AssertionError(s)

def con(name, typ, col, pos, st="ENABLED", val="VALIDATED"): return {"CNAME": name, "CTYPE": typ, "CSTATUS": st, "CVALIDATED": val, "COL": col, "POS": pos}
def ix(name, uniq, col, pos, st="VALID"): return {"INAME": name, "UNIQ": uniq, "ISTATUS": st, "COL": col, "POS": pos}


def test_primary_key_is_strong_and_composite_order_follows_position():
    o = KeyOra(cons=[con("PK1", "P", "B", 2), con("PK1", "P", "A", 1)])    # rows deliberately out of order
    r = K.discover_keys(o, "M", "T")
    assert r["recommendation"] == K.STRONG and r["candidates"][0]["columns"] == ["A", "B"]
    assert r["candidates"][0]["sources"] == [{"kind": "PRIMARY_KEY", "name": "PK1"}]
    assert "NOT a final source_row_key" in r["note"]

def test_nullable_columns_reported_and_make_candidate_weak():
    o = KeyOra(cons=[con("U1", "U", "A", 1)], cols=(("A", "Y"),))
    r = K.discover_keys(o, "M", "T")
    c = r["candidates"][0]
    assert r["recommendation"] == K.WEAK and c["nullable_columns"] == ["A"] and any("nullable" in x for x in c["reasons"])

def test_pk_and_unique_index_on_same_columns_merge():
    o = KeyOra(cons=[con("PK1", "P", "A", 1)], idx=[ix("PK1_IX", "UNIQUE", "A", 1)])
    r = K.discover_keys(o, "M", "T")
    assert len(r["candidates"]) == 1 and {s["kind"] for s in r["candidates"][0]["sources"]} == {"PRIMARY_KEY", "UNIQUE_INDEX"}

def test_disabled_constraint_and_unusable_index_are_weak():
    assert K.discover_keys(KeyOra(cons=[con("PK1", "P", "A", 1, st="DISABLED")]), "M", "T")["recommendation"] == K.WEAK
    assert K.discover_keys(KeyOra(idx=[ix("I", "UNIQUE", "A", 1, st="UNUSABLE")]), "M", "T")["recommendation"] == K.WEAK

def test_function_based_index_column_is_weak():
    r = K.discover_keys(KeyOra(idx=[ix("I", "UNIQUE", "SYS_NC0001$", 1)], cols=()), "M", "T")
    assert r["recommendation"] == K.WEAK and any("expression" in x for x in r["candidates"][0]["reasons"])

def test_non_unique_index_is_not_a_candidate_but_listed():
    r = K.discover_keys(KeyOra(idx=[ix("I", "NONUNIQUE", "A", 1)]), "M", "T")
    assert r["recommendation"] == K.NONE and r["other_non_unique_indexes"] == [{"index": "I", "columns": ["A"]}]
    assert "visibility" in r["note"]

def test_view_noted_and_missing_object_raises():
    assert "VIEW" in K.discover_keys(KeyOra(otype="VIEW"), "M", "V")["note"]
    with pytest.raises(LookupError): K.discover_keys(KeyOra(otype=None), "M", "GHOST")

def test_shared_object_reports_discriminator_inclusion():
    o = KeyOra(cons=[con("PK1", "P", "CUBENAME", 1), con("PK1", "P", "ID", 2)], cols=(("CUBENAME", "N"), ("ID", "N")))
    r = K.discover_keys(o, "M", "T", discriminator_column="CUBENAME")
    assert r["candidates"][0]["includes_discriminator"] is True and "Shared object" in r["note"]

def test_discover_keys_is_metadata_only_no_row_scans():
    o = KeyOra(cons=[con("PK1", "P", "A", 1)], idx=[ix("I", "UNIQUE", "B", 1)])
    K.discover_keys(o, "M", "T")
    assert o.calls and all(classify(q) == "METADATA" for q in o.calls)
    for q in o.calls:
        assert_read_only(q); assert "FETCH FIRST" not in q and "COUNT(" not in q.upper()
    assert len(o.calls) == 4        # object type, columns, constraints, indexes


# ---------------- profile_group ----------------
class GOra:
    def __init__(self, n=3): self.n, self.calls = n, []
    def query(self, sql, params=None):
        self.calls.append((sql, params))
        return [{"GRP": f"S{i}", "N": 10 - i, "DEBIT": 1, "CREDIT": 2} for i in range(self.n)]

T = P.Target("MISRETAIL", "T$FINREGSITE_844")

def test_group_is_one_query_one_dimension_bounded():
    o = GOra(); r = P.profile_group(o, T, "RELEASE_STATUS", debit_col="DR", credit_col="CR")
    assert len(o.calls) == 1
    sql = o.calls[0][0]
    assert sql.count("GROUP BY") == 1 and "FETCH FIRST 101 ROWS ONLY" in sql and "SUM(" in sql and r["truncated"] is False
    assert classify(sql) == "DATA_AGGREGATE"
    assert_read_only(sql)

def test_group_truncation_flag_and_cap():
    o = GOra(n=101); r = P.profile_group(o, T, "C")
    assert r["truncated"] is True and len(r["groups"]) == 100

@pytest.mark.parametrize("bad", ["A, B", 'A"; DROP', "A B", ["A", "B"], None, ""])
def test_group_rejects_multi_or_unsafe_columns(bad):
    o = GOra()
    with pytest.raises(ValueError): P.profile_group(o, T, bad)
    assert o.calls == []

def test_group_unsafe_sum_columns_rejected():
    with pytest.raises(ValueError): P.profile_group(GOra(), T, "C", debit_col="x y")

def test_group_applies_discriminator_as_bind():
    t = P.Target.from_physical(PhysicalObject("M", "T_ALL", "TABLE", SHARED_DISCRIMINATOR, "CUBENAME", "V' OR '1'='1"))
    o = GOra(); P.profile_group(o, t, "REL")
    sql, binds = o.calls[0]
    assert 'WHERE "CUBENAME" = :disc' in sql and "OR '1'='1" not in sql and binds == {"disc": "V' OR '1'='1"}

def test_classify_kinds():
    assert classify("SELECT x FROM all_tab_columns WHERE a = :o") == "METADATA"
    assert classify("SELECT 1 AS ok FROM dual") == "METADATA"
    assert classify('SELECT COUNT(*) AS n FROM "M"."T"') == "DATA_AGGREGATE"
    assert classify('SELECT * FROM "M"."T" FETCH FIRST 5 ROWS ONLY') == "DATA_SAMPLE"
    assert classify('SELECT "C" AS grp, COUNT(*) AS n FROM "M"."T" GROUP BY "C" FETCH FIRST 101 ROWS ONLY') == "DATA_AGGREGATE"
    assert classify("SELECT a FROM all_constraints c JOIN all_cons_columns cc ON 1=1") == "METADATA"
    assert classify('SELECT a FROM all_objects o JOIN "M"."T" t ON 1=1') != "METADATA"
