"""Guard: committed *.example.* config files must never be copies of the real (git-ignored) finance files."""
from pathlib import Path

CFG = Path(__file__).resolve().parents[2] / "config" / "mgmt"


def test_examples_are_not_copies_of_real_files():
    bad = []
    for ex in CFG.glob("*.example.*"):
        real = ex.with_name(ex.name.replace(".example", ""))
        if real.exists() and real.read_bytes() == ex.read_bytes():
            bad.append(ex.name)
    assert not bad, f"example files identical to real finance files (would leak real data): {bad}"


def test_examples_use_placeholder_entities():
    for ex in CFG.glob("*.example.csv"):
        text = ex.read_text(encoding="utf-8", errors="ignore").lower()
        for real_id in ("ckspl", "ckvpl", "crpl", "retail pvt", "stores pvt", "unsecured loan", "haryana"):
            assert real_id not in text, f"{ex.name} contains a real identifier: {real_id}"
