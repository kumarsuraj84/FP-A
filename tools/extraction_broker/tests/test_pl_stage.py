"""P&L actuals staging (pl_stage.py) on SYNTHETIC runs. No Oracle, no database, no real data."""
from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import manifest as mf  # noqa: E402
import pl_stage as ps  # noqa: E402

AS_OF = "2026-10-07"
GL = [("1000000001", "Sales - POS", "Income"), ("1000000002", "Salary", "Expense"), ("1000000003", "Mystery Fee", "Expense")]
L2G = {"Sales - POS": "01-Net Sales", "Salary": "02-Employee Cost"}


def _write(run: Path, name: str, rows: list[dict], cols: list[str]):
    pq.write_table(pa.table({c.upper(): pa.array([None if r.get(c) is None else str(r.get(c)) for r in rows], type=pa.string()) for c in cols}), run / f"{name}.parquet")


def _entry(run: Path, name, role, kind="extract"):
    f = run / f"{name}.parquet"
    return {"dataset": name, "kind": kind, "role": role, "source_object": None, "logical_source": None, "copy_id": None, "query_id": 1, "query_hash": "a" * 64, "extracted_at": "2026-10-07T04:00:00+00:00",
            "row_count": pq.ParquetFile(f).metadata.num_rows, "row_cap": 1000, "min_date": None, "max_date": None, "file_name": f"{name}.parquet", "file_size": f.stat().st_size,
            "sha256": mf.sha256_file(f), "status": "ok", "description": name, "error": None}


