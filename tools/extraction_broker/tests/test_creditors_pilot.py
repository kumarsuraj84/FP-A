import json
import re
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import creditors_stage as cs  # noqa: E402
import guard  # noqa: E402
import manifest as mf  # noqa: E402
from packages import CREDITOR_LEDGERS, CREDITORS_PILOT_01, PACKAGE_META, PACKAGES, PILOT_RULES  # noqa: E402

RULES = PILOT_RULES
AS_OF = date(2026, 10, 4)


# ───────────── the package ─────────────


def test_package_registered_guarded_and_in_the_agreed_order_with_roles():
    assert PACKAGES["creditors_pilot_01"] is CREDITORS_PILOT_01
    assert [(d.name, d.role) for d in CREDITORS_PILOT_01] == [
        ("c1_source_control_pre", "control_pre"), ("c2_vendor_control_pre", "control_pre"), ("c3_snapshot_control_pre", "control_pre"),
        ("e1_open_items", "extract"), ("e2_identity_all_rows", "identity"),
        ("c1_source_control_post", "control_post"), ("c2_vendor_control_post", "control_post"), ("c3_snapshot_control_post", "control_post"),
    ]
    caps = {d.name: guard.check(d.sql, d.kind).row_cap for d in CREDITORS_PILOT_01}
    assert caps["e1_open_items"] == 50_000 and caps["e2_identity_all_rows"] == 500_000
    assert PACKAGE_META["creditors_pilot_01"]["halt_on_failure"] is True
    # the post controls are byte-identical to the pre controls, so any difference can only come from the data
    by = {d.name: d.sql for d in CREDITORS_PILOT_01}
    for k in ("c1_source_control", "c2_vendor_control", "c3_snapshot_control"):
        assert by[f"{k}_pre"] == by[f"{k}_post"]


def test_scope_columns_and_exclusions():
    by = {d.name: d.sql for d in CREDITORS_PILOT_01}
    for name, sql in by.items():
        assert "o.ledger_code IN (1000000026, 1000000024, 1000000092, 1000000025)" in sql, name
        for excluded in ("1000000029", "1000000014", "1114925452"):
            assert excluded not in sql
        assert "SSRK" not in sql.upper() and "PUBLIC" not in sql.upper()
        for obj in re.findall(r"(?i)\b(?:from|join)\s+([\w$#\".]+)", sql):
            assert obj.upper().startswith("MISRETAIL.") or obj == "(", (name, obj)
    assert "o.pending <> 0" in by["e1_open_items"] and "o.pending <> 0" not in by["e2_identity_all_rows"]
    e1 = by["e1_open_items"].lower()
    for forbidden in ("narration", "agentname", "agent_alias", "no_of_days", "release_status", "end_date", "billing", "email", "mobile", "pan_no", "bankaccount"):
        assert forbidden not in e1, forbidden
    assert re.findall(r"(?i)as\s+([a-z_]+)", by["e1_open_items"]) and all(len(a) <= 30 for a in re.findall(r"(?i)\bas\s+([a-z_][a-z0-9_]*)", by["e1_open_items"]))
    # numbers and dates leave Oracle as exact text
    for c in ("amount", "adjusted", "pending", "sub_ledger_code"):
        assert f"TO_CHAR(o.{c}, 'TM9')" in by["e1_open_items"]
    for c in ("document_date", "due_date", "ref_date", "entry_date", "report_date"):
        assert f"TO_CHAR(o.{c}, 'YYYY-MM-DD')" in by["e1_open_items"]
    # comparisons in the Oracle-side rules are on whole days, like the offline rules
    c1 = by["c1_source_control_pre"]
    assert "TRUNC(o.due_date) < TRUNC(o.document_date)" in c1 and "TRUNC(o.document_date) < DATE '2000-01-01'" in c1


# ───────────── rules ─────────────


def age(text):
    return cs.classify_age(cs.parse_date(text), AS_OF, RULES)


