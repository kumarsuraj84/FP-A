"""pl_actuals_01: guarded, MISRETAIL-only, chunked by month, window ends at the as-of day, registers switch at the financial year start. No Oracle."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import guard  # noqa: E402
import packages  # noqa: E402
import pl_actuals as pl  # noqa: E402


def ds(as_of="2026-10-05"):
    pl.configure_pl(as_of)
    return {d.name: d for d in packages.PACKAGES["pl_actuals_01"]}


def test_every_query_is_guarded_capped_misretail_only_and_without_ssrk_views():
    for d in ds().values():
        c = guard.check(d.sql, d.kind)
        assert c.row_cap <= 100_000
        assert "SSRK" not in d.sql.upper() and "PUBLIC" not in d.sql.upper() and "V_CFO_DASHBOARD" not in d.sql.upper() and "COGS_DATA" not in d.sql.upper()
        for obj in re.findall(r"(?i)\b(?:from|join)\s+([\w$#\".]+)", d.sql):
            assert obj.upper().startswith("MISRETAIL."), (d.name, obj)


def test_one_query_per_month_from_april_2025_and_the_window_ends_at_the_as_of_day():
    d = ds("2026-10-05")
    months = sorted(n for n in d if n.startswith("g_"))
    assert months[0] == "g_2025_04" and months[-1] == "g_2026_10" and len(months) == 19
    assert "r.entry_date < DATE '2026-10-06'" in d["g_2026_10"].sql and "r.entry_date >= DATE '2026-10-01'" in d["g_2026_10"].sql   # the as-of day included, nothing after it
    assert "r.entry_date < DATE '2026-09-01'" in d["g_2026_08"].sql.replace("2026-09-01", "2026-09-01")
    assert "DATE '2026-09-01'" in d["g_2026_08"].sql and "DATE '2026-12" not in "".join(x.sql for x in d.values())   # future-dated entries are never read


def test_registers_switch_at_the_financial_year_start():
    d = ds()
    assert "T$FINREGSITE_877" in d["g_2026_03"].sql and "T$FINREGSITE_844" not in d["g_2026_03"].sql
    assert "T$FINREGSITE_844" in d["g_2026_04"].sql and "T$FINREGSITE_877" not in d["g_2026_04"].sql


def test_the_ledger_filter_is_the_gl_master_type_and_the_controls_have_a_different_shape():
    d = ds()
    assert all("g.type IN ('Income', 'Expense')" in d[n].sql for n in d if n.startswith(("g_", "c1_")))
    ctl = d["c1_totals_cur_pre"].sql
    assert "GROUP BY TO_CHAR(r.entry_date, 'YYYY-MM'), r.release_status" in ctl and "GROUP BY r.sitecode" not in ctl and "SELECT TO_CHAR(r.sitecode)" not in ctl
    assert d["c1_totals_cur_pre"].sql == d["c1_totals_cur_post"].sql and d["c0_register_pre"].sql == d["c0_register_post"].sql


@pytest.mark.parametrize("bad", ["2026-13-01", "10-05-2026", "2026-10-5", "", "2026-03-31", "today"])
def test_the_as_of_date_is_explicit_and_validated(bad):
    with pytest.raises(ValueError):
        pl.configure_pl(bad)
    pl.configure_pl("2026-10-05")
