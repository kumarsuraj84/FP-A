from datetime import date
from decimal import Decimal as D
from app.ageing.buckets import bucket_for, summarise
from app.recon.framework import ReconResult, ReconReport

def test_bucket_edges():
    assert [bucket_for(d) for d in (0, 30, 31, 60, 61, 90, 91, 180, 181, 365, 366)] == \
        ["0-30","0-30","31-60","31-60","61-90","61-90","91-180","91-180","181-365","181-365",">365"]
def test_summary_totals_preserved():
    items = [(date(2026,9,1), D("100.50")), (date(2025,1,1), D("200.25"))]
    assert sum(summarise(items, date(2026,10,3)).values()) == D("300.75")
def test_recon_is_exact_zero_tolerance():
    assert not ReconResult("debit", "co", D("100.00"), D("100.01")).passed
    assert ReconResult("debit", "co", D("100.00"), D("100.00"), D("100.00")).passed
def test_explained_variance_is_accepted_but_not_gate_pass():
    r = ReconResult("x", "s", D(10), D(9), explanation="unreleased entries excluded")
    rep = ReconReport([r]); assert r.accepted and not rep.gate_passed
def test_empty_report_never_passes(): assert not ReconReport().gate_passed
