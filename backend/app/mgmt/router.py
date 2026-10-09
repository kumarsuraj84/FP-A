"""Management (MIS) P&L API, read-only. Money is a JSON number in INR Cr with 4 decimals (Decimal inside, float only at the edge); pct_ lines are percentage points of total income.

  GET /api/v1/mgmt/current          run id, as-of date, months available, warnings, data_state
  GET /api/v1/mgmt/pnl              management P&L, every line book / adjustment / total per month
  GET /api/v1/mgmt/stores           per-store 4-wall EBITDA and EBITDA after the blended DC + HO apportionment (rate is a fraction)
  GET /api/v1/mgmt/reconciliation   portal vs the published MIS by line and month, plus the corporate EBITDA bridge
  GET /api/v1/mgmt/adjustments      the adjustments (register rows and evaluated rule rows) for the window; optional month, entity
  GET /api/v1/mgmt/mapping          ledger map and the exception list of unmapped ledgers
Common parameters: entity=consolidated|subco|holdco (default consolidated, which is what the MIS shows; echoed in every header), include_proposed=true|false.
"""
from __future__ import annotations

import json
from decimal import Decimal as D

from fastapi import APIRouter, HTTPException, Query, Request, Response

from . import config as cfg
from . import engine as eng
from . import service as svc


def ok(data) -> Response:
    return Response(content=json.dumps(data, default=lambda o: float(o) if isinstance(o, D) else str(o)), media_type="application/json")


router = APIRouter(prefix="/api/v1/mgmt")
ENTITY = Query("consolidated", pattern="^(consolidated|subco|holdco)$")


def database(request: Request):
    db = request.app.state.db
    if db is None or not hasattr(db, "rel"):
        raise HTTPException(503, "The management P&L reads gold_fpa; start the API with FPA_SOURCE=gold")
    return db


def window(conn, lo, hi):
    try:
        return svc.check_window(conn, lo, hi)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None


def run(conn, lo, hi, include_proposed, entity):
    try:
        return svc.run(conn, lo, hi, include_proposed, entity)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None


@router.get("/current")
def current(request: Request):
    with database(request).session("pnl") as conn:
        ms = svc.available_months(conn)
        lo, hi = svc.default_window(conn)
        ctx = run(conn, lo, hi, True, "consolidated")
        pub = sorted({m for m, _ in cfg.mis_published()})
        return ok({**svc.header(conn), "months": ms, "months_available": ms, "default_from_month": lo, "default_to_month": hi, "mis_published_months": pub,
                   "data_state": "management_view", "warnings": svc.warnings(conn, ctx), "entities": list(cfg.ENTITIES), "config_files": cfg.files_present()})


@router.get("/pnl")
def pnl(request: Request, from_month: str | None = None, to_month: str | None = None, include_proposed: bool = True, entity: str = ENTITY):
    with database(request).session("pnl") as conn:
        lo, hi = window(conn, from_month, to_month)
        ctx = run(conn, lo, hi, include_proposed, entity)
        calc = ctx["calc"]["detail"]
        det = {}
        for ln in ("dc_cost", "ho_cost"):
            keys = sorted({k for (m, l, k) in calc if l == ln})
            det[ln] = [{"key": k, "label": k.replace("_", " ").capitalize(),
                        "values": {m: {"book": eng.q4(calc[(m, ln, k)]["book"]), "adjustment": eng.q4(calc[(m, ln, k)]["adj"]), "total": eng.q4(calc[(m, ln, k)]["book"] + calc[(m, ln, k)]["adj"])}
                                   for m in ctx["months"] if (m, ln, k) in calc}} for k in keys]
        return ok({**svc.header(conn, entity), "from_month": lo, "to_month": hi, "include_proposed": include_proposed, "months": ctx["months"], "lines": ctx["lines"],
                   "detail": det, "store_count": 0 if entity == "holdco" else _store_count(conn, ctx), "warnings": svc.warnings(conn, ctx)})


