"""Offline staging validation for the Cash pilot (cash_stage.py): synthetic runs only, no Oracle, no database, no real data."""
from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cash_stage as cs  # noqa: E402
import manifest as mf  # noqa: E402
from packages import PACKAGE_META  # noqa: E402

AS_OF, TILL = "2026-10-04", "2026-10-03"
# (code, name, nature) ; the fifth ledger has no entries at all
LEDGERS = [("111", "BANK ALPHA-1", "Bank"), ("222", "BANK BETA-2", "Bank"), ("333", "CASH IN HAND", "Cash"), ("444", "POOL ACCOUNT", "Bank"), ("555", "DORMANT BANK", "Bank")]
# opening dr, opening cr, posted dr, posted cr, unposted dr, unposted cr, contra dr/cr
FIG = {"111": ("2000000.50", "0", "90000000", "100000000.25", "30000000", "5000000", "1000000", "1000000"),
       "222": ("500000", "0", "4000000", "4300000", "700000", "600000", "0", "0"),
       "333": ("10000", "0", "10000", "1000", "0", "2000", "0", "0"),
       "444": ("0", "27000", "300000", "0", "100000", "366300", "0", "0")}
TILL_ROWS = [("S001", "Store One", "5000.25", "1000", "900", "9000", "8500", "2026-10-03"), ("S002", "Store Two", "0", "0", "0", "100", "100", None),
             ("S003", "Store Three", "7000", "2000.50", "1800", "20000", "19000", "2026-10-02"), ("S004", "Store Four", "-150", "50", "200", "600", "750", "2026-10-03")]


def write_pq(path: Path, rows: list[dict], cols: list[str]) -> None:
    pq.write_table(pa.table({c.upper(): pa.array([r.get(c) for r in rows], type=pa.string()) for c in cols}), path)


def bank_rows(register: str, rd: str, unposted_scale: int = 1, prior: bool = False) -> list[dict]:
    out = []
    for code, name, nature in LEDGERS:
        base = {"register": register, "glcode": code, "glname": name, "gl_type": "Asset", "nature": nature, "extinct": "No"}
        if code not in FIG:
            out.append(base)
            continue
        od, oc, pd_, pc, ud, uc, cd, cc = FIG[code]
        if prior:                                   # prior-year closing: opening + movement equals this year's opening
            o = Decimal(od) - Decimal(oc)
            od, oc, pd_, pc, ud, uc = "0", "0", str(max(o, 0)), str(max(-o, 0)), "0", "0"
        out.append({**base, "open_dr": od, "open_cr": oc, "open_rows": "1", "open_unposted_rows": "0", "posted_dr": pd_, "posted_cr": pc, "posted_rows": "5",
                    "unposted_dr": str(Decimal(ud) * unposted_scale), "unposted_cr": str(Decimal(uc) * unposted_scale), "unposted_rows": "2", "future_posted_dr": "0", "future_posted_cr": "0",
                    "future_unposted_dr": "0", "future_unposted_cr": "0", "future_rows": "0", "contra_posted_dr": cd, "contra_posted_cr": cc, "last_posted_date": "2026-09-30",
                    "last_entry_date": "2026-10-02", "report_date": rd})
    return out


BANK_COLS = ["register", "glcode", "glname", "gl_type", "nature", "extinct", "entry_glcode", "open_dr", "open_cr", "open_rows", "open_unposted_rows", "posted_dr", "posted_cr", "posted_rows",
             "unposted_dr", "unposted_cr", "unposted_rows", "future_posted_dr", "future_posted_cr", "future_unposted_dr", "future_unposted_cr", "future_rows", "contra_posted_dr",
             "contra_posted_cr", "last_posted_date", "last_entry_date", "report_date"]
TILL_COLS = ["site_code", "store_name", "till_date", "cumulative_balance", "mtd_debit", "mtd_credit", "fytd_debit", "fytd_credit", "last_activity_date"]
C1_COLS = ["till_date", "stores_with_a_row", "sum_cumulative", "mtd_debit", "mtd_credit", "fytd_debit", "fytd_credit"]
C2_COLS = ["report_date", "ledgers_with_entries", "open_dr", "open_cr", "posted_dr", "posted_cr", "unposted_dr", "unposted_cr", "open_rows", "posted_rows", "unposted_rows", "future_rows"]


