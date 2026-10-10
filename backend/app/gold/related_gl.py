"""Every GL register entry between Citykart Ventures (HoldCo, gold entity VENTURES) and Citykart Stores (SubCo, entity RETAIL), read-only.

A voucher line is related-party if (a) its party (voucher_lines.vendor_name) matches config/mgmt/related_party_names.csv for THAT entity, or (b) its ledger is in
config/mgmt/intercompany_ledgers.csv (the loan / interest / service ledgers; the service ledgers carry no party name). Codes collide across entities, so every match is on
(entity, slcode) or (entity, glcode), never on slcode alone. Entries are grouped one per (entity, entcode).

names CSV columns: books_of_entity (RETAIL | VENTURES), party_pattern (case-insensitive regex on vendor_name; first matching row wins), counterparty_entity (HOLDCO | SUBCO |
SAME_COMPANY), status (proposed | confirmed), note. SAME_COMPANY = the company's own other GST registration (e.g. SubCo's ISD): listed separately, never a counterparty.
Matched lines are cached for 5 minutes (the party match scans voucher_lines once).
"""
from __future__ import annotations

import csv
import logging
import os
import re
import threading
import time
from decimal import Decimal
from pathlib import Path

from . import intercompany as ic

log = logging.getLogger(__name__)
ROOT = ic.ROOT
ZERO = Decimal(0)
ENTITIES = ("RETAIL", "VENTURES")
COUNTERPARTIES = ("HOLDCO", "SUBCO", "SAME_COMPANY")
TTL = 300
_names: list[dict] | None = None
_cache: dict = {}
_lock = threading.Lock()


def path() -> Path:
    return Path(os.environ.get("FPA_RELATED_PARTY_NAMES") or ROOT / "config" / "mgmt" / "related_party_names.csv")


def pg_pattern(pat: str) -> str:
    r"""Translate a register pattern (Python regex) to Postgres ARE for the SQL prefilter, or raise ValueError when it has no equivalent.
    Postgres reads \b as a backspace (word boundary is \y), accepts embedded options only at the very start, and has no (?P<name>..) groups.
    Matching is case-insensitive anyway (~*), so a leading (?i) is dropped."""
    if "(?P" in pat or re.search(r"\(\?[aiLmsux]+[:)]", pat[1:]):
        raise ValueError(f"pattern {pat!r} uses Python-only regex syntax")
    pat = re.sub(r"^\(\?i\)", "", pat)
    return re.sub(r"\\(.)", lambda m: {"b": "\\y", "B": "\\Y"}.get(m.group(1), m.group(0)), pat)



def parse(text: str) -> list[dict]:
    """Rows need a valid entity, a compilable regex and a known counterparty; others are skipped."""
    out = []
    for row in csv.DictReader(text.splitlines()):
        row = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
        ent, pat, cp = row.get("books_of_entity", "").upper(), row.get("party_pattern", ""), row.get("counterparty_entity", "").upper()
        if ent not in ENTITIES or not pat or cp not in COUNTERPARTIES:
            continue
        try:
            re.compile(pat)
            pg_pattern(pat)
        except (re.error, ValueError):
            log.warning("related_party_names: bad pattern %r skipped", pat)
            continue
        st = row.get("status", "").lower()
        out.append({"books_of_entity": ent, "party_pattern": pat, "counterparty_entity": cp, "status": st if st in ic.STATUSES else "proposed", "note": row.get("note", "")})
    return out


def load(force: bool = False) -> list[dict]:
    global _names
    if _names is None or force:
        p = path()
        if p.exists():
            _names = parse(p.read_text(encoding="utf-8-sig"))
        else:
            log.warning("related-party name register %s not found: only the intercompany ledgers are matched", p)
            _names = []
    return _names


def reload() -> list[dict]:
    global _cache
    _cache = {}
    return load(force=True)


def clear_cache() -> None:
    _cache.clear()


def match_party(names: list[dict], entity: str, vendor_name: str | None) -> dict | None:
    """First register row for this entity whose pattern matches the party name."""
    if not vendor_name:
        return None
    for n in names:
        if n["books_of_entity"] == entity and re.search(n["party_pattern"], vendor_name, re.I):
            return n
    return None


def _month(d) -> str:
    return d.strftime("%Y-%m") if d else "undated"