def _store_count(conn, ctx) -> int:
    hi = ctx["months"][-1]
    return svc.cached(("storecount", hi), lambda: conn.execute("SELECT count(*) AS n FROM gold_fpa.cogs_store_month WHERE site_kind = 'STORE' AND month = %s AND net_sales_ex_gst > 0",
                                                              (svc.mdate(hi),)).fetchone()["n"])


@router.get("/stores")
def stores(request: Request, month: str | None = None, to_month: str | None = None, include_proposed: bool = True, entity: str = ENTITY):
    with database(request).session("pnl") as conn:
        _, dhi = svc.default_window(conn)
        lo, hi = window(conn, month or dhi, to_month or month or dhi)
        ctx = run(conn, lo, hi, include_proposed, entity)
        res = svc.stores(conn, ctx)
        return ok({**svc.header(conn, entity), "from_month": lo, "to_month": hi, **res, "warnings": svc.warnings(conn, ctx)})


NATURE = {"book": "Start", "adjustment": "Management adjustment", "subtotal": "Subtotal", "override": "MIS hard-coded override", "residual": "Residual", "mis": "Published MIS"}


def _steps(src):
    return [{"step": s["label"], "cr": s["amount_cr"], "nature": NATURE[s["kind"]], "note": ""} for s in src]


@router.get("/reconciliation")
def reconciliation(request: Request, from_month: str | None = None, to_month: str | None = None, include_proposed: bool = True, entity: str = ENTITY):
    pub = cfg.mis_published()
    pm = sorted({m for m, _ in pub})
    with database(request).session("pnl") as conn:
        lo, hi = window(conn, from_month or (pm[0] if pm else None), to_month or (pm[-1] if pm else None))
        ctx = run(conn, lo, hi, include_proposed, entity)
        ovr = cfg.mis_overrides()
        base = {**svc.header(conn, entity), "from_month": lo, "to_month": hi, "include_proposed": include_proposed}
        if entity != "consolidated":
            return ok({**base, "note": "The published MIS is consolidated; reconcile with entity=consolidated.", "months": [], "lines": [], "bridge": [], "overrides": [],
                       "warnings": svc.warnings(conn, ctx)})
        rec = eng.reconcile(ctx["lines"], ctx["months"], pub, ovr, ctx["rules"])
        by_line: dict[str, dict] = {}
        for c in rec["cells"]:
            ln = by_line.setdefault(c["line"], {"key": c["line"], "label": c["label"], "values": {}})
            ln["values"][c["month"]] = {"mis": c["mis"], "portal": c["portal"], "variance": c["variance"], "tied": c["tied"],
                                        "override_reason": "; ".join(c["explained_by"]) if c["explained_by"] else None}
        order = [k for k, *_ in eng.LINES]
        lines = sorted(by_line.values(), key=lambda x: order.index(x["key"]))
        br = eng.bridge(ctx["lines"], ctx["items"], ctx["months"], pub, ovr, entity)
        return ok({**base, "months": rec["months"], "lines": lines, "bridge": _steps(br["window"]), "bridge_by_month": {m: _steps(v) for m, v in br["by_month"].items()},
                   "tolerance_cr": rec["tolerance_cr"], "subtotal_tolerance_cr": rec["subtotal_tolerance_cr"],
                   "overrides": [{"month": o["month"], "line": o["line"], "portal_minus_mis_cr": eng.q4(o["expected"]), "reason": o["reason"], "category": o.get("category", "")}
                                 for o in ovr if o["month"] in ctx["months"]],
                   "warnings": svc.warnings(conn, ctx)})


