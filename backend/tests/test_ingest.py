from dataclasses import replace
from datetime import date
from decimal import Decimal as D
from pathlib import Path
import pytest
from app.ingest.identity import SourceRowIdentity, scope_of
from app.ingest.promotion import FactStore, Staging
from app.registry.models import PhysicalObject, SourceEntry, PhysicalUnresolvedError

def entry(copy, obj):
    return SourceEntry("SITE_REG", "CUBE$FINREGSITE", copy, None, date(2024, 4, 1), date(2025, 3, 31), status="CONFIRMED",
                       physical=PhysicalObject("MISRETAIL", obj, "TABLE"))
E24, E25 = entry("874", "T$FINREGSITE_874"), entry("902", "T$FINREGSITE_902")
def ident(e, k): return SourceRowIdentity.for_row(e, k)
def row(dr="100.00", cr="0"): return {"debit": dr, "credit": cr}

def test_same_key_same_source_is_same_identity(): assert ident(E24, "1") == ident(E24, "1")
def test_same_key_different_annual_copy_is_different_identity(): assert ident(E24, "1") != ident(E25, "1")
def test_unresolved_entry_cannot_build_identity():
    with pytest.raises(PhysicalUnresolvedError): SourceRowIdentity.for_row(replace(E24, status="UNVERIFIED"), "1")
def test_empty_key_rejected():
    with pytest.raises(ValueError): ident(E24, " ")

def test_same_key_same_source_duplicate_within_batch_rejected():
    with pytest.raises(ValueError): FactStore().promote("b1", [(ident(E24, "1"), row()), (ident(E24, "1"), row())])
def test_same_key_different_copy_both_kept_no_cross_copy_dedupe():
    f = FactStore(); r = f.promote("b1", [(ident(E24, "1"), row("100")), (ident(E25, "1"), row("100"))])
    assert r["inserted"] == 2 and f.total("debit") == D(200)

def test_rerun_same_batch_is_idempotent():
    f = FactStore(); items = [(ident(E24, str(i)), row("10")) for i in range(5)]
    f.promote("b1", items); r = f.promote("b1", items)
    assert r == {"inserted": 0, "updated": 0, "unchanged": 5, "tombstoned": 0, "revived": 0} and f.total("debit") == D(50)
def test_new_batch_same_data_does_not_double_count():
    f = FactStore(); items = [(ident(E24, "1"), row("10"))]
    f.promote("b1", items); f.promote("b2", items); assert f.total("debit") == D(10)
def test_changed_row_updates_not_duplicates():
    f = FactStore(); f.promote("b1", [(ident(E24, "1"), row("10"))])
    r = f.promote("b2", [(ident(E24, "1"), row("12"))]); assert r["updated"] == 1 and f.total("debit") == D(12)
def test_full_refresh_tombstones_missing_rows_only_in_same_scope():
    f = FactStore(); a, b, other = ident(E25, "1"), ident(E25, "2"), ident(E24, "1")
    f.promote("b1", [(a, row("5")), (b, row("5")), (other, row("7"))])
    scope = scope_of(E25)
    r = f.promote("b2", [(a, row("5"))], full_refresh_scope=scope)
    assert r["tombstoned"] == 1 and f.total("debit") == D(12)       # b excluded; other-copy row untouched
def test_tombstoned_row_revives_when_it_returns():
    f = FactStore(); a = ident(E25, "1"); scope = scope_of(E25)
    f.promote("b1", [(a, row("5"))]); f.promote("b2", [], full_refresh_scope=scope)
    assert f.total("debit") == 0; r = f.promote("b3", [(a, row("5"))]); assert r["revived"] == 1 and f.total("debit") == D(5)

def test_staging_is_append_only_snapshot_history():
    s = Staging(); i = ident(E24, "1")
    assert s.append("b1", [(i, row("1"))]) == 1
    assert s.append("b1", [(i, row("1"))]) == 0      # same batch: no-op
    assert s.append("b2", [(i, row("1"))]) == 1      # new batch: history retained
    assert len(s.rows) == 2