def classify(names: list[dict], ledgers: list[dict], raw: list[dict]) -> list[dict]:
    """Pure: tag raw voucher lines (already narrowed in SQL) with reason / counterparty. Lines that match neither rule are dropped."""
    led = {(l["entity"], l["glcode"]): l for l in ledgers}
    out = []
    for r in raw:
        n = match_party(names, r["entity"], r.get("vendor_name"))
        l = led.get((r["entity"], r["glcode"]))
        if n:
            reason, cp, status = "party", n["counterparty_entity"], n["status"]
        elif l:
            reason, cp, status = "ledger:" + l["role"], ("SUBCO" if r["entity"] == "VENTURES" else "HOLDCO"), l["status"]
        else:
            continue
        out.append({**r, "month": _month(r["entdt"]), "reason": reason, "counterparty_entity": cp, "register_status": status, "ledger_role": l["role"] if l else None})
    return out


def fetch_lines(conn, names: list[dict], ledgers: list[dict]) -> list[dict]:
    """Related-party lines of both books. One scan finds the party codes per entity; the lines then come from the slcode / glcode indexes."""
    sl: dict[str, set] = {e: set() for e in ENTITIES}
    if names:
        rx = "|".join(f"(?:{pg_pattern(n['party_pattern'])})" for n in names)
        for r in conn.execute("SELECT entity, slcode, vendor_name FROM gold_fpa.voucher_lines WHERE vendor_name ~* %s GROUP BY 1, 2, 3", (rx,)).fetchall():
            if match_party(names, r["entity"], r["vendor_name"]) and r["slcode"] is not None:
                sl[r["entity"]].add(r["slcode"])
    gl = {e: sorted({l["glcode"] for l in ledgers if l["entity"] == e}) for e in ENTITIES}
    cols = "entity, entcode, entno, entdt, entry_type, enttype, glcode, glname, slcode, vendor_name, damount, camount, release_status, narration"
    sql = f"SELECT {cols} FROM gold_fpa.voucher_lines WHERE " + " OR ".join(f"(entity = '{e}' AND (slcode = ANY(%s) OR glcode = ANY(%s)))" for e in ENTITIES)
    params = []
    for e in ENTITIES:
        params += [sorted(sl[e]), gl[e]]
    return classify(names, ledgers, conn.execute(sql, params).fetchall())


TABLE_REASONS = {"party_holdco": "HOLDCO", "party_subco": "SUBCO", "same_company_isd": "SAME_COMPANY"}


def classify_table(ledgers: list[dict], raw: list[dict], names: list[dict] | None = None) -> list[dict]:
    """Pure: tag rows of gold_fpa.related_party_gl_lines. The table's own `reason` decides (precedence ISD, then party, then ledger list)."""
    led = {(l["entity"], l["glcode"]): l for l in ledgers}
    out = []
    for r in raw:
        cp = TABLE_REASONS.get(r["reason"])
        l = led.get((r["entity"], r["glcode"]))
        if cp:
            n = match_party(names or [], r["entity"], r.get("vendor_name"))
            reason, status = ("party" if cp != "SAME_COMPANY" else "same_company"), (n["status"] if n else "proposed")
        else:
            cp = "SUBCO" if r["entity"] == "VENTURES" else "HOLDCO"
            reason, status = "ledger:" + (l["role"] if l else "ledger_list"), (l["status"] if l else "proposed")
        out.append({**r, "month": _month(r["entdt"]), "reason": reason, "counterparty_entity": cp, "register_status": status, "ledger_role": l["role"] if l else None})
    return out


def fetch_table_lines(conn, ledgers: list[dict], names: list[dict] | None = None) -> list[dict]:
    raw = conn.execute(f"""SELECT entity, entcode, entno, entry_date AS entdt, entry_type, enttype, glcode, glname, slcode, party_name AS vendor_name, debit AS damount, credit AS camount,
        running_balance, release_status, narration, reason FROM {ic.TABLE} ORDER BY entity, glcode, slcode, entry_date, postcode""").fetchall()
    return classify_table(ledgers, raw, names)


