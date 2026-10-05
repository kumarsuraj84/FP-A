"""
Entry layer: mart = API reconciliation gate (controls E10, E11, E12 at the API layer; E4, E5 and E7 to E9 re-proved through the API).

    cd backend && python -m app.entry_api.reconcile run_20261005_001            # compare only
    cd backend && python -m app.entry_api.reconcile run_20261005_001 --record   # also record the results as API-layer controls and ask the database to mark the run api_verified

Everything is read back through the API and compared, exactly and with zero tolerance, against the mart read with differently shaped SQL:
  * every bank ledger, and every posted / unposted / opening entry list of every ledger, reconciles to the cash review card;
  * the till: all stores reconcile to Store Till Cash; every store's days reconcile to its balance; a sample of store-days reconciles entry by entry;
  * the creditor bridge: link counts by status and coverage; a sample of bills per status; Exact always resolves to one fetchable entry, Ambiguous and Not linked never to any;
  * entries: a sample of entries returns every line the mart holds; masked responses carry none of the restricted fields and none of the Finance-only text values;
  * a drill that names the wrong domain run is refused (409).
Telemetry stays metadata-only: this module prints counts and control ids, never an entry number, narration, reference or name.
"""
from __future__ import annotations

import random
import sys
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

ZERO = Decimal(0)
RESTRICTED_KEYS = {"entry_no", "narration", "reference_no", "reference_date", "cheque_no", "cheque_date", "prepared_by", "prepared_on", "modified_by", "modified_on", "released_by", "released_on",
                   "sub_ledger_code", "counter_ledgers", "identity", "created_by_site", "text"}


@dataclass
class Check:
    control: str
    dimension: str
    mart: Decimal
    api: Decimal

    @property
    def ok(self) -> bool:
        return self.mart == self.api


def D(x) -> Decimal:
    return Decimal(str(x))


def keys_of(o):
    if isinstance(o, dict):
        for k, v in o.items():
            yield k
            yield from keys_of(v)
    elif isinstance(o, list):
        for v in o:
            yield from keys_of(v)


def fetch_mart(db, run_id: str) -> dict:
    with db.session("entry_verifier") as c:
        run = c.execute("SELECT * FROM entry.v_serving_run WHERE entry_run_id = %s", (run_id,)).fetchone()
        bank = c.execute(
            "SELECT l.ledger_code, count(DISTINCT l.entry_ref) AS entries, sum(l.debit) FILTER (WHERE l.release_status = 'Posted' AND trim(h.entry_type_long) <> 'Opening' AND h.entry_date <= %s) AS pd, "
            "sum(l.credit) FILTER (WHERE l.release_status = 'Posted' AND trim(h.entry_type_long) <> 'Opening' AND h.entry_date <= %s) AS pc "
            "FROM entry.v_entry_line l JOIN entry.v_entry_header h USING (entry_run_id, entry_ref) WHERE l.entry_run_id = %s AND l.ledger_nature IN ('Bank', 'Cash') GROUP BY l.ledger_code",
            (run["register_report_date"], run["register_report_date"], run_id)).fetchall()
        tdays = c.execute("SELECT site_code, day, debit, credit, cumulative_balance FROM entry.v_till_day WHERE entry_run_id = %s", (run_id,)).fetchall()
        links = c.execute("SELECT source_row_key, link_status, entry_ref, matched_entries, coverage FROM entry.v_creditor_bill_link WHERE entry_run_id = %s", (run_id,)).fetchall()
        heads = c.execute("SELECT entry_ref, line_count, total_dr, total_cr FROM entry.v_entry_header WHERE entry_run_id = %s", (run_id,)).fetchall()
    return {"run": run, "bank": bank, "till_days": tdays, "links": links, "headers": heads}


