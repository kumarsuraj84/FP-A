"""Structured mapping evidence. A confirmed registry mapping must say WHY:
which discovery artifact (path + sha256 + discovery time), which row in it, and how strongly
that row supports the mapping.

verification levels (never claim more than was done):
  MACHINE_VERIFIED    the referenced OLAP_DATACUBE_LIST row mentions BOTH the copy id and the physical
                      object name (and the discriminator value for shared mode) as exact cell values.
                      This is a generic cell-value match - OLAP_DATACUBE_LIST's column semantics are
                      UNVERIFIED, so no field-specific mapping is assumed.
  OPERATOR_CONFIRMED  the row exists and mentions at least one of copy id / object, but the match is
                      partial; a human vouched for the rest. The gaps are recorded in `notes`.
Rejected: missing file, bad shape, missing row, or a row that mentions neither copy id nor object."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

MACHINE_VERIFIED = "MACHINE_VERIFIED"
OPERATOR_CONFIRMED = "OPERATOR_CONFIRMED"


class EvidenceError(ValueError):
    pass


def _cells(row: dict) -> set[str]:
    return {str(v).strip().upper() for v in row.values() if v is not None and str(v).strip()}


def build_evidence(artifact: str | Path, row_index: int, *, registry_key: str, copy_id: str,
                   owner: str, object_name: str, access_mode: str,
                   discriminator_column: str | None, discriminator_value: str | None,
                   confirmed_by: str = "operator") -> dict:
    path = Path(artifact)
    if not path.is_file():
        raise EvidenceError(f"evidence file not found: {path}")
    raw = path.read_bytes()
    try:
        doc = json.loads(raw)
        rows = doc["list"]["rows"]
    except (ValueError, KeyError, TypeError):
        raise EvidenceError("evidence file is not a cube_registry_discovery artifact (expected list.rows)")
    if not isinstance(row_index, int) or not 0 <= row_index < len(rows):
        raise EvidenceError(f"evidence row {row_index} out of range (artifact has {len(rows)} rows, 0-based)")
    row = rows[row_index]
    cells = _cells(row)
    has_copy = copy_id.strip().upper() in cells
    has_obj = object_name.upper() in cells or f"{owner}.{object_name}".upper() in cells
    has_disc = discriminator_value is None or discriminator_value.strip().upper() in cells
    if not has_copy and not has_obj:
        raise EvidenceError(f"evidence row {row_index} mentions neither copy id {copy_id!r} nor object {object_name!r}; "
                            "pick the row that actually describes this cube copy")
    notes = []
    if not has_copy: notes.append("copy id not found as a cell value in evidence row")
    if not has_obj: notes.append("object name not found as a cell value in evidence row")
    if not has_disc: notes.append("discriminator value not found as a cell value in evidence row")
    level = MACHINE_VERIFIED if (has_copy and has_obj and has_disc) else OPERATOR_CONFIRMED
    return {
        "verification": level, "notes": notes,
        "artifact_path": str(path), "artifact_sha256": hashlib.sha256(raw).hexdigest(),
        "artifact_discovered_at": doc.get("discovered_at"), "evidence_row_index": row_index,
        "evidence_row_snapshot": row, "registry_key": registry_key,
        "physical": {"owner": owner, "object_name": object_name, "access_mode": access_mode,
                     "discriminator_column": discriminator_column, "discriminator_value": discriminator_value},
        "confirmed_by": confirmed_by, "confirmed_at": datetime.now(timezone.utc).isoformat(),
    }
