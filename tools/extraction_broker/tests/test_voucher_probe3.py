import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import guard  # noqa: E402
from packages import PACKAGES  # noqa: E402


def test_voucher_probe_is_aggregate_only_capped_and_never_reads_names_paths_or_narration():
    ds = PACKAGES["voucher_probe_03"]
    assert len(ds) == 12
    for d in ds:
        c = guard.check(d.sql, d.kind)
        assert c.row_cap <= 2000, d.name
        low = d.sql.lower()
        assert "select *" not in low and "narration" not in low and "attachment_path," not in low and "ssrk" not in low, d.name
    pop = {d.name: d.sql.lower() for d in ds}["p2_portal_attachment_population"]
    assert "count(attachment_path)" in pop and "select attachment_path" not in pop   # existence counts only


def test_bridge_probes_restrict_the_register_to_the_four_creditor_ledgers_and_classify_by_distinct_entry_identity():
    for d in PACKAGES["voucher_probe_03"]:
        if d.name.startswith("b"):
            assert "entry_glcode IN (1000000026, 1000000024, 1000000092, 1000000025)" in d.sql, d.name
            assert "COUNT(DISTINCT r.st || '|' || r.t || '|' || r.n)" in d.sql, d.name   # (site, entry type, entry number)
