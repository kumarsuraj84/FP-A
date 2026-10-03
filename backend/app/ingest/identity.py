"""Two identity concepts, kept apart:

1. SOURCE-ROW IDENTITY (this module): where a row physically came from. Used ONLY for
   ingestion idempotency. The same row_key in two annual copies is two different source rows.

   CANONICAL REPRESENTATION (identical in Python, staging DDL, fact DDL, tombstone scope):
       source_system                  e.g. ORACLE_GINESYS
       source_owner                   e.g. MISRETAIL
       source_object                  physical object NAME ONLY, e.g. T$FINREGSITE_844 / CUBE$BILLCOLL
       source_copy_id                 cube/copy id from the registry
       source_discriminator_column    '' for a separate-object source, else e.g. CUBENAME
       source_discriminator_value     '' for a separate-object source, else e.g. the cube-name value
       source_row_key                 row identifier within that physical source
   '' (not NULL) is the "none" sentinel so UNIQUE constraints compare it (Postgres treats NULLs
   as distinct, which would silently allow duplicates). Column and value are both '' or both set.

2. CANONICAL FINANCE TRANSACTION IDENTITY: the business key saying two source rows are the same
   economic entry. UNKNOWN until live discovery; NOT implemented. Nothing here (or in the mart)
   may deduplicate across physical sources on a row key alone."""
from dataclasses import dataclass

from app.registry.models import SourceEntry

SCOPE_FIELDS = ("source_system", "source_owner", "source_object", "source_copy_id",
                "source_discriminator_column", "source_discriminator_value")


@dataclass(frozen=True)
class SourceRowIdentity:
    source_system: str
    source_owner: str
    source_object: str
    source_copy_id: str
    source_discriminator_column: str
    source_discriminator_value: str
    source_row_key: str

    def __post_init__(self):
        for f in ("source_system", "source_owner", "source_object", "source_copy_id", "source_row_key"):
            v = getattr(self, f)
            if not isinstance(v, str) or not v.strip():
                raise ValueError(f"source identity field {f} must be a non-empty string")
        if not isinstance(self.source_discriminator_column, str) or not isinstance(self.source_discriminator_value, str):
            raise ValueError("discriminator fields must be strings ('' for none), never None")
        if bool(self.source_discriminator_column) != bool(self.source_discriminator_value):
            raise ValueError("discriminator column and value must be both set or both ''")

    @property
    def scope(self) -> tuple:
        """The physical source this row belongs to (everything except the row key). Tombstoning
        of a full-refresh batch is limited to exactly one scope."""
        return tuple(getattr(self, f) for f in SCOPE_FIELDS)

    @classmethod
    def for_row(cls, entry: SourceEntry, row_key: str, source_system: str = "ORACLE_GINESYS") -> "SourceRowIdentity":
        p = entry.require_physical()
        return cls(source_system, p.owner, p.object_name, entry.copy_id,
                   p.discriminator_column or "", p.discriminator_value or "", str(row_key))


def scope_of(entry: SourceEntry, source_system: str = "ORACLE_GINESYS") -> tuple:
    p = entry.require_physical()
    return (source_system, p.owner, p.object_name, entry.copy_id, p.discriminator_column or "", p.discriminator_value or "")
