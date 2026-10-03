from dataclasses import replace
from datetime import date
from pathlib import Path
import json
import pytest
from app.registry.models import (SourceEntry, PhysicalObject, PhysicalUnresolvedError,
                                 SEPARATE_OBJECT, SHARED_DISCRIMINATOR)
from app.registry.resolver import (load_seed, resolve, validate_no_double_coverage, OverlapError, fy_of,
                                   apply_overlay, find)

SEED = Path(__file__).resolve().parents[2] / "config" / "source_registry_seed.csv"


def e(copy, a, b, auth=True, **kw):
    return SourceEntry("SITE_REG", "CUBE$FINREGSITE", copy, None, date.fromisoformat(a), date.fromisoformat(b),
                       authoritative=auth, **kw)


def test_seed_has_no_double_coverage(): validate_no_double_coverage(load_seed(SEED))
def test_seed_is_entirely_unverified_with_no_physical_objects():
    s = load_seed(SEED)
    assert all(x.status == "UNVERIFIED" and x.physical is None for x in s)
def test_hints_only_where_prior_docs_gave_them():
    hints = {x.copy_id: x.physical_hint for x in load_seed(SEED) if x.physical_hint}
    assert hints == {"844": "MISRETAIL.T$FINREGSITE_844", "902": "MISRETAIL.T$FINREGSITE_902"}
def test_resolve_by_date_not_hardcode():
    s = load_seed(SEED)
    assert resolve(s, "SITE_REG", date(2026, 4, 1)).copy_id == "844"
    assert resolve(s, "SITE_REG", date(2026, 3, 31)).copy_id == "902"
def test_copy_ids_need_not_be_chronological():   # 548 sits in FY23-24; ordering carries no meaning
    assert resolve(load_seed(SEED), "SITE_REG", date(2023, 6, 1)).copy_id == "548"
def test_all_years_plus_yearly_copy_is_rejected():
    with pytest.raises(OverlapError):
        validate_no_double_coverage([e("877", "2023-04-01", "2026-03-31"), e("874", "2024-04-01", "2025-03-31")])
def test_known_duplicate_copy_marked_non_authoritative_is_allowed():
    validate_no_double_coverage([e("877", "2023-04-01", "2026-03-31"), e("874", "2024-04-01", "2025-03-31", auth=False)])
def test_gap_raises():
    with pytest.raises(LookupError): resolve([e("1", "2024-04-01", "2025-03-31")], "SITE_REG", date(2030, 1, 1))
def test_fy(): assert fy_of(date(2026, 3, 31)) == "FY25-26" and fy_of(date(2026, 4, 1)) == "FY26-27"


# ---- logical vs physical ----
def test_unresolved_physical_is_blocked_not_guessed():
    entry = find(load_seed(SEED), "SITE_REG", "844")
    with pytest.raises(PhysicalUnresolvedError): entry.require_physical()   # hint must NOT be used as a name
def test_confirmed_status_without_physical_still_blocked():
    with pytest.raises(PhysicalUnresolvedError): replace(e("844", "2026-04-01", "2027-03-31"), status="CONFIRMED").require_physical()
def test_separate_object_architecture():
    p = PhysicalObject("MISRETAIL", "T$FINREGSITE_844", "TABLE")
    assert p.qualified == '"MISRETAIL"."T$FINREGSITE_844"' and p.identity == "MISRETAIL.T$FINREGSITE_844"
def test_shared_object_architecture_needs_discriminator():
    with pytest.raises(ValueError): PhysicalObject("M", "T_ALL", "TABLE", SHARED_DISCRIMINATOR)
    p = PhysicalObject("M", "T_ALL", "TABLE", SHARED_DISCRIMINATOR, "CUBE_ID", "844")
    assert p.identity == "M.T_ALL#CUBE_ID=844"
def test_separate_object_rejects_discriminator():
    with pytest.raises(ValueError): PhysicalObject("M", "T", "TABLE", SEPARATE_OBJECT, "C", "1")
def test_physical_names_validated():
    with pytest.raises(ValueError): PhysicalObject("M", 'T"; DROP', "TABLE")
def test_overlay_confirms_mapping(tmp_path):
    ov = tmp_path / "ov.json"
    ov.write_text(json.dumps({"SITE_REG|CUBE$FINREGSITE|844": {"status": "CONFIRMED", "evidence": "row 12",
        "physical": {"owner": "MISRETAIL", "object_name": "T$FINREGSITE_844", "object_type": "TABLE", "access_mode": "SEPARATE_OBJECT"}}}))
    merged = apply_overlay(load_seed(SEED), ov)
    assert find(merged, "SITE_REG", "844").require_physical().object_name == "T$FINREGSITE_844"
    assert not find(merged, "SITE_REG", "902").physical_resolved
def test_find_requires_copy_when_ambiguous():
    with pytest.raises(LookupError): find(load_seed(SEED), "SITE_REG")