@pytest.mark.parametrize("days,bucket", [(0, "D0_30"), (30, "D0_30"), (31, "D31_60"), (60, "D31_60"), (61, "D61_90"), (90, "D61_90"), (91, "D91_180"), (180, "D91_180"),
                                         (181, "D181_365"), (365, "D181_365"), (366, "D365_PLUS"), (4000, "D365_PLUS")])
def test_document_age_bucket_edges(days, bucket):
    b, d, q = age((AS_OF - timedelta(days=days)).isoformat())
    assert (b, d, q) == (bucket, days, "OK")


def test_unclassified_document_age_is_never_forced_into_a_bucket():
    assert age(None) == ("UNCLASSIFIED_MISSING", None, "MISSING")
    assert age("0202-01-01") == ("UNCLASSIFIED_BEFORE_MIN", None, "BEFORE_MIN")  # the real year-0202 rows
    assert age("1999-12-31")[0] == "UNCLASSIFIED_BEFORE_MIN" and age("2000-01-01")[0] == "D365_PLUS"
    assert age("2026-10-05") == ("UNCLASSIFIED_AFTER_AS_OF", None, "AFTER_AS_OF")  # one day after the as-of date
    assert age("2026-10-04")[0] == "D0_30"
    assert age("2026-13-45") == ("UNCLASSIFIED_UNPARSEABLE", None, "UNPARSEABLE")
    assert age("not a date")[0] == "UNCLASSIFIED_UNPARSEABLE"


def test_the_validity_window_is_configurable_not_hard_coded():
    wide = {**RULES, "valid_date_min": "1990-01-01"}
    assert cs.classify_age(cs.parse_date("1995-06-01"), AS_OF, wide)[0] == "D365_PLUS"
    assert cs.classify_age(cs.parse_date("1995-06-01"), AS_OF, RULES)[0] == "UNCLASSIFIED_BEFORE_MIN"


def due(text, doc=None):
    return cs.classify_due(cs.parse_date(text), cs.parse_date(doc), AS_OF, RULES)


def test_due_status_rules_including_the_distinctions_the_cfo_asked_for():
    assert due(None) == ("DUE_UNAVAILABLE", None)  # never derived from CREDIT_DAYS
    assert due("2026-10-05", "2026-09-01") == ("NOT_YET_DUE", None)  # due after the as-of date: not yet due, NOT invalid
    assert due("2026-10-04", "2026-09-01") == ("PAST_DUE_OR_DUE_TODAY", 0)
    assert due("2026-09-24", "2026-09-01") == ("PAST_DUE_OR_DUE_TODAY", 10)
    assert due("2026-08-31", "2026-09-01") == ("DUE_INVALID", None)  # due before the document date
    assert due("2026-09-01", "2026-09-01")[0] == "PAST_DUE_OR_DUE_TODAY"
    assert due("1999-01-01")[0] == "DUE_INVALID" and due("2101-01-01")[0] == "DUE_INVALID" and due("garbage")[0] == "DUE_INVALID"
    assert due("2026-09-01", None)[0] == "PAST_DUE_OR_DUE_TODAY"  # no document date: nothing to compare against
    assert due("2026-09-01", "0202-01-01")[0] == "PAST_DUE_OR_DUE_TODAY"  # compared with the stored value, which is earlier


def test_decimals_are_exact_and_oracle_tm9_forms_are_accepted():
    assert cs.parse_decimal(".5") == Decimal("0.5") and cs.parse_decimal("-.5") == Decimal("-0.5")
    assert cs.parse_decimal("-2889490.03") == Decimal("-2889490.03") and cs.parse_decimal("0") == 0
    assert cs.parse_decimal(None) is None
    for bad in ("1,5", "1e5", "", " ", "abc", "1.2.3", "--1", "₹5"):
        with pytest.raises(cs.StageError):
            cs.parse_decimal(bad)


