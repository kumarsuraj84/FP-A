import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import guard  # noqa: E402
from packages import CREDITOR_LEDGERS, PACKAGES, PAYABLES_PROBE_02  # noqa: E402


def test_registered_and_passes_the_guard():
    assert "payables_probe_02" in PACKAGES
    assert [d.name for d in PAYABLES_PROBE_02] == ["r1_creditor_due_by_ledger", "r2_creditor_due_by_party_class"]
    for d in PAYABLES_PROBE_02:
        assert guard.check(d.sql, d.kind).kind == "extract"


def test_scope_is_exactly_the_four_sundry_creditors_ledgers_and_open_rows():
    assert CREDITOR_LEDGERS == (1000000026, 1000000024, 1000000092, 1000000025)
    for d in PAYABLES_PROBE_02:
        sql = d.sql
        assert "o.ledger_code IN (1000000026, 1000000024, 1000000092, 1000000025)" in sql, d.name
        assert "o.pending <> 0" in sql, d.name
        for excluded in ("1000000029", "1000000014", "1114925452"):  # TDS Payable, Sundry Debtors, Inter-Company
            assert excluded not in sql, (d.name, excluded)


def test_misretail_only_aggregates_with_no_row_level_or_personal_columns():
    for d in PAYABLES_PROBE_02:
        up = d.sql.upper()
        assert "SSRK" not in up and "PUBLIC" not in up and "T$FINOTSD_637" not in up, d.name
        for obj in re.findall(r"(?i)\b(?:from|join)\s+([\w$#\".]+)", d.sql):
            assert obj.upper().startswith("MISRETAIL."), (d.name, obj)
        assert "GROUP BY" in up and "REPORT_DATE >= DATE" in up
        for bad in ("sl_name", "slid", "slcode,", "sub_ledger_code,", "addr", "phone", "email", "mobile"):
            assert bad not in d.sql.lower().split("from (")[0], (d.name, bad)
        for alias in re.findall(r"(?i)\bAS\s+([a-z_][a-z0-9_$#]*)", d.sql):
            assert len(alias) <= 30, (d.name, alias)


def test_it_reports_exactly_what_was_asked():
    r1, r2 = PAYABLES_PROBE_02[0].sql.lower(), PAYABLES_PROBE_02[1].sql.lower()
    for piece in ("ledger_name", "drcr", "credit_days_state", "due_state", "count(*) as open_rows", "sum(abs(pending)) as abs_pending", "sum(pending) as signed_pending"):
        assert piece in r1, piece
    assert "party_class" in r2 and "group by party_class" in r2
    inner = PAYABLES_PROBE_02[0].sql
    for state in ("credit_days_null", "credit_days_zero", "credit_days_positive", "due_missing", "due_present_not_yet_due", "due_present_due_or_past"):
        assert state in inner