@router.get("/adjustments")
def adjustments(request: Request, from_month: str | None = None, to_month: str | None = None, month: str | None = None, include_proposed: bool = True, entity: str = ENTITY):
    with database(request).session("pnl") as conn:
        lo, hi = window(conn, month or from_month, month or to_month)
        ctx = run(conn, lo, hi, include_proposed, entity)
        rows = []
        for i in sorted(ctx["items"], key=lambda x: (x["month"], x["id"])):
            if entity != "consolidated" and i["entity"] != entity.upper():
                continue
            rows.append({"id": i["id"], "month": i["month"], "mis_line": i["mis_line"], "location_type": i["location_type"], "amount_cr": eng.q4(i["amount_cr"]), "kind": i["kind"],
                         "rule": i["rule"], "owner": i["owner"], "status": i["status"], "source": i["source"], "note": i["note"], "entity": i["entity"], "origin": i["origin"],
                         "provisional": i["provisional"], "counterparty": i.get("counterparty") or None, "counterparty_entity": i.get("counterparty_entity") or None})
        r = ctx["rules"]
        rules = [{"id": "RULE-COGSCORR", "description": f"COGS correction = {D(r['cogs_correction']['pct']) * 100:.1f}% of store net sales, every month from {r['cogs_correction']['from_month']}", "status": "confirmed"},
                 {"id": "RULE-COGSBIF", "description": "Purchase / early-payment discounts booked at DC and HO are charged to stores: " + ", ".join(r["cogs_bifurcation"]["ledgers"]), "status": "confirmed"},
                 {"id": "RULE-ADVMOVE", "description": f"All HO and DC advertisement is charged to stores from {r['adv_reclass']['from_month']} (earlier months: explicit register rows)", "status": "confirmed"},
                 {"id": "PROV-*", "description": "Fixed monthly provisions continue after the last register month: " + "; ".join(f"{p['label']} {p['amount_cr']}" for p in r["fixed_provisions"]), "status": "proposed"}]
        return ok({**svc.header(conn, entity), "from_month": lo, "to_month": hi, "include_proposed": include_proposed, "rows": rows, "register_rows": len(ctx["register"]),
                   "rules": rules, "warnings": svc.warnings(conn, ctx)})


@router.get("/mapping")
def mapping(request: Request, from_month: str | None = None, to_month: str | None = None):
    with database(request).session("pnl") as conn:
        ms = svc.available_months(conn)
        lo, hi = window(conn, from_month or ms[0], to_month or ms[-1])
        book = svc.fetch_book(conn, lo, hi)
        ic = lambda name: any(h in name.lower() for h in cfg.INTERCO_HINTS)
        exc = sorted(({"ledger": e["ledger"], "amount_cr": eng.q4(e["amount_cr"]), "reason": e["reason"] + (" - looks like an intercompany charge" if ic(e["ledger"]) else ""),
                       "months": sorted(e["months"]), "likely_intercompany": ic(e["ledger"])} for e in book.exceptions.values() if abs(e["amount_cr"]) >= D("0.00005")),
                     key=lambda e: -abs(e["amount_cr"]))
        rows = [{"ledger": r["ledger"], "mgmt_group": r["mgmt_group"], "major_group": r.get("major_group", ""), "category": r.get("category") or None, "source": r.get("source", ""),
                 "note": r.get("note") or None, "location_rule": r.get("location_rule", "")} for r in cfg.ledger_map_rows()]
        return ok({**svc.header(conn), "from_month": lo, "to_month": hi, "rows": rows, "exceptions": exc,
                   "excluded": [{"ledger": k, "amount_cr": eng.q4(v)} for k, v in sorted(book.excluded.items(), key=lambda kv: -abs(kv[1]))],
                   "location_rule": {"kinds": cfg.LOC_OF_KIND, "site_overrides": list(cfg.site_loc().values())},
                   "counts": {"entries": len(rows), "unmapped_with_amounts": len(exc)}})


from .expenses import router as _expenses_router  # noqa: E402  Store / DC expense review: /api/v1/mgmt/expenses/*
router.include_router(_expenses_router)
