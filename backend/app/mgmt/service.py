"""Reads gold_fpa (grouped SQL on the base tables, never the heavy pnl.v_* views) and runs the management engine. Read-only."""
from __future__ import annotations

import re
import threading
import time
from datetime import date
from decimal import Decimal as D

from . import config as cfg
from . import engine as eng

TTL = 120
_cache: dict = {}
_lock = threading.Lock()
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
HOLDCO_SQL = ("CASE WHEN left(upper(coalesce(d.short_name, '')), 5) = 'CKVPL' OR left(upper(coalesce(d.short_name, '')), 4) = 'CRPL' "
              "OR upper(coalesce(d.initial_name, '')) = 'CKVPL' THEN 'HOLDCO' ELSE 'SUBCO' END")
HOLDCO_COL_SQL = "CASE WHEN upper(p.entity) ~ 'VENTURE|HOLDCO|CKVPL|CRPL' THEN 'HOLDCO' ELSE 'SUBCO' END"


def cached(key, fn):
    now = time.time()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < TTL:
            return hit[1]
    val = fn()
    with _lock:
        _cache[key] = (now, val)
    return val


def mdate(m: str) -> date:
    return date(int(m[:4]), int(m[5:7]), 1)


def detect(conn) -> dict:
    """Pluggable entity source: does gold carry an entity column or intercompany / loan tables yet?"""
    def go():
        has_col = conn.execute("SELECT 1 FROM information_schema.columns WHERE table_schema = 'gold_fpa' AND table_name = 'pnl_store_month' AND column_name = 'entity'").fetchone() is not None
        tabs = [r["table_name"] for r in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'gold_fpa' AND (table_name ILIKE ANY(%s)) ORDER BY 1", (["%entity%", "%interco%", "%loan%", "%elimin%"],)).fetchall()]
        return {"pnl_has_entity": has_col, "tables": tabs}
    return cached("detect", go)


def available_months(conn) -> list[str]:
    return cached("months", lambda: [r["m"] for r in conn.execute("SELECT to_char(month, 'YYYY-MM') AS m FROM gold_fpa.pnl_store_month GROUP BY 1 ORDER BY 1").fetchall()])


def as_of(conn) -> date:
    return cached("asof", lambda: conn.execute("SELECT max(last_bill) AS d FROM gold_fpa.cogs_store_month WHERE last_bill <= current_date").fetchone()["d"])


def fetch_book(conn, lo: str, hi: str) -> eng.Book:
    det = detect(conn)

    def go():
        sl = cfg.site_loc()
        ent = HOLDCO_COL_SQL if det["pnl_has_entity"] else HOLDCO_SQL
        rows = conn.execute(
            f"SELECT to_char(p.month, 'YYYY-MM') AS month, p.site_kind, CASE WHEN p.site_code = ANY(%s::int[]) THEN p.site_code END AS site_code, {ent} AS entity, "
            "p.glname, p.fin_group, p.is_mapped, sum(p.profit_effect) AS pe FROM gold_fpa.pnl_store_month p LEFT JOIN gold_fpa.dim_site d ON d.site_code = p.site_code "
            "WHERE p.month >= %s AND p.month <= %s GROUP BY 1, 2, 3, 4, 5, 6, 7", (list(sl), mdate(lo), mdate(hi))).fetchall()
        cg = conn.execute("SELECT to_char(month, 'YYYY-MM') AS month, sum(net_sales_ex_gst) AS ns, sum(cogs_v) AS cogs FROM gold_fpa.cogs_store_month "
                          "WHERE site_kind = 'STORE' AND month >= %s AND month <= %s GROUP BY 1", (mdate(lo), mdate(hi))).fetchall()
        return eng.build_book(rows, cg, cfg.ledger_map(), sl)
    return cached(("book", lo, hi, det["pnl_has_entity"]), go)


def gold_eliminations(conn, months: list[str]) -> list[dict]:
    """Hook: gold_fpa.mgmt_eliminations(month, entity, counterparty, mis_line, location_type, amount_cr), if the extraction ever delivers it."""
    det = detect(conn)
    if "mgmt_eliminations" not in det["tables"]:
        return []
    rows = conn.execute("SELECT to_char(month, 'YYYY-MM') AS month, entity, counterparty, mis_line, location_type, amount_cr FROM gold_fpa.mgmt_eliminations "
                        "WHERE month >= %s AND month <= %s", (mdate(months[0]), mdate(months[-1]))).fetchall()
    return [{"id": f"GOLD-ELIM-{i}", "month": r["month"], "entity": (r["entity"] or "SUBCO").upper(), "counterparty": r["counterparty"], "mis_line": r["mis_line"],
             "location_type": r["location_type"], "amount": D(str(r["amount_cr"])), "kind": "elimination", "status": "confirmed", "rule": "gold_fpa.mgmt_eliminations",
             "owner": "Extraction", "source": "gold_fpa", "note": ""} for i, r in enumerate(rows)]


def default_window(conn) -> tuple[str, str]:
    ms = available_months(conn)
    hi = ms[-1]
    y = int(hi[:4]) - (1 if int(hi[5:7]) < 4 else 0)
    return max(f"{y}-04", ms[0]), hi


def check_window(conn, lo: str | None, hi: str | None) -> tuple[str, str]:
    dlo, dhi = default_window(conn)
    lo, hi = lo or dlo, hi or dhi
    if not (MONTH_RE.match(lo) and MONTH_RE.match(hi)):
        raise ValueError("months are written YYYY-MM")
    if lo > hi:
        raise ValueError("from_month is after to_month")
    if (int(hi[:4]) - int(lo[:4])) * 12 + int(hi[5:7]) - int(lo[5:7]) > 35:
        raise ValueError("window is limited to 36 months")
    return lo, hi


def run(conn, lo: str, hi: str, include_proposed: bool = True, entity: str = "consolidated") -> dict:
    if entity not in ("consolidated", "subco", "holdco"):
        raise ValueError("entity is consolidated, subco or holdco")
    months = eng.month_list(lo, hi)
    book = fetch_book(conn, lo, hi)
    rules = cfg.rules()
    register = cfg.adjustments()
    elim = gold_eliminations(conn, months)
    items = eng.evaluate_adjustments(book, months, register + elim, rules, include_proposed, last_month=available_months(conn)[-1])
    calc = eng.compute_pnl(book, items, months, entity)
    lines = eng.shape_lines(calc, months)
    return {"months": months, "book": book, "items": items, "calc": calc, "lines": lines, "rules": rules, "register": register + elim, "entity": entity}


def warnings(conn, ctx: dict) -> list[str]:
    book, items, months, register = ctx["book"], ctx["items"], ctx["months"], ctx["register"]
    w: list[str] = []
    det = detect(conn)
    sg_months = {r["month"] for r in register if r["kind"] == "stopgap_entity" and r["status"] != "in_books"}
    in_gold = book.holdco_months
    inm = sorted(in_gold & set(months))
    if det["pnl_has_entity"]:
        w.append("gold_fpa.pnl_store_month carries an entity column: entity is taken from it, not from the site name.")
    if inm:
        w.append("Citykart Ventures (HoldCo) postings found in gold_fpa for " + ", ".join(inm) + ": used in preference to the workbook stop-gap.")
    if set(months) - in_gold and sg_months & (set(months) - in_gold):
        w.append("Citykart Ventures not in gold: stop-gap from workbook (HoldCo cost, excluding interest income and finance cost, shown as adjustments).")
    missing = [m for m in months if m not in sg_months and m not in in_gold and m >= "2026-04"]
    if missing:
        w.append("Citykart Ventures cost is missing for " + ", ".join(missing) + " (no workbook stop-gap and not in gold): corporate EBITDA is overstated by about 3 Cr a month.")
    pre = [m for m in months if m < ctx["rules"]["cogs_correction"]["from_month"]]
    if pre:
        w.append("Months before " + ctx["rules"]["cogs_correction"]["from_month"] + " have no management layer (" + ", ".join(pre[:3]) + (" ..." if len(pre) > 3 else "") + "): books only.")
    exc = [e for e in book.exceptions.values() if abs(e["amount_cr"]) >= D("0.00005") and e["months"] & set(months)]
    if exc:
        tot = sum((e["amount_cr"] for e in exc), D(0))
        w.append(f"{len(exc)} ledgers unmapped (not in the P&L, net {eng.q4(tot)} Cr); see /api/v1/mgmt/mapping.")
        ic = [e for e in exc if any(h in e["ledger"].lower() for h in cfg.INTERCO_HINTS)]
        if ic:
            w.append(f"{len(ic)} unmapped ledgers look like intercompany charges (" + ", ".join(e["ledger"] for e in ic[:4]) + ").")
    prov = [i for i in items if i["provisional"]]
    if prov:
        w.append(f"Provisional adjustments included: {len(prov)} rows (status proposed or stopgap), {eng.q4(sum((i['amount_cr'] for i in prov), D(0)))} Cr net.")
    elim = [r for r in register if r["kind"] == "elimination"]
    if not elim:
        w.append("Intercompany expense and loan eliminations not loaded." + (" Gold tables to review: " + ", ".join(det["tables"]) + "." if det["tables"] else ""))
    elif det["tables"]:
        w.append("Gold tables with entity / intercompany / loan names detected: " + ", ".join(det["tables"]) + ".")
    if abs(book.non_store_revenue) >= D("0.0005"):
        w.append(f"Revenue outside store sites ({eng.q4(book.non_store_revenue)} Cr) is not part of MIS revenue.")
    if abs(book.unclassified) >= D("0.0005"):
        w.append(f"Postings at unclassified site kinds excluded: {eng.q4(book.unclassified)} Cr.")
    last = available_months(conn)[-1]
    asof = as_of(conn)
    if last in months and asof and asof.strftime("%Y-%m") == last and (asof.day < 28):
        w.append(f"{last} is a partial month (data to {asof.isoformat()}).")
    f = cfg.files_present()
    absent = [n for n, ok_ in f.items() if not ok_ and n != "rules.json"]
    if absent:
        w.append("Config files missing in config/mgmt: " + ", ".join(absent) + " (run tools/mgmt/seed_from_workbook.py).")
    return w


def header(conn, entity: str = "consolidated") -> dict:
    asof = as_of(conn)
    return {"run_id": "MGMT-" + asof.strftime("%Y%m%d"), "as_of_date": asof.isoformat(), "entity": entity, "currency": "INR Cr"}


def stores(conn, ctx: dict) -> dict:
    lo, hi = ctx["months"][0], ctx["months"][-1]

    def go():
        sr = conn.execute("SELECT to_char(month, 'YYYY-MM') AS month, site_code, glname, fin_group, is_mapped, sum(profit_effect) AS pe FROM gold_fpa.pnl_store_month "
                          "WHERE site_kind = 'STORE' AND month >= %s AND month <= %s GROUP BY 1, 2, 3, 4, 5", (mdate(lo), mdate(hi))).fetchall()
        cs = conn.execute("SELECT to_char(month, 'YYYY-MM') AS month, site_code, sum(net_sales_ex_gst) AS ns, sum(cogs_v) AS cogs FROM gold_fpa.cogs_store_month "
                          "WHERE site_kind = 'STORE' AND month >= %s AND month <= %s GROUP BY 1, 2", (mdate(lo), mdate(hi))).fetchall()
        return sr, cs
    sr, cs = cached(("stores", lo, hi), go)
    names = cached("names", lambda: {r["site_code"]: r for r in conn.execute("SELECT site_code, short_name, store_name, store_type FROM gold_fpa.dim_site").fetchall()})
    return eng.build_stores(sr, cs, names, ctx["items"], ctx["months"], ctx["lines"], cfg.ledger_map(), ctx["entity"])
