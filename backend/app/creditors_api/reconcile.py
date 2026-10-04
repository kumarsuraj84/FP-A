"""
mart = API reconciliation gate.

    cd backend && python -m app.creditors_api.reconcile run_20261004_006            # compare only
    cd backend && python -m app.creditors_api.reconcile run_20261004_006 --record   # also record the results as API-layer controls and ask the database to mark the run api_verified

Everything the API serves for a run is read back through the API (every endpoint, every vendor, every open item) and compared, exactly and
with zero tolerance, against the mart read with differently shaped SQL. With --record the results are written through
cred.record_control as the verifier and cred.api_verify_run moves the run to api_verified (still unpublished). A single difference blocks it.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from .repository import AGE_BUCKETS, DUE_STATES

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
    """The mart's own numbers, read with grouping queries that do not share SQL with the API."""
    with db.session("candidate") as c:
        g = c.execute("SELECT ledger_code, drcr, document_age_bucket AS bk, due_status AS du, count(*) AS n, sum(abs(pending)) AS a, sum(pending) AS s FROM cred.v_open_item_candidate "
                      "WHERE extraction_run_id = %s GROUP BY 1, 2, 3, 4", (run_id,)).fetchall()
        v = c.execute("SELECT ledger_code, drcr, count(DISTINCT vendor_ref) AS v FROM cred.v_open_item_candidate WHERE extraction_run_id = %s GROUP BY ROLLUP (ledger_code, drcr)", (run_id,)).fetchall()
        vend = c.execute("SELECT vendor_ref, drcr, count(*) AS n, sum(abs(pending)) AS a FROM cred.v_open_item_candidate WHERE extraction_run_id = %s GROUP BY 1, 2", (run_id,)).fetchall()
        allv = c.execute("SELECT count(DISTINCT vendor_ref) AS v FROM cred.v_open_item_candidate WHERE extraction_run_id = %s", (run_id,)).fetchone()["v"]
    return {"groups": g, "vendor_counts": v, "vendor_drcr": vend, "vendors": allv}


