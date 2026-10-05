import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import packages  # noqa: E402

BROKER = Path(__file__).resolve().parents[1] / "broker.py"


def run(*args):
    return subprocess.run([sys.executable, str(BROKER), *args], capture_output=True, text=True, timeout=120)


def test_the_entry_cutoff_is_a_parameter_and_reaches_every_dataset_that_uses_it():
    packages.configure_entry("2026-10-05")
    try:
        assert packages.ENTRY_META["contract"]["as_of_cutoff"] == "2026-10-05"
        used = [d for d in packages.ENTRY_PILOT_01 if d.name.startswith(("h2", "h3", "l2", "c1_", "c2_"))]
        assert used and all("DATE '2026-10-05'" in d.sql and "DATE '2026-10-04'" not in d.sql for d in used)
        assert packages.PACKAGES["entry_pilot_01"] is packages.ENTRY_PILOT_01
    finally:
        packages.configure_entry("2026-10-04")


@pytest.mark.parametrize("bad", ["2026-13-45", "05-10-2026", "2026-10-5", "today", ""])
def test_a_malformed_date_is_refused(bad):
    with pytest.raises(ValueError):
        packages.configure_entry(bad)


def test_the_broker_has_no_implicit_today_and_no_date_for_other_packages():
    r = run("plan", "entry_pilot_01")
    assert r.returncode == 2 and "explicit --as-of" in r.stdout and "implicit today" in r.stdout
    assert run("plan", "entry_pilot_01", "--as-of", "2026-10-05").returncode == 0
    r = run("plan", "cash_pilot_01", "--as-of", "2026-10-05")
    assert r.returncode == 2 and "does not take an as-of date" in r.stdout
