"""Entry layer: package guard checks and offline staging validation (entry_stage.py) on SYNTHETIC runs. No Oracle, no database, no real data."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import entry_stage as es  # noqa: E402
import entry_synth as syn  # noqa: E402
import guard  # noqa: E402
from packages import PACKAGE_META, PACKAGES  # noqa: E402


def test_package_is_registered_guarded_capped_misretail_only_and_pre_post_identical():
    ENTRY_PILOT_01 = PACKAGES["entry_pilot_01"]  # read at call time: the as-of date may have been configured since import
    assert PACKAGE_META["entry_pilot_01"]["halt_on_failure"] is True
    assert [d.role for d in ENTRY_PILOT_01][:3] == ["control_pre"] * 3 and [d.role for d in ENTRY_PILOT_01][-3:] == ["control_post"] * 3
    caps = {d.name: guard.check(d.sql, d.kind).row_cap for d in ENTRY_PILOT_01}
    assert "h3_lines_till" not in caps and caps["l2_till_day"] == 100_000 and caps["h1_lines_creditors_cur"] == 400_000 and all(c <= 5_000_000 for c in caps.values())
    by = {d.name: d.sql for d in ENTRY_PILOT_01}
    for k in ("c1_totals_creditors_cur", "c1_totals_creditors_old", "c1_totals_bank", "c3_bills", "c4_register"):
        assert by[f"{k}_pre"] == by[f"{k}_post"]
    assert not any(n.startswith("c2_histogram") and n.endswith("_post") for n in by) and all(f"c2_histogram_{n}_pre" in by for n in ("creditors_cur", "creditors_old", "bank"))
    for name, sql in by.items():
        assert "SSRK" not in sql.upper() and "PUBLIC" not in sql.upper(), name
        for obj in re.findall(r"(?i)\b(?:from|join)\s+([\w$#\".]+)", sql):
            assert obj.upper().startswith("MISRETAIL.") or obj == "(", (name, obj)
        if name.startswith("h"):  # numbers and dates leave Oracle as exact text
            assert "TO_CHAR(r.debit, 'TM9')" in sql and "TO_CHAR(r.entry_date, 'YYYY-MM-DD')" in sql
    # creditors are restricted to the four ledgers; the till drill ends at the store-day, so no Cash Drawer line is extracted anywhere
    assert "1000000026, 1000000024, 1000000092, 1000000025" in by["h1_lines_creditors_cur"]
    assert not any("Cash Drawer" in sql for name, sql in by.items() if name != "l2_till_day") and "h3_lines_till" not in by


def run_and_report(tmp_path, **kw):
    run, expected = syn.build(tmp_path, **kw)
    return run, expected, es.validate(run)


def test_a_clean_run_passes_with_every_control_green(tmp_path):
    run, expected, rep = run_and_report(tmp_path)
    assert rep["verdict"] == "PASSED", rep["hard_failures"]
    assert all(c["verdict"] == "PASS" for c in rep["controls"]) and len(rep["controls"]) > 20
    links = pq.read_table(run / "staging" / "creditor_bill_link.parquet").to_pylist()
    by_status = {}
    for k in links:
        by_status[k["link_status"]] = by_status.get(k["link_status"], 0) + 1
    assert set(by_status) == {"EXACT", "STRONG", "AMBIGUOUS", "NOT_LINKED"} and sum(by_status.values()) == 48
    assert rep["aggregates"]["links_by_status"] == by_status
    # E5: nothing ambiguous or unlinked carries an entry; E4: every exact one carries exactly one
    assert all((k["entry_ref"] is None) == (k["link_status"] in ("AMBIGUOUS", "NOT_LINKED")) for k in links)
    assert all(k["matched_entries"] == 1 and k["amount_agrees"] is True for k in links if k["link_status"] == "EXACT")
    assert all(k["matched_entries"] == 1 and k["amount_agrees"] is False for k in links if k["link_status"] == "STRONG")
    assert all(k["matched_entries"] > 1 for k in links if k["link_status"] == "AMBIGUOUS")
    reasons = {(k["coverage"], k["not_linked_reason"]) for k in links if k["link_status"] == "NOT_LINKED"}
    assert reasons == {("CURRENT_FY", "NO_MATCH"), ("PRIOR_YEARS_IN_COVERAGE", "NO_MATCH"), ("BEFORE_COVERAGE", "REGISTER_COVERAGE_UNAVAILABLE")}  # a coverage gap is not a generic failure
    # E3 and E2: every entry balances and a multi-line voucher is stored whole
    hdr = pq.read_table(run / "staging" / "entry_header.parquet").to_pylist()
    lines = pq.read_table(run / "staging" / "entry_line.parquet").to_pylist()
    assert all(h["total_dr"] == h["total_cr"] for h in hdr)
    per = {}
    for ln in lines:
        per.setdefault(ln["entry_ref"], []).append(ln["line_no"])
    counts = {h["entry_ref"]: h["line_count"] for h in hdr}
    assert all(sorted(v) == list(range(1, len(v) + 1)) and len(v) == counts[k] for k, v in per.items())
    assert max(len(v) for v in per.values()) == 4  # the synthetic multi-line voucher
    # an entry carried by two drills is stored once and tagged with both
    assert any(h["selections"] == ["bank", "creditors_cur"] for h in hdr)
    # the identity is (site, type, number, creating site, date): the register reuses numbers across warehouses and days, and none of those entries may merge
    ident = pq.read_table(run / "staging" / "entry_identity.parquet").to_pylist()
    hdr_by_ref = {h["entry_ref"]: h for h in hdr}
    assert len({i["entry_ref"] for i in ident}) == len(ident) == len(hdr)
    triples = {(i["site_code"], i["entry_type_short"], i["entry_no"]) for i in ident}
    assert len(triples) < len(ident)                                                  # the same (site, type, number) is more than one entry
    coll = [i for i in ident if (i["site_code"], i["entry_type_short"], i["entry_no"]) == ("010", "RCP", "COLL1")]
    assert len(coll) == 4 and sorted((str(i["created_by_site"]), hdr_by_ref[i["entry_ref"]]["entry_date"].isoformat()) for i in coll) == [("HO", "2026-09-15"), ("HO", "2026-09-16"), ("None", "2026-09-15"), ("WH2", "2026-09-15")]
    # the register repeats SEQ inside an entry: those lines stay distinct and are numbered 1..n
    texts = {}
    for ln in lines:
        texts.setdefault(ln["entry_ref"], []).append(ln["source_seq"])
    assert any(len(v) != len(set(v)) for v in texts.values())


def test_sensitive_text_never_reaches_a_report_or_a_message(tmp_path):
    run, _, rep = run_and_report(tmp_path)
    assert rep["verdict"] == "PASSED"
    blob = (run / "staging" / "validation_report.json").read_text(encoding="utf-8") + (run / "staging" / "VALIDATION_REPORT.md").read_text(encoding="utf-8") + json.dumps(rep, default=str)
    for s in syn.SENTINELS:
        assert s not in blob, s
    # the text IS stored, but only in the restricted derived file
    assert syn.SENT_NARR.encode() in (run / "staging" / "entry_line_text.parquet").read_bytes()
    unrestricted = b"".join((run / "staging" / f"{n}.parquet").read_bytes() for n in ("entry_line", "entry_header", "creditor_bill_link", "till_day"))
    for s in syn.SENTINELS:
        assert s.encode() not in unrestricted, s


def test_a_parse_error_names_the_field_and_row_but_never_echoes_the_value(tmp_path):
    def tweak(files, b):
        rows, cols = files["h2_lines_bank"]
        rows[0]["debit"] = "SENTINEL_BAD_AMOUNT"
        files["h2_lines_bank"] = (rows, cols)

    run, _, rep = run_and_report(tmp_path, tweak=tweak)
    assert rep["verdict"] == "FAILED" and any("not a plain decimal number" in f for f in rep["hard_failures"])
    assert "SENTINEL_BAD_AMOUNT" not in json.dumps(rep) and "SENTINEL_BAD_AMOUNT" not in (run / "staging" / "VALIDATION_REPORT.md").read_text(encoding="utf-8")


def test_pre_post_difference_rejects_the_run(tmp_path):
    def tweak(files, b):
        d, cols = files["c1_totals_bank_post"]
        files["c1_totals_bank_post"] = ([{**d[0], "lines": "999999"}] + d[1:], cols)

    _, _, rep = run_and_report(tmp_path, tweak=tweak)
    assert rep["verdict"] == "FAILED" and any("REFRESH RACE" in f for f in rep["hard_failures"])


def test_cube_and_register_must_be_the_same_snapshot(tmp_path):
    def tweak(files, b):
        for k in ("c3_bills_pre", "c3_bills_post"):
            d, cols = files[k]
            files[k] = ([{**d[0], "cube_report_date": "2026-10-05"}], cols)

    _, _, rep = run_and_report(tmp_path, tweak=tweak)
    assert rep["verdict"] == "FAILED" and any("not the same snapshot" in f for f in rep["hard_failures"])


def test_a_line_extracted_by_two_selections_must_be_identical_in_both(tmp_path):
    def tweak(files, b):
        rows, cols = files["h2_lines_bank"]
        both = next(r for r in rows if r["glname"] == "BANK ALPHA-1" and r["debit"] == "0" and r["credit"] == "0")
        both["narration"] = "changed"
        files["h2_lines_bank"] = (rows, cols)

    _, _, rep = run_and_report(tmp_path, tweak=tweak)
    assert rep["verdict"] == "FAILED" and any("conflicting duplicate" in f for f in rep["hard_failures"])


def test_a_dropped_line_breaks_balance_and_the_source_controls(tmp_path):
    def tweak(files, b):
        rows, cols = files["h1_lines_creditors_cur"]
        multi = [r for r in rows if r["glname"] == "Purchases"]
        rows.remove(multi[3])
        files["h1_lines_creditors_cur"] = (rows, cols)

    _, _, rep = run_and_report(tmp_path, tweak=tweak)
    assert rep["verdict"] == "FAILED"
    msgs = " ".join(rep["hard_failures"])
    assert "E3" in msgs and "control E1_creditors_cur" in msgs and "control E2_creditors_cur" in msgs


def test_a_link_to_an_entry_that_was_not_extracted_is_refused(tmp_path):
    def tweak(files, b):
        rows, cols = files["h1_lines_creditors_cur"]
        keep = [r for r in rows if r["entry_no"] != rows[0]["entry_no"]]
        files["h1_lines_creditors_cur"] = (keep, cols)

    _, _, rep = run_and_report(tmp_path, tweak=tweak)
    assert rep["verdict"] == "FAILED"


def test_capped_or_failed_dataset_fails_the_run(tmp_path):
    _, _, rep = run_and_report(tmp_path, statuses={"h2_lines_bank": "capped"})
    assert rep["verdict"] == "FAILED" and any("capped" in f for f in rep["hard_failures"])


def test_a_source_that_has_moved_past_the_pinned_cutoff_stops_the_run(tmp_path):
    def tweak(files, b):
        for k in ("c3_bills_pre", "c3_bills_post"):
            d, cols = files[k]
            files[k] = ([{**d[0], "cube_report_date": "2026-10-05"}], cols)
        for k in ("c4_register_pre", "c4_register_post"):
            files[k] = ([{"register_report_date": "2026-10-05"}], ["register_report_date"])

    _, _, rep = run_and_report(tmp_path, tweak=tweak)
    assert rep["verdict"] == "FAILED" and any("the source has moved on" in f for f in rep["hard_failures"])


def test_an_entry_carried_by_two_selections_with_different_lines_is_refused(tmp_path):
    def tweak(files, b):
        rows, cols = files["h2_lines_bank"]
        both = next(r for r in rows if r["glname"] == "BANK ALPHA-1" and r["debit"] == "0" and r["credit"] == "0" and r["entry_type_short"] == "PIM")
        rows.remove(next(r for r in rows if r["entry_no"] == both["entry_no"] and r["glname"] == "Purchases"))   # the bank selection extracted the entry incompletely
        files["h2_lines_bank"] = (rows, cols)

    _, _, rep = run_and_report(tmp_path, tweak=tweak)
    assert rep["verdict"] == "FAILED" and any("conflicting duplicate" in f for f in rep["hard_failures"])


def test_an_identical_line_twice_in_one_dataset_is_refused_not_deduplicated(tmp_path):
    def tweak(files, b):
        rows, cols = files["h2_lines_bank"]
        rows.append(dict(rows[0]))
        files["h2_lines_bank"] = (rows, cols)

    _, _, rep = run_and_report(tmp_path, tweak=tweak)
    assert rep["verdict"] == "FAILED" and any("identical line appears twice" in f for f in rep["hard_failures"])
