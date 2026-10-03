from dataclasses import replace
from datetime import date
from decimal import Decimal as D
from pathlib import Path
import pytest
from app.ingest.identity import SourceRowIdentity
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
    scope = ("ORACLE_GINESYS", "MISRETAIL", "MISRETAIL.T$FINREGSITE_902", "902")
    r = f.promote("b2", [(a, row("5"))], full_refresh_scope=scope)
    assert r["tombstoned"] == 1 and f.total("debit") == D(12)       # b excluded; other-copy row untouched
def test_tombstoned_row_revives_when_it_returns():
    f = FactStore(); a = ident(E25, "1"); scope = ("ORACLE_GINESYS", "MISRETAIL", "MISRETAIL.T$FINREGSITE_902", "902")
    f.promote("b1", [(a, row("5"))]); f.promote("b2", [], full_refresh_scope=scope)
    assert f.total("debit") == 0; r = f.promote("b3", [(a, row("5"))]); assert r["revived"] == 1 and f.total("debit") == D(5)

def test_staging_is_append_only_snapshot_history():
    s = Staging(); i = ident(E24, "1")
    assert s.append("b1", [(i, row("1"))]) == 1
    assert s.append("b1", [(i, row("1"))]) == 0      # same batch: no-op
    assert s.append("b2", [(i, row("1"))]) == 1      # new batch: history retained
    assert len(s.rows) == 2

def test_ddl_uses_full_source_identity_not_object_plus_key():
    ddl = (Path(__file__).resolve().parents[1] / "app/mart/schema.sql").read_text()
    assert "UNIQUE (source_system, source_owner, source_object, source_copy_id, source_row_key)" in ddl
    assert "UNIQUE (source_object, source_row_key)" not in ddl
    assert "source_row_key, extract_batch_id)" in ddl
    assert "canonical_txn_key" in ddl
