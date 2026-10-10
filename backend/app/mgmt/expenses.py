"""Store Expense and DC Expense review API (read-only), built on the management P&L engine so every definition is the MIS one.

  GET /api/v1/mgmt/expenses/summary     heads (Rent, Employee Cost, Power and Fuel, Advertisement, Freight Forwarding, Other expenses) as book / adjustment / total,
                                        % of net sales (stores) or per site (DC), share, MoM, vs last year
  GET /api/v1/mgmt/expenses/trend       monthly by head (+ last-year total per month where gold has it)
  GET /api/v1/mgmt/expenses/sites       stores (or DC / HO sites) ranked: expense, % of net sales, per sq ft, vs peer median, rank, flags
  GET /api/v1/mgmt/expenses/ledgers     ledger rows behind a head (or a site, or one ledger by site) with line counts; each row carries the keys for the voucher drill
  GET /api/v1/mgmt/expenses/exceptions  outliers with the rule text of each
  GET /api/v1/mgmt/expenses/controls    store + DC + HO scope = total expense of the management P&L (tolerance 0.005 Cr), and site/ledger rows = engine book

Scopes: store = location type STORES, dc = DC, ho = HO (the rule per site kind and the site overrides are the engine's: see mgmt/engine.py).
Entity: consolidated | subco (Citykart Stores, gold entity RETAIL) | holdco (Citykart Ventures, gold entity VENTURES). Site codes collide between the two entities, so a site is always (entity, site_code).
Money is INR Cr with 4 decimals, expenses POSITIVE (the engine shows costs negative); a net credit in an expense head is therefore negative. Reads only the gold_fpa base tables.
"""
from __future__ import annotations

import json
import re
import statistics
from collections import defaultdict
from datetime import date
from decimal import Decimal as D

from fastapi import APIRouter, HTTPException, Query, Request, Response

from . import config as cfg
from . import engine as eng
from . import service as svc

ZERO = D(0)
CR = eng.CR
TOL = D("0.005")

HEADS = ("rent", "employee_cost", "power_fuel", "advertisement", "freight", "other_expenses")
COGS_HEAD = "cogs_items"
LABEL = {"rent": "Rent", "employee_cost": "Employee Cost", "power_fuel": "Power and Fuel", "advertisement": "Advertisement", "freight": "Freight Forwarding",
         "other_expenses": "Other expenses", COGS_HEAD: "Purchase discounts and other COGS-type ledgers"}
SCOPE_LOC = {"store": "STORES", "dc": "DC", "ho": "HO"}
SCOPE_LABEL = {"store": "Store expenses", "dc": "DC cost", "ho": "HO cost"}
SCOPE_LINE = {"dc": "dc_cost", "ho": "ho_cost"}
STORE_KINDS = ("STORE", "VIRTUAL", "EXTERNAL")
DC_KINDS = ("WAREHOUSE", "WAREHOUSE_OTHER", "WAREHOUSE_LEGACY")
SCOPE_KINDS = {"store": STORE_KINDS, "dc": DC_KINDS, "ho": ("HEAD_OFFICE",)}
VOUCHER_ENTITY = {"SUBCO": "RETAIL", "HOLDCO": "VENTURES"}
ENTITY_NAME = {"SUBCO": "SubCo (Citykart Stores)", "HOLDCO": "HoldCo (Citykart Ventures)"}
HOLDCO_RE = re.compile(r"VENTURE|HOLDCO|CKVPL|CRPL")

RULES = [
    {"id": "SITE_ABOVE_PEER", "title": "Store ledger above its peers",
     "text": "A store's ledger expense, as % of the store's net sales, is above the 95th percentile of the stores that book that ledger, at least 3 times their median, and at least 0.02 Cr above the median level for that store's sales. Stores only."},
    {"id": "MOM_JUMP", "title": "Month-on-month jump",
     "text": "A site's head expense in the latest month of the period is more than the threshold above the month before (default +50%) and at least 0.03 Cr higher (0.05 Cr for DC and HO)."},
    {"id": "DUPLICATE_BOOKING", "title": "Same ledger booked twice in a month",
     "text": "Two different vouchers post the same amount (at least Rs 50,000) on the same ledger at the same site in the same month. Possible duplicate: check both vouchers."},
    {"id": "CREDIT_IN_EXPENSE", "title": "Net credit in an expense ledger",
     "text": "A ledger in an expense head has a net CREDIT (a negative expense) for the period at a site, of at least Rs 10,000. Reversal, refund or a wrong-side posting."},
    {"id": "UNMAPPED_LEDGER", "title": "Ledger with no management group",
     "text": "A ledger posted at a site of this scope that is not in the management ledger map and has no finance group in gold, so it is outside the P&L. Add it to config/mgmt/mgmt_ledger_map.csv."},
]


# ------------------------------------------------------------------ small helpers

def ok(data) -> Response:
    return Response(content=json.dumps(data, default=lambda o: float(o) if isinstance(o, D) else (o.isoformat() if isinstance(o, date) else str(o))), media_type="application/json")


def q4(x) -> D:
    return eng.q4(D(x))


def add_months(m: str, n: int) -> str:
    t = int(m[:4]) * 12 + int(m[5:7]) - 1 + n
    return f"{t // 12:04d}-{t % 12 + 1:02d}"


def fy_start(m: str) -> date:
    y = int(m[:4]) - (1 if int(m[5:7]) < 4 else 0)
    return date(y, 4, 1)


def median(xs: list) -> D | None:
    return D(str(statistics.median(xs))) if xs else None


def pctile(xs: list, p: float) -> D | None:
    """Linear-interpolated percentile (p in 0..100) of a list of numbers."""
    if not xs:
        return None
    s = sorted(xs)
    k = (len(s) - 1) * p / 100
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return D(s[f]) + (D(s[c]) - D(s[f])) * D(str(k - f))


def head_of(scope: str, loc: str, key: str) -> str | None:
    """The expense head an atomic (location, key) amount belongs to in this scope, or None when it is not an expense of the scope."""
    if loc != SCOPE_LOC[scope]:
        return None
    ln = eng.line_targets(loc, key)
    if ln is None:
        return None
    if scope == "store":
        return ln if ln in eng.STORE_EXP else None
    if ln != SCOPE_LINE[scope]:
        return None
    if key in eng.STORE_EXP:
        return key
    if key == "director_remuneration":
        return "other_expenses"
    if key == "material_cost":
        return COGS_HEAD
    return None


def heads_of(scope: str) -> tuple:
    return HEADS if scope == "store" else HEADS + (COGS_HEAD,)


def ent_filter(entity: str):
    return (lambda e: True) if entity == "consolidated" else (lambda e: e == entity.upper())


def classify_entity(raw: str | None) -> str:
    return "HOLDCO" if HOLDCO_RE.search((raw or "").upper()) else "SUBCO"


# ------------------------------------------------------------------ engine-level aggregation