def test_identity_key_is_stable_and_ignores_mutable_state():
    k = cs.source_row_key("DOC-1", "123")
    assert k == cs.source_row_key("DOC-1", "123") and len(k) == 64
    assert k != cs.source_row_key("DOC-1", "124") and k != cs.source_row_key("DOC-2", "123")
    assert cs.k1_signature("DOC-1", "1000000026", "123", "Cr") != k
    base = {"ledger_code": "1", "drcr": "Cr", "amount": Decimal("-10.00"), "adjusted": None, "pending": Decimal("-10.00"), "document_date": "2026-01-01"}
    f1 = cs.fingerprint(cs.FINGERPRINT_FIELDS, base)
    assert f1 == cs.fingerprint(cs.FINGERPRINT_FIELDS, {**base, "amount": Decimal("-10.0")})  # numerically equal, same fingerprint
    for change in ({"pending": Decimal("-5.00")}, {"drcr": "Dr"}, {"ledger_code": "2"}, {"adjusted": Decimal("1")}):
        assert cs.fingerprint(cs.FINGERPRINT_FIELDS, {**base, **change}) != f1  # drift is visible, identity unchanged
    assert cs.canon(Decimal("-0.00")) == "0" and cs.canon(None) == cs.NULL
    assert cs.check_identity_parts("A|B", "1") == "contains_delimiter" and cs.check_identity_parts("", "1") == "null_or_empty" and cs.check_identity_parts("A", None) == "null_or_empty"


def test_staging_never_reads_the_current_date():
    src = Path(cs.__file__).read_text(encoding="utf-8")
    code = "\n".join(line for line in src.splitlines() if not line.lstrip().startswith(("#", '"""')))
    for banned in ("date.today", "datetime.now", "datetime.today", "time.time(", "CURRENT_DATE", "SYSDATE"):
        assert banned not in code, banned


# ───────────── end to end on a synthetic run ─────────────

LED = [str(c) for c in CREDITOR_LEDGERS]
NAMES = dict(zip(LED, ["Sundry Creditors-Apparels", "Sundry Creditors for Expenses", "Sundry Creditors-GM", "Sundry Creditors-Non Trading"]))


def synth_rows():
    rows = []
    n = 0
    for i, led in enumerate(LED):
        for j in range(12):
            n += 1
            cr = j % 4 != 3
            pend = Decimal(f"{(n * 137) % 9000 + 10}.{n % 100:02d}")
            pend = -pend if cr else pend
            doc_age = [3, 40, 75, 120, 200, 400, 0, 90, 30, 365, 366, 31][j]
            docd = (AS_OF - timedelta(days=doc_age)).isoformat()
            dd = {0: None, 1: (AS_OF + timedelta(days=5)).isoformat(), 2: (AS_OF - timedelta(days=20)).isoformat(), 3: "2026-01-01"}[j % 4]
            row = {
                "as_of_date": AS_OF.isoformat(), "document_code": f"DOC{n:04d}", "sub_ledger_code": str(500 + (n % 7)), "ledger_code": led, "ledger_name": NAMES[led],
                "slid": f"SL{500 + (n % 7)}", "vendor_name": f"Vendor {n % 7}", "party_class": "Supplier-Apparels" if (n % 7) % 5 else "Staff", "party_class_type": "Supplier",
                "credit_days": "30" if (n % 7) % 2 else "0", "vendor_extinct": "No", "document_no": f"N{n}", "document_type": "PI", "document_initial": "PI",
                "document_date": docd, "due_date": dd, "due_date_basis": "Document Date", "ref_no": None if n % 3 else f"R{n}", "ref_date": None,
                "entry_date": docd, "drcr": "Cr" if cr else "Dr", "amount": str(pend), "adjusted": None, "pending": str(pend), "created_by_site": "HO",
            }
            rows.append(row)
    rows[5]["document_date"] = "0202-01-01"  # a bad date that must end up Unclassified
    rows[6]["document_date"] = None
    rows[7]["due_date"] = "2026-06-01"
    rows[7]["document_date"] = "2026-07-01"  # due before document: invalid due
    return rows


