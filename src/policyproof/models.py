from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal


Decision = Literal["APPROVE", "REJECT", "REVIEW"]


@dataclass(frozen=True)
class PolicyRule:
    id: str
    condition: str
    decision: Decision


@dataclass(frozen=True)
class TestCase:
    amount: Decimal
    has_service_date: bool
    description: str = ""


@dataclass(frozen=True)
class TestResult:
    case: TestCase
    expected: Decision
    actual: Decision
    rule_id: str | None = None
    explanation: str = ""

    @property
    def mismatch(self) -> bool:
        return self.expected != self.actual


@dataclass
class VerificationReport:
    results: list[TestResult] = field(default_factory=list)

    @property
    def mismatch_count(self) -> int:
        return sum(result.mismatch for result in self.results)

    @property
    def passed(self) -> bool:
        return self.mismatch_count == 0
