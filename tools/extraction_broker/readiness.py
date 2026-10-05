"""
Source readiness for entry_pilot_01: a cheap check that runs BEFORE any expensive extract (and before a run folder or manifest exists).

It does three things and one sanity check, and nothing else:
  1. the current-year site register (T$FINREGSITE_844) is non-empty;
  2. its REPORT_DATE is non-null;
  3. its REPORT_DATE equals the outstanding cube's REPORT_DATE exactly;
  4. (sanity, not a financial control) its current-year row count has not collapsed against the last snapshot that passed: below READINESS_MIN_FRACTION of that
     count is treated as a warehouse refresh in progress (an inference from the observed sequence, not direct refresh evidence).

A failure is `SOURCE_NOT_READY`: it is NOT a failed extraction, writes no run folder and no manifest, and therefore leaves nothing that looks like a candidate staging run.
Only counts, dates and a reason are ever recorded: no row values.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

READINESS_MIN_FRACTION = 0.5     # conservative: a readiness check, not a control; half of the last good count is far above any refresh-in-progress state

EMPTY = "register empty"
DATE_UNAVAILABLE = "register date unavailable"
CUBE_DATE_UNAVAILABLE = "cube date unavailable"
MISMATCH = "snapshot mismatch"
COLLAPSED = "register row count collapsed against the last good snapshot"
PROBE_FAILED = "readiness probe did not complete"


def _num(x):
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return None


def assess(register: dict | None, cube: dict | None, baseline: dict | None) -> tuple[bool, str]:
    """-> (ready, reason). `register` = {register_rows, register_report_date}; `cube` = {cube_report_date}; `baseline` = {register_rows} of the last good snapshot or None."""
    if register is None or cube is None:
        return False, PROBE_FAILED
    rows = _num(register.get("register_rows"))
    if not rows:                                   # None or 0
        return False, EMPTY
    rdate = register.get("register_report_date")
    if rdate in (None, ""):
        return False, DATE_UNAVAILABLE
    cdate = cube.get("cube_report_date")
    if cdate in (None, ""):
        return False, CUBE_DATE_UNAVAILABLE
    if str(rdate) != str(cdate):
        return False, MISMATCH
    last = _num((baseline or {}).get("register_rows"))
    if last and rows < last * READINESS_MIN_FRACTION:
        return False, COLLAPSED
    return True, "ready"


def load_baseline(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def record_baseline(path: Path, rows: int, report_date: str) -> None:
    """Only ever ratchets the count up: a partial reading that still passes can never lower the floor."""
    old = _num((load_baseline(path) or {}).get("register_rows")) or 0
    path.write_text(json.dumps({"register_rows": max(old, rows), "report_date": report_date, "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}), encoding="utf-8")