def reclass_cells(scope: str, entity: str, months, reclass: list | None):
    """Active corrections in EXPENSE sign (positive cost): yields (month, head, delta). A moved line of profit effect a leaves its original (month, head) by -(-a) and enters the
    corrected one by +(-a), so the deltas net to zero. Only moves inside this scope's heads count; a correction never changes the location type."""
    ok_e, mset = ent_filter(entity), set(months)
    for rc in reclass or []:
        if not ok_e(rc["entity"]):
            continue
        a = rc["amount_cr"]
        hf, ht = head_of(scope, rc["location_type"], rc["key_from"]), head_of(scope, rc["location_type"], rc["key_to"])
        if hf is not None and rc["month_from"] in mset:
            yield rc["month_from"], hf, a
        if ht is not None and rc["month_to"] in mset:
            yield rc["month_to"], ht, -a


def engine_cells(book: eng.Book, items: list, scope: str, entity: str, months, reclass: list | None = None) -> dict:
    """{(month, head): {'book': D, 'adj': D, 'adj0': D, 'rc': D}} as positive expenses, from the management engine's book cells, adjustment items and active corrections.
    `adj` is the management movement shown on these pages (adjustments + corrections' reclass, collapsed); `adj0` is the adjustments alone (only they are spread to stores
    pro rata to net sales; a correction belongs to its own site) and `rc` the reclass alone. The Management P&L page shows them in separate columns."""
    ok_e, mset = ent_filter(entity), set(months)
    out: dict = defaultdict(lambda: {"book": ZERO, "adj": ZERO, "adj0": ZERO, "rc": ZERO})
    for (m, e, loc, key), v in book.cells.items():
        if m in mset and ok_e(e):
            h = head_of(scope, loc, key)
            if h:
                out[(m, h)]["book"] -= v
    for it in items:
        if it["month"] in mset and ok_e(it["entity"]) and not (it["kind"] == "elimination" and entity != "consolidated"):
            h = head_of(scope, it["location_type"], it["mis_line"])
            if h:
                out[(it["month"], h)]["adj"] -= it["amount_cr"]
                out[(it["month"], h)]["adj0"] -= it["amount_cr"]
    for m, h, d in reclass_cells(scope, entity, months, reclass):
        out[(m, h)]["adj"] += d
        out[(m, h)]["rc"] += d
    return out


def net_sales(book: eng.Book, entity: str, months) -> dict:
    return {m: (ZERO if entity == "holdco" else book.sales.get(m, ZERO)) for m in months}


def tot_of(cells: dict, months, heads) -> dict:
    t = {"book": ZERO, "adj": ZERO}
    for m in months:
        for h in heads:
            c = cells.get((m, h))
            if c:
                t["book"] += c["book"]
                t["adj"] += c["adj"]
    return t


def triple(book_v: D, adj_v: D) -> dict:
    return {"book": q4(book_v), "adjustment": q4(adj_v), "total": q4(book_v + adj_v)}


# ------------------------------------------------------------------ site-level rows (SQL on the base table)

def fetch_aggregates(conn, lo: str, hi: str, scope: str) -> dict:
    """Ledger x site x month rows of the scope, classified exactly as the engine does (resolve_group, KEY_OF_GROUP, site kind with the site overrides)."""
    det = svc.detect(conn)

    def go():
        sl = cfg.site_loc()
        lmap = cfg.ledger_map()
        ent_sql = "p.entity" if det["pnl_has_entity"] else svc.HOLDCO_SQL
        join = "" if det["pnl_has_entity"] else " LEFT JOIN gold_fpa.dim_site d ON d.site_code = p.site_code AND d.entity = 'RETAIL'"
        kinds = list(SCOPE_KINDS[scope]) + (["VIRTUAL"] if scope == "ho" else [])
        rows = conn.execute(
            f"SELECT to_char(p.month, 'YYYY-MM') AS month, {ent_sql} AS entity, p.site_code, p.site_kind, p.glcode, p.glname, p.fin_group, p.is_mapped, max(p.store_name) AS store_name, "
            f"sum(p.profit_effect) AS pe, sum(p.lines_n) AS n FROM gold_fpa.pnl_store_month p{join} WHERE p.month >= %s AND p.month <= %s "
            "AND (p.site_kind = ANY(%s) OR p.site_code = ANY(%s::int[])) GROUP BY 1, 2, 3, 4, 5, 6, 7, 8",
            (svc.mdate(lo), svc.mdate(hi), kinds, list(sl))).fetchall()
        led: dict = defaultdict(lambda: defaultdict(lambda: [ZERO, 0]))
        names: dict = {}
        unmapped: dict = defaultdict(lambda: defaultdict(D))
        for r in rows:
            ent = classify_entity(r["entity"])
            sc = r["site_code"]
            loc = sl[sc]["location_type"] if (ent == "SUBCO" and sc in sl) else cfg.LOC_OF_KIND.get(r["site_kind"])
            if loc != SCOPE_LOC[scope]:
                continue
            amt = D(str(r["pe"])) / CR
            grp, _ = eng.resolve_group(r["glname"], r.get("fin_group"), bool(r.get("is_mapped")), lmap)
            if grp == cfg.EXCLUDED:
                continue
            key = cfg.KEY_OF_GROUP.get(grp) if grp else None
            names[(ent, sc)] = (r["store_name"], r["site_kind"])
            if key is None:
                unmapped[(ent, sc, r["glcode"], r["glname"], "no management group" if grp is None else f"group {grp} is not a P&L group")][r["month"]] += amt
                continue
            h = head_of(scope, loc, key)
            if h is None:
                continue
            cell = led[(ent, sc, r["glcode"], r["glname"], h, grp)][r["month"]]
            cell[0] -= amt
            cell[1] += int(r["n"] or 0)
        return {"led": {k: {m: tuple(v) for m, v in mm.items()} for k, mm in led.items()}, "names": names, "unmapped": {k: dict(v) for k, v in unmapped.items()}}
    return svc.cached(("exp_agg", lo, hi, scope, det["pnl_has_entity"]), go)


def fetch_store_meta(conn) -> dict:
    def go():
        return {r["site_code"]: r for r in conn.execute("SELECT site_code, short_name, store_name, store_type, state, city, area, opening_date, store_status FROM gold_fpa.dim_site WHERE entity = 'RETAIL'").fetchall()}
    return svc.cached("exp_meta", go)


def fetch_site_sales(conn, lo: str, hi: str) -> dict:
    def go():
        out: dict = defaultdict(lambda: defaultdict(D))
        for r in conn.execute("SELECT to_char(month, 'YYYY-MM') AS month, site_code, sum(net_sales_ex_gst) AS ns FROM gold_fpa.cogs_store_month WHERE site_kind = 'STORE' AND month >= %s AND month <= %s GROUP BY 1, 2",
                              (svc.mdate(lo), svc.mdate(hi))).fetchall():
            out[r["site_code"]][r["month"]] += D(str(r["ns"] or 0)) / CR
        return {k: dict(v) for k, v in out.items()}
    return svc.cached(("exp_ns", lo, hi), go)


# ------------------------------------------------------------------ request context

