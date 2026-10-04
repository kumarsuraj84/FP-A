import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import guard  # noqa: E402
from packages import PACKAGES, PAYABLES_PROBE_01  # noqa: E402


def test_the_package_is_registered_and_every_query_passes_the_guard():
    assert "payables_probe_01" in PACKAGES
    assert [d.name for d in PAYABLES_PROBE_01] == ["q1_due_date_derivation", "q2_date_quality_by_exposure", "q3_payable_population", "q4_amount_adjusted_pending"]
    for d in PAYABLES_PROBE_01:
        assert guard.check(d.sql, d.kind).kind == "extract"


def test_scope_is_misretail_only_and_the_joins_stay_inside_misretail():
    for d in PAYABLES_PROBE_01:
        up = d.sql.upper()
        assert "SSRK" not in up and "PUBLIC" not in up and "FINPOST" not in up, d.name
        assert 'MISRETAIL."T$FINOTSD_533"' in up and "T$FINOTSD_637" not in up, d.name
        for obj in re.findall(r"(?i)\b(?:from|join)\s+([\w$#\".]+)", d.sql):
            assert obj.upper().startswith("MISRETAIL."), (d.name, obj)
        assert "REPORT_DATE >= DATE" in up, f"{d.name}: date-bounded"


def test_no_row_level_extract_no_star_no_personal_columns():
    for d in PAYABLES_PROBE_01:
        assert not re.search(r"(?i)select\s+(distinct\s+)?\*", d.sql), d.name
        assert "GROUP BY" in d.sql.upper(), f"{d.name}: aggregates only"
        for bad in ("addr", "phone", "email", "mobile", "pan_no", "contact", "fax", "billing_", "sl_name", "slid", "customer"):
            assert bad not in d.sql.lower(), (d.name, bad)


def test_every_alias_fits_oracle_12_1s_30_character_limit():
    for d in PAYABLES_PROBE_01:
        for alias in re.findall(r"(?i)\bAS\s+([a-z_][a-z0-9_$#]*)", d.sql):
            assert len(alias) <= 30, f"{d.name}: alias '{alias}' is {len(alias)} characters"


def test_probe_1_looks_only_at_open_rows_and_never_writes_a_derived_due_date():
    sql = PAYABLES_PROBE_01[0].sql.lower()
    assert "o.pending <> 0" in sql
    assert "trunc(o.document_date) + s.credit_days" in sql and "trunc(o.entry_date) + s.credit_days" in sql
    for k in ("due_date_basis", "sl_class_type", "sl_class", "drcr", "credit_days_state"):
        assert f"group by due_date_basis, sl_class_type, sl_class, drcr, credit_days_state" in sql or k in sql
    assert "update" not in sql and "insert" not in sql


def test_probe_2_splits_settled_vs_open_and_weights_by_absolute_pending():
    sql = PAYABLES_PROBE_01[1].sql.lower()
    assert "case when o.pending = 0 then 'settled' else 'open' end" in sql
    for f in ("doc_pre2000", "doc_after_report", "due_after_report", "doc_null", "due_null", "credit_null"):
        assert f"{f}_rows" in sql and f"{f}_abs" in sql, f
    assert "abs(o.pending)" in sql


def test_probe_3_groups_by_ledger_type_drcr_and_party_class_with_signed_and_absolute_pending():
    sql = PAYABLES_PROBE_01[2].sql.lower()
    for piece in ("o.ledger_code", "l.glname", "l.type", "o.drcr", "s.sl_class_type", "s.sl_class", "sum(o.pending)", "sum(abs(o.pending))", "count(distinct", "open_rows"):
        assert piece in sql, piece
    assert "left join misretail.ledger_mv" in sql and "left join misretail.sub_ledger_mv" in sql  # unmatched rows are kept, not dropped


def test_probe_4_tests_the_candidate_sign_conventions():
    sql = PAYABLES_PROBE_01[3].sql.lower()
    for piece in ("amount - nvl(adjusted, 0)", "amount + nvl(adjusted, 0)", "sign(amount)", "adjusted_positive", "adjusted_negative", "group by drcr, pending_state"):
        assert piece in sql, piece
