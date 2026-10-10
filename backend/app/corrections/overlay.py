"""Active corrections as a read-time overlay on the management book. Never a copy of finance data: the amount of every moved line is read from gold_fpa.voucher_lines
(the immutable source); the app database supplies only the line key and the corrected group and month (view v_correction_overlay).

A moved line posts -x in its original (month, management line) and +x in the corrected one, in the engine's reclass layer, so the layer nets to zero. A line whose group
changes but stays on the same P&L line (two 'other expenses' groups) and keeps its month moves nothing at line level; it matters on the expense-head pages only."""
from __future__ import annotations

import logging
from collections import defaultdict
from decimal import Decimal

from ..appdb.conn import app_connection
from ..mgmt import config as cfg
from ..mgmt import engine as eng

log = logging.getLogger(__name__)
CR = Decimal(10_000_000)
ENTITY = {"RETAIL": "SUBCO", "VENTURES": "HOLDCO"}
GOLD_LINE_SQL = """SELECT cost_tag_key, entity, entcode, entdt, glcode, glname, fin_group, tag_site_code, site_kind, damount, camount, profit_effect
                   FROM gold_fpa.voucher_lines WHERE entity = %s AND cost_tag_key = ANY(%s)"""


def month_of(d) -> str:
    return d.strftime("%Y-%m")


def line_group(row: dict, lmap: dict) -> str | None:
    grp, _ = eng.resolve_group(row["glname"], row.get("fin_group"), bool(row.get("fin_group")) and row.get("fin_group") != "UNMAPPED", lmap)
    return grp


def location_of(row: dict, site_loc: dict) -> str | None:
    sc = row.get("tag_site_code")
    return site_loc[sc]["location_type"] if sc in site_loc else cfg.LOC_OF_KIND.get(row.get("site_kind"))


def build_items(overlay_rows: list[dict], gold_rows: dict[tuple, dict], lmap: dict, site_loc: dict, skipped: list | None = None) -> list[dict]:
    """Pure. overlay_rows: v_correction_overlay rows; gold_rows: {(gold entity, cost_tag_key): voucher line}. Lines that vanished or are not P&L lines are skipped here
    (the source check reports them as ORPHANED / review)."""
    items = []
    for o in overlay_rows:
        g = gold_rows.get((o["source_entity"], int(o["source_line_key"])))
        if g is None:
            if skipped is not None:
                skipped.append({"request_id": str(o["request_id"]), "line": str(o["source_line_key"]), "reason": "the finance line no longer exists"})
            continue
        grp = line_group(g, lmap)
        key_from = cfg.KEY_OF_GROUP.get(grp) if grp and grp != cfg.EXCLUDED else None
        loc = location_of(g, site_loc)
        if key_from is None or loc is None:
            if skipped is not None:
                skipped.append({"request_id": str(o["request_id"]), "line": str(o["source_line_key"]), "reason": "the line is no longer a Management P&L line"})
            continue
        key_to = cfg.KEY_OF_GROUP.get(o["corrected_group"], key_from) if o["corrected_group"] else key_from
        m_from = month_of(g["entdt"])
        m_to = o["corrected_month"].strftime("%Y-%m") if o["corrected_month"] else m_from
        if key_from == key_to and m_from == m_to:
            continue
        items.append({"request_id": str(o["request_id"]), "line_id": str(o["line_id"]), "entity": ENTITY[o["source_entity"]], "location_type": loc, "key_from": key_from, "key_to": key_to,
                      "group_from": grp, "group_to": o["corrected_group"] or grp, "month_from": m_from, "month_to": m_to, "amount_cr": Decimal(g["profit_effect"]) / CR,
                      "ledger": g["glname"], "voucher": g["entcode"], "site_code": g.get("tag_site_code")})
    return items


def load(gconn, skipped: list | None = None) -> list[dict]:
    """The reclass items for the engine. Raises when the app database cannot be read: the caller reports it rather than silently showing totals without corrections."""
    with app_connection() as a:
        rows = a.execute("SELECT * FROM v_correction_overlay").fetchall()
    if not rows:
        return []
    keys = defaultdict(list)
    for r in rows:
        keys[r["source_entity"]].append(int(r["source_line_key"]))
    gold_rows = {}
    for ent, ks in keys.items():
        for g in gconn.execute(GOLD_LINE_SQL, (ent, ks)).fetchall():
            gold_rows[(g["entity"], g["cost_tag_key"])] = g
    return build_items(rows, gold_rows, cfg.ledger_map(), cfg.site_loc(), skipped)