def lines(conn, force: bool = False) -> tuple[list[dict], str]:
    """(lines, source). The full-ledger table is used when it exists at request time; voucher_lines otherwise. Cached for 5 minutes per source, one fetch at a time;
    the key carries the table's row count and last entry date so a re-extraction is seen at once."""
    use_table = ic.table_present(conn)
    mark = None
    if use_table:
        w = conn.execute(f"SELECT count(*) AS n, max(entry_date) AS d FROM {ic.TABLE}").fetchone()
        mark = (w["n"], w["d"])
    key = (use_table, mark, tuple((n["books_of_entity"], n["party_pattern"], n["counterparty_entity"], n["status"]) for n in load()), tuple((l["entity"], l["glcode"], l["role"]) for l in ic.load()))
    with _lock:
        hit = _cache.get("v")
        if not force and hit and hit["key"] == key and time.time() - hit["t"] < TTL:
            return hit["lines"], hit["source"]
        src = "related_party_gl_lines" if use_table else "voucher_lines"
        data = fetch_table_lines(conn, ic.load(), load()) if use_table else fetch_lines(conn, load(), ic.load())
        _cache["v"] = {"key": key, "t": time.time(), "lines": data, "source": src}
        return data, src


def table_control(conn) -> dict | None:
    """The table against its own control_totals rows (written by the build) and against a fresh recompute from the table: counts and sums per entity."""
    if not ic.table_present(conn):
        return None
    ctl = {r["group_key"]: r for r in conn.execute("""SELECT group_key, sum(row_count) AS n, sum(sum_debit) AS dr, sum(sum_credit) AS cr FROM gold_fpa.control_totals WHERE table_name = 'related_party_gl_lines' GROUP BY 1""").fetchall()}
    cur = {r["entity"]: r for r in conn.execute(f"SELECT entity, count(*) AS n, sum(debit) AS dr, sum(credit) AS cr FROM {ic.TABLE} GROUP BY 1").fetchall()}
    rows = []
    for e in ENTITIES:
        c, t = ctl.get(e), cur.get(e)
        rows.append({"entity": e, "control_rows": int(c["n"]) if c else None, "table_rows": t["n"] if t else 0, "control_debit": c["dr"] if c else None, "table_debit": t["dr"] if t else ZERO,
                     "control_credit": c["cr"] if c else None, "table_credit": t["cr"] if t else ZERO,
                     "ok": bool(c and t and int(c["n"]) == t["n"] and abs(c["dr"] - t["dr"]) <= 1 and abs(c["cr"] - t["cr"]) <= 1)})
    return {"ok": all(r["ok"] for r in rows), "by_entity": rows}


def _money(dr: Decimal, cr: Decimal) -> dict:
    return {"debit": dr, "credit": cr, "net": dr - cr, "debit_cr": ic._cr(dr), "credit_cr": ic._cr(cr), "net_cr": ic._cr(dr - cr)}