def reconcile(client, db, run_id: str, cash_run: str, creditors_run: str, finance_token: str | None = None, sample: int = 60, seed: int = 7) -> list[Check]:
    rnd = random.Random(seed)
    base = f"/api/v1/entries/runs/{run_id}"
    out: list[Check] = []
    add = lambda control, dim, m, a: out.append(Check(control, dim, D(m), D(a)))  # noqa: E731
    mart = fetch_mart(db, run_id)
    run = mart["run"]
    st = client.get(base).json()
    add("ENT-STATE", "data_state stated by the API matches the run's publication state", 1, int(st["data_state"] == {"unpublished": "verified_candidate", "live": "live"}.get(run["publication_state"], run["publication_state"])))

    # ── bank (E7, E10) ──
    led = client.get(base + "/bank/ledgers", params={"cash_run": cash_run}).json()
    add("ENT-BANK", "every ledger row reconciles to the review card", 0, sum(1 for r in led["ledgers"] if not r["reconciles"]))
    add("ENT-BANK", "the ledger list reconciles as a whole", 1, int(led["reconciles"]))
    m_bank = {r["ledger_code"]: r for r in mart["bank"]}
    add("ENT-BANK", "bank ledgers listed", len(m_bank), len(led["ledgers"]))
    add("ENT-BANK", "ledgers whose posted Dr/Cr differ from the mart", 0, sum(1 for r in led["ledgers"] if (D(r["posted_dr"]), D(r["posted_cr"])) != (D(m_bank[r["ledger_code"]]["pd"] or 0), D(m_bank[r["ledger_code"]]["pc"] or 0))))
    bad_lists = n_lists = 0
    for r in led["ledgers"]:
        for status in ("posted", "unposted", "opening"):
            n, off, got, dr, cr = 0, 0, 0, ZERO, ZERO
            while True:
                page = client.get(f"{base}/bank/ledgers/{r['ledger_code']}/entries", params={"cash_run": cash_run, "status": status, "limit": 500, "offset": off}).json()
                if off == 0:
                    n_lists += 1
                    bad_lists += int(not page["reconciles"])
                    expected_count = page["entry_count"]
                got += len(page["entries"])
                dr += sum((D(e["debit"]) for e in page["entries"]), ZERO)
                cr += sum((D(e["credit"]) for e in page["entries"]), ZERO)
                off += 500
                if page["returned"] < 500:
                    break
            bad_lists += int(got != expected_count or (dr, cr) != (D(page["children_sum"]["debit"]), D(page["children_sum"]["credit"])))
    add("ENT-BANK", f"entry lists that do not reconcile or are incomplete (of {n_lists})", 0, bad_lists)

    # ── till (E8, E10) ──
    ts = client.get(base + "/till/stores", params={"cash_run": cash_run}).json()
    add("ENT-TILL", "the store list reconciles to Store Till Cash", 1, int(ts["reconciles"]))
    md = defaultdict(list)
    for d in mart["till_days"]:
        md[d["site_code"]].append(d)
    add("ENT-TILL", "stores listed", len(md), len(ts["stores"]))
    bad_days = 0
    for s in ts["stores"]:
        res = client.get(f"{base}/till/stores/{s['site_code']}/days", params={"cash_run": cash_run}).json()
        bad_days += int(not res["reconciles"])
        active = [d for d in md[s["site_code"]] if D(d["debit"]) or D(d["credit"])]
        bad_days += int(len(res["days"]) != len(active))
    add("ENT-TILL", "stores whose day list does not reconcile to their balance", 0, bad_days)
    pool = [(d["site_code"], d["day"]) for d in mart["till_days"] if D(d["debit"]) or D(d["credit"])]
    bad_entries = 0
    for site, day in rnd.sample(pool, min(sample, len(pool))):
        res = client.get(f"{base}/till/stores/{site}/days/{day}/entries", params={"cash_run": cash_run}).json()
        bad_entries += int(not res["reconciles"])
    add("ENT-TILL", f"sampled store-days whose entries do not reconcile (of {min(sample, len(pool))})", 0, bad_entries)

    # ── creditor bridge (E4, E5, E6) ──
    summ = client.get(base + "/creditors/links", params={"creditors_run": creditors_run}).json()
    api_counts = {(r["link_status"], r["coverage"]): r["bills"] for r in summ["by_status_and_coverage"]}
    m_counts = defaultdict(int)
    for k in mart["links"]:
        m_counts[(k["link_status"], k["coverage"])] += 1
    for key in sorted(set(api_counts) | set(m_counts)):
        add("ENT-LINK", f"bills {key[0]} / {key[1]}", m_counts.get(key, 0), api_counts.get(key, 0))
    by_status = defaultdict(list)
    for k in mart["links"]:
        by_status[k["link_status"]].append(k)
    wrong = 0
    sampled = 0
    for status, ks in by_status.items():
        for k in rnd.sample(ks, min(sample, len(ks))):
            sampled += 1
            r = client.get(f"{base}/creditors/items/{k['source_row_key']}/link", params={"creditors_run": creditors_run}).json()["link"]
            if r["link_status"] != status or r["entry_ref"] != k["entry_ref"]:
                wrong += 1
            if status in ("AMBIGUOUS", "NOT_LINKED") and r["entry_ref"] is not None:
                wrong += 1
            if status == "EXACT":
                e = client.get(f"{base}/entry/{r['entry_ref']}")
                wrong += int(e.status_code != 200)
    add("ENT-LINK", f"sampled bills whose link differs, or where an unresolved bill carries an entry (of {sampled})", 0, wrong)

    # ── entries and masking (E2, E3, E12) ──
    heads = {h["entry_ref"]: h for h in mart["headers"]}
    refs = rnd.sample(sorted(heads), min(sample * 3, len(heads)))
    short = bad_bal = leaks = 0
    finance_strings: set[str] = set()
    masked_dump = []
    for ref in refs:
        e = client.get(f"{base}/entry/{ref}").json()["entry"]
        short += int(len(e["lines"]) != heads[ref]["line_count"])
        bad_bal += int(sum((D(x["debit"]) for x in e["lines"]), ZERO) != D(heads[ref]["total_dr"]) or sum((D(x["credit"]) for x in e["lines"]), ZERO) != D(heads[ref]["total_cr"]))
        leaks += len(RESTRICTED_KEYS & set(keys_of(e)))
        masked_dump.append(str(e))
        add_att = e["attachment"]
        leaks += int(add_att != {"available": False, "message": "No verified attachment source available"})
    add("ENT-ENTRY", f"sampled entries missing lines (of {len(refs)})", 0, short)
    add("ENT-ENTRY", "sampled entries whose line totals differ from the header", 0, bad_bal)
    add("ENT-MASK", "restricted field names (or a wrong attachment note) in masked entry responses", 0, leaks)
    if finance_token:
        fh = {"Authorization": f"Bearer {finance_token}"}
        add("ENT-MASK", "the Finance entry route without a token is refused", 401, client.get(f"{base}/finance/entry/{refs[0]}").status_code)
        fin_missing = 0
        for ref in refs[: max(20, sample // 2)]:
            r = client.get(f"{base}/finance/entry/{ref}", headers=fh).json()["entry"]
            fin_missing += int(not r.get("identity") or any("text" not in ln for ln in r["lines"]))
            for ln in r["lines"]:
                for k in ("narration", "reference_no", "cheque_no", "prepared_by", "released_by", "sub_ledger_code"):
                    v = ln["text"].get(k)
                    if v and len(str(v)) >= 6:
                        finance_strings.add(str(v))
            if r.get("identity"):
                finance_strings.add(str(r["identity"]["entry_no"]))
        add("ENT-MASK", "Finance entries missing identity or text", 0, fin_missing)
        blob = " ".join(masked_dump)
        add("ENT-MASK", "Finance-only text values found in masked responses", 0, sum(1 for v in finance_strings if len(v) >= 8 and v in blob))
    # ── lineage (E11) ──
    add("ENT-LINEAGE", "a drill naming the wrong cash run is refused", 409, client.get(base + "/bank/ledgers", params={"cash_run": "run_19990101_001"}).status_code)
    add("ENT-LINEAGE", "a drill naming the wrong creditors run is refused", 409, client.get(base + "/creditors/links", params={"creditors_run": "run_19990101_001"}).status_code)
    return out


def record(db, run_id: str, checks: list[Check]) -> dict:
    with db.session("entry_verifier", readonly=False) as c:
        for ch in checks:
            c.execute("SELECT entry.record_control(%s,%s,%s,'mart',%s,'api',%s)", (run_id, ch.control, ch.dimension[:200], ch.mart, ch.api))
        return c.execute("SELECT entry.api_verify_run(%s) AS r", (run_id,)).fetchone()["r"]


def main(argv: list[str]) -> int:
    from fastapi.testclient import TestClient

    from ..creditors_api.config import ApiSettings
    from ..creditors_api.db import Db
    from ..creditors_api.main import create_app

    if len(argv) < 2:
        print(__doc__)
        return 2
    run_id = argv[1]
    settings = ApiSettings.load()
    if not settings.conninfo:
        print("No API database login: run tools/creditors_mart/install_api.py first.")
        return 2
    db = Db(settings.conninfo)
    with db.session("entry_verifier") as c:
        pin = c.execute("SELECT cash_run_id, creditors_run_id FROM entry.v_serving_run WHERE entry_run_id = %s", (run_id,)).fetchone()
    if pin is None:
        print("that entry run is not served (it must be verified first)")
        return 2
    checks = reconcile(TestClient(create_app(settings, db)), db, run_id, pin["cash_run_id"], pin["creditors_run_id"], settings.finance_token)
    bad = [c for c in checks if not c.ok]
    by: dict = defaultdict(lambda: [0, 0])
    for c in checks:
        by[c.control][0] += 1
        by[c.control][1] += c.ok
    print(f"{run_id}: {len(checks)} checks, {len(checks) - len(bad)} identical, {len(bad)} different")
    for k, (n, good) in sorted(by.items()):
        print(f"  {k:12s} {good}/{n}")
    for c in bad[:20]:
        print(f"  DIFFERENT {c.control} {c.dimension}: mart {c.mart} vs api {c.api}")
    if "--record" in argv:
        if bad:
            print("NOT recorded: a single difference blocks the API-layer verification.")
            return 1
        print("Recorded; database answer:", record(db, run_id, checks))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