def build(tmp_path: Path, tweak=None):
    pl, cg = tmp_path / "run_20261007_900", tmp_path / "run_20261007_901"
    pl.mkdir()
    cg.mkdir()
    chunks = {
        "g_2026_09": [{"site_code": "10", "glcode": "1000000001", "entry_type_short": "PSD", "release_status": "Posted", "debit": "0", "credit": "1000", "lines_n": "5"},
                      {"site_code": "10", "glcode": "1000000002", "entry_type_short": "JDJ", "release_status": "Posted", "debit": "300", "credit": "0", "lines_n": "2"},
                      {"site_code": "10", "glcode": "1000000003", "entry_type_short": "JDJ", "release_status": "Posted", "debit": "40", "credit": "0", "lines_n": "1"}],
        "g_2026_10": [{"site_code": "10", "glcode": "1000000001", "entry_type_short": "PSD", "release_status": "Unposted", "debit": "0", "credit": "500", "lines_n": "3"}],
    }
    files = {n: (r, ["site_code", "glcode", "entry_type_short", "release_status", "debit", "credit", "lines_n"]) for n, r in chunks.items()}
    ctl = [{"month": "2026-09", "release_status": "Posted", "lines_n": "8", "debit": "340", "credit": "1000"}, {"month": "2026-10", "release_status": "Unposted", "lines_n": "3", "debit": "0", "credit": "500"}]
    files["c1_totals_cur_pre"] = (ctl, ["month", "release_status", "lines_n", "debit", "credit"])
    files["c1_totals_cur_post"] = (ctl, ["month", "release_status", "lines_n", "debit", "credit"])
    files["d_ly_aligned"] = ([{"site_code": "10", "glcode": "1000000001", "entry_type_short": "PSD", "release_status": "Posted", "debit": "0", "credit": "400", "lines_n": "3"},
                               {"site_code": "10", "glcode": "1000000002", "entry_type_short": "JDJ", "release_status": "Posted", "debit": "100", "credit": "0", "lines_n": "1"}],
                              ["site_code", "glcode", "entry_type_short", "release_status", "debit", "credit", "lines_n"])
    files["c1_totals_aligned_pre"] = ([{"month": "2025-10", "release_status": "Posted", "lines_n": "4", "debit": "100", "credit": "400"}], ["month", "release_status", "lines_n", "debit", "credit"])
    files["c1_totals_old_pre"] = ([{"month": "2025-04", "release_status": "Posted", "lines_n": "0", "debit": "0", "credit": "0"}], ["month", "release_status", "lines_n", "debit", "credit"])
    reg = [{"register_rows": "100", "register_report_date": AS_OF}]
    files["c0_register_pre"] = (reg, ["register_rows", "register_report_date"])
    files["c0_register_post"] = (reg, ["register_rows", "register_report_date"])
    files["m1_gl_master"] = ([{"glcode": c, "glname": n, "grpcode": "1", "type": t, "nature": "General", "extinct": "No"} for c, n, t in GL], ["glcode", "glname", "grpcode", "type", "nature", "extinct"])
    files["m2_ledger_to_group"] = ([{"ledger": k, "sk_grp": v} for k, v in L2G.items()], ["ledger", "sk_grp"])
    files["m3_group_to_major"] = ([{"sk_grp": "x", "sk_maj_grp": "y"}], ["sk_grp", "sk_maj_grp"])
    files["m4_site_master"] = ([{"site_code": "10", "store_name": "STORE TEN", "opening_date": "2020-01-01", "store_status": "ACTIVE", "store_current_status": "SAME STORE", "cluster_type": "BR1", "region_type": "R1",
                                 "state": "UP", "store_type": "OLD STORE", "area": "10000", "st_type": "TYPE-1", "store_grade": "A", "last_bill_date": AS_OF},
                                {"site_code": "40", "store_name": "STORE FORTY", "opening_date": "2026-05-10", "store_status": "CLOSED", "store_current_status": "CLOSED STORE", "cluster_type": "CLOSED", "region_type": "R2",
                                 "state": "BIHAR", "store_type": "NEW STORE", "area": "8000", "st_type": "-", "store_grade": "-", "last_bill_date": "2026-08-20"}],
                               ["site_code", "store_name", "opening_date", "store_status", "store_current_status", "cluster_type", "region_type", "state", "store_type", "area", "st_type", "store_grade", "last_bill_date"])
    cogs = {"g1_site_month": ([{"site_code": "10", "month": "2026-09", "early": "1", "rows_n": "15", "bill_days": "7", "sl_v": "590", "tax_amt": "90", "cogs_v": "300", "sl_q": "35", "tax_rows": "15", "first_bill": "2026-09-01", "last_bill": "2026-09-07"},
                                         {"site_code": "10", "month": "2026-09", "early": "0", "rows_n": "35", "bill_days": "23", "sl_v": "590", "tax_amt": "90", "cogs_v": "300", "sl_q": "35", "tax_rows": "35", "first_bill": "2026-09-08", "last_bill": "2026-09-30"},
                                         {"site_code": "20", "month": "2026-09", "early": "1", "rows_n": "5", "bill_days": "5", "sl_v": "11800", "tax_amt": "1800", "cogs_v": "60", "sl_q": "7", "tax_rows": "5", "first_bill": "2026-09-01", "last_bill": "2026-09-05"}],
                                        ["site_code", "month", "early", "rows_n", "bill_days", "sl_v", "tax_amt", "cogs_v", "sl_q", "tax_rows", "first_bill", "last_bill"])}
    if tweak:
        tweak(files, cogs)
    pl_entries = []
    for n, (r, c) in files.items():
        _write(pl, n, r, c)
        role = "control_pre" if n.endswith("_pre") else "control_post" if n.endswith("_post") else "extract"
        pl_entries.append(_entry(pl, n, role, "master" if n.startswith("m") else "extract"))
    for n, (r, c) in cogs.items():
        _write(cg, n, r, c)
    mf.write_manifest(pl, {"run_id": pl.name, "package": "pl_actuals_01", "created_at": "x", "broker_version": "1", "manifest_version": 2, "contract": {"as_of_cutoff": AS_OF, "contract": "pl-actuals-1.1", "aligned_days": 7, "ly_aligned_month": "2025-10-01"}, "datasets": pl_entries})
    mf.write_manifest(cg, {"run_id": cg.name, "package": "cogs_scan_02", "created_at": "x", "broker_version": "1", "contract": {"as_of_cutoff": AS_OF, "aligned_days": 7}, "datasets": [_entry(cg, "g1_site_month", "")]})
    return pl, cg


