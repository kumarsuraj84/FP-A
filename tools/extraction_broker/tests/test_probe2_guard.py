import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import guard  # noqa: E402
from packages import PACKAGES  # noqa: E402


def test_every_dataset_of_the_follow_up_probe_passes_the_guard_and_stays_aggregate():
    for d in PACKAGES["profit_cash_probe_02"]:
        assert guard.check(d.sql, d.kind).row_cap <= 5000, d.name
        assert "select *" not in d.sql.lower(), d.name


def test_the_payment_mode_column_is_allowed_by_exact_name_only():
    ok = "SELECT SUM(mop_phonepe) AS p FROM MISRETAIL.V_FINANCE_MOP_SALES WHERE billdate >= DATE '2026-04-01' FETCH FIRST 1 ROWS ONLY"
    assert guard.check(ok, "extract")
    for bad in ("phone_no", "customer_phone", "mobile_no", "mop_phonepe_no", "phonepe_number"):
        sql = f"SELECT {bad} FROM MISRETAIL.V_FINANCE_MOP_SALES WHERE billdate >= DATE '2026-04-01' FETCH FIRST 1 ROWS ONLY"
        with pytest.raises(guard.GuardError):
            guard.check(sql, "extract")