def reconcile(client, db, run_id: str, finance_token: str | None = None, walk_items: bool = True) -> list[Check]:
    base = f"/api/v1/creditors/runs/{run_id}"
    get = lambda path, **kw: client.get(base + path, **kw)  # noqa: E731
    out: list[Check] = []
    add = lambda control, dim, m, a: out.append(Check(control, dim, D(m), D(a)))  # noqa: E731
    mart = fetch_mart(db, run_id)
    G = mart["groups"]
    tot = lambda f, key: sum((D(r[key]) for r in G if f(r)), ZERO)  # noqa: E731

    s = get("/summary").json()
    add("API-C1", "item rows", sum(r["n"] for r in G), s["item_rows"])
    add("API-C1", "credit items", sum(r["n"] for r in G if r["drcr"].strip() == "Cr"), s["credit_items"])
    add("API-C1", "debit items", sum(r["n"] for r in G if r["drcr"].strip() == "Dr"), s["debit_items"])
    add("API-C2", "credit outstanding", tot(lambda r: r["drcr"].strip() == "Cr", "a"), s["credit_outstanding"])
    add("API-C3", "creditor debit balance", tot(lambda r: r["drcr"].strip() == "Dr", "a"), s["creditor_debit_balance"])
    add("API-C4", "signed net", tot(lambda r: True, "s"), s["signed_net"])
    add("API-C8", "vendor count", mart["vendors"], s["vendors"])
    add("API-STRIP", "past due credit", tot(lambda r: r["drcr"].strip() == "Cr" and r["du"] == "PAST_DUE_OR_DUE_TODAY", "a"), s["past_due_credit"])
    add("API-STRIP", "due date unavailable credit", tot(lambda r: r["drcr"].strip() == "Cr" and r["du"] == "DUE_UNAVAILABLE", "a"), s["due_unavailable_credit"])
    add("API-STRIP", "document age over 90 credit", tot(lambda r: r["drcr"].strip() == "Cr" and r["bk"] in ("D91_180", "D181_365", "D365_PLUS"), "a"), s["over_90_credit"])
    add("API-STRIP", "document age over 180 credit", tot(lambda r: r["drcr"].strip() == "Cr" and r["bk"] in ("D181_365", "D365_PLUS"), "a"), s["over_180_credit"])

    st = get("").json()
    add("API-STATE", "control failures reported by the API", 0, st["controls"]["failed"])

    age = {b["bucket"]: b for b in get("/document-age").json()["buckets"]}
    for key, _label in AGE_BUCKETS + [("UNCLASSIFIED", "")]:
        sel = (lambda r, k=key: r["bk"] == k) if key != "UNCLASSIFIED" else (lambda r: r["bk"].startswith("UNCLASSIFIED"))
        add("API-C5", f"{key} credit items", sum(r["n"] for r in G if sel(r) and r["drcr"].strip() == "Cr"), age[key]["credit_items"])
        add("API-C5", f"{key} credit outstanding", tot(lambda r: sel(r) and r["drcr"].strip() == "Cr", "a"), age[key]["credit_outstanding"])
        add("API-C5", f"{key} debit items", sum(r["n"] for r in G if sel(r) and r["drcr"].strip() == "Dr"), age[key]["debit_items"])
        add("API-C5", f"{key} debit balance", tot(lambda r: sel(r) and r["drcr"].strip() == "Dr", "a"), age[key]["debit_balance"])
    add("API-C6", "unclassified rows (credit + debit)", sum(r["n"] for r in G if r["bk"].startswith("UNCLASSIFIED")), age["UNCLASSIFIED"]["credit_items"] + age["UNCLASSIFIED"]["debit_items"])
    add("API-C5", "buckets add up to the total (credit)", D(s["credit_outstanding"]), sum((D(b["credit_outstanding"]) for b in age.values()), ZERO))

    due = {d["state"]: d for d in get("/due-status").json()["states"]}
    for key, _label in DUE_STATES:
        add("API-C7", f"{key} credit items", sum(r["n"] for r in G if r["du"] == key and r["drcr"].strip() == "Cr"), due[key]["credit_items"])
        add("API-C7", f"{key} credit outstanding", tot(lambda r: r["du"] == key and r["drcr"].strip() == "Cr", "a"), due[key]["credit_outstanding"])
        add("API-C7", f"{key} debit items", sum(r["n"] for r in G if r["du"] == key and r["drcr"].strip() == "Dr"), due[key]["debit_items"])
        add("API-C7", f"{key} debit balance", tot(lambda r: r["du"] == key and r["drcr"].strip() == "Dr", "a"), due[key]["debit_balance"])
    add("API-C7", "states add up to the total (debit)", D(s["creditor_debit_balance"]), sum((D(d["debit_balance"]) for d in due.values()), ZERO))

    led = {l["ledger_code"]: l for l in get("/ledgers").json()["ledgers"]}
    add("API-C9", "number of ledgers", len({r["ledger_code"] for r in G}), len(led))
    vc = {(r["ledger_code"], (r["drcr"] or "").strip() or None): r["v"] for r in mart["vendor_counts"]}
    for code, l in led.items():
        add("API-C9", f"{code} credit items", sum(r["n"] for r in G if r["ledger_code"] == code and r["drcr"].strip() == "Cr"), l["credit_items"])
        add("API-C9", f"{code} credit outstanding", tot(lambda r: r["ledger_code"] == code and r["drcr"].strip() == "Cr", "a"), l["credit_outstanding"])
        add("API-C9", f"{code} debit items", sum(r["n"] for r in G if r["ledger_code"] == code and r["drcr"].strip() == "Dr"), l["debit_items"])
        add("API-C9", f"{code} debit balance", tot(lambda r: r["ledger_code"] == code and r["drcr"].strip() == "Dr", "a"), l["debit_balance"])
        add("API-C9", f"{code} signed net", tot(lambda r: r["ledger_code"] == code, "s"), l["signed_net"])
        add("API-C8", f"{code} vendors", vc[(code, None)], l["vendors"])
        add("API-C8", f"{code} credit vendors", vc.get((code, "Cr"), 0), l["credit_vendors"])
        add("API-C8", f"{code} debit vendors", vc.get((code, "Dr"), 0), l["debit_vendors"])

    # every vendor and every open item, read through the API
    vendors, offset = [], 0
    while True:
        page = get("/vendors", params={"limit": 500, "offset": offset}).json()
        vendors += page["vendors"]
        offset += 500
        if offset >= int(page["total"]["vendors"]):
            break
    add("API-C8", "vendors listed by the vendor endpoint", mart["vendors"], len(vendors))
    add("API-C2", "sum of vendor credit outstanding", D(s["credit_outstanding"]), sum((D(v["credit_outstanding"]) for v in vendors), ZERO))
    add("API-C3", "sum of vendor debit balance", D(s["creditor_debit_balance"]), sum((D(v["debit_balance"]) for v in vendors), ZERO))
    add("API-C4", "sum of vendor signed net", D(s["signed_net"]), sum((D(v["signed_net"]) for v in vendors), ZERO))
    per_vendor = defaultdict(lambda: {"Cr": (0, ZERO), "Dr": (0, ZERO)})
    for r in mart["vendor_drcr"]:
        per_vendor[r["vendor_ref"]][r["drcr"].strip()] = (r["n"], D(r["a"]))
    bad = 0
    for v in vendors:
        m = per_vendor[v["vendor_ref"]]
        bad += (v["credit_items"], D(v["credit_outstanding"]), v["debit_items"], D(v["debit_balance"])) != (m["Cr"][0], m["Cr"][1], m["Dr"][0], m["Dr"][1])
    add("API-C9", "vendors whose totals differ from the mart", 0, bad)
    if walk_items:
        n_items, a_cr, a_dr, mismatches = 0, ZERO, ZERO, 0
        for v in vendors:
            off, got = 0, []
            while True:
                it = get(f"/vendors/{v['vendor_ref']}/items", params={"limit": 2000, "offset": off}).json()
                got += it["items"]
                off += 2000
                if off >= it["total_items"]:
                    break
            n_items += len(got)
            a_cr += sum((abs(D(i["pending"])) for i in got if i["drcr"].strip() == "Cr"), ZERO)
            a_dr += sum((abs(D(i["pending"])) for i in got if i["drcr"].strip() == "Dr"), ZERO)
            mismatches += len(got) != v["items"]
        add("API-C1", "open items listed by the item endpoints", sum(r["n"] for r in G), n_items)
        add("API-C2", "sum of listed item credit", D(s["credit_outstanding"]), a_cr)
        add("API-C3", "sum of listed item debit", D(s["creditor_debit_balance"]), a_dr)
        add("API-C1", "vendors whose item count differs from their profile", 0, mismatches)

    if finance_token:
        fh = {"Authorization": f"Bearer {finance_token}"}
        fv, off = [], 0
        while True:
            page = client.get(base + "/finance/vendors", params={"limit": 500, "offset": off}, headers=fh).json()
            fv += page["vendors"]
            off += 500
            if off >= int(page["total"]["vendors"]):
                break
        add("API-FIN", "finance vendors = masked vendors", len(vendors), len(fv))
        add("API-FIN", "finance credit = masked credit", sum((D(v["credit_outstanding"]) for v in vendors), ZERO), sum((D(v["credit_outstanding"]) for v in fv), ZERO))
        add("API-FIN", "finance rows that carry a vendor name", len(fv), sum(1 for v in fv if v.get("vendor_name")))
        add("API-FIN", "masked rows that carry a vendor name or code", 0, sum(1 for v in vendors if any(k in v for k in ("vendor_name", "slid", "sub_ledger_code", "credit_days"))))
    return out