def write_pq(path, rows, cols):
    pq.write_table(pa.table({c: pa.array([r[c] if isinstance(r[c], (str, type(None))) else str(r[c]) for r in rows], type=pa.string()) for c in cols}), path)


def controls_for(rows):
    """Independent re-implementation of the Oracle-side source controls on the raw rows."""
    g, vend = {}, {}
    for r in rows:
        doc, due = cs.parse_date(r["document_date"]), cs.parse_date(r["due_date"])
        b = cs.classify_age(doc, AS_OF, RULES)[0]
        u = cs.classify_due(due, doc, AS_OF, RULES)[0]
        p = Decimal(r["pending"])
        k = (r["ledger_code"], r["drcr"], b, u)
        x = g.setdefault(k, [0, Decimal(0), Decimal(0)])
        x[0] += 1; x[1] += abs(p); x[2] += p
    c1 = [{"ledger_code": k[0], "drcr": k[1], "doc_age_bucket": k[2], "due_status": k[3], "item_rows": v[0], "abs_pending": str(v[1]), "signed_pending": str(v[2])} for k, v in sorted(g.items())]
    sets = {"all": set(), **{}}
    c2 = []
    for gl, gd, led, dr in [(1, 1, None, None)] + [(0, 1, l, None) for l in LED] + [(1, 0, None, d) for d in ("Cr", "Dr")] + [(0, 0, l, d) for l in LED for d in ("Cr", "Dr")]:
        sel = [r for r in rows if (gl and gd) or (gd and r["ledger_code"] == led) or (gl and r["drcr"] == dr) or (not gl and not gd and r["ledger_code"] == led and r["drcr"] == dr)]
        if sel:
            c2.append({"g_ledger": gl, "g_drcr": gd, "ledger_code": led, "drcr": dr, "vendors": len({r["sub_ledger_code"] for r in sel}), "item_rows": len(sel)})
    c3 = [{"item_rows": len(rows), "report_dates": 1, "min_as_of": AS_OF.isoformat(), "max_as_of": AS_OF.isoformat(),
           "distinct_identity_keys": len({(r["document_code"], r["sub_ledger_code"]) for r in rows}),
           "distinct_k1_keys": len({(r["document_code"], r["ledger_code"], r["sub_ledger_code"], r["drcr"]) for r in rows}), "null_identity_rows": 0,
           "null_document_date_rows": sum(1 for r in rows if r["document_date"] is None), "null_due_date_rows": sum(1 for r in rows if r["due_date"] is None),
           "rows_without_vendor_master": 0, "rows_without_ledger_master": 0}]
    return c1, c2, c3


C1_COLS = ["ledger_code", "drcr", "doc_age_bucket", "due_status", "item_rows", "abs_pending", "signed_pending"]
C2_COLS = ["g_ledger", "g_drcr", "ledger_code", "drcr", "vendors", "item_rows"]
C3_COLS = ["item_rows", "report_dates", "min_as_of", "max_as_of", "distinct_identity_keys", "distinct_k1_keys", "null_identity_rows", "null_document_date_rows",
           "null_due_date_rows", "rows_without_vendor_master", "rows_without_ledger_master"]