def test_a_clean_run_passes_keeps_the_unmapped_ledger_and_stores_the_sales_tieout(tmp_path):
    pl, cg = build(tmp_path)
    rep = ps.validate(pl, cg)
    assert rep["verdict"] == "PASSED", rep["hard_failures"]
    assert all(c["verdict"] == "PASS" for c in rep["controls"]) and len(rep["controls"]) >= 9
    rows = pq.read_table(pl / "staging" / "gl_site_month.parquet").to_pylist()
    sections = {r["ledger_name"]: r["section"] for r in rows}
    assert sections == {"Sales - POS": "REVENUE", "Salary": "STORE_OPEX", "Mystery Fee": "UNMAPPED"}                 # an unmapped ledger is kept, never dropped, never guessed
    assert rep["aggregates"]["unmapped_ledgers"] == 1
    tie = {(t["site_code"], str(t["month"])): t for t in pq.read_table(pl / "staging" / "sales_tieout.parquet").to_pylist()}
    t = tie[("10", "2026-09-01")]
    assert Decimal(str(t["books_sales"])) == 1000 and Decimal(str(t["cogs_table_sales_ex_gst"])) == 1000 and t["tied"] is True
    assert tie[("20", "2026-09-01")]["tied"] is False and rep["aggregates"]["cogs_sites_without_books_sales"] == 1      # a COGS-table site with no books sales is shown, not hidden


def test_chunks_that_do_not_add_up_to_the_control_fail_the_run(tmp_path):
    def tweak(files, cogs):
        r, c = files["g_2026_09"]
        r[0]["credit"] = "999"
        files["g_2026_09"] = (r, c)

    rep = ps.validate(*build(tmp_path, tweak))
    assert rep["verdict"] == "FAILED" and any("E1_month_status" in f for f in rep["hard_failures"])


def test_a_register_that_changed_between_pre_and_post_is_a_refresh_race(tmp_path):
    def tweak(files, cogs):
        files["c1_totals_cur_post"] = ([{**files["c1_totals_cur_post"][0][0], "lines_n": "9"}, files["c1_totals_cur_post"][0][1]], files["c1_totals_cur_post"][1])

    rep = ps.validate(*build(tmp_path, tweak))
    assert rep["verdict"] == "FAILED" and any("REFRESH RACE" in f for f in rep["hard_failures"])


def test_a_register_date_that_is_not_the_as_of_date_or_an_empty_register_fails(tmp_path):
    def tweak(files, cogs):
        for k in ("c0_register_pre", "c0_register_post"):
            files[k] = ([{"register_rows": "100", "register_report_date": "2026-10-06"}], files[k][1])

    rep = ps.validate(*build(tmp_path, tweak))
    assert rep["verdict"] == "FAILED" and any("not the as-of date" in f for f in rep["hard_failures"])


def test_a_ledger_missing_from_the_gl_master_fails(tmp_path):
    def tweak(files, cogs):
        r, c = files["g_2026_09"]
        r[0]["glcode"] = "1999999999"
        files["g_2026_09"] = (r, c)

    rep = ps.validate(*build(tmp_path, tweak))
    assert rep["verdict"] == "FAILED" and any("not in the GL master" in f for f in rep["hard_failures"])


def test_a_finance_group_without_a_section_fails_rather_than_being_guessed(tmp_path):
    def tweak(files, cogs):
        files["m2_ledger_to_group"] = ([{"ledger": "Sales - POS", "sk_grp": "99-A Brand New Group"}, {"ledger": "Salary", "sk_grp": "02-Employee Cost"}], ["ledger", "sk_grp"])

    rep = ps.validate(*build(tmp_path, tweak))
    assert rep["verdict"] == "FAILED" and any("no P&L section" in f for f in rep["hard_failures"])