class X:
    """Everything one request needs: window, engine run over [window start - 1 month, window end], flags."""
    pass


def load(conn, scope: str, lo: str | None, hi: str | None, entity: str, include_proposed: bool = True, with_ly: bool = False) -> X:
    if scope not in SCOPE_LOC:
        raise HTTPException(422, "scope is store, dc or ho")
    if entity not in ("consolidated", "subco", "holdco"):
        raise HTTPException(422, "entity is consolidated, subco or holdco")
    try:
        lo, hi = svc.check_window(conn, lo, hi)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    x = X()
    ms = svc.available_months(conn)
    x.scope, x.entity, x.lo, x.hi, x.include_proposed = scope, entity, lo, hi, include_proposed
    x.available = ms
    x.months = eng.month_list(lo, hi)
    x.prev = add_months(lo, -1) if add_months(lo, -1) >= ms[0] else lo
    x.ext = eng.month_list(x.prev, hi)
    x.ctx = svc.run(conn, x.prev, hi, include_proposed, entity)
    x.cells = engine_cells(x.ctx["book"], x.ctx["items"], scope, entity, x.ext, x.ctx.get("reclass"))
    x.ns = net_sales(x.ctx["book"], entity, x.ext)
    x.heads = heads_of(scope)
    x.ly = None
    if with_ly:
        ly_months = [add_months(m, -12) for m in x.months]
        if ly_months[0] >= ms[0]:
            x.ly = svc.run(conn, ly_months[0], ly_months[-1], include_proposed, entity)
            x.ly_months = ly_months
            x.ly_cells = engine_cells(x.ly["book"], x.ly["items"], scope, entity, ly_months, x.ly.get("reclass"))
            x.ly_ns = net_sales(x.ly["book"], entity, ly_months)
    return x


def window_totals(x: X) -> dict:
    return {h: tot_of(x.cells, x.months, (h,)) for h in x.heads}


def database(request: Request):
    db = request.app.state.db
    if db is None or not hasattr(db, "rel"):
        raise HTTPException(503, "The expense review reads gold_fpa; start the API with FPA_SOURCE=gold")
    return db


def header(conn, x: X, extra: dict | None = None) -> dict:
    return {**svc.header(conn, x.entity), "scope": x.scope, "scope_label": SCOPE_LABEL[x.scope], "from_month": x.lo, "to_month": x.hi, "months": x.months, "include_proposed": x.include_proposed,
            "currency_note": "INR Cr; expenses are positive, a net credit is negative", **(extra or {})}


# ------------------------------------------------------------------ controls

def controls_engine(x: X) -> dict:
    """Store + DC + HO scope against the management P&L (/mgmt/pnl) for the same months and entity."""
    lines = {ln["key"]: ln for ln in x.ctx["lines"]}
    rows = []
    for layer in ("book", "adjustment", "total"):
        parts = {}
        for sc in ("store", "dc", "ho"):
            cells = x.cells if sc == x.scope else engine_cells(x.ctx["book"], x.ctx["items"], sc, x.entity, x.months, x.ctx.get("reclass"))
            t = tot_of(cells, x.months, heads_of(sc))
            parts[sc] = t["book"] if layer == "book" else t["adj"] if layer == "adjustment" else t["book"] + t["adj"]
        pnl = sum((-sum((lines[k]["values"][m][layer] + (lines[k]["values"][m].get("reclass", ZERO) if layer == "adjustment" else ZERO) for m in x.months), ZERO) for k in ("total_store_expenses", "dc_cost", "ho_cost")), ZERO)
        s = parts["store"] + parts["dc"] + parts["ho"]
        rows.append({"layer": layer, "store": q4(parts["store"]), "dc": q4(parts["dc"]), "ho": q4(parts["ho"]), "sum_of_scopes": q4(s), "mgmt_pnl": q4(pnl), "variance": q4(s - pnl), "ok": abs(s - pnl) <= TOL})
    return {"tolerance_cr": q4(TOL), "basis": "Store + DC + HO expense (this module) against total store expenses + DC cost + HO cost of /api/v1/mgmt/pnl, same months and entity",
            "rows": rows, "ok": all(r["ok"] for r in rows)}


def controls_rows(conn, x: X) -> dict:
    """Ledger x site rows (SQL on the base table) against the engine's book for the same scope: proves the drill rows add up to the heads table."""
    agg = fetch_aggregates(conn, x.prev, x.hi, x.scope)
    ok_e = ent_filter(x.entity)
    got: dict = defaultdict(D)
    for (ent, sc, gl, nm, h, grp), mm in agg["led"].items():
        if ok_e(ent):
            for m in x.months:
                if m in mm:
                    got[h] += mm[m][0]
    out = []
    for h in x.heads:
        eb = tot_of(x.cells, x.months, (h,))["book"]
        out.append({"head": h, "label": LABEL[h], "engine_book": q4(eb), "ledger_rows": q4(got.get(h, ZERO)), "variance": q4(got.get(h, ZERO) - eb), "ok": abs(got.get(h, ZERO) - eb) <= TOL})
    return {"tolerance_cr": q4(TOL), "scope": x.scope, "rows": out, "ok": all(r["ok"] for r in out)}


# ------------------------------------------------------------------ site build

