"""Reconciliation gate: source vs mart vs KPI. Tolerance is exactly zero.
Every non-zero variance must carry an explanation; it is never rounded away."""
from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class ReconResult:
    name: str
    scope: str
    source: Decimal
    mart: Decimal
    kpi: Decimal | None = None
    explanation: str = ""

    @property
    def variance_mart(self) -> Decimal:
        return self.mart - self.source

    @property
    def variance_kpi(self) -> Decimal:
        return Decimal(0) if self.kpi is None else self.kpi - self.mart

    @property
    def passed(self) -> bool:
        return self.variance_mart == 0 and self.variance_kpi == 0

    @property
    def accepted(self) -> bool:
        """Zero variance, or non-zero but explicitly explained (reported, not hidden)."""
        return self.passed or bool(self.explanation)


@dataclass
class ReconReport:
    results: list[ReconResult] = field(default_factory=list)

    def add(self, r: ReconResult) -> ReconResult:
        self.results.append(r)
        return r

    @property
    def gate_passed(self) -> bool:
        return bool(self.results) and all(r.passed for r in self.results)

    def to_markdown(self) -> str:
        rows = ["| Check | Scope | Source | Mart | KPI | Mart-Src | KPI-Mart | Status | Explanation |",
                "|---|---|---|---|---|---|---|---|---|"]
        for r in self.results:
            rows.append(f"| {r.name} | {r.scope} | {r.source} | {r.mart} | {r.kpi if r.kpi is not None else '-'} | "
                        f"{r.variance_mart} | {r.variance_kpi} | {'PASS' if r.passed else 'FAIL'} | {r.explanation} |")
        return "\n".join(rows)
