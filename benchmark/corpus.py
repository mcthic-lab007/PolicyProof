"""Ground-truth corpus for the PolicyProof adversarial-verification benchmark.

CORPUS_VERSION identifies this exact corpus. Any change to a target, its
ground truth or an expected verdict is a new version, so results from
different versions are never compared as if they measured the same thing.

Every case runs the committed synthetic Muse-shaped fixture (not a live
model response) against the fictional DemoCo meal policy, so the benchmark
needs no API key or network and measures PolicyProof's own verification
machinery only.

Ground truth: ``intervals`` lists every input region where the target's
decision differs from the policy as the reference reads it, as inclusive
(has_service_date, first, last) whole-cent ranges. A case whose defect is
not a small set of intervals gives ``predicate`` instead. tests/test_benchmark.py
checks each declaration against the target at its edges and at seeded
samples; that is a consistency check, not an exhaustive proof.

``expected_exit`` is the verdict PolicyProof's documented exit-code contract
(verification.EXIT_CODES) requires for the case when the verifier is right.
For defective targets that is 3, whether or not the search finds the
defect: a run that misses it is a false negative, never a correct "0".
The one exception is ``documented_limitation`` cases, where the contract
itself says the defect cannot be seen (search budget 0).
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal


CORPUS_VERSION = "1"
CORRECT, DEFECT, FAILURE, SCENARIO = "correct", "defect", "execution_failure", "scenario"

Interval = tuple[bool, Decimal, Decimal]


@dataclass(frozen=True)
class Case:
    id: str
    group: str
    target: str                  # "module:function", run in the worker
    why: str
    expected_exit: int
    intervals: tuple[Interval, ...] = ()
    predicate: Callable[[Decimal, bool], bool] | None = None
    # A defect the target has but that a correct verifier must not confirm
    # (for example because its own reference disagrees); see SCENARIO cases.
    must_not_confirm: bool = False
    options: dict = field(default_factory=dict)
    documented_limitation: bool = False

    @property
    def defective(self) -> bool:
        return bool(self.intervals) or self.predicate is not None

    def discrepant(self, amount: Decimal, dated: bool) -> bool:
        """Ground truth: does the target differ from the reference here?"""
        if self.predicate is not None:
            return self.predicate(amount, dated)
        return any(d == dated and lo <= amount <= hi for d, lo, hi in self.intervals)


def _iv(dated: bool, first: str, last: str) -> Interval:
    return (dated, Decimal(first), Decimal(last))


def _odd_cents(amount: Decimal, dated: bool) -> bool:
    return dated and amount > Decimal("40.00") and int(amount * 100) % 2 == 1


T = "benchmark.targets:"

CASES: tuple[Case, ...] = (
    # --- correct targets: any confirmed discrepancy is a false accusation
    Case("fixed-engine", CORRECT, "examples.fixed_engine:evaluate_meal_claim",
         "the repository's corrected engine", 0),
    Case("integer-cents", CORRECT, T + "correct_integer_cents",
         "same policy in integer cents", 0),
    Case("reordered-checks", CORRECT, T + "correct_reordered",
         "different control flow, same behaviour", 0),
    Case("float-compare", CORRECT, T + "correct_float",
         "uses floats, yet is exact for whole-cent inputs", 0),

    # --- defects at or next to the policy's threshold
    Case("exclusive-boundary", DEFECT, "examples.buggy_engine:evaluate_meal_claim",
         "< instead of <= at $40.00", 3, (_iv(True, "40.00", "40.00"),)),
    Case("off-by-one-cent", DEFECT, T + "off_by_one_cent",
         "approves up to $40.01", 3, (_iv(True, "40.01", "40.01"),)),
    Case("truncated-cents", DEFECT, T + "truncates_cents",
         "int() drops cents before comparing", 3, (_iv(True, "40.01", "40.99"),)),
    Case("bankers-rounding", DEFECT, T + "bankers_rounding",
         "rounds half-to-even to whole dollars first", 3, (_iv(True, "40.01", "40.50"),)),
    Case("date-after-amount", DEFECT, T + "date_checked_after_amount",
         "missing-date precedence lost above $40", 3, (_iv(False, "40.01", "1000000.00"),)),

    # --- defects far from any threshold the policy states
    Case("loophole-1000-4999", DEFECT, "examples.loophole_engine:evaluate_meal_claim",
         "the repository's loophole engine", 3, (_iv(True, "1000.00", "4999.99"),)),
    Case("single-cent-777.77", DEFECT, T + "single_cent_override",
         "one isolated wrong cent", 3, (_iv(True, "777.77", "777.77"),)),
    Case("narrow-literal-range", DEFECT, T + "narrow_literal_range",
         "33-cent range written as literals", 3, (_iv(True, "12345.67", "12345.99"),)),
    Case("narrow-computed-range", DEFECT, T + "narrow_computed_range",
         "16-cent range whose edges appear in no literal", 3, (_iv(True, "2000.37", "2000.52"),)),
    Case("approves-from-900k", DEFECT, T + "approves_from_900k",
         "range that runs to the end of the domain", 3, (_iv(True, "900000.00", "1000000.00"),)),
    Case("two-disconnected", DEFECT, T + "two_disconnected_ranges",
         "two separate ranges, one per date value", 3,
         (_iv(True, "100.00", "199.99"), _iv(False, "5000.00", "9999.99"))),
    Case("odd-cents", DEFECT, T + "odd_cents_approved",
         "half of all amounts above $40, none adjacent", 3, predicate=_odd_cents),

    # --- the target fails to execute; failures differ from every decision
    Case("raises-above-500", FAILURE, T + "raises_above_500",
         "exception for dated claims above $500", 3, (_iv(True, "500.01", "1000000.00"),)),
    Case("hangs-at-40", FAILURE, T + "hangs_at_threshold",
         "never returns at dated $40.00", 3, (_iv(True, "40.00", "40.00"),)),
    Case("lowercase-decision", FAILURE, T + "lowercase_approve",
         "returns 'approve', not a decision", 3, (_iv(True, "0.00", "40.00"),)),
    Case("import-fails", FAILURE, "benchmark.targets_broken:decide",
         "module cannot be imported: nothing may be concluded about it", 3,
         options={"not_evaluated": True}),

    # --- evidence semantics: the right answer is not "confirmed"
    Case("no-reference", SCENARIO, "examples.buggy_engine:evaluate_meal_claim",
         "buggy target, no reference: only the model contradicts it", 4,
         (_iv(True, "40.00", "40.00"),), must_not_confirm=True, options={"reference": None}),
    Case("contradicting-expectation", SCENARIO, "examples.buggy_engine:evaluate_meal_claim",
         "proposal's own test case expects REJECT at $40.00", 3,
         (_iv(True, "40.00", "40.00"),), must_not_confirm=True,
         options={"contradict_case": "exact-threshold"}),
    Case("conflicting-reference", SCENARIO, "examples.fixed_engine:evaluate_meal_claim",
         "reference reads 'or less' as exclusive; rules and target do not", 4,
         must_not_confirm=True, options={"reference": "exclusive"}),
    Case("require-l3-without-reference", SCENARIO, "examples.fixed_engine:evaluate_meal_claim",
         "correct target, but L3 is required and no reference is given", 5,
         options={"reference": None, "required_level": "L3"}),
    Case("time-limit-exhausted", SCENARIO, T + "slow_correct",
         "correct but slow; the total target-time limit cuts the search short", 3,
         options={"target_time_limit": 2.0}),
    Case("loophole-budget-0", SCENARIO, "examples.loophole_engine:evaluate_meal_claim",
         "search disabled: the loophole is invisible by contract", 0,
         (_iv(True, "1000.00", "4999.99"),), options={"search_budget": 0},
         documented_limitation=True),
)


def by_id(case_id: str) -> Case:
    return next(case for case in CASES if case.id == case_id)