def synth(tmp_path: Path, name="run_20261004_950", tweak=None, statuses=None) -> Path:
    run = tmp_path / name
    run.mkdir()
    till = [{"site_code": a, "store_name": b, "till_date": TILL, "cumulative_balance": c, "mtd_debit": d, "mtd_credit": e, "fytd_debit": f, "fytd_credit": g, "last_activity_date": h} for a, b, c, d, e, f, g, h in TILL_ROWS]
    site = bank_rows("site_register", AS_OF)
    gl = bank_rows("gl_register", AS_OF)
    prior = bank_rows("prior_year_closing", "2026-03-31", prior=True)
    S = lambda rows, k: str(sum((Decimal(r[k]) for r in rows), Decimal(0)))  # noqa: E731
    c1 = [{"till_date": TILL, "stores_with_a_row": str(len(till)), "sum_cumulative": S(till, "cumulative_balance"), "mtd_debit": S(till, "mtd_debit"), "mtd_credit": S(till, "mtd_credit"),
           "fytd_debit": S(till, "fytd_debit"), "fytd_credit": S(till, "fytd_credit")}]
    mv = [r for r in site if "open_dr" in r]
    c2 = [{"report_date": AS_OF, "ledgers_with_entries": str(len(mv)), **{k: S(mv, k) for k in ("open_dr", "open_cr", "posted_dr", "posted_cr", "unposted_dr", "unposted_cr")},
           "open_rows": str(len(mv)), "posted_rows": str(5 * len(mv)), "unposted_rows": str(2 * len(mv)), "future_rows": "0"}]
    files = {"c1_till_control_pre": (c1, C1_COLS), "c2_bank_control_pre": (c2, C2_COLS), "e1_store_till": (till, TILL_COLS), "e2_bank_site_register": (site, BANK_COLS + ["sites"]),
             "e3_bank_gl_register": (gl, BANK_COLS), "e4_bank_prior_year_closing": (prior, BANK_COLS), "c1_till_control_post": (c1, C1_COLS), "c2_bank_control_post": (c2, C2_COLS)}
    for r in files["e2_bank_site_register"][0]:
        r["sites"] = "3" if "open_dr" in r else None
    if tweak:
        tweak(files)
    entries = []
    for ds, (data, cols) in files.items():
        f = run / f"{ds}.parquet"
        write_pq(f, data, cols)
        entries.append({"dataset": ds, "kind": "extract", "role": cs.EXPECTED_DATASETS[ds], "source_object": "MISRETAIL.X", "logical_source": None, "copy_id": None, "query_id": 1,
                        "query_hash": "a" * 64, "extracted_at": "2026-10-04T10:00:00", "row_count": len(data), "row_cap": 1_000_000, "min_date": None, "max_date": None, "file_name": f.name,
                        "file_size": f.stat().st_size, "sha256": mf.sha256_file(f), "status": (statuses or {}).get(ds, "ok")})
    mf.write_manifest(run, {"run_id": name, "package": "cash_pilot_01", "created_at": "x", "broker_version": "1", "manifest_version": 2, "contract": {**PACKAGE_META["cash_pilot_01"]["contract"]}, "datasets": entries})
    return run


def test_a_clean_run_passes_and_writes_aggregate_only_reports(tmp_path):
    run = synth(tmp_path)
    rep = cs.validate(run)
    assert rep["verdict"] == "PASSED", rep["hard_failures"]
    assert len(rep["controls"]) == 17 and all(c["verdict"] == "PASS" for c in rep["controls"])
    assert rep["ties"]["violations"] == [] and rep["ties"]["checked_ledgers"] == 5
    a = rep["aggregates"]
    assert a["stores"] == 4 and Decimal(a["till"]["cumulative_balance"]) == Decimal("11850.25") and a["bank_rows"] == 15
    pos = a["site_register_position"]
    # posted closing = opening + posted Dr - posted Cr, summed over the four ledgers with entries
    assert Decimal(pos["opening"]) == Decimal("2000000.50") + 500000 + 10000 - 27000
    assert Decimal(pos["posted_closing"]) == Decimal(pos["opening"]) + Decimal("90000000") + 4000000 + 10000 + 300000 - Decimal("100000000.25") - 4300000 - 1000
    assert Decimal(pos["including_unposted"]) == Decimal(pos["posted_closing"]) + (30000000 + 700000 + 0 + 100000) - (5000000 + 600000 + 2000 + 366300)
    st = run / "staging"
    t = pq.read_table(st / "cash_store_till.parquet").to_pylist()
    b = pq.read_table(st / "cash_bank_ledger.parquet").to_pylist()
    assert len(t) == 4 and len(b) == 15 and all(isinstance(r["cumulative_balance"], Decimal) for r in t)
    dormant = [r for r in b if r["ledger_name"] == "DORMANT BANK"]
    assert len(dormant) == 3 and all(not r["has_movement"] and r["open_dr"] == 0 for r in dormant)  # no movement: present, flagged, never missing
    text = (st / "validation_report.json").read_text(encoding="utf-8") + (st / "VALIDATION_REPORT.md").read_text(encoding="utf-8")
    assert "Store Three" not in text  # no store names in the reports
    assert "NOT bank-reconciled".lower() in text.lower() or "not bank-reconciled" in text.lower()


