import csv
from datetime import date
from pathlib import Path

from .models import SourceEntry


class OverlapError(ValueError):
    pass


def load_seed(path: str | Path) -> list[SourceEntry]:
    out = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            out.append(SourceEntry(
                source_type=r["source_type"], cube_name=r["cube_name"], cube_code=r["cube_code"],
                financial_year=r["financial_year"] or None,
                date_from=date.fromisoformat(r["date_from"]), date_to=date.fromisoformat(r["date_to"]),
                is_current=r["is_current"] == "true", is_auto_refresh=r["is_auto_refresh"] == "true",
                status=r["status"], authoritative=r["authoritative"] == "true"))
    return out


def validate_no_double_coverage(entries: list[SourceEntry]) -> None:
    """Exactly one authoritative, non-retired source per source_type x period."""
    live = [e for e in entries if e.authoritative and e.status != "RETIRED"]
    for i, a in enumerate(live):
        for b in live[i + 1:]:
            if a.source_type == b.source_type and a.overlaps(b):
                raise OverlapError(
                    f"{a.source_type}: {a.cube_name}/{a.cube_code} [{a.date_from}..{a.date_to}] overlaps "
                    f"{b.cube_name}/{b.cube_code} [{b.date_from}..{b.date_to}]")


def resolve(entries: list[SourceEntry], source_type: str, on: date) -> SourceEntry:
    validate_no_double_coverage(entries)
    hits = [e for e in entries if e.source_type == source_type and e.authoritative
            and e.status != "RETIRED" and e.date_from <= on <= e.date_to]
    if not hits:
        raise LookupError(f"no authoritative {source_type} source covers {on}")
    return hits[0]


def fy_of(d: date) -> str:
    """Indian FY, Apr-Mar. CONFIRMED by citykart data-model docs."""
    y = d.year if d.month >= 4 else d.year - 1
    return f"FY{y % 100:02d}-{(y + 1) % 100:02d}"