SHARED = SourceEntry("MOP", "CUBE$BILLCOLL", "X1", None, date(2026, 4, 1), date(2027, 3, 31), status="CONFIRMED",
                     physical=PhysicalObject("MISRETAIL", "CUBE$BILLCOLL", "TABLE", "SHARED_DISCRIMINATOR", "CUBENAME", "SYN_A"))
SHARED2 = replace(SHARED, copy_id="X2", physical=PhysicalObject("MISRETAIL", "CUBE$BILLCOLL", "TABLE", "SHARED_DISCRIMINATOR", "CUBENAME", "SYN_B"))

def test_identity_convention_object_name_only_and_discriminator_fields():
    i = ident(E24, "9")
    assert (i.source_owner, i.source_object, i.source_copy_id) == ("MISRETAIL", "T$FINREGSITE_874", "874")
    assert (i.source_discriminator_column, i.source_discriminator_value) == ("", "")
    j = SourceRowIdentity.for_row(SHARED, "9")
    assert (j.source_object, j.source_discriminator_column, j.source_discriminator_value) == ("CUBE$BILLCOLL", "CUBENAME", "SYN_A")
def test_shared_object_different_discriminator_values_are_different_sources():
    assert SourceRowIdentity.for_row(SHARED, "1") != SourceRowIdentity.for_row(SHARED2, "1")
    f = FactStore(); r = f.promote("b", [(SourceRowIdentity.for_row(SHARED, "1"), row("3")), (SourceRowIdentity.for_row(SHARED2, "1"), row("3"))])
    assert r["inserted"] == 2
def test_none_discriminator_rejected_and_pairing_enforced():
    with pytest.raises(ValueError): SourceRowIdentity("s", "o", "t", "c", None, None, "k")
    with pytest.raises(ValueError): SourceRowIdentity("s", "o", "t", "c", "COL", "", "k")
def test_tombstone_scope_includes_discriminator():
    f = FactStore(); a, b = SourceRowIdentity.for_row(SHARED, "1"), SourceRowIdentity.for_row(SHARED2, "1")
    f.promote("b1", [(a, row("5")), (b, row("5"))])
    r = f.promote("b2", [], full_refresh_scope=scope_of(SHARED))     # empties only SYN_A, same physical object
    assert r["tombstoned"] == 1 and f.total("debit") == D(5)
def test_full_refresh_batch_with_foreign_rows_rejected():
    with pytest.raises(ValueError): FactStore().promote("b", [(ident(E24, "1"), row())], full_refresh_scope=scope_of(E25))

IDCOLS = "source_system, source_owner, source_object, source_copy_id,"
def test_ddl_uses_full_source_identity_in_staging_and_fact():
    ddl = (Path(__file__).resolve().parents[1] / "app/mart/schema.sql").read_text()
    uniq = "UNIQUE (source_system, source_owner, source_object, source_copy_id,\n          source_discriminator_column, source_discriminator_value, source_row_key"
    assert ddl.count(uniq) == 2                      # staging (+ batch id) and fact
    assert "source_row_key, extract_batch_id)" in ddl
    assert "UNIQUE (source_object, source_row_key)" not in ddl
    assert ddl.count("source_discriminator_column TEXT NOT NULL DEFAULT ''") == 2   # '' sentinel, not NULL
    assert "canonical_txn_key" in ddl
def test_python_identity_fields_match_ddl_columns():
    import re
    from app.ingest.identity import SCOPE_FIELDS
    ddl = (Path(__file__).resolve().parents[1] / "app/mart/schema.sql").read_text()
    fact = ddl[ddl.index("CREATE TABLE fin.fact_finance_entry"):]
    for f in (*SCOPE_FIELDS, "source_row_key"): assert re.search(rf"\b{f}\b", fact), f
def test_btree_gist_is_prerequisite_not_created_by_schema():
    d = Path(__file__).resolve().parents[1] / "app/mart"
    ddl = (d / "schema.sql").read_text()
    assert "CREATE EXTENSION" not in ddl and "no_double_coverage" in ddl
    assert "pg_extension" in ddl and "RAISE EXCEPTION" in ddl                     # fails fast with clear message
    assert "CREATE EXTENSION IF NOT EXISTS btree_gist" in (d / "bootstrap_admin.sql").read_text()
