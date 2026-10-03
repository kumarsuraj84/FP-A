import csv
import json
from dataclasses import replace
from datetime import date
from pathlib import Path

from .models import PhysicalObject, SourceEntry


class OverlapError(ValueError):
    pass


def load_seed(path: str | Path) -> list[SourceEntry]:
    out = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            out.append(SourceEntry(
                source_type=r["source_type"], logical_cube_name=r["logical_cube_name"], copy_id=r["copy_id"],
                financial_year=r["financial_year"] or None,
                date_from=date.fromisoformat(r["date_from"]), date_to=date.fromisoformat(r["date_to"]),
                is_current=r["is_current"] == "true", is_auto_refresh=r["is_auto_refresh"] == "true",
                status=r["status"], authoritative=r["authoritative"] == "true",
                physical_hint=r.get("physical_hint") or None))
    return out


def apply_overlay(entries: list[SourceEntry], overlay_path: str | Path) -> list[SourceEntry]:
    """Overlay = locally generated, git-ignored evidence from live discovery
    ({registry_key: {status, physical:{...}, last_refresh_at, evidence}})."""
    p = Path(overlay_path)
    if not p.exists():
        return entries
    ov = json.loads(p.read_text())
    out = []
    for e in entries:
        o = ov.get(e.registry_key)
        if not o:
            out.append(e); continue
        phys = PhysicalObject(**o["physical"]) if o.get("physical") else e.physical
        out.append(replace(e, status=o.get("status", e.status), physical=phys,
                           last_refresh_at=o.get("last_refresh_at", e.last_refresh_at)))
    return out


def validate_no_double_coverage(entries: list[SourceEntry]) -> None:
    """Exactly one authoritative, non-retired source per source_type x period."""
    live = [e for e in entries if e.authoritative and e.status != "RETIRED"]
    for i, a in enumerate(live):
        for b in live[i + 1:]:
            if a.source_type == b.source_type and a.overlaps(b):
                raise OverlapError(
                    f"{a.source_type}: {a.registry_key} [{a.date_from}..{a.date_to}] overlaps "
                    f"{b.registry_key} [{b.date_from}..{b.date_to}]")


def resolve(entries: list[SourceEntry], source_type: str, on: date) -> SourceEntry:
    validate_no_double_coverage(entries)
    hits = [e for e in entries if e.source_type == source_type and e.authoritative
            and e.status != "RETIRED" and e.date_from <= on <= e.date_to]
    if not hits:
        raise LookupError(f"no authoritative {source_type} source covers {on}")
    return hits[0]


def find(entries: list[SourceEntry], source_type: str, copy_id: str | None = None) -> SourceEntry:
    hits = [e for e in entries if e.source_type == source_type and (copy_id is None or e.copy_id == copy_id)]
    if not hits:
        raise LookupError(f"no registry entry for {source_type} copy={copy_id}")
    if len(hits) > 1:
        raise LookupError(f"{source_type}: {len(hits)} copies; pass an explicit copy id "
                          f"({', '.join(h.copy_id for h in hits)})")
    return hits[0]


def fy_of(d: date) -> str:
    """Indian FY, Apr-Mar. CONFIRMED by citykart data-model docs."""
    y = d.year if d.month >= 4 else d.year - 1
    return f"FY{y % 100:02d}-{(y + 1) % 100:02d}"


def load_local_entries(path: str | Path) -> list[SourceEntry]:
    """Operator-added entries (registry-add), local and git-ignored: sources the seed does not list
    yet (e.g. OUTSTANDING). Always UNVERIFIED until registry-confirm."""
    p = Path(path)
    if not p.exists():
        return []
    return [SourceEntry(source_type=r["source_type"], logical_cube_name=r["logical_cube_name"], copy_id=r["copy_id"],
                        financial_year=r.get("financial_year"), date_from=date.fromisoformat(r["date_from"]),
                        date_to=date.fromisoformat(r["date_to"]), is_current=bool(r.get("is_current")),
                        is_auto_refresh=bool(r.get("is_auto_refresh")), status="UNVERIFIED", authoritative=True)
            for r in json.loads(p.read_text())]


def format_status(entries: list[SourceEntry]) -> list[str]:
    return [f"{e.status:10} {e.registry_key:34} {e.financial_year or '-':8} "
            f"physical={e.physical.display_name if e.physical else '-'} hint={e.physical_hint or '-'} "
            f"authoritative={e.authoritative}" for e in entries]
