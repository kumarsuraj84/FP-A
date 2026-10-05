"""A SYNTHETIC entry-layer run for tests: coherent with the synthetic creditors run (test_creditors_pilot) and the synthetic cash run (test_cash_stage), so every
cross-domain control can pass or be broken on purpose. No Oracle, no real data. Free-text fields carry SENTINEL markers so tests can prove they never leak into telemetry."""
from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import entry_stage as es  # noqa: E402
import manifest as mf  # noqa: E402
import test_cash_stage as tcs  # noqa: E402
import test_creditors_pilot as tcp  # noqa: E402
from packages import PACKAGE_META  # noqa: E402

AS_OF = "2026-10-04"
TILL_DATE = "2026-10-03"
SENT_NARR, SENT_USER, SENT_REF, SENT_CHQ = "SENTINEL_NARRATION_9f3a", "SENTINEL_USER_7c1d", "SENTINEL_REF_5e2b", "SENTINEL_CHQ_3b8e"
SENTINELS = [SENT_NARR, SENT_USER, SENT_REF, SENT_CHQ]
GL_NAME = {"111": "BANK ALPHA-1", "222": "BANK BETA-2", "333": "CASH IN HAND", "444": "POOL ACCOUNT"}
NATURE = {"111": "Bank", "222": "Bank", "333": "Cash", "444": "Bank"}


class Builder:
    def __init__(self):
        self.seq = 0
        self.lines: list[dict] = []          # every line, with the selections it belongs to
        self.no = 0

    def line(self, sels, site, typ, typ_long, no, date_, gl, name, nature, sl, dr, cr, status="Posted", **text):
        self.seq += 1
        self.lines.append({
            "sels": set(sels), "site_code": site, "entry_type_short": typ, "entry_type_long": typ_long, "entry_no": no, "entry_date": date_, "seq": str(self.seq), "glcode": gl, "glname": name,
            "glnature": nature, "slcode": sl, "debit": str(Decimal(dr)), "credit": str(Decimal(cr)), "release_status": status, "created_by_site": "HO", "cubename": "SITE_REG_26-27",
            "narration": text.get("narration", f"{SENT_NARR} entry {no}"), "reference_no": text.get("reference_no", f"{SENT_REF}-{no}"), "reference_date": date_,
            "cheque_no": text.get("cheque_no", f"{SENT_CHQ}-{no}"), "cheque_date": date_, "counter_ledgers": "counter", "prepared_by": SENT_USER, "prepared_on": f"{date_} 10:00:00",
            "modified_by": SENT_USER, "modified_on": f"{date_} 11:00:00", "released_by": SENT_USER, "released_on": f"{date_} 12:00:00"})


def window(doc_date: str | None) -> str:
    if not doc_date or doc_date < "2023-04-01":
        return "BEFORE_COVERAGE"
    return "CURRENT_FY" if doc_date >= "2026-04-01" else "PRIOR_YEARS_IN_COVERAGE"