def build_run(tmp_path, rows=None, settled=3, post_tweak=None, statuses=None, name="run_test_001"):
    run = tmp_path / name
    run.mkdir()
    rows = rows or synth_rows()
    c1, c2, c3 = controls_for(rows)
    e2 = [{"document_code": r["document_code"], "sub_ledger_code": r["sub_ledger_code"], "ledger_code": r["ledger_code"], "drcr": r["drcr"], "pending": r["pending"],
           "entry_date": r["entry_date"], "as_of_date": r["as_of_date"]} for r in rows]
    for i in range(settled):
        e2.append({"document_code": f"SETTLED{i}", "sub_ledger_code": str(900 + i), "ledger_code": LED[0], "drcr": "Dr", "pending": "0", "entry_date": "2025-01-01", "as_of_date": AS_OF.isoformat()})
    files = {
        "c1_source_control_pre": (c1, C1_COLS), "c2_vendor_control_pre": (c2, C2_COLS), "c3_snapshot_control_pre": (c3, C3_COLS),
        "e1_open_items": (rows, cs.E1_COLUMNS), "e2_identity_all_rows": (e2, cs.E2_COLUMNS),
        "c1_source_control_post": (c1, C1_COLS), "c2_vendor_control_post": (c2, C2_COLS), "c3_snapshot_control_post": (c3, C3_COLS),
    }
    if post_tweak:
        post_tweak(files)
    entries = []
    for name, (data, cols) in files.items():
        f = run / f"{name}.parquet"
        write_pq(f, data, cols)
        entries.append({"dataset": name, "kind": "extract", "role": cs.EXPECTED_DATASETS[name], "source_object": 'MISRETAIL."T$FINOTSD_533"', "logical_source": None, "copy_id": None,
                        "query_id": 1, "query_hash": "a" * 64, "extracted_at": "2026-10-04T10:00:00", "row_count": len(data), "row_cap": 1_000_000, "min_date": None, "max_date": None,
                        "file_name": f.name, "file_size": f.stat().st_size, "sha256": mf.sha256_file(f), "status": (statuses or {}).get(name, "ok")})
    manifest = {"run_id": run.name, "package": "creditors_pilot_01", "created_at": "x", "broker_version": "1", "manifest_version": 2,
                "contract": {**PACKAGE_META["creditors_pilot_01"]["contract"]}, "datasets": entries}
    mf.write_manifest(run, manifest)
    return run


def test_a_clean_run_passes_and_writes_aggregate_only_reports(tmp_path):
    run = build_run(tmp_path)
    rep = cs.validate(run)
    assert rep["verdict"] == "PASSED", rep["hard_failures"]
    assert all(c["verdict"] == "PASS" for c in rep["controls"]) and len(rep["controls"]) > 100
    a = rep["aggregates"]
    assert a["rows"] == 48 and a["distinct_keys"] == 48 and a["e2_settled_rows"] == 3 and a["e2_open_rows"] == 48
    assert Decimal(a["credit_outstanding"]) + Decimal(a["creditor_debit_balances"]) == sum(abs(Decimal(r["pending"])) for r in synth_rows())
    assert Decimal(a["signed_net"]) == sum(Decimal(r["pending"]) for r in synth_rows())
    out = run / "staging"
    t = pq.read_table(out / "creditor_open_items.parquet").to_pylist()
    assert len(t) == 48 and len({r["source_row_key"] for r in t}) == 48
    assert any(r["document_age_bucket"] == "UNCLASSIFIED_BEFORE_MIN" for r in t) and any(r["document_age_bucket"] == "UNCLASSIFIED_MISSING" for r in t)
    assert any(r["due_status"] == "DUE_INVALID" for r in t) and any(r["due_status"] == "DUE_UNAVAILABLE" for r in t) and any(r["due_status"] == "NOT_YET_DUE" for r in t)
    assert {r["classification_status"] for r in t} == {"CREDIT_OUTSTANDING", "CREDITOR_DEBIT_BALANCE_CLASSIFICATION_PENDING"}
    assert all(isinstance(r["pending"], Decimal) for r in t)
    text = (out / "validation_report.json").read_text(encoding="utf-8") + (out / "VALIDATION_REPORT.md").read_text(encoding="utf-8")
    assert "Vendor 3" not in text and "DOC0001" not in text and "SL503" not in text  # no vendor names, document codes or vendor codes in reports


