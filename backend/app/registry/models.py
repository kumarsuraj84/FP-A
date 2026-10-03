"""Finance Source Registry: metadata-driven source selection.

No cube codes are hardcoded in business logic. Every entry below the seed file is
UNVERIFIED until live discovery confirms it (status field)."""
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class SourceEntry:
    source_type: str          # e.g. SITE_REG, GL_REG, MOP, TDS
    cube_name: str            # e.g. CUBE$FINREGSITE
    cube_code: str            # value of the cube discriminator column (string, not business logic)
    financial_year: str | None  # 'FY25-26' or None for multi-year
    date_from: date
    date_to: date
    is_current: bool = False
    is_auto_refresh: bool = False
    last_refresh_at: str | None = None
    status: str = "UNVERIFIED"   # UNVERIFIED | CONFIRMED | BLOCKED | RETIRED
    authoritative: bool = True   # False = known duplicate copy, never loaded

    def overlaps(self, other: "SourceEntry") -> bool:
        return self.date_from <= other.date_to and other.date_from <= self.date_to
