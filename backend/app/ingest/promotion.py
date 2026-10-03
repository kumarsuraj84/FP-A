"""Staging + promotion semantics (reference implementation mirrored by fin.* SQL).

STAGING  = append-only snapshot history. One row per (source-row identity, extract_batch_id).
           Re-submitting the same batch id is a no-op. Different batches of the same source
           row are all kept (audit/lineage).
PROMOTION = deterministic, idempotent upsert into the typed fact keyed by SourceRowIdentity.
           Re-running a batch changes nothing. A changed row (hash differs) is updated.
           For full-refresh sources, rows of the same physical scope absent from the new
           batch are tombstoned (source_deleted), never silently kept in totals nor hard-deleted.
Totals must exclude tombstoned rows."""
import hashlib
import json
from dataclasses import dataclass, field
from decimal import Decimal

from .identity import SourceRowIdentity


def row_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


@dataclass
class Staging:
    rows: dict = field(default_factory=dict)   # (identity, batch_id) -> (hash, payload)

    def append(self, batch_id: str, items: list[tuple[SourceRowIdentity, dict]]) -> int:
        n = 0
        for ident_, payload in items:
            k = (ident_, batch_id)
            if k in self.rows:
                continue          # same batch re-submitted: idempotent no-op
            self.rows[k] = (row_hash(payload), payload); n += 1
        return n


@dataclass
class FactStore:
    facts: dict = field(default_factory=dict)  # identity -> {hash,payload,batch_id,deleted}

    def promote(self, batch_id: str, items: list[tuple[SourceRowIdentity, dict]], *, full_refresh_scope: tuple | None = None) -> dict:
        """full_refresh_scope = SourceRowIdentity.scope / identity.scope_of(entry) when this batch is a
        complete extract of that ONE physical source; rows of that scope not in the batch are tombstoned.
        Every item in the batch must belong to that scope."""
        res = {"inserted": 0, "updated": 0, "unchanged": 0, "tombstoned": 0, "revived": 0}
        seen = set()
        if full_refresh_scope:
            stray = [i for i, _ in items if i.scope != tuple(full_refresh_scope)]
            if stray:
                raise ValueError(f"full-refresh batch contains rows outside its scope: {stray[0]}")
        for i, payload in items:
            if i in seen:
                raise ValueError(f"duplicate source-row identity within one batch: {i}")
            seen.add(i)
            h = row_hash(payload)
            cur = self.facts.get(i)
            if cur is None:
                self.facts[i] = {"hash": h, "payload": payload, "batch_id": batch_id, "deleted": False}; res["inserted"] += 1
            elif cur["hash"] == h and not cur["deleted"]:
                res["unchanged"] += 1
            else:
                if cur["deleted"]: res["revived"] += 1
                else: res["updated"] += 1
                cur.update(hash=h, payload=payload, batch_id=batch_id, deleted=False)
        if full_refresh_scope:
            for i, cur in self.facts.items():
                if i.scope == tuple(full_refresh_scope) \
                        and i not in seen and not cur["deleted"]:
                    cur["deleted"] = True; res["tombstoned"] += 1
        return res

    def total(self, col: str) -> Decimal:
        return sum((Decimal(str(f["payload"].get(col, 0))) for f in self.facts.values() if not f["deleted"]), Decimal(0))