def site_table(conn, x: X) -> dict:
    """Per-site expense by head and month (book + the adjustments allocated pro rata to net sales for stores), plus store meta, ns, peers, flags."""
    agg = fetch_aggregates(conn, x.prev, x.hi, x.scope)
    ok_e = ent_filter(x.entity)
    meta = fetch_store_meta(conn)
    sales = fetch_site_sales(conn, x.prev, x.hi) if x.scope == "store" else {}
    per: dict = defaultdict(lambda: {"heads": defaultdict(lambda: defaultdict(D))})
    for (ent, sc, gl, nm, h, grp), mm in agg["led"].items():
        if not ok_e(ent):
            continue
        s = per[(ent, sc)]
        for m, (v, _n) in mm.items():
            s["heads"][h][m] += v
    # adjustments: allocate (stores) pro rata to each store's share of the month's net sales; DC / HO adjustments stay unallocated
    adj_m: dict = defaultdict(D)     # (month, head) -> adjustment
    for (m, h), c in x.cells.items():
        adj_m[(m, h)] = c["adj0"]
    tot_ns = {m: sum((sales.get(sc, {}).get(m, ZERO) for sc in sales), ZERO) for m in x.ext} if x.scope == "store" else {}
    for (ent, sc), s in per.items():
        s["alloc"] = defaultdict(lambda: defaultdict(D))
        if x.scope == "store" and ent == "SUBCO":
            for m in x.ext:
                n = sales.get(sc, {}).get(m, ZERO)
                if n and tot_ns[m]:
                    for h in HEADS:
                        a = adj_m.get((m, h), ZERO)
                        if a:
                            s["alloc"][h][m] += a * n / tot_ns[m]
    # active corrections belong to their own site and month (not spread pro rata): add them to that site's management movement
    for rc in x.ctx.get("reclass") or []:
        sc_ = rc.get("site_code")
        if sc_ is None or not ok_e(rc["entity"]):
            continue
        hf, ht = head_of(x.scope, rc["location_type"], rc["key_from"]), head_of(x.scope, rc["location_type"], rc["key_to"])
        s_ = per.setdefault((rc["entity"], sc_), {"heads": defaultdict(lambda: defaultdict(D))})
        s_.setdefault("alloc", defaultdict(lambda: defaultdict(D)))
        a = rc["amount_cr"]
        if hf is not None and rc["month_from"] in x.ext:
            s_["alloc"][hf][rc["month_from"]] += a
        if ht is not None and rc["month_to"] in x.ext:
            s_["alloc"][ht][rc["month_to"]] -= a
    # sites with a sales row but no expense row still belong to the peer set
    if x.scope == "store" and ok_e("SUBCO"):
        for sc in sales:
            per.setdefault(("SUBCO", sc), {"heads": defaultdict(lambda: defaultdict(D)), "alloc": defaultdict(lambda: defaultdict(D))})
    W, last = x.months, x.hi
    prev = add_months(last, -1)
    fy = fy_start(last)
    rows = []
    for (ent, sc), s in per.items():
        book_h = {h: sum((s["heads"][h].get(m, ZERO) for m in W), ZERO) for h in x.heads}
        adj_h = {h: sum((s["alloc"][h].get(m, ZERO) for m in W), ZERO) for h in x.heads}
        tot_h = {h: book_h[h] + adj_h[h] for h in x.heads}
        total = sum(tot_h.values(), ZERO)
        if abs(total) < D("0.0005") and not (x.scope == "store" and ent == "SUBCO" and any(sales.get(sc, {}).get(m) for m in W)):
            continue
        month_tot = {m: sum((s["heads"][h].get(m, ZERO) + s["alloc"][h].get(m, ZERO) for h in x.heads), ZERO) for m in x.ext}
        nm, kind = agg["names"].get((ent, sc), (None, None))
        mt = meta.get(sc) if ent == "SUBCO" else None
        ns_w = sum((sales.get(sc, {}).get(m, ZERO) for m in W), ZERO) if (x.scope == "store" and ent == "SUBCO") else None
        opening = mt["opening_date"] if mt else None
        area = D(str(mt["area"])) if mt and mt["area"] and D(str(mt["area"])) > 0 else None
        mom = None
        if prev in month_tot and last in month_tot and prev in x.ext and month_tot[prev] != 0:
            mom = (month_tot[last] - month_tot[prev]) / abs(month_tot[prev]) * 100
        rows.append({
            "key": f"{ent}:{sc}", "entity": ent, "entity_label": ENTITY_NAME[ent], "voucher_entity": VOUCHER_ENTITY[ent], "site_code": sc,
            "short_name": (mt["short_name"] if mt else None) or nm, "name": (mt["store_name"] if mt else None) or nm, "site_kind": kind,
            "store_type": mt["store_type"] if mt else None, "state": mt["state"] if mt else None, "city": mt["city"] if mt else None,
            "opening_date": opening, "nso_ty": bool(opening and opening >= fy), "area_sqft": area,
            "net_sales": ns_w, "months_with_sales": sum(1 for m in W if sales.get(sc, {}).get(m)) if ns_w is not None else None,
            "book": book_h, "adj": adj_h, "heads_total": tot_h, "total": total, "book_total": sum(book_h.values(), ZERO), "adj_total": sum(adj_h.values(), ZERO),
            "last_month_total": month_tot.get(last), "prev_month_total": month_tot.get(prev) if prev in x.ext else None, "mom_pct": mom,
        })
    return {"rows": rows, "agg": agg, "adj_m": adj_m, "sales": sales}


def decorate(x: X, st: dict, head: str | None) -> dict:
    """Percentages, peer medians, ranks and flags on top of the site table."""
    rows = st["rows"]
    n_months = len(x.months)
    basis = (lambda r: r["heads_total"][head]) if head else (lambda r: r["total"])
    peers_note = ""
    if x.scope == "store":
        for r in rows:
            ns = r["net_sales"]
            r["pct_ns"] = (r["total"] / ns * 100) if ns else None
            r["pct_ns_heads"] = {h: (r["heads_total"][h] / ns * 100 if ns else None) for h in x.heads}
            r["per_sqft_month"] = (r["total"] * CR / r["area_sqft"] / n_months) if r["area_sqft"] else None
        lo_first = date(int(x.lo[:4]), int(x.lo[5:7]), 1)
        trade = [r for r in rows if r["entity"] == "SUBCO" and r["net_sales"] and r["net_sales"] > 0]
        full = [r for r in trade if not (r["opening_date"] and r["opening_date"] >= lo_first)]
        peers, peers_note = (full, "Peers: stores with net sales in the period that did not open inside it.") if len(full) >= 10 else (trade, "Peers: every store with net sales in the period (fewer than 10 full-period stores).")
        pv = lambda r: (r["heads_total"][head] / r["net_sales"] * 100) if head else r["pct_ns"]
        pcts = [float(pv(r)) for r in peers]
        med, p90 = median(pcts), pctile(pcts, 90)
        peer_heads = {}
        for h in x.heads:
            xs = [float(r["heads_total"][h] / r["net_sales"] * 100) for r in peers]
            peer_heads[h] = {"median_pct": q4(median(xs)) if xs else None, "p90_pct": q4(pctile(xs, 90)) if xs else None}
        ranked = sorted(trade, key=lambda r: -pv(r))
        rank = {r["key"]: i + 1 for i, r in enumerate(ranked)}
        for r in rows:
            r["rank"] = rank.get(r["key"])
            r["vs_peer_pp"] = (pv(r) - med) if (med is not None and r["net_sales"]) else None
            r["vs_peer_ratio"] = (pv(r) / med) if (med and r["net_sales"]) else None
        peer = {"n": len(peers), "basis": "pct_of_net_sales", "head": head, "median_pct": q4(med) if med is not None else None, "p90_pct": q4(p90) if p90 is not None else None, "heads": peer_heads,
                "method": "Median and 90th percentile (linear interpolation) of expense as % of net sales across the peer stores. " + peers_note, "ranked_stores": len(ranked)}
    else:
        bases = [basis(r) for r in rows]
        med = median([float(b) for b in bases])
        for r in rows:
            r["pct_ns"], r["pct_ns_heads"], r["per_sqft_month"] = None, {}, ((r["total"] * CR / r["area_sqft"] / n_months) if r["area_sqft"] else None)
            r["vs_peer_ratio"] = (basis(r) / med) if med else None
            r["vs_peer_pp"] = None
        ranked = sorted(rows, key=lambda r: -basis(r))
        rank = {r["key"]: i + 1 for i, r in enumerate(ranked)}
        for r in rows:
            r["rank"] = rank[r["key"]]
        peer = {"n": len(rows), "basis": "total_cr", "head": head, "median_cr": q4(med) if med is not None else None, "heads": {},
                "method": "Median total expense (INR Cr) across the sites of this scope in the period; the ratio column is the site total divided by that median.", "ranked_stores": len(rows)}
    # flags
    for r in rows:
        f = []
        if x.scope == "store" and r["entity"] == "SUBCO":
            if r["nso_ty"]:
                f.append(("nso_ty", "NSO TY: opened this financial year"))
            if not r["net_sales"]:
                f.append(("no_sales", "Expense with no net sales in the period: pre-opening, closed or a virtual site"))
            elif r.get("vs_peer_ratio") and peer["p90_pct"] is not None and r["pct_ns"] is not None and head is None and r["pct_ns"] > peer["p90_pct"] and r["vs_peer_ratio"] >= D("1.25"):
                f.append(("above_peer", f"Expense is {q4(r['pct_ns'])}% of net sales against a peer median of {peer['median_pct']}% and a 90th percentile of {peer['p90_pct']}%"))
            if r["area_sqft"] is None:
                f.append(("no_area", "No area in the store master: per sq ft not computed"))
        elif x.scope != "store" and r["entity"] == "HOLDCO":
            f.append(("no_area", "Citykart Ventures sites carry no area or master data in gold: per sq ft not computed"))
        if r["mom_pct"] is not None and r["mom_pct"] > 50 and (r["last_month_total"] - (r["prev_month_total"] or ZERO)) >= (D("0.03") if x.scope == "store" else D("0.05")):
            f.append(("mom_jump", f"Latest month is {float(r['mom_pct']):.1f}% above the month before"))
        if r["total"] < 0:
            f.append(("net_credit", "Net credit: the site's expense for the period is negative"))
        r["flags"] = [{"code": c, "text": t} for c, t in f]
    return peer