def build(tmp_path: Path, name: str = "run_20261005_960", tweak=None, statuses=None, bank_delta: bool = False, till_delta: bool = False, rows=None):
    b = Builder()
    rows = rows if rows is not None else tcp.synth_rows()
    cur = [r for r in rows if window(r["document_date"]) == "CURRENT_FY"]
    prior = [r for r in rows if window(r["document_date"]) == "PRIOR_YEARS_IN_COVERAGE"]
    kinds = {cur[0]["document_code"]: "ambiguous", cur[1]["document_code"]: "nomatch", cur[2]["document_code"]: "strong", cur[3]["document_code"]: "multiline",
             cur[4]["document_code"]: "overlap_bank", prior[0]["document_code"]: "nomatch"}
    expected_status = {}
    for r in rows:
        w = window(r["document_date"])
        if w == "BEFORE_COVERAGE":
            continue
        kind = kinds.get(r["document_code"], "exact")
        sels = ["creditors_cur"] if w == "CURRENT_FY" else ["creditors_old"]
        amt = abs(Decimal(r["amount"]))
        dr, cr = (amt, 0) if r["drcr"] == "Dr" else (0, amt)
        no = r["document_no"]
        if kind == "nomatch":
            continue
        site = "001"
        led, sl, d = r["ledger_code"], r["sub_ledger_code"], r["document_date"]
        if kind == "strong":
            dr, cr = (dr + 1, 0) if dr else (0, cr + 1)
        entry_sels = sels + (["bank"] if kind == "overlap_bank" else [])
        if kind == "multiline":
            third = (amt / 3).quantize(Decimal("0.01"))
            parts = [third, third, amt - 2 * third]
            b.line(entry_sels, site, "PIM", "Purchase Invoice", no, d, led, r["ledger_name"], None, sl, dr, cr)
            for p in parts:
                b.line(entry_sels, site, "PIM", "Purchase Invoice", no, d, "7001", "Purchases", None, None, cr and p, dr and p)
        else:
            b.line(entry_sels, site, "PIM", "Purchase Invoice", no, d, led, r["ledger_name"], None, sl, dr, cr)
            b.line(entry_sels, site, "PIM", "Purchase Invoice", no, d, "7001", "Purchases", None, None, cr, dr)   # counter line balances the entry
            if kind == "overlap_bank":                                                                            # a bank line with no amount: the entry belongs to two drills
                b.line(entry_sels, site, "PIM", "Purchase Invoice", no, d, "111", GL_NAME["111"], "Bank", None, 0, 0)
        if kind == "ambiguous":                                                                                   # the same number, ledger and sub-ledger at another site
            b.line(sels, "002", "PIM", "Purchase Invoice", no, d, led, r["ledger_name"], None, sl, dr, cr)
            b.line(sels, "002", "PIM", "Purchase Invoice", no, d, "7001", "Purchases", None, None, cr, dr)
        expected_status[r["document_code"]] = {"exact": "EXACT", "strong": "STRONG", "ambiguous": "AMBIGUOUS", "multiline": "EXACT", "overlap_bank": "EXACT"}[kind]
    for r in rows:
        w = window(r["document_date"])
        expected_status.setdefault(r["document_code"], "NOT_LINKED")

    # bank: opening + posted + unposted entries per ledger, matching the cash run's synthetic figures exactly
    n = 0
    for code, fig in tcs.FIG.items():
        od, oc, pd_, pc, ud, uc = (Decimal(x) for x in fig[:6])
        lname = GL_NAME[code]
        n += 1
        if od or oc:
            b.line(["bank"], "010", "OPN", " Opening", f"O{n}", "2026-04-01", code, lname, NATURE[code], None, od, oc)
            b.line(["bank"], "010", "OPN", " Opening", f"O{n}", "2026-04-01", "9000", "Opening Balance Equity", None, None, oc, od)
        for tag, status, dr, cr in (("P", "Posted", pd_, pc), ("U", "Unposted", ud, uc)):
            if dr:
                b.line(["bank"], "010", "RCP", "Voucher", f"{tag}D{n}", "2026-09-15", code, lname, NATURE[code], None, dr, 0, status)
                b.line(["bank"], "010", "RCP", "Voucher", f"{tag}D{n}", "2026-09-15", "8001", "Sales", None, None, 0, dr, status)
            if cr:
                b.line(["bank"], "010", "PAY", "Voucher", f"{tag}C{n}", "2026-09-20", code, lname, NATURE[code], None, 0, cr, status)
                b.line(["bank"], "010", "PAY", "Voucher", f"{tag}C{n}", "2026-09-20", "8002", "Purchases", None, None, cr, 0, status)

    if bank_delta:    # one rupee more posted at the bank than the cash run's review card says: the layer must then disagree with the card
        b.line(["bank"], "010", "RCP", "Voucher", "XD1", "2026-09-16", "111", GL_NAME["111"], "Bank", None, 1, 0)
        b.line(["bank"], "010", "RCP", "Voucher", "XD1", "2026-09-16", "8001", "Sales", None, None, 0, 1)

    # till: the Cash Drawer ledger per store; opening + a retail sale + a deposit so that the running total equals the cash run's till balance on the till date
    till_days = ["2026-04-01", "2026-10-02", "2026-10-03"]
    till_rows = []
    for k, (site, _name, bal, *_rest) in enumerate(tcs.TILL_ROWS):
        bal = Decimal(bal)
        movement = {"2026-10-02": (Decimal(1000), Decimal(0)), "2026-10-03": (Decimal(0), Decimal(400))} if site in ("S001", "S003") else {}
        opening = bal - sum((dr - cr) for dr, cr in movement.values())
        day_amounts = {"2026-04-01": (max(opening, 0), max(-opening, 0))}
        day_amounts.update(movement)
        for d, (dr, cr) in day_amounts.items():
            if not (dr or cr):
                continue
            typ, tl = ("OPN", " Opening") if d == "2026-04-01" else (("RTL", "Retail Sale") if dr else ("POS", "POS Journal"))
            no = f"T{k}-{d[-5:]}"
            b.line(["till"], site, typ, tl, no, d, "9100", "Cash Drawer", None, None, dr, cr)
            b.line(["till"], site, typ, tl, no, d, "8101", "Sales" if dr else "Bank Deposit In Transit", None, None, cr, dr)
        run_bal = Decimal(0)
        for d in till_days:
            dr, cr = day_amounts.get(d, (Decimal(0), Decimal(0)))
            run_bal += dr - cr
            till_rows.append({"site_code": site, "day": d, "debit": str(dr), "credit": str(cr), "cumulative_balance": str(run_bal)})

    if till_delta:    # a Cash Drawer line the till view does not carry
        b.line(["till"], "S002", "RTL", "Retail Sale", "TX1", "2026-10-03", "9100", "Cash Drawer", None, None, 1, 0)
        b.line(["till"], "S002", "RTL", "Retail Sale", "TX1", "2026-10-03", "8101", "Sales", None, None, 0, 1)
    return finish(tmp_path, name, b, rows, till_rows, expected_status, tweak, statuses)


