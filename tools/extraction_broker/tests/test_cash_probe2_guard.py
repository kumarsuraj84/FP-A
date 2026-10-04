import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import guard  # noqa: E402
from packages import PACKAGES  # noqa: E402


def test_cash_probe_is_aggregate_only_capped_and_misretail_only():
    for d in PACKAGES["cash_wc_probe_02"]:
        c = guard.check(d.sql, d.kind)
        assert c.row_cap <= 300, d.name
        assert "select *" not in d.sql.lower() and "SSRK" not in d.sql.upper(), d.name


def test_bank_position_uses_a_strict_report_date_cutoff_and_keeps_future_entries_apart():
    sql = {d.name: d.sql for d in PACKAGES["cash_wc_probe_02"]}["a1_bank_cash_position_gl_register"]
    assert "TRUNC(t.entry_date) <= TRUNC(r.rd)" in sql and "TRUNC(t.entry_date) > TRUNC(r.rd)" in sql
    for col in ("open_dr", "posted_dr", "posted_cr", "unposted_dr", "unposted_cr", "future_unposted_dr", "last_posted_date", "last_entry_date"):
        assert col in sql
    assert "LEFT JOIN" in sql  # ledgers without any movement still appear


def test_no_party_names_or_contact_columns_are_selected_for_debtors():
    for d in PACKAGES["cash_wc_probe_02"]:
        if d.name.startswith("b"):
            assert "sl_name" not in d.sql.lower() and "narration" not in d.sql.lower(), d.name