# ------------------------------------------------------------------ router

router = APIRouter(prefix="/expenses")
ENTITY = Query("consolidated", pattern="^(consolidated|subco|holdco)$")
SCOPE = Query("store", pattern="^(store|dc|ho)$")


@router.get("/summary")
def summary(request: Request, scope: str = SCOPE, from_month: str | None = None, to_month: str | None = None, entity: str = ENTITY, include_proposed: bool = True):
    with database(request).session("pnl") as conn:
        x = load(conn, scope, from_month, to_month, entity, include_proposed, with_ly=True)
        last = x.hi
        prev = add_months(last, -1)
        has_prev = prev in x.ext and prev >= x.available[0]
        ns_w = sum((x.ns[m] for m in x.months), ZERO) if scope == "store" else None
        n_sites = _site_count(conn, x) if scope != "store" else None
        rows = []
        tb = tot_of(x.cells, x.months, x.heads)
        grand = tb["book"] + tb["adj"]
        ly_tot = tot_of(x.ly_cells, x.ly_months, x.heads) if x.ly else None
        ly_ns = sum((x.ly_ns[m] for m in x.ly_months), ZERO) if (x.ly and scope == "store") else None

        def head_row(key, label, cells, ly_cells):
            t = tot_of(cells, x.months, (key,) if key else x.heads)
            tl = t["book"] + t["adj"]
            r = {"key": key or "total", "label": label, **triple(t["book"], t["adj"]),
                 "pct_ns": {"book": q4(t["book"] / ns_w * 100), "adjustment": q4(t["adj"] / ns_w * 100), "total": q4(tl / ns_w * 100)} if ns_w else None,
                 "share_pct": q4(tl / grand * 100) if grand else None,
                 "per_site_avg": q4(tl / n_sites) if n_sites else None}
            lm = sum((cells.get((last, h), {"book": ZERO, "adj": ZERO})["book"] + cells.get((last, h), {"book": ZERO, "adj": ZERO})["adj"] for h in ((key,) if key else x.heads)), ZERO)
            pm = sum((cells.get((prev, h), {"book": ZERO, "adj": ZERO})["book"] + cells.get((prev, h), {"book": ZERO, "adj": ZERO})["adj"] for h in ((key,) if key else x.heads)), ZERO)
            r["mom"] = {"last_month": last, "prev_month": prev, "last": q4(lm), "prev": q4(pm), "delta": q4(lm - pm), "delta_pct": q4((lm - pm) / abs(pm) * 100) if pm else None} if has_prev else None
            if x.ly:
                lt = tot_of(ly_cells, x.ly_months, (key,) if key else x.heads)
                ll = lt["book"] + lt["adj"]
                r["ly"] = {"total": q4(ll), "book": q4(lt["book"]), "delta": q4(tl - ll), "delta_pct": q4((tl - ll) / abs(ll) * 100) if ll else None,
                           "delta_pct_book": q4((t["book"] - lt["book"]) / abs(lt["book"]) * 100) if lt["book"] else None,
                           "pct_ns": q4(ll / ly_ns * 100) if ly_ns else None, "pct_ns_delta_pp": q4(tl / ns_w * 100 - ll / ly_ns * 100) if (ly_ns and ns_w) else None}
            else:
                r["ly"] = None
            return r
        for h in x.heads:
            rows.append(head_row(h, LABEL[h], x.cells, x.ly_cells if x.ly else None))
        if scope != "store":     # the COGS-type head only exists at DC / HO: hide it when empty
            rows = [r for r in rows if r["key"] != COGS_HEAD or r["total"] != 0 or r["book"] != 0]
        total = head_row(None, SCOPE_LABEL[scope], x.cells, x.ly_cells if x.ly else None)
        adj_months = sorted({m for (m, h), c in x.cells.items() if m in x.months and c["adj"] != 0})
        notes = []
        if entity == "holdco" and scope == "store":
            notes.append("Citykart Ventures (HoldCo) has no stores: store expenses are Citykart Stores (SubCo) only.")
        if entity == "consolidated" and scope == "store":
            notes.append("Store expenses are Citykart Stores (SubCo) only; HoldCo has no stores.")
        if not x.ly:
            notes.append(f"No last-year comparison: gold starts at {x.available[0]}, and last year for {x.lo} would be {add_months(x.lo, -12)}.")
        elif x.ly_months[0] < "2026-04":
            notes.append("Last-year months before 2026-04 carry books only (the management adjustment layer starts in 2026-04); the book-only change is shown beside the total change.")
        if adj_months:
            notes.append("Management adjustments in the period: " + ", ".join(adj_months) + ".")
        if x.ctx.get("reclass"):
            notes.append(f"{len(x.ctx['reclass'])} approved line corrections move cost between heads and months; their effect is inside the Adjustment column here (the Management P&L shows Reclass separately). The ledger and voucher drills still show the source postings.")
        pnl_w = [w for w in svc.warnings(conn, x.ctx) if "partial month" in w or "Citykart Ventures cost is missing" in w]
        return ok({**header(conn, x), "entity_label": {"consolidated": "Consolidated", "subco": "SubCo (Citykart Stores)", "holdco": "HoldCo (Citykart Ventures)"}[entity],
                   "net_sales": q4(ns_w) if ns_w is not None else None, "site_count": n_sites, "heads": rows, "total": total,
                   "ly_available": bool(x.ly), "ly_from_month": x.ly_months[0] if x.ly else None, "ly_to_month": x.ly_months[-1] if x.ly else None,
                   "adjustment_months": adj_months, "controls": controls_engine(x), "notes": notes, "warnings": pnl_w})