def selection_stats(b: Builder, sel: str):
    ls = [x for x in b.lines if sel in x["sels"]]
    ents = {}
    for x in ls:
        ents.setdefault((x["site_code"], x["entry_type_short"], x["entry_no"]), []).append(x)
    hist = {}
    for v in ents.values():
        hist[len(v)] = hist.get(len(v), 0) + 1
    return ents, ls, hist


def finish(tmp_path, name, b, rows, till_rows, expected_status, tweak, statuses):
    run = tmp_path / name
    run.mkdir()
    S = lambda xs, k: str(sum((Decimal(x[k]) for x in xs), Decimal(0)))  # noqa: E731
    sels = {"creditors_cur": "h1_lines_creditors_cur", "creditors_old": "h1b_lines_creditors_old", "bank": "h2_lines_bank", "till": "h3_lines_till"}
    files = {}
    c1, c2 = [], []
    for sel, ds in sels.items():
        ents, ls, hist = selection_stats(b, sel)
        files[ds] = ([{k: x[k] for k in es.LINE_COLUMNS} for x in ls], es.LINE_COLUMNS)
        c1.append({"selection": sel, "entries": str(len(ents)), "lines": str(len(ls)), "sum_debit": S(ls, "debit"), "sum_credit": S(ls, "credit")})
        c2 += [{"selection": sel, "lines_per_entry": str(n), "entries": str(c)} for n, c in sorted(hist.items())]
    wins = {"CURRENT_FY": [], "PRIOR_YEARS_IN_COVERAGE": [], "BEFORE_COVERAGE": []}
    for r in rows:
        wins[window(r["document_date"])].append(r)
    c3 = [{"cube_report_date": AS_OF, "register_report_date": AS_OF, "open_bills": str(len(rows)), "bills_current_fy": str(len(wins["CURRENT_FY"])), "bills_prior_years": str(len(wins["PRIOR_YEARS_IN_COVERAGE"])),
           "bills_before_coverage": str(len(wins["BEFORE_COVERAGE"]))}]

    def link_rows(group, ds_sel):
        out = []
        ents_all = {}
        for x in b.lines:
            if ds_sel in x["sels"]:
                ents_all.setdefault((x["site_code"], x["entry_type_short"], x["entry_no"]), []).append(x)
        for r in group:
            hit = {k: v for k, v in ents_all.items() if k[2] == r["document_no"] and any(x["glcode"] == r["ledger_code"] and x["slcode"] == r["sub_ledger_code"] for x in v)}
            m = len(hit)
            row = {"document_code": r["document_code"], "sub_ledger_code": r["sub_ledger_code"], "ledger_code": r["ledger_code"], "bill_amount": r["amount"], "matched_entries": str(m),
                   "site_code": None, "entry_type_short": None, "entry_no": None, "entry_net_dr_minus_cr": None}
            if m == 1:
                (site, typ, no), v = next(iter(hit.items()))
                net = sum((Decimal(x["debit"]) - Decimal(x["credit"]) for x in v if x["glcode"] == r["ledger_code"] and x["slcode"] == r["sub_ledger_code"]), Decimal(0))
                row.update({"site_code": site, "entry_type_short": typ, "entry_no": no, "entry_net_dr_minus_cr": str(net)})
            out.append(row)
        return out

    files["l1a_links_current"] = (link_rows(wins["CURRENT_FY"], "creditors_cur"), es.LINK_COLUMNS)
    files["l1b_links_prior"] = (link_rows(wins["PRIOR_YEARS_IN_COVERAGE"], "creditors_old"), es.LINK_COLUMNS)
    files["l1c_bills_before_coverage"] = ([{"document_code": r["document_code"], "sub_ledger_code": r["sub_ledger_code"], "ledger_code": r["ledger_code"], "bill_amount": r["amount"], "document_date": r["document_date"]}
                                           for r in wins["BEFORE_COVERAGE"]], ["document_code", "sub_ledger_code", "ledger_code", "bill_amount", "document_date"])
    files["l2_till_day"] = (till_rows, ["site_code", "day", "debit", "credit", "cumulative_balance"])
    for pre in ("pre", "post"):
        files[f"c1_totals_{pre}"] = (c1, ["selection", "entries", "lines", "sum_debit", "sum_credit"])
        files[f"c2_histogram_{pre}"] = (c2, ["selection", "lines_per_entry", "entries"])
        files[f"c3_bills_{pre}"] = (c3, list(c3[0].keys()))
    if tweak:
        tweak(files, b)
    entries = []
    for ds, (data, cols) in files.items():
        f = run / f"{ds}.parquet"
        pq.write_table(pa.table({c.upper(): pa.array([None if r.get(c) is None else str(r.get(c)) for r in data], type=pa.string()) for c in cols}), f)
        entries.append({"dataset": ds, "kind": "extract", "role": es.EXPECTED[ds], "source_object": "MISRETAIL.X", "logical_source": None, "copy_id": None, "query_id": 1, "query_hash": "a" * 64,
                        "extracted_at": "2026-10-05T10:00:00", "row_count": len(data), "row_cap": 1_000_000, "min_date": None, "max_date": None, "file_name": f.name, "file_size": f.stat().st_size,
                        "sha256": mf.sha256_file(f), "status": (statuses or {}).get(ds, "ok")})
    mf.write_manifest(run, {"run_id": name, "package": "entry_pilot_01", "created_at": "x", "broker_version": "1", "manifest_version": 2, "contract": {**PACKAGE_META["entry_pilot_01"]["contract"]}, "datasets": entries})
    return run, expected_status
