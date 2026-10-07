"""
Offline check of a cash_bank_live_01 run (never talks to Oracle). Usage:
    python tools/extraction_broker/cash_bank_live_check.py data/inbox/run_YYYYMMDD_NNN [data/inbox/<verified cash run>]

Hard checks (any failure = not usable):
  1. the manifest validates and every dataset is ok; the bank control is identical before and after the extract (no posting mid-run);
  2. every amount parses as an exact decimal; 34 ledgers in each register; the same ledgers in all three;
  3. the site register and the GL register agree on every figure;
  4. each ledger's FY25-26 closing (opening + posted Dr - posted Cr to 31 Mar 2026) equals its FY26-27 opening;
  5. the per-ledger figures add up to the source control (no per-ledger grouping), to the paisa.
Comparison (information, never a failure): against a verified cash run of an earlier date, ledger by ledger. The openings must be identical; differences in posted figures are movement since that date.
"""
from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
import manifest as mf  # noqa: E402

D0 = Decimal(0)
FIELDS = ["open_dr", "open_cr", "posted_dr", "posted_cr", "unposted_dr", "unposted_cr", "future_posted_dr", "future_posted_cr", "future_unposted_dr", "future_unposted_cr", "contra_posted_dr", "contra_posted_cr"]


def dec(v) -> Decimal:
    return D0 if v in (None, "") else Decimal(str(v))


def rows(run: Path, name: str) -> list[dict]:
    return [{k.lower(): v for k, v in r.items()} for r in pq.read_table(run / f"{name}.parquet").to_pylist()]


def closing(r: dict) -> Decimal:
    return dec(r["open_dr"]) - dec(r["open_cr"]) + dec(r["posted_dr"]) - dec(r["posted_cr"])


def main(argv: list[str]) -> int:
    run = Path(argv[0])
    out: list[str] = []
    fails: list[str] = []
    v = mf.validate_manifest(run)
    if not v.ok:
        fails += [f"manifest: {e}" for e in v.errors]
    m = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    for d in m["datasets"]:
        if d["status"] != "ok":
            fails.append(f"dataset {d['dataset']} has status {d['status']}")
    pre, post = rows(run, "c2_bank_control_pre"), rows(run, "c2_bank_control_post")
    if pre != post:
        fails.append("the bank control differs between PRE and POST (a posting was made during the extract)")
    site, gl, prior = rows(run, "e2_bank_site_register"), rows(run, "e3_bank_gl_register"), rows(run, "e4_bank_prior_year_closing")
    by = lambda rs: {int(r["glcode"]): r for r in rs}  # noqa: E731
    s, g, p = by(site), by(gl), by(prior)
    if not (len(s) == len(g) == len(p) == 34 and set(s) == set(g) == set(p)):
        fails.append(f"ledger sets differ or are not 34 ({len(s)}, {len(g)}, {len(p)})")
    if not fails:
        for k in sorted(g):
            for f in FIELDS:
                if dec(s[k][f]) != dec(g[k][f]):
                    fails.append(f"ledger {k}: site register and GL register differ on {f}")
            cl = closing(p[k])
            op = dec(g[k]["open_dr"]) - dec(g[k]["open_cr"])
            if cl != op:
                fails.append(f"ledger {k}: FY25-26 closing {cl} does not equal FY26-27 opening {op}")
        c = pre[0]
        for f, label in (("open_dr", "open_dr"), ("open_cr", "open_cr"), ("posted_dr", "posted_dr"), ("posted_cr", "posted_cr"), ("unposted_dr", "unposted_dr"), ("unposted_cr", "unposted_cr")):
            if sum((dec(r[f]) for r in gl), D0) != dec(c[label]):
                fails.append(f"control: sum of ledgers {f} {sum((dec(r[f]) for r in gl), D0)} differs from the source control {dec(c[label])}")
        out.append(f"{run.name}: report date {pre[0]['report_date']}, 34 ledgers, {sum(1 for r in gl if r['entry_glcode'] is not None)} with entries")
        out.append(f"  posted Dr {sum((dec(r['posted_dr']) for r in gl), D0):,.2f}  Cr {sum((dec(r['posted_cr']) for r in gl), D0):,.2f}  | unposted Dr {sum((dec(r['unposted_dr']) for r in gl), D0):,.2f}  Cr {sum((dec(r['unposted_cr']) for r in gl), D0):,.2f}")
        if len(argv) > 1:
            ref = by(rows(Path(argv[1]), "e3_bank_gl_register"))
            same_open = sum(1 for k in g if dec(g[k]["open_dr"]) == dec(ref[k]["open_dr"]) and dec(g[k]["open_cr"]) == dec(ref[k]["open_cr"]))
            ident = sum(1 for k in g if all(dec(g[k][f]) == dec(ref[k][f]) for f in FIELDS))
            out.append(f"  against {argv[1]}: openings identical for {same_open} of 34 ledgers; every figure identical for {ident} of 34")
            for k in sorted(g):
                if not all(dec(g[k][f]) == dec(ref[k][f]) for f in FIELDS):
                    out.append(f"    {k} {g[k]['glname']}: posted Dr {dec(ref[k]['posted_dr']):,.2f} -> {dec(g[k]['posted_dr']):,.2f}, Cr {dec(ref[k]['posted_cr']):,.2f} -> {dec(g[k]['posted_cr']):,.2f}; unposted Dr {dec(ref[k]['unposted_dr']):,.2f} -> {dec(g[k]['unposted_dr']):,.2f}, Cr {dec(ref[k]['unposted_cr']):,.2f} -> {dec(g[k]['unposted_cr']):,.2f}")
    print("\n".join(out))
    if fails:
        print("FAILED:\n  " + "\n  ".join(fails))
        return 1
    print("PASSED: manifest, pre/post control, sets, site = GL register, prior closing = opening, ledgers = source control")
    return 0


if __name__ == "__main__":
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    sys.exit(main(sys.argv[1:]))