def _site_count(conn, x: X) -> int:
    agg = fetch_aggregates(conn, x.prev, x.hi, x.scope)
    ok_e = ent_filter(x.entity)
    return len({(e, s) for (e, s, *_r), mm in agg["led"].items() if ok_e(e) and any(m in mm for m in x.months)})


@router.get("/trend")
def trend(request: Request, scope: str = SCOPE, from_month: str | None = None, to_month: str | None = None, entity: str = ENTITY, include_proposed: bool = True):
    with database(request).session("pnl") as conn:
        x = load(conn, scope, from_month, to_month, entity, include_proposed)
        months = x.months
        series = []
        for h in x.heads:
            series.append({"key": h, "label": LABEL[h], "values": {m: triple(x.cells.get((m, h), {"book": ZERO})["book"], x.cells.get((m, h), {"adj": ZERO})["adj"]) for m in months}})
        if scope != "store":
            series = [s for s in series if s["key"] != COGS_HEAD or any(v["total"] or v["book"] for v in s["values"].values())]
        totals, ly_vals = {}, {}
        for m in months:
            t = tot_of(x.cells, [m], x.heads)
            totals[m] = triple(t["book"], t["adj"])
            ly_m = add_months(m, -12)
            if ly_m >= x.available[0]:
                ly_vals[m] = None
        # last year, month by month (one engine run over the whole window shifted by 12 months)
        have = [m for m in months if add_months(m, -12) >= x.available[0]]
        if have:
            lyx = svc.run(conn, add_months(have[0], -12), add_months(have[-1], -12), include_proposed, entity)
            lyc = engine_cells(lyx["book"], lyx["items"], scope, entity, [add_months(m, -12) for m in have], lyx.get("reclass"))
            for m in have:
                t = tot_of(lyc, [add_months(m, -12)], x.heads)
                ly_vals[m] = q4(t["book"] + t["adj"])
        ns = {m: q4(x.ns[m]) for m in months} if scope == "store" else None
        pct = {m: (q4((totals[m]["total"]) / x.ns[m] * 100) if x.ns.get(m) else None) for m in months} if scope == "store" else None
        return ok({**header(conn, x), "series": series, "total": totals, "net_sales": ns, "pct_ns": pct, "ly_total": ly_vals,
                   "note": "Months before 2026-04 are books only: the management adjustment layer starts in 2026-04."})


@router.get("/sites")
def sites(request: Request, scope: str = SCOPE, from_month: str | None = None, to_month: str | None = None, entity: str = ENTITY, head: str | None = Query(None, pattern="^[a-z_]+$"), include_proposed: bool = True):
    with database(request).session("pnl") as conn:
        x = load(conn, scope, from_month, to_month, entity, include_proposed)
        if head is not None and head not in x.heads:
            raise HTTPException(422, "unknown head")
        st = site_table(conn, x)
        peer = decorate(x, st, head)
        ns_tot = sum((x.ns[m] for m in x.months), ZERO)
        grand_t = tot_of(x.cells, x.months, x.heads)
        grand = grand_t["book"] + grand_t["adj"]
        basis = (lambda r: r["heads_total"][head]) if head else (lambda r: r["total"])
        rows = sorted(st["rows"], key=lambda r: -basis(r))
        out = []
        for r in rows:
            out.append({"key": r["key"], "entity": r["entity"], "entity_label": r["entity_label"], "voucher_entity": r["voucher_entity"], "site_code": r["site_code"],
                        "short_name": r["short_name"], "name": r["name"], "site_kind": r["site_kind"], "store_type": r["store_type"], "state": r["state"], "city": r["city"],
                        "opening_date": r["opening_date"], "nso_ty": r["nso_ty"], "area_sqft": r["area_sqft"],
                        "net_sales": q4(r["net_sales"]) if r["net_sales"] is not None else None, "months_with_sales": r["months_with_sales"],
                        "book": q4(r["book_total"]), "adjustment": q4(r["adj_total"]), "total": q4(r["total"]),
                        "heads": {h: triple(r["book"][h], r["adj"][h]) for h in x.heads},
                        "pct_ns": q4(r["pct_ns"]) if r["pct_ns"] is not None else None,
                        "pct_ns_heads": {h: (q4(v) if v is not None else None) for h, v in r["pct_ns_heads"].items()},
                        "per_sqft_month": q4(r["per_sqft_month"]) if r["per_sqft_month"] is not None else None,
                        "share_pct": q4(r["total"] / grand * 100) if grand else None,
                        "vs_peer_pp": q4(r["vs_peer_pp"]) if r["vs_peer_pp"] is not None else None, "vs_peer_ratio": q4(r["vs_peer_ratio"]) if r["vs_peer_ratio"] is not None else None,
                        "rank": r["rank"], "mom_pct": q4(D(r["mom_pct"])) if r["mom_pct"] is not None else None,
                        "last_month": q4(r["last_month_total"]) if r["last_month_total"] is not None else None, "prev_month": q4(r["prev_month_total"]) if r["prev_month_total"] is not None else None,
                        "flags": r["flags"]})
        children = sum((r["total"] for r in rows), ZERO)
        unalloc = grand - children
        return ok({**header(conn, x), "head": head, "head_label": LABEL[head] if head else None, "net_sales": q4(ns_tot) if scope == "store" else None, "sites": out, "peer": peer,
                   "parent": {"total": q4(grand)}, "children_sum": {"total": q4(children)}, "unallocated": {"total": q4(unalloc), "note": "Management adjustments that are not attributable to one site: DC and HO adjustments, and store adjustments in months without store sales."},
                   "reconciles": abs(unalloc) <= TOL if scope == "store" else True,
                   "area_note": "Per sq ft is INR per sq ft per month on the area in the store master (gold dim_site.area, taken as sq ft); not computed where the master has no area or the site is Citykart Ventures.",
                   "flag_legend": {"nso_ty": "NSO TY: store opened in this financial year", "above_peer": "Above the 90th percentile of peers and at least 1.25 times their median", "mom_jump": "Latest month more than 50% above the month before",
                                   "no_sales": "Expense but no net sales", "net_credit": "Net credit in the period", "no_area": "No area in the master"}})


def _site_arg(site: int | None, site_entity: str | None, entity: str) -> str | None:
    if site is None:
        return None
    if site_entity:
        return site_entity.upper()
    return "HOLDCO" if entity == "holdco" else "SUBCO"


