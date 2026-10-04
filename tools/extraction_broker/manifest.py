"""
Manifest for one extraction run. FP&A validates it BEFORE loading any file: every dataset must be present on
disk, byte-identical to what the broker recorded, and the row count in the manifest must match the Parquet file.
Missing values are never turned into zeros: null min/max dates stay null with the status explaining why.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

REQUIRED_KEYS = (
    "dataset",
    "kind",
    "source_object",
    "logical_source",
    "copy_id",
    "query_id",
    "query_hash",
    "extracted_at",
    "row_count",
    "row_cap",
    "min_date",
    "max_date",
    "file_name",
    "file_size",
    "sha256",
    "status",
)
OK_STATUSES = {"ok", "capped", "sampled"}  # capped = hard row cap hit (may be incomplete); sampled = an intentional small sample
ALL_STATUSES = OK_STATUSES | {"failed", "skipped", "pending"}
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_manifest(run_dir: Path, manifest: dict) -> None:
    """Atomic write so a crash never leaves a half-written manifest."""
    tmp = run_dir / "manifest.json.tmp"
    tmp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, run_dir / "manifest.json")


@dataclass
class Verdict:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    loadable: list[str] = field(default_factory=list)


def _parquet_rows(path: Path) -> int:
    import pyarrow.parquet as pq

    return pq.ParquetFile(path).metadata.num_rows


def validate_manifest(run_dir: Path) -> Verdict:
    """Everything FP&A checks before it will load a run. Returns the datasets that are safe to load."""
    v = Verdict(ok=True)
    mpath = run_dir / "manifest.json"
    if not mpath.exists():
        return Verdict(False, ["manifest.json is missing"])
    try:
        m = json.loads(mpath.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return Verdict(False, [f"manifest.json is not valid JSON: {e}"])
    if not isinstance(m.get("datasets"), list) or not m["datasets"]:
        return Verdict(False, ["manifest has no datasets"])
    for k in ("run_id", "package", "created_at", "broker_version"):
        if k not in m:
            v.errors.append(f"manifest is missing '{k}'")

    seen = set()
    for d in m["datasets"]:
        name = d.get("dataset", "?")
        missing = [k for k in REQUIRED_KEYS if k not in d]
        if missing:
            v.errors.append(f"{name}: missing keys {missing}")
            continue
        if name in seen:
            v.errors.append(f"{name}: listed twice")
        seen.add(name)
        if d["status"] not in ALL_STATUSES:
            v.errors.append(f"{name}: unknown status '{d['status']}'")
            continue
        if d["status"] in ("failed", "skipped", "pending"):
            v.warnings.append(f"{name}: not loadable (status {d['status']})")
            continue
        if not _HEX64.match(str(d["query_hash"])) or not _HEX64.match(str(d["sha256"])):
            v.errors.append(f"{name}: query_hash / sha256 is not a 64-char hex digest")
            continue
        f = run_dir / d["file_name"]
        if Path(d["file_name"]).name != d["file_name"]:
            v.errors.append(f"{name}: file_name must be a plain file name")
            continue
        if not f.exists():
            v.errors.append(f"{name}: file {d['file_name']} is missing")
            continue
        if f.stat().st_size != d["file_size"]:
            v.errors.append(f"{name}: file size differs from the manifest")
            continue
        if sha256_file(f) != d["sha256"]:
            v.errors.append(f"{name}: file content differs from the manifest (sha256 mismatch)")
            continue
        try:
            rows = _parquet_rows(f)
        except Exception as e:  # noqa: BLE001 - any unreadable parquet is a hard error
            v.errors.append(f"{name}: not a readable Parquet file ({type(e).__name__})")
            continue
        if rows != d["row_count"]:
            v.errors.append(f"{name}: manifest says {d['row_count']} rows, file has {rows}")
            continue
        if d["row_count"] > d["row_cap"]:
            v.errors.append(f"{name}: row_count exceeds the recorded cap")
            continue
        if d["status"] == "ok" and d["row_count"] >= d["row_cap"]:
            v.errors.append(f"{name}: status 'ok' but the row cap was reached (should be 'capped')")
            continue
        if d["status"] == "sampled" and d["kind"] != "sample":
            v.errors.append(f"{name}: only a 'sample' dataset may have status 'sampled'")
            continue
        if d["status"] == "capped":
            v.warnings.append(f"{name}: row cap reached; the file may be incomplete")
        if d["row_count"] == 0:
            v.warnings.append(f"{name}: zero rows (an empty result, not missing data)")
        v.loadable.append(name)
    v.ok = not v.errors
    return v
