"""Register of related-party (intercompany) creditor sub-ledgers, read once from config/mgmt/related_parties.csv (git-ignored: real finance data).

Columns: sub_ledger_code, party_name, group_entity, relationship (group company | cross charge), basis, status (proposed | confirmed), note.
Every registered sub-ledger (proposed AND confirmed) is excluded from the main creditors relation and shown on the Related Party Transactions page.
A missing file excludes nothing (a warning is logged). FPA_RELATED_PARTIES overrides the path; reload() re-reads it.
"""
from __future__ import annotations

import csv
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[3]
STATUSES = ("proposed", "confirmed")
_cache: list[dict] | None = None


def path() -> Path:
    return Path(os.environ.get("FPA_RELATED_PARTIES") or ROOT / "config" / "mgmt" / "related_parties.csv")


def parse(text: str) -> list[dict]:
    """Parse register CSV text. Rows without a numeric sub_ledger_code are skipped; duplicates keep the first; unknown status falls back to proposed."""
    out, seen = [], set()
    for row in csv.DictReader(text.splitlines()):
        row = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
        code = row.get("sub_ledger_code", "")
        if not code.isdigit() or int(code) in seen:
            continue
        seen.add(int(code))
        status = row.get("status", "").lower()
        out.append({"sub_ledger_code": int(code), "party_name": row.get("party_name", ""), "group_entity": row.get("group_entity", ""),
                    "relationship": row.get("relationship", ""), "basis": row.get("basis", ""), "status": status if status in STATUSES else "proposed", "note": row.get("note", "")})
    return out


def load(force: bool = False) -> list[dict]:
    global _cache
    if _cache is None or force:
        p = path()
        if p.exists():
            _cache = parse(p.read_text(encoding="utf-8-sig"))
        else:
            log.warning("related-party register %s not found: no creditor is excluded as intercompany", p)
            _cache = []
    return _cache


def reload() -> list[dict]:
    return load(force=True)


def codes() -> list[int]:
    return [r["sub_ledger_code"] for r in load()]


def in_list() -> str:
    """SQL list of integer codes (ints only, so safe to inline)."""
    return ", ".join(str(int(c)) for c in codes())
