"""Two identity concepts, kept apart:

1. SOURCE-ROW IDENTITY (this module): where a row physically came from. Used ONLY for
   ingestion idempotency. (source_system, source_owner, physical_object, copy_id, row_key).
   The same row_key in two annual copies is two different source rows.

2. CANONICAL FINANCE TRANSACTION IDENTITY: the business key that says two source rows are
   the same economic entry. UNKNOWN until live discovery; NOT implemented. Nothing here
   (or in the mart) may deduplicate across physical sources on a row key alone."""
from dataclasses import dataclass

from app.registry.models import SourceEntry


@dataclass(frozen=True)
class SourceRowIdentity:
    source_system: str
    source_owner: str
    physical_object: str     # PhysicalObject.identity (includes discriminator when shared)
    copy_id: str
    row_key: str

    def __post_init__(self):
        for f in ("source_system", "source_owner", "physical_object", "copy_id", "row_key"):
            if not getattr(self, f) or not str(getattr(self, f)).strip():
                raise ValueError(f"source identity field {f} must be non-empty")

    @classmethod
    def for_row(cls, entry: SourceEntry, row_key: str, source_system: str = "ORACLE_GINESYS") -> "SourceRowIdentity":
        p = entry.require_physical()
        return cls(source_system, p.owner, p.identity, entry.copy_id, str(row_key))