def test_pre_post_difference_rejects_the_run(tmp_path):
    def tweak(files):
        d, cols = files["c1_till_control_post"]
        files["c1_till_control_post"] = ([{**d[0], "sum_cumulative": "999"}], cols)

    rep = cs.validate(synth(tmp_path, tweak=tweak))
    assert rep["verdict"] == "FAILED" and any("REFRESH RACE" in f for f in rep["hard_failures"])
    assert not (tmp_path / "run_20261004_950" / "staging" / "cash_store_till.parquet").exists()


def test_a_broken_opening_to_prior_closing_tie_is_a_hard_failure(tmp_path):
    def tweak(files):
        rows, cols = files["e4_bank_prior_year_closing"]
        rows[0]["posted_dr"] = str(Decimal(rows[0]["posted_dr"]) + 1)  # one rupee off
        files["e4_bank_prior_year_closing"] = (rows, cols)

    rep = cs.validate(synth(tmp_path, tweak=tweak))
    assert rep["verdict"] == "FAILED" and rep["ties"]["violations"] and any("prior_year_closing_vs_opening" in f for f in rep["hard_failures"])


def test_the_two_registers_must_agree_on_every_posted_figure(tmp_path):
    def tweak(files):
        rows, cols = files["e3_bank_gl_register"]
        rows[1]["posted_cr"] = str(Decimal(rows[1]["posted_cr"]) + Decimal("0.01"))
        files["e3_bank_gl_register"] = (rows, cols)

    rep = cs.validate(synth(tmp_path, tweak=tweak))
    assert rep["verdict"] == "FAILED" and any("site_vs_gl_register" in f for f in rep["hard_failures"])


def test_unposted_may_differ_between_registers_because_their_report_dates_differ(tmp_path):
    def tweak(files):
        files["e3_bank_gl_register"] = (bank_rows("gl_register", "2026-10-03", unposted_scale=2), files["e3_bank_gl_register"][1])

    assert cs.validate(synth(tmp_path, tweak=tweak))["verdict"] == "PASSED"


def test_duplicate_store_and_source_control_mismatch_fail_without_repair(tmp_path):
    def dup(files):
        rows, cols = files["e1_store_till"]
        rows.append(dict(rows[0]))
        files["e1_store_till"] = (rows, cols)

    rep = cs.validate(synth(tmp_path, tweak=dup))
    assert rep["verdict"] == "FAILED" and any("duplicated" in f for f in rep["hard_failures"])

    def short(files):
        rows, cols = files["e1_store_till"]
        files["e1_store_till"] = (rows[:-1], cols)

    rep2 = cs.validate(synth(tmp_path, name="run_20261004_951", tweak=short))
    assert rep2["verdict"] == "FAILED" and any(f.startswith("control T1") for f in rep2["hard_failures"])


def test_capped_failed_or_skipped_dataset_fails_the_run(tmp_path):
    rep = cs.validate(synth(tmp_path, statuses={"e1_store_till": "capped"}))
    assert rep["verdict"] == "FAILED" and any("capped" in f for f in rep["hard_failures"])


def test_till_date_after_the_register_date_is_refused(tmp_path):
    def tweak(files):
        d, cols = files["c1_till_control_pre"]
        files["c1_till_control_pre"] = ([{**d[0], "till_date": "2026-10-09"}], cols)
        files["c1_till_control_post"] = files["c1_till_control_pre"]

    rep = cs.validate(synth(tmp_path, tweak=tweak))
    assert rep["verdict"] == "FAILED" and any("till date" in f for f in rep["hard_failures"])


def test_amounts_are_exact_decimals_and_junk_is_refused(tmp_path):
    def tweak(files):
        rows, cols = files["e1_store_till"]
        rows[0]["cumulative_balance"] = "1.0E3"
        files["e1_store_till"] = (rows, cols)

    rep = cs.validate(synth(tmp_path, tweak=tweak))
    assert rep["verdict"] == "FAILED" and any("plain decimal" in f for f in rep["hard_failures"])
    assert json.loads((tmp_path / "run_20261004_950" / "staging" / "validation_report.json").read_text())["verdict"] == "FAILED"