@router.get("/ledgers")
def ledgers(request: Request, scope: str = SCOPE, from_month: str | None = None, to_month: str | None = None, entity: str = ENTITY, head: str | None = Query(None, pattern="^[a-z_]+$"),
            site: int | None = Query(None, ge=0), site_entity: str | None = Query(None, pattern="^(subco|holdco|SUBCO|HOLDCO)$"), glcode: int | None = Query(None, ge=0),
            include_proposed: bool = True, limit: int = Query(300, ge=1, le=2000)):
    """Without glcode: one row per ledger (optionally at one site / one head). With glcode: that ledger broken down by site."""
    with database(request).session("pnl") as conn:
        x = load(conn, scope, from_month, to_month, entity, include_proposed)
        if head is not None and head not in x.heads:
            raise HTTPException(422, "unknown head")
        agg = fetch_aggregates(conn, x.prev, x.hi, x.scope)
        ok_e = ent_filter(x.entity)
        site_ent = _site_arg(site, site_entity, entity)
        by: dict = {}
        for (ent, sc, gl, nm, h, grp), mm in agg["led"].items():
            if not ok_e(ent) or (head and h != head) or (glcode is not None and gl != glcode):
                continue
            if site is not None and (sc != site or ent != site_ent):
                continue
            amt = sum((mm[m][0] for m in x.months if m in mm), ZERO)
            lines = sum((mm[m][1] for m in x.months if m in mm), 0)
            if lines == 0 and amt == 0:
                continue
            k = (ent, sc) if glcode is not None else (gl, nm, h, grp)
            r = by.setdefault(k, {"amount": ZERO, "lines": 0, "sites": set(), "months": set(), "ent": ent, "sc": sc, "gl": gl, "nm": nm, "h": h, "grp": grp, "ents": set()})
            r["amount"] += amt
            r["lines"] += lines
            r["sites"].add((ent, sc))
            r["ents"].add(ent)
            r["months"].update(m for m in x.months if m in mm)
        # parent: the heads table (or the site's own head total)
        t_head = tot_of(x.cells, x.months, (head,) if head else x.heads)
        if site is not None:
            st = site_table(conn, x)
            sr = next((r for r in st["rows"] if r["entity"] == site_ent and r["site_code"] == site), None)
            parent = (sr["heads_total"][head] if head else sr["total"]) if sr else ZERO
            alloc = (sr["adj"][head] if head else sr["adj_total"]) if sr else ZERO
        else:
            parent = t_head["book"] + t_head["adj"]
            alloc = None
        ns_total = sum((x.ns[m] for m in x.months), ZERO) if scope == "store" else None
        rows = []
        book_sum = sum((r["amount"] for r in by.values()), ZERO)
        meta = fetch_store_meta(conn)
        for k, r in sorted(by.items(), key=lambda kv: -abs(kv[1]["amount"]))[:limit]:
            base = {"amount_cr": q4(r["amount"]), "lines": r["lines"], "share_pct": q4(r["amount"] / book_sum * 100) if book_sum else None, "months_active": len(r["months"])}
            if glcode is not None:
                mt = meta.get(r["sc"]) if r["ent"] == "SUBCO" else None
                rows.append({**base, "kind": "site", "site_code": r["sc"], "site_entity": r["ent"], "voucher_entity": VOUCHER_ENTITY[r["ent"]], "ledger_code": r["gl"], "ledger_name": r["nm"], "head": r["h"],
                             "site_name": (mt["short_name"] if mt else None) or agg["names"].get((r["ent"], r["sc"]), (None,))[0]})
            else:
                ent = next(iter(r["ents"])) if len(r["ents"]) == 1 else None
                rows.append({**base, "kind": "ledger", "ledger_code": r["gl"], "ledger_name": r["nm"], "head": r["h"], "head_label": LABEL[r["h"]], "mgmt_group": r["grp"], "sites": len(r["sites"]),
                             "pct_ns": q4(r["amount"] / ns_total * 100) if ns_total else None,
                             "site_code": site, "site_entity": site_ent if site is not None else None, "voucher_entity": VOUCHER_ENTITY[site_ent] if site is not None else (VOUCHER_ENTITY[ent] if ent else None)})
        adjustments = []
        if site is None and glcode is None:
            ok_i = ent_filter(entity)
            for it in sorted(x.ctx["items"], key=lambda i: (i["month"], i["id"])):
                if it["month"] in x.months and ok_i(it["entity"]) and not (it["kind"] == "elimination" and entity != "consolidated"):
                    h = head_of(scope, it["location_type"], it["mis_line"])
                    if h and (not head or h == head):
                        adjustments.append({"id": it["id"], "month": it["month"], "head": h, "head_label": LABEL[h], "amount_cr": q4(-it["amount_cr"]), "kind": it["kind"], "status": it["status"], "rule": it["rule"], "note": it["note"],
                                            "entity": it["entity"], "provisional": it["provisional"]})
        adj_sum = sum((a["amount_cr"] for a in adjustments), ZERO)
        if site is not None:
            children = book_sum + alloc
        elif glcode is not None:
            children = book_sum
        else:
            children = book_sum + adj_sum
        parent_cmp = parent if glcode is None else book_sum
        return ok({**header(conn, x), "head": head, "head_label": LABEL[head] if head else None, "site": site, "site_entity": site_ent, "glcode": glcode,
                   "grain": "site" if glcode is not None else "ledger", "rows": rows, "row_count": len(by), "truncated": len(by) > limit,
                   "adjustments": adjustments, "allocated_adjustment": {"amount_cr": q4(alloc), "note": "Management adjustments allocated to this site pro rata to its share of store net sales (as /mgmt/stores does)."} if alloc is not None else None,
                   "parent": {"total": q4(parent_cmp), "book": q4(t_head["book"]) if site is None and glcode is None else None}, "children_sum": {"total": q4(children)},
                   "reconciles": abs(children - parent_cmp) <= TOL if len(by) <= limit else None,
                   "voucher_note": "Each ledger row opens the voucher list for the ledger at the site; the lines count is the number of cost-tag lines behind the amount."})


