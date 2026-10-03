from datetime import date
from pathlib import Path
import pytest
from app.registry.models import SourceEntry
from app.registry.resolver import load_seed, resolve, validate_no_double_coverage, OverlapError, fy_of

SEED = Path(__file__).resolve().parents[2] / "config" / "source_registry_seed.csv"

def e(code, a, b, auth=True):
    return SourceEntry("SITE_REG", "C", code, None, date.fromisoformat(a), date.fromisoformat(b), authoritative=auth)

def test_seed_has_no_double_coverage(): validate_no_double_coverage(load_seed(SEED))
def test_resolve_by_date_not_hardcode():
    s = load_seed(SEED)
    assert resolve(s, "SITE_REG", date(2026, 4, 1)).cube_code == "844"
    assert resolve(s, "SITE_REG", date(2026, 3, 31)).cube_code == "902"
def test_all_years_plus_yearly_copy_is_rejected():
    with pytest.raises(OverlapError):
        validate_no_double_coverage([e("877", "2023-04-01", "2026-03-31"), e("874", "2024-04-01", "2025-03-31")])
def test_known_duplicate_copy_marked_non_authoritative_is_allowed():
    validate_no_double_coverage([e("877", "2023-04-01", "2026-03-31"), e("874", "2024-04-01", "2025-03-31", auth=False)])
def test_gap_raises(): 
    with pytest.raises(LookupError): resolve([e("1", "2024-04-01", "2025-03-31")], "SITE_REG", date(2030, 1, 1))
def test_fy(): assert fy_of(date(2026, 3, 31)) == "FY25-26" and fy_of(date(2026, 4, 1)) == "FY26-27"