def build(all_lines: list[dict], names: list[dict], entity: str | None = None, from_month: str | None = None, to_month: str | None = None, basis: str = "all",
          limit: int = 100, offset: int = 0) -> dict:
    """Pure: filter, group lines into entries, summarise, and mirror HoldCo's books against SubCo's."""
    sel = [x for x in all_lines if (not entity or x["entity"] == entity) and (not from_month or x["month"] >= from_month) and (not to_month or x["month"] <= to_month)
           and (basis == "all" or (basis == "party" and x["reason"] == "party") or (basis == "ledger" and x["reason"].startswith("ledger:")))]
    entries: dict = {}
    for x in sel:
        e = entries.setdefault((x["entity"], x["entcode"]), {"entcode": x["entcode"], "entity": x["entity"], "entno": None, "entdt": x["entdt"], "entry_type": x["entry_type"], "enttype": x["enttype"],
                                                            "ledgers": [], "parties": [], "counterparty_entity": x["counterparty_entity"], "debit": ZERO, "credit": ZERO,
                                                            "release_statuses": set(), "balances": {}, "narration": None, "reason": x["reason"], "register_status": x["register_status"], "lines": 0})
        e["entno"] = e["entno"] or x["entno"]
        e["narration"] = e["narration"] or x["narration"]
        if x["glname"] not in e["ledgers"]:
            e["ledgers"].append(x["glname"])
        if x["vendor_name"] and x["vendor_name"] not in e["parties"]:
            e["parties"].append(x["vendor_name"])
        if x["reason"] == "party" and e["reason"] != "party":
            e["reason"], e["counterparty_entity"], e["register_status"] = "party", x["counterparty_entity"], x["register_status"]
        e["debit"] += x["damount"]; e["credit"] += x["camount"]; e["lines"] += 1
        if x.get("running_balance") is not None:
            e["balances"][(x["glname"], x["vendor_name"])] = x["running_balance"]
        e["release_statuses"].add(x["release_status"])
    rows = sorted(entries.values(), key=lambda e: (e["entdt"] is None, -(e["entdt"].toordinal() if e["entdt"] else 0), e["entcode"]))
    for e in rows:
        rs = e.pop("release_statuses")
        e["release_status"] = next(iter(rs)) if len(rs) == 1 else "mixed"
        e["party"] = "; ".join(e.pop("parties")) or None
        e["debit_cr"], e["credit_cr"] = ic._cr(e["debit"]), ic._cr(e["credit"])
        e["balances"] = [{"ledger": k[0], "party": k[1], "running_balance": v, "running_balance_cr": ic._cr(v)} for k, v in e["balances"].items()]

    def agg(items):
        d = sum((i["damount"] for i in items), ZERO); c = sum((i["camount"] for i in items), ZERO)
        return {"entries": len({(i["entity"], i["entcode"]) for i in items}), "lines": len(items), **_money(d, c)}

    by_entity = {e: agg([x for x in sel if x["entity"] == e and x["counterparty_entity"] != "SAME_COMPANY"]) for e in ENTITIES}
    same = agg([x for x in sel if x["counterparty_entity"] == "SAME_COMPANY"])
    grp: dict = {}
    for x in sel:
        grp.setdefault((x["entity"], x["counterparty_entity"], x["glcode"], x["glname"], x["month"]), []).append(x)
    summary = [{"entity": k[0], "counterparty_entity": k[1], "glcode": k[2], "glname": k[3], "month": k[4], **agg(v)} for k, v in sorted(grp.items(), key=lambda kv: (kv[0][4], kv[0][0], kv[0][3]))]
    # party mirror: HoldCo books' lines against SubCo (Dr there should be Cr here and vice versa)
    hb = agg([x for x in sel if x["entity"] == "VENTURES" and x["counterparty_entity"] == "SUBCO" and x["reason"] == "party"])
    sb = agg([x for x in sel if x["entity"] == "RETAIL" and x["counterparty_entity"] == "HOLDCO" and x["reason"] == "party"])
    d1, d2 = hb["debit"] - sb["credit"], hb["credit"] - sb["debit"]
    mirror = {"holdco_books": hb, "subco_books": sb, "debit_vs_credit": d1, "credit_vs_debit": d2, "debit_vs_credit_cr": ic._cr(d1), "credit_vs_debit_cr": ic._cr(d2),
              "mirrors": abs(d1) <= ic.TOL and abs(d2) <= ic.TOL,
              "note": "Party-tagged lines only. HoldCo debits should equal SubCo credits and HoldCo credits SubCo debits; any difference is shown, never forced to zero."}
    page = rows[offset:offset + limit]
    return {"filters": {"entity": entity, "from_month": from_month, "to_month": to_month, "basis": basis, "limit": limit, "offset": offset},
            "total_entries": len(rows), "returned": len(page), "entries": page, "summary": summary, "by_entity": by_entity, "same_company": {**same, "label": "same-company registration (ISD)"},
            "mirror": mirror, "register": [{**n} for n in names],
            "party_register": {"path_exists": path().exists(), "patterns": len(names), "proposed": sum(n["status"] == "proposed" for n in names), "confirmed": sum(n["status"] == "confirmed" for n in names)}}


def headline(conn) -> dict:
    """The small block for the page header cards and /summary."""
    data, src = lines(conn)
    b = build(data, load(), limit=0)
    return {"source": src, "entries": b["total_entries"], "by_entity": b["by_entity"], "same_company": b["same_company"], "mirror_mirrors": b["mirror"]["mirrors"],
            "mirror_debit_vs_credit_cr": b["mirror"]["debit_vs_credit_cr"], "mirror_credit_vs_debit_cr": b["mirror"]["credit_vs_debit_cr"]}


def compute(conn, **kw) -> dict:
    data, src = lines(conn)
    out = build(data, load(), **kw)
    out["source"] = {"entries": src, "full_ledger": ic.table_source(conn), "control": table_control(conn)}
    out["ledger_mirror"] = [{"pair_id": p["pair_id"], "label": p["label"], "source": p.get("source"), **{k: p["totals"][k] for k in ("holdco_net_cr", "subco_net_cr", "difference_cr", "mirrors")}} for p in ic.compute(conn)["pairs"]]
    return out
