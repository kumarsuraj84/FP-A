"""
Cash: mart = API reconciliation gate.

    cd backend && python -m app.cash_api.reconcile run_20261004_013            # compare only
    cd backend && python -m app.cash_api.reconcile run_20261004_013 --record   # also record the results as API-layer controls and ask the database to mark the run api_verified

Everything the Cash API serves for a run is read back through the API and compared, exactly and with zero tolerance, against the mart read with
differently shaped SQL. The creditor figures on the Cash page are also compared with what the Creditors API serves for the same creditors run, so
the two pages cannot disagree. With --record the results are written through cash.record_control as the verifier and cash.api_verify_run moves the
run to api_verified (still unpublished). A single difference blocks it.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

ZERO = Decimal(0)


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


def fetch_mart(db, run_id: str) -> dict:
    with db.session("cash_verifier") as c:
        till = c.execute("SELECT site_code, cumulative_balance AS bal, mtd_debit AS md, mtd_credit AS mc, fytd_debit AS fd, fytd_credit AS fc FROM cash.v_store_till WHERE run_id = %s", (run_id,)).fetchall()
        bank = c.execute("SELECT source, ledger_code, has_movement, opening_dr - opening_cr AS op, opening_dr - opening_cr + posted_dr - posted_cr AS pc, "
                         "opening_dr - opening_cr + posted_dr - posted_cr + unposted_dr - unposted_cr AS iu FROM cash.v_bank_ledger WHERE run_id = %s", (run_id,)).fetchall()
        run = c.execute("SELECT publication_state FROM cash.v_serving_run WHERE run_id = %s", (run_id,)).fetchone()
    return {"till": till, "bank": bank, "publication_state": run["publication_state"]}


def reconcile(client, db, run_id: str) -> list[Check]:
    base = f"/api/v1/cash/runs/{run_id}"
    out: list[Check] = []
    add = lambda control, dim, m, a: out.append(Check(control, dim, D(m), D(a)))  # noqa: E731
    mart = fetch_mart(db, run_id)
    s = client.get(base + "/summary").json()
    t = s["till"]
    T = mart["till"]
    add("CASH-C1", "stores", len(T), t["stores"])
    add("CASH-C1", "store till cash", sum((D(r["bal"]) for r in T), ZERO), t["store_till_cash"])
    add("CASH-C1", "month-to-date debit", sum((D(r["md"]) for r in T), ZERO), t["mtd_debit"])
    add("CASH-C1", "month-to-date credit", sum((D(r["mc"]) for r in T), ZERO), t["mtd_credit"])
    add("CASH-C1", "year-to-date debit", sum((D(r["fd"]) for r in T), ZERO), t["fytd_debit"])
    add("CASH-C1", "year-to-date credit", sum((D(r["fc"]) for r in T), ZERO), t["fytd_credit"])
    add("CASH-C1", "stores with a negative balance", sum(1 for r in T if D(r["bal"]) < 0), t["stores_negative"])

    rows, off = [], 0
    while True:
        page = client.get(base + "/store-till", params={"limit": 500, "offset": off}).json()
        rows += page["stores"]
        off += 500
        if page["returned"] < 500:
            break
    api = {r["site_code"]: r for r in rows}
    mt = {r["site_code"]: r for r in T}
    add("CASH-C2", "store rows listed", len(mt), len(rows))
    add("CASH-C2", "stores missing or extra", 0, len(set(mt) ^ set(api)))
    add("CASH-C2", "stores whose balance differs", 0, sum(1 for k in mt if k in api and D(api[k]["cumulative_balance"]) != D(mt[k]["bal"])))
    add("CASH-C2", "stores whose month or year figures differ", 0, sum(1 for k in mt if k in api and (D(api[k]["mtd_debit"]), D(api[k]["mtd_credit"]), D(api[k]["fytd_debit"]), D(api[k]["fytd_credit"])) != (D(mt[k]["md"]), D(mt[k]["mc"]), D(mt[k]["fd"]), D(mt[k]["fc"]))))

    B = mart["bank"]
    for src in ("site_register", "gl_register", "prior_year_closing"):
        a = client.get(base + "/bank-ledgers", params={"source": src}).json()["ledgers"]
        m = {r["ledger_code"]: r for r in B if r["source"] == src}
        ag = {r["ledger_code"]: r for r in a}
        add("CASH-C3", f"{src}: ledgers listed", len(m), len(a))
        add("CASH-C3", f"{src}: ledgers missing or extra", 0, len(set(m) ^ set(ag)))
        add("CASH-C3", f"{src}: ledgers whose opening / posted closing / including-unposted differ", 0,
            sum(1 for k in m if k in ag and (D(ag[k]["opening_balance"]), D(ag[k]["posted_closing"]), D(ag[k]["including_unposted"])) != (D(m[k]["op"]), D(m[k]["pc"]), D(m[k]["iu"]))))
        add("CASH-C3", f"{src}: ledgers whose movement flag differs", 0, sum(1 for k in m if k in ag and ag[k]["has_movement"] != m[k]["has_movement"]))
    site = [r for r in B if r["source"] == "site_register"]
    bt = s["bank_review"]["totals"]
    add("CASH-C4", "bank review opening", sum((D(r["op"]) for r in site), ZERO), bt["opening_balance"])
    add("CASH-C4", "bank review posted closing", sum((D(r["pc"]) for r in site), ZERO), bt["posted_closing"])
    add("CASH-C4", "bank review including unposted", sum((D(r["iu"]) for r in site), ZERO), bt["including_unposted"])
    add("CASH-C4", "ledgers with movement", sum(1 for r in site if r["has_movement"]), s["bank_review"]["ledgers_with_movement"])
    add("CASH-C4", "bank status is the provisional label", 1, int(s["bank_review"]["status"] == "PROVISIONAL · NOT BANK-RECONCILED"))
    add("CASH-C4", "opening ties to prior-year closing for every ledger", 0, s["bank_review"]["opening_ties_to_prior_year_closing"]["ledgers_not_tying"])

    cr = s["creditors"]
    if cr.get("available"):
        c = client.get(f"/api/v1/creditors/runs/{cr['creditors_run_id']}/summary").json()
        due = {d["state"]: d for d in client.get(f"/api/v1/creditors/runs/{cr['creditors_run_id']}/due-status").json()["states"]}
        for k_cash, k_cred in (("credit_outstanding", "credit_outstanding"), ("creditor_debit_balance", "creditor_debit_balance"), ("past_due_credit", "past_due_credit"),
                               ("due_unavailable_credit", "due_unavailable_credit"), ("credit_items", "credit_items")):
            add("CASH-C5", f"creditors page = cash page: {k_cash}", c[k_cred], cr[k_cash])
        add("CASH-C5", "creditors page = cash page: not yet due", due["NOT_YET_DUE"]["credit_outstanding"], cr["not_yet_due_credit"])
    else:
        add("CASH-C5", "creditors figures available", 1, 0)

    expect = {"unpublished": "verified_candidate", "live": "live"}.get(mart["publication_state"], mart["publication_state"])
    add("CASH-STATE", "data_state stated by the API matches the run's publication state", 1, int(s["data_state"] == expect))
    add("CASH-STATE", "no consolidated-cash figure in the summary", 0, int(any(k in s for k in ("cash_position", "consolidated_cash", "cash_available", "forecast"))))
    return out


def record(db, run_id: str, checks: list[Check]) -> dict:
    with db.session("cash_verifier", readonly=False) as c:
        for ch in checks:
            c.execute("SELECT cash.record_control(%s,%s,%s,'mart',%s,'api',%s)", (run_id, ch.control, ch.dimension[:200], ch.mart, ch.api))
        return c.execute("SELECT cash.api_verify_run(%s) AS r", (run_id,)).fetchone()["r"]


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
    checks = reconcile(TestClient(create_app(settings, db)), db, run_id)
    bad = [c for c in checks if not c.ok]
    by: dict = defaultdict(lambda: [0, 0])
    for c in checks:
        by[c.control][0] += 1
        by[c.control][1] += c.ok
    print(f"{run_id}: {len(checks)} checks, {len(checks) - len(bad)} identical, {len(bad)} different")
    for k, (n, good) in sorted(by.items()):
        print(f"  {k:11s} {good}/{n}")
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