def test_pre_post_difference_rejects_the_run_even_if_the_extract_looks_valid(tmp_path):
    def tweak(files):
        c3, cols = files["c3_snapshot_control_post"]
        files["c3_snapshot_control_post"] = ([{**c3[0], "item_rows": c3[0]["item_rows"] + 1}], cols)
    rep = cs.validate(build_run(tmp_path, post_tweak=tweak))
    assert rep["verdict"] == "FAILED" and any("REFRESH RACE" in f for f in rep["hard_failures"])
    assert not (tmp_path / "run_test_001" / "staging" / "creditor_open_items.parquet").exists()  # nothing publishable is written


def test_duplicate_primary_key_fails_the_run_with_no_deduplication(tmp_path):
    rows = synth_rows()
    rows.append({**rows[0], "ledger_code": LED[1], "drcr": rows[0]["drcr"]})  # same DOCUMENT_CODE + SUB_LEDGER_CODE
    rep = cs.validate(build_run(tmp_path, rows=rows))
    assert rep["verdict"] == "FAILED" and any("DUPLICATE PRIMARY KEY" in f for f in rep["hard_failures"])


@pytest.mark.parametrize("status", ["capped", "failed", "skipped"])
def test_a_capped_failed_or_skipped_dataset_fails_the_pilot(tmp_path, status):
    rep = cs.validate(build_run(tmp_path, statuses={"e1_open_items": status}))
    assert rep["verdict"] == "FAILED"


def test_a_source_control_that_disagrees_with_the_extract_fails_with_the_variance(tmp_path):
    def tweak(files):
        for suffix in ("pre", "post"):
            c1, cols = files[f"c1_source_control_{suffix}"]
            c1 = [dict(r) for r in c1]
            c1[0]["abs_pending"] = str(Decimal(c1[0]["abs_pending"]) + Decimal("0.01"))  # one paisa
            files[f"c1_source_control_{suffix}"] = (c1, cols)
    rep = cs.validate(build_run(tmp_path, post_tweak=tweak))
    assert rep["verdict"] == "FAILED" and any("CONTROL FAILED" in f and "0.01" in f for f in rep["hard_failures"])


def test_wrong_sign_mixed_as_of_and_identity_extract_disagreement_all_fail(tmp_path):
    rows = synth_rows()
    rows[0]["pending"] = rows[0]["amount"] = str(-Decimal(rows[0]["pending"]))  # Cr with positive PENDING
    assert cs.validate(build_run(tmp_path, rows=rows))["verdict"] == "FAILED"

    (tmp_path / "b").mkdir()
    rows = synth_rows()
    rows[3]["as_of_date"] = "2026-10-03"
    assert cs.validate(build_run(tmp_path / "b", rows=rows))["verdict"] == "FAILED"

    (tmp_path / "c").mkdir()

    def tweak(files):
        e2, cols = files["e2_identity_all_rows"]
        e2 = [dict(r) for r in e2]
        e2[0]["pending"] = "0"  # e1 says open, e2 says settled
        files["e2_identity_all_rows"] = (e2, cols)
    rep = cs.validate(build_run(tmp_path / "c", post_tweak=tweak))
    assert rep["verdict"] == "FAILED" and any("e2" in f for f in rep["hard_failures"])


def test_identity_parts_that_are_null_or_contain_the_delimiter_fail(tmp_path):
    rows = synth_rows()
    rows[2]["document_code"] = "A|B"
    assert cs.validate(build_run(tmp_path, rows=rows))["verdict"] == "FAILED"


def test_the_columns_must_match_the_contract_exactly(tmp_path):
    def tweak(files):
        e1, cols = files["e1_open_items"]
        files["e1_open_items"] = (e1, [c for c in cols if c != "ref_no"])
    with pytest.raises(Exception):
        cs.validate(build_run(tmp_path, post_tweak=tweak))