def test_reports_carry_counts_only_no_ledger_or_store_names(tmp_path):
    pl, cg = build(tmp_path)
    ps.validate(pl, cg)
    blob = (pl / "staging" / "validation_report.json").read_text(encoding="utf-8") + (pl / "staging" / "VALIDATION_REPORT.md").read_text(encoding="utf-8")
    for s in ("STORE TEN", "Mystery Fee", "Salary", "Sales - POS"):
        assert s not in blob, s


def test_every_group_label_the_finance_map_uses_has_a_section():
    real_labels = {"01-Net Sales", "02-Employee Cost", "01-Rent", "02-COGS(Others)", "21-Finance Cost", "24-Interest Income", "02-Other Income", "17-Bank Charges"}
    assert real_labels <= set(ps.SECTION_OF_GROUP) and set(ps.SECTION_OF_GROUP.values()) <= set(ps.SECTIONS)
    json.dumps(ps.SECTION_OF_GROUP)


def _d(x):
    from datetime import date as D
    return D.fromisoformat(x)


def test_the_effective_area_rule_matches_the_worked_example_and_its_edges():
    from decimal import Decimal as Dec
    A = Dec(10500)
    days, cal, eff, why = ps.effective_area(A, _d("2026-03-05"), None, _d("2026-03-01"), _d("2026-10-07"))
    assert (days, cal) == (27, 31) and eff == Dec("9145.1613") and why == "OPENED_IN_MONTH"           # 10,500 x 27 / 31
    assert ps.effective_area(A, _d("2020-01-01"), None, _d("2026-03-01"), _d("2026-10-07"))[2:] == (A, "FULL_MONTH")  # a full month: the whole area
    d, c, e, w = ps.effective_area(A, _d("2020-01-01"), _d("2026-03-10"), _d("2026-03-01"), _d("2026-10-07"))
    assert (d, e, w) == (10, (A * 10 / 31).quantize(Dec("0.0001")), "CLOSED_IN_MONTH")                  # closed on the 10th: ten days, both ends counted
    d, c, e, w = ps.effective_area(A, _d("2026-03-05"), _d("2026-03-20"), _d("2026-03-01"), _d("2026-10-07"))
    assert d == 16 and "OPENED_IN_MONTH" in w and "CLOSED_IN_MONTH" in w                               # opened and closed in the same month
    assert ps.effective_area(A, _d("2026-11-01"), None, _d("2026-10-01"), _d("2026-10-07"))[0] == 0     # not yet open
    assert ps.effective_area(A, _d("2020-01-01"), _d("2026-02-10"), _d("2026-03-01"), _d("2026-10-07"))[0] == 0   # closed before the month
    d, c, e, w = ps.effective_area(A, _d("2020-01-01"), None, _d("2026-10-01"), _d("2026-10-07"))      # the as-of month runs to the as-of date, over the whole calendar month
    assert (d, c) == (7, 31) and e == (A * 7 / 31).quantize(Dec("0.0001")) and "PARTIAL_MONTH_TO_AS_OF" in w
    assert ps.effective_area(None, _d("2020-01-01"), None, _d("2026-03-01"), _d("2026-10-07"))[2:] == (None, "AREA_MISSING")
    assert ps.effective_area(Dec(0), _d("2020-01-01"), None, _d("2026-03-01"), _d("2026-10-07"))[2] is None
    assert "OPENING_DATE_PLACEHOLDER" in ps.effective_area(A, _d("2000-01-01"), None, _d("2026-03-01"), _d("2026-10-07"))[3]
    assert ps.effective_area(A, _d("2020-01-01"), None, _d("2024-02-01"), _d("2026-10-07"))[1] == 29   # a leap February has 29 calendar days