@router.get("/exceptions")
def exceptions(request: Request, scope: str = SCOPE, from_month: str | None = None, to_month: str | None = None, entity: str = ENTITY, include_proposed: bool = True,
               mom_threshold: float = Query(0.5, ge=0.05, le=10), limit: int = Query(200, ge=1, le=1000)):
    with database(request).session("pnl") as conn:
        x = load(conn, scope, from_month, to_month, entity, include_proposed)
        agg = fetch_aggregates(conn, x.prev, x.hi, x.scope)
        ok_e = ent_filter(x.entity)
        meta = fetch_store_meta(conn)
        sales = fetch_site_sales(conn, x.prev, x.hi) if scope == "store" else {}
        W = x.months
        last, prev = x.hi, add_months(x.hi, -1)
        out: list = []

        def site_label(ent, sc):
            mt = meta.get(sc) if ent == "SUBCO" else None
            return (mt["short_name"] if mt else None) or agg["names"].get((ent, sc), (None,))[0] or f"Site {sc}"

        def add(rule, sev, ent, sc, head, gl, nm, amount, metric, month=None, extra=None):
            out.append({"rule_id": rule, "severity": sev, "entity": ent, "voucher_entity": VOUCHER_ENTITY[ent] if ent else None, "site_code": sc, "site_name": site_label(ent, sc) if sc is not None else None,
                        "head": head, "head_label": LABEL.get(head) if head else None, "ledger_code": gl, "ledger_name": nm, "month": month, "amount_cr": q4(amount) if amount is not None else None,
                        "metric": metric, "from_month": x.lo, "to_month": x.hi, **(extra or {})})
        # 1. ledger above peers (stores)
        if scope == "store":
            by_led: dict = defaultdict(list)
            for (ent, sc, gl, nm, h, grp), mm in agg["led"].items():
                if ent != "SUBCO" or not ok_e(ent):
                    continue
                amt = sum((mm[m][0] for m in W if m in mm), ZERO)
                ns = sum((sales.get(sc, {}).get(m, ZERO) for m in W), ZERO)
                if ns > 0 and amt > 0:
                    by_led[(gl, nm, h)].append((sc, amt, ns, amt / ns * 100))
            for (gl, nm, h), lst in by_led.items():
                if len(lst) < 10:
                    continue
                vals = [float(v[3]) for v in lst]
                med, p95 = median(vals), pctile(vals, 95)
                for sc, amt, ns, pc in lst:
                    excess = amt - med * ns / 100
                    if pc > p95 and med > 0 and pc >= 3 * med and excess >= D("0.02"):
                        add("SITE_ABOVE_PEER", "high" if excess >= D("0.1") else "medium", "SUBCO", sc, h, gl, nm, amt,
                            f"{q4(pc)}% of net sales against a peer median of {q4(med)}% and a 95th percentile of {q4(p95)}% ({len(lst)} stores book this ledger); {q4(excess)} Cr above the median level",
                            extra={"peer_median_pct": q4(med), "peer_p95_pct": q4(p95), "pct_ns": q4(pc), "excess_cr": q4(excess)})
        # 2. month-on-month jump (site x head)
        site_head: dict = defaultdict(lambda: defaultdict(D))
        for (ent, sc, gl, nm, h, grp), mm in agg["led"].items():
            if ok_e(ent):
                for m, (v, _n) in mm.items():
                    site_head[(ent, sc, h)][m] += v
        floor = D("0.03") if scope == "store" else D("0.05")
        if prev in x.ext and prev >= x.available[0]:
            for (ent, sc, h), mm in site_head.items():
                a, b = mm.get(last, ZERO), mm.get(prev, ZERO)
                if b > 0 and a - b >= floor and (a - b) / b > D(str(mom_threshold)):
                    add("MOM_JUMP", "high" if (a - b) >= floor * 5 else "medium", ent, sc, h, None, None, a - b,
                        f"{LABEL[h]} {q4(a)} Cr in {last} against {q4(b)} Cr in {prev}: +{float((a - b) / b * 100):.1f}%", month=last, extra={"last": q4(a), "prev": q4(b), "delta_pct": q4((a - b) / b * 100)})
        # 3. credits in expense heads (site x ledger, period net)
        for (ent, sc, gl, nm, h, grp), mm in agg["led"].items():
            if not ok_e(ent):
                continue
            amt = sum((mm[m][0] for m in W if m in mm), ZERO)
            if amt <= -D("0.001"):
                add("CREDIT_IN_EXPENSE", "high" if amt <= -D("0.05") else "medium", ent, sc, h, gl, nm, amt, f"Net credit of {q4(-amt)} Cr in {LABEL[h]} for the period")
        # 4. same ledger booked twice in a month (voucher register)
        glcodes = sorted({gl for (e, s, gl, *_r) in agg["led"] if ok_e(e)})
        if glcodes:
            vent = [VOUCHER_ENTITY[e] for e in ("SUBCO", "HOLDCO") if ok_e(e)]
            kinds = list(SCOPE_KINDS[scope]) + (["VIRTUAL"] if scope == "ho" else [])
            dup = svc.cached(("exp_dup", x.lo, x.hi, scope, tuple(vent)), lambda: conn.execute(
                "SELECT entity, tag_site_code AS site_code, glcode, max(glname) AS glname, to_char(date_trunc('month', entdt), 'YYYY-MM') AS month, round(abs(profit_effect), 2) AS amt, count(DISTINCT entcode) AS vouchers "
                "FROM gold_fpa.voucher_lines WHERE entdt >= %s AND entdt < %s AND entity = ANY(%s) AND site_kind = ANY(%s) AND glcode = ANY(%s) AND abs(profit_effect) >= 50000 "
                "GROUP BY 1, 2, 3, 5, 6 HAVING count(DISTINCT entcode) = 2 ORDER BY 6 DESC LIMIT 400",
                (svc.mdate(x.lo), svc.mdate(add_months(x.hi, 1)), vent, kinds, glcodes)).fetchall())
            heads_by_gl = {(e, gl): h for (e, s, gl, nm, h, grp) in agg["led"]}
            for r in dup:
                ent = "HOLDCO" if r["entity"] == "VENTURES" else "SUBCO"
                h = heads_by_gl.get((ent, r["glcode"]))
                if h is None:
                    continue
                a = D(str(r["amt"])) / CR
                add("DUPLICATE_BOOKING", "high" if a >= D("0.05") else "medium", ent, r["site_code"], h, r["glcode"], r["glname"], a,
                    f"Two vouchers post Rs {D(str(r['amt'])):,.0f} on {r['glname']} at the same site in {r['month']}", month=r["month"], extra={"rupees": r["amt"]})
        # 5. unmapped ledgers at sites of this scope
        for (ent, sc, gl, nm, why), mm in agg["unmapped"].items():
            if not ok_e(ent):
                continue
            amt = sum((v for m, v in mm.items() if m in W), ZERO)
            if abs(amt) >= D("0.0005"):
                add("UNMAPPED_LEDGER", "medium", ent, sc, None, gl, nm, -amt, f"{nm}: {why}; {q4(-amt)} Cr outside the P&L for the period", extra={"reason": why, "likely_intercompany": any(h in nm.lower() for h in cfg.INTERCO_HINTS)})
        order = {"high": 0, "medium": 1, "low": 2}
        out.sort(key=lambda e: (order[e["severity"]], -abs(e["amount_cr"] or ZERO)))
        counts = defaultdict(int)
        for e in out:
            counts[e["rule_id"]] += 1
        return ok({**header(conn, x), "rules": [{**r, "count": counts.get(r["id"], 0)} for r in RULES if scope == "store" or r["id"] != "SITE_ABOVE_PEER"], "counts": dict(counts), "total": len(out),
                   "exceptions": out[:limit], "truncated": len(out) > limit, "mom_threshold": mom_threshold,
                   "note": "Exceptions are review prompts from stated rules, not findings of error."})


@router.get("/controls")
def controls(request: Request, scope: str = SCOPE, from_month: str | None = None, to_month: str | None = None, entity: str = ENTITY, include_proposed: bool = True):
    with database(request).session("pnl") as conn:
        x = load(conn, scope, from_month, to_month, entity, include_proposed)
        eng_c = controls_engine(x)
        led_c = controls_rows(conn, x)
        return ok({**header(conn, x), "scopes_vs_mgmt_pnl": eng_c, "ledger_rows_vs_engine": led_c, "ok": eng_c["ok"] and led_c["ok"]})
