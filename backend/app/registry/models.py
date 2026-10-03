"""Finance Source Registry.

Two separate identities (never conflated):
  * LOGICAL  : source_type (SITE_REG, GL_REG, MOP, ...) + Ginesys logical cube name
               (e.g. CUBE$FINREGSITE) + copy_id (the cube/copy identifier).
  * PHYSICAL : the Oracle object that actually holds the rows (owner, name, type) and
               HOW it is addressed (own object per copy, or shared object + discriminator).

The physical part is None until live metadata (OLAP_DATACUBE_LIST + ALL_OBJECTS) has
confirmed it. Nothing may build a physical name from a pattern; `require_physical()`
is the only way business/ingestion code obtains a table reference."""
from dataclasses import dataclass
from datetime import date

from app.identifiers import ident, quote

SEPARATE_OBJECT = "SEPARATE_OBJECT"          # architecture A: one physical object per copy
SHARED_DISCRIMINATOR = "SHARED_DISCRIMINATOR"  # architecture B: shared object + discriminator column


class PhysicalUnresolvedError(RuntimeError):
    """The logical source has no CONFIRMED physical object yet."""


@dataclass(frozen=True)
class PhysicalObject:
    owner: str
    object_name: str
    object_type: str                      # TABLE | VIEW | MATERIALIZED VIEW (as reported by ALL_OBJECTS)
    access_mode: str = SEPARATE_OBJECT
    discriminator_column: str | None = None
    discriminator_value: str | None = None

    def __post_init__(self):
        ident(self.owner); ident(self.object_name)
        if self.access_mode not in (SEPARATE_OBJECT, SHARED_DISCRIMINATOR):
            raise ValueError(f"bad access_mode {self.access_mode}")
        if self.access_mode == SHARED_DISCRIMINATOR:
            if not (self.discriminator_column and self.discriminator_value):
                raise ValueError("SHARED_DISCRIMINATOR needs discriminator column+value")
            ident(self.discriminator_column)
        elif self.discriminator_column or self.discriminator_value:
            raise ValueError("SEPARATE_OBJECT must not carry a discriminator")

    @property
    def qualified(self) -> str:
        return f"{quote(self.owner)}.{quote(self.object_name)}"

    @property
    def display_name(self) -> str:
        """HUMAN-READABLE label only (owner.object[#column=value]). Never used as a lineage key:
        provenance stores owner / object name / discriminator column / discriminator value as
        separate fields (see app/ingest/identity.py)."""
        base = f"{self.owner}.{self.object_name}"
        if self.access_mode == SHARED_DISCRIMINATOR:
            base += f"#{self.discriminator_column}={self.discriminator_value}"
        return base


@dataclass(frozen=True)
class SourceEntry:
    source_type: str                 # logical dataset: SITE_REG, GL_REG, MOP, OUTSTANDING ...
    logical_cube_name: str           # Ginesys logical cube, e.g. CUBE$FINREGSITE
    copy_id: str                     # cube/copy identifier (opaque; need not be chronological)
    financial_year: str | None
    date_from: date
    date_to: date
    is_current: bool = False
    is_auto_refresh: bool = False
    last_refresh_at: str | None = None
    status: str = "UNVERIFIED"       # UNVERIFIED | CONFIRMED | BLOCKED | RETIRED
    authoritative: bool = True       # False = known duplicate copy, never loaded
    physical: PhysicalObject | None = None
    physical_hint: str | None = None  # prior-documentation hint, used ONLY as an existence-check candidate

    @property
    def registry_key(self) -> str:
        return f"{self.source_type}|{self.logical_cube_name}|{self.copy_id}"

    @property
    def physical_resolved(self) -> bool:
        return self.status == "CONFIRMED" and self.physical is not None

    def require_physical(self) -> PhysicalObject:
        if not self.physical_resolved:
            raise PhysicalUnresolvedError(
                f"{self.registry_key} has no CONFIRMED physical object (status={self.status}); "
                "run discover-cube-registry / registry-confirm against live Oracle")
        return self.physical

    def overlaps(self, other: "SourceEntry") -> bool:
        return self.date_from <= other.date_to and other.date_from <= self.date_to