def test_a_closing_date_is_the_last_bill_date_only_when_it_is_real_and_the_status_says_closed():
    assert ps.closing_date_of("CLOSED", _d("2026-08-20"), _d("2026-10-07")) == _d("2026-08-20")
    assert ps.closing_date_of("IN-ACTIVE", _d("2000-01-01"), _d("2026-10-07")) is None               # a placeholder is not a date
    assert ps.closing_date_of("ACTIVE", _d("2026-08-20"), _d("2026-10-07")) is None                  # an active store has not closed
    assert ps.closing_date_of("CLOSED", None, _d("2026-10-07")) is None


def test_the_effective_area_table_is_staged_with_a_reason_for_every_site_and_month(tmp_path):
    pl, cg = build(tmp_path)
    rep = ps.validate(pl, cg)
    assert rep["verdict"] == "PASSED", rep["hard_failures"]
    eff = pq.read_table(pl / "staging" / "store_month_effective_area.parquet").to_pylist()
    assert len(eff) == 2 * 19 and rep["aggregates"]["effective_area_rows"] == 38
    by = {(e["site_code"], str(e["month"])): e for e in eff}
    full = by[("10", "2026-09-01")]
    assert Decimal(str(full["effective_area"])) == 10000 and full["reason"] == "FULL_MONTH" and full["active_days"] == 30
    oct_ = by[("10", "2026-10-01")]
    assert oct_["active_days"] == 7 and "PARTIAL_MONTH_TO_AS_OF" in oct_["reason"]
    closed = by[("40", "2026-08-01")]
    assert closed["closing_date"] == "2026-08-20" and closed["active_days"] == 20 and "CLOSED_IN_MONTH" in closed["reason"] and "OPENED_IN_MONTH" not in closed["reason"]
    assert by[("40", "2026-09-01")]["active_days"] == 0 and "AFTER_CLOSE" in by[("40", "2026-09-01")]["reason"]
    assert by[("40", "2026-05-01")]["active_days"] == 22 and "OPENED_IN_MONTH" in by[("40", "2026-05-01")]["reason"]    # opened 10 May: 22 of 31 days


def test_the_day_aligned_window_of_last_year_is_controlled_and_the_cogs_early_part_is_kept(tmp_path):
    pl, cg = build(tmp_path)
    rep = ps.validate(pl, cg)
    assert rep["verdict"] == "PASSED", rep["hard_failures"]
    assert rep["aggregates"]["aligned_days"] == 7 and rep["aggregates"]["ly_aligned_month"] == "2025-10-01" and rep["aggregates"]["aligned_rows"] == 2
    assert any(c["control"] == "E1_aligned_status" for c in rep["controls"])
    al = pq.read_table(pl / "staging" / "gl_aligned.parquet").to_pylist()
    assert {a["section"] for a in al} == {"REVENUE", "STORE_OPEX"} and all(str(a["month"]) == "2025-10-01" for a in al)
    cogs = {(c["site_code"], str(c["month"])): c for c in pq.read_table(pl / "staging" / "cogs_site_month.parquet").to_pylist()}
    c10 = cogs[("10", "2026-09-01")]
    assert Decimal(str(c10["cogs_v"])) == 600 and Decimal(str(c10["cogs_early"])) == 300 and Decimal(str(c10["sl_v_early"])) == 590     # the month is its two parts


def test_an_aligned_window_that_does_not_add_up_to_its_control_fails_the_run(tmp_path):
    def tweak(files, cogs):
        r, c = files["d_ly_aligned"]
        r[0]["credit"] = "399"
        files["d_ly_aligned"] = (r, c)

    rep = ps.validate(*build(tmp_path, tweak))
    assert rep["verdict"] == "FAILED" and any("E1_aligned_status" in f for f in rep["hard_failures"])


def test_a_cogs_scan_built_for_another_date_is_refused(tmp_path):
    pl, cg = build(tmp_path)
    m = json.loads((cg / "manifest.json").read_text(encoding="utf-8"))
    m["contract"]["aligned_days"] = 6
    (cg / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
    rep = ps.validate(pl, cg)
    assert rep["verdict"] == "FAILED"
