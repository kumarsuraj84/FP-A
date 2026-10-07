"""A RICH SYNTHETIC P&L run (invented stores, deterministic) for the review tests: 24 stores over 19 months, a head-office site, areas, a closed store, a store opened mid-month, a store with no
area, planted anomalies, and the day-aligned window of last year. Every control is computed from the generated rows, so the run passes staging and loads. No Oracle, no real data."""
from __future__ import annotations

import sys
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import manifest as mf  # noqa: E402
from test_pl_stage import AS_OF, GL, L2G, _entry, _write  # noqa: E402

D = Decimal
GL4 = [("1000000001", "Sales - POS", "Income"), ("1000000002", "Salary", "Expense"), ("1000000003", "Mystery Fee", "Expense"), ("1000000004", "Shop Rent", "Expense"), ("1000000005", "Electricity", "Expense")]
MAP = {"Sales - POS": "01-Net Sales", "Salary": "02-Employee Cost", "Shop Rent": "01-Rent", "Electricity": "03-Power and Fuel Expenses"}
LEDGER = {"rev": "1000000001", "pay": "1000000002", "fee": "1000000003", "rent": "1000000004", "power": "1000000005"}
MONTHS = [date(2025 + (3 + i) // 12, (3 + i) % 12 + 1, 1) for i in range(19)]          # 2025-04 .. 2026-10
STORES = [str(101 + i) for i in range(24)]
HO = "900"
N_DAYS = 7                                                                               # the as-of day of the month
CAL = {m: [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m.month - 1] for m in MONTHS}


def _scale(m: date) -> D:
    return D(N_DAYS) / D(CAL[m]) if m == MONTHS[-1] else D(1)                            # the as-of month holds days 1..7 only


def revenue(s: str, m: date) -> D:
    i, k = STORES.index(s), MONTHS.index(m)
    base = D(9_000_000 + 400_000 * (i % 7)) * (D(1) + D("0.012") * k)                    # a gentle upward trend, a different size per store
    if s == "122" and m > date(2026, 6, 1):
        return D(0)                                                                      # the closed store stops trading after June
    if s == "123" and m < date(2026, 3, 1):
        return D(0)                                                                      # opened 5 March 2026
    if s == "123" and m == date(2026, 3, 1):
        base = base * D(27) / D(31)
    if s in ("119", "120", "121") and m < date(2025, 11, 1):
        return D(0)                                                                      # new stores of last winter
    if s == "111" and m == date(2026, 9, 1):
        base = base * D("0.55")                                                          # planted: a sales collapse
    if s == "113" and m >= date(2026, 6, 1):
        base = base * D("1.35")                                                          # planted: strong growth ...
    return (base * _scale(m)).quantize(D("0.01"))


def cogs_pct(s: str, m: date) -> D:
    if s == "113" and m >= date(2026, 6, 1):
        return D("0.74")                                                                 # ... with a falling gross margin
    return D("0.62")


def cost(s: str, m: date, kind: str) -> D:
    i = STORES.index(s)
    r = revenue(s, m)
    if r == 0:
        return D(0)
    full = r / _scale(m)
    amt = {"pay": D("0.045") * full + 20_000 * (i % 3), "rent": D(250_000 + 8_000 * (i % 5)), "power": D(80_000 + 3_000 * (i % 4))}[kind]
    if s == "107" and kind == "power" and m == date(2026, 9, 1):
        amt = amt * D("2.4")                                                             # planted: an electricity spike
    if s == "109" and kind == "rent" and m == date(2026, 9, 1):
        amt = amt * D("0.15")                                                            # planted: a rent posting that went missing
    return (amt * _scale(m)).quantize(D("0.01"))


def build_rich(tmp_path: Path):
    pl, cg = tmp_path / "run_20261007_910", tmp_path / "run_20261007_911"
    pl.mkdir()
    cg.mkdir()
    cur_months = [m for m in MONTHS if m >= date(2026, 4, 1)]
    by_month: dict[date, list[dict]] = defaultdict(list)

    def add(m: date, site: str, led: str, debit: D, credit: D, status: str, lines: int = 3):
        by_month[m].append({"site_code": site, "glcode": LEDGER[led], "entry_type_short": "JDJ", "release_status": status, "debit": str(debit), "credit": str(credit), "lines_n": str(lines)})

    for m in MONTHS:
        status = "Unposted" if m == MONTHS[-1] else "Posted"
        for s in STORES:
            r = revenue(s, m)
            if r == 0:
                continue
            add(m, s, "rev", D(0), r, status, 20)
            for kind, led in (("pay", "pay"), ("rent", "rent"), ("power", "power")):
                add(m, s, led, cost(s, m, kind), D(0), status, 2)
        add(m, HO, "pay", D(1_000_000) * _scale(m), D(0), status, 5)
        add(m, HO, "fee", D(50_000) * _scale(m), D(0), status, 1)                      # a ledger the finance mapping does not know
    files: dict[str, tuple[list[dict], list[str]]] = {}
    cols = ["site_code", "glcode", "entry_type_short", "release_status", "debit", "credit", "lines_n"]
    ctl_cur, ctl_old = [], []
    for m in MONTHS:
        files[f"g_{m:%Y_%m}"] = (by_month[m], cols)
        agg: dict[str, list] = defaultdict(lambda: [0, D(0), D(0)])
        for r in by_month[m]:
            a = agg[r["release_status"]]
            a[0] += int(r["lines_n"])
            a[1] += D(r["debit"])
            a[2] += D(r["credit"])
        for st, (n, dr, cr_) in agg.items():
            (ctl_cur if m >= date(2026, 4, 1) else ctl_old).append({"month": f"{m:%Y-%m}", "release_status": st, "lines_n": str(n), "debit": str(dr), "credit": str(cr_)})
    ccols = ["month", "release_status", "lines_n", "debit", "credit"]
    files["c1_totals_cur_pre"] = (ctl_cur, ccols)
    files["c1_totals_cur_post"] = (ctl_cur, ccols)
    files["c1_totals_old_pre"] = (ctl_old, ccols)
    reg = [{"register_rows": "100", "register_report_date": AS_OF}]
    files["c0_register_pre"] = (reg, ["register_rows", "register_report_date"])
    files["c0_register_post"] = (reg, ["register_rows", "register_report_date"])
    # last year's day-aligned window: days 1..7 of October 2025
    lym = date(2025, 10, 1)
    al, a_agg = [], defaultdict(lambda: [0, D(0), D(0)])
    for s in STORES:
        r = revenue(s, lym) * D(N_DAYS) / D(31)
        if r:
            al.append({"site_code": s, "glcode": LEDGER["rev"], "entry_type_short": "JDJ", "release_status": "Posted", "debit": "0", "credit": str(r.quantize(D("0.01"))), "lines_n": "4"})
            al.append({"site_code": s, "glcode": LEDGER["rent"], "entry_type_short": "JDJ", "release_status": "Posted", "debit": str((cost(s, lym, "rent") * D(N_DAYS) / D(31)).quantize(D("0.01"))), "credit": "0", "lines_n": "1"})
    for r in al:
        a = a_agg["Posted"]
        a[0] += int(r["lines_n"])
        a[1] += D(r["debit"])
        a[2] += D(r["credit"])
    files["d_ly_aligned"] = (al, cols)
    files["c1_totals_aligned_pre"] = ([{"month": "2025-10", "release_status": "Posted", "lines_n": str(a_agg["Posted"][0]), "debit": str(a_agg["Posted"][1]), "credit": str(a_agg["Posted"][2])}], ccols)
    files["m1_gl_master"] = ([{"glcode": c, "glname": n, "grpcode": "1", "type": t, "nature": "General", "extinct": "No"} for c, n, t in GL4], ["glcode", "glname", "grpcode", "type", "nature", "extinct"])
    files["m2_ledger_to_group"] = ([{"ledger": k, "sk_grp": v} for k, v in MAP.items()], ["ledger", "sk_grp"])
    files["m3_group_to_major"] = ([{"sk_grp": "x", "sk_maj_grp": "y"}], ["sk_grp", "sk_maj_grp"])
    sm = []
    for i, s in enumerate(STORES):
        new = s in ("119", "120", "121", "123")
        opening = {"119": "2025-12-10", "120": "2025-12-10", "121": "2026-01-15", "123": "2026-03-05"}.get(s, "2020-01-01")
        sm.append({"site_code": s, "store_name": f"STORE {s}", "opening_date": opening, "store_status": "CLOSED" if s == "122" else "ACTIVE", "store_current_status": "NEW STORE" if new else "SAME STORE",
                   "cluster_type": "C1" if i % 2 == 0 else "C2", "region_type": "R1" if i % 2 == 0 else "R2", "state": "UP" if i % 2 == 0 else "BIHAR", "store_type": "NEW STORE" if new else "OLD STORE",
                   "area": "0" if s == "124" else str(8000 + 100 * i), "st_type": "-", "store_grade": "A", "last_bill_date": "2026-06-15" if s == "122" else AS_OF})
    sm.append({"site_code": HO, "store_name": "HEAD OFFICE", "opening_date": "2000-01-01", "store_status": "ACTIVE", "store_current_status": "-", "cluster_type": "-", "region_type": "-", "state": "-", "store_type": "-",
               "area": "0", "st_type": "-", "store_grade": "-", "last_bill_date": "2000-01-01"})
    files["m4_site_master"] = (sm, ["site_code", "store_name", "opening_date", "store_status", "store_current_status", "cluster_type", "region_type", "state", "store_type", "area", "st_type", "store_grade", "last_bill_date"])
    # the COGS table: month totals and the first 7 days
    crows = []
    for s in STORES:
        for m in MONTHS:
            r = revenue(s, m)
            if r == 0:
                continue
            full = r / _scale(m)
            cg_full = full * cogs_pct(s, m)
            parts = [(1, D(N_DAYS) / D(CAL[m]))] + ([] if m == MONTHS[-1] else [(0, D(1) - D(N_DAYS) / D(CAL[m]))])
            for early, share in parts:
                ex = (full * share).quantize(D("0.01"))
                tax = (ex * D("0.06")).quantize(D("0.01"))
                crows.append({"site_code": s, "month": f"{m:%Y-%m}", "early": str(early), "rows_n": "30", "bill_days": str(N_DAYS if early else CAL[m] - N_DAYS), "sl_v": str(ex + tax), "tax_amt": str(tax),
                              "cogs_v": str((cg_full * share).quantize(D("0.01"))), "sl_q": "100", "tax_rows": "30", "first_bill": f"{m:%Y-%m}-01" if early else f"{m:%Y-%m}-08", "last_bill": f"{m:%Y-%m}-07" if early else f"{m:%Y-%m}-{CAL[m]}"})
    cogs = {"g1_site_month": (crows, ["site_code", "month", "early", "rows_n", "bill_days", "sl_v", "tax_amt", "cogs_v", "sl_q", "tax_rows", "first_bill", "last_bill"])}
    entries = []
    for n, (r, c) in files.items():
        _write(pl, n, r, c)
        role = "control_pre" if n.endswith("_pre") else "control_post" if n.endswith("_post") else "extract"
        entries.append(_entry(pl, n, role, "master" if n.startswith("m") else "extract"))
    for n, (r, c) in cogs.items():
        _write(cg, n, r, c)
    mf.write_manifest(pl, {"run_id": pl.name, "package": "pl_actuals_01", "created_at": "x", "broker_version": "1", "manifest_version": 2,
                           "contract": {"as_of_cutoff": AS_OF, "contract": "pl-actuals-1.1", "aligned_days": N_DAYS, "ly_aligned_month": "2025-10-01"}, "datasets": entries})
    mf.write_manifest(cg, {"run_id": cg.name, "package": "cogs_scan_02", "created_at": "x", "broker_version": "1", "contract": {"as_of_cutoff": AS_OF, "aligned_days": N_DAYS}, "datasets": [_entry(cg, "g1_site_month", "")]})
    return pl, cg