def record(db, run_id: str, checks: list[Check]) -> dict:
    """Write the results as mart->api controls through the verifier's function, then ask the database to advance the run. A failed check blocks it."""
    with db.session("candidate", readonly=False) as c:
        for ch in checks:
            c.execute("SELECT cred.record_control(%s,%s,%s,'mart',%s,'api',%s)", (run_id, ch.control, ch.dimension[:200], ch.mart, ch.api))
        res = c.execute("SELECT cred.api_verify_run(%s) AS r", (run_id,)).fetchone()["r"]
    return res


def main(argv: list[str]) -> int:
    from fastapi.testclient import TestClient

    from .config import ApiSettings
    from .db import Db
    from .main import create_app

    if len(argv) < 2:
        print(__doc__)
        return 2
    run_id = argv[1]
    settings = ApiSettings.load()
    if not settings.conninfo:
        print("No API database login: run tools/creditors_mart/install_api.py first.")
        return 2
    db = Db(settings.conninfo)
    client = TestClient(create_app(settings, db))
    checks = reconcile(client, db, run_id, settings.finance_token)
    bad = [c for c in checks if not c.ok]
    by_control: dict = defaultdict(lambda: [0, 0])
    for c in checks:
        by_control[c.control][0] += 1
        by_control[c.control][1] += c.ok
    print(f"{run_id}: {len(checks)} checks, {len(checks) - len(bad)} identical, {len(bad)} different")
    for k, (n, good) in sorted(by_control.items()):
        print(f"  {k:10s} {good}/{n}")
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
