"""Deterministic, budgeted search of a target between evaluated points.

The derived points cover every distinct behaviour of the rule document, but
the target is a black box: it can be wrong at amounts the rules never
mention. This module looks for such places and pins down their edges.

Algorithm, run separately for each value of has_service_date:
  0. Probe any ``hints`` first, each with one cent either side: amounts
     written in the target's own source (see source_literals).
  1. Probe a fixed "round number" ladder, 1, 2, 2.5 and 5 x 10^k dollars
     (k = 0..6) and one cent either side, where human-written thresholds
     tend to sit.
  2. Probe seeded samples between every pair of neighbouring evaluated
     amounts. Each gap is split into power-of-ten bands of whole cents and
     the bands are sampled round-robin with ``random.Random(seed).randrange``
     (integer arithmetic only, so the same seed gives the same amounts on
     every platform).
  3. Group neighbouring disagreeing amounts into ranges. For each edge,
     bisect in whole cents between the nearest agreeing amount and the range
     until the two are one cent apart, so both sides of every reported edge
     have been evaluated. Ranges the search contributed to are bounded
     first. A run of evaluated points only is bounded afterwards and
     reported as a range only if the search evaluated at least one of its
     amounts or edge neighbours; otherwise everything about it is already
     among the evaluated points, which report it on their own.

Budget: at most ``budget`` judge calls in total, never more. A quarter is
reserved for bisection; the rest is shared equally by the two date values.
An edge that cannot be resolved within the budget, or because an amount
cannot be judged, is reported as unresolved together with the interval
that contains it.

Limits: this is sampling. A fault confined to a few isolated amounts can be
missed, and between two evaluated disagreeing amounts the target was not
checked at every cent, so a range may contain agreeing amounts that were
never sampled.
"""

import random
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any


CENT = Decimal("0.01")
DEFAULT_SEED = 20261104
DEFAULT_BUDGET = 2000
MAX_BUDGET = 100_000
BISECTION_SHARE = 4  # 1 / BISECTION_SHARE of the budget is reserved for edges
LADDER_MANTISSAS = (Decimal("1"), Decimal("2"), Decimal("2.5"), Decimal("5"))
LADDER_EXPONENTS = range(0, 7)


@dataclass(frozen=True)
class Judgement:
    """Whether the target agreed with the comparison basis at one input.
    ``agrees`` is None when there is no basis to judge against."""

    agrees: bool | None
    payload: Any = None


@dataclass(frozen=True)
class Edge:
    """One edge of a range. ``inside`` disagrees; ``outside`` agrees. When
    ``verified`` they are adjacent cents and both were evaluated. ``outside``
    is None when the range reaches the end of the domain."""

    verified: bool
    inside: Decimal
    outside: Decimal | None


@dataclass(frozen=True)
class DiscrepancyRange:
    has_service_date: bool
    lower: Edge
    upper: Edge
    disagreeing: tuple[Decimal, ...]  # every evaluated disagreeing amount in the range
    found_by_search: int


@dataclass(frozen=True)
class SearchOutcome:
    seed: int
    budget: int
    probe_calls: int
    bisection_calls: int
    unjudged: int
    ranges: tuple[DiscrepancyRange, ...]
    observations: dict[tuple[Decimal, bool], Judgement]
    # Searched inputs whose judgement was None, in ascending order: the
    # search says nothing about the target there.
    unjudged_inputs: tuple[tuple[Decimal, bool], ...] = ()

    @property
    def calls(self) -> int:
        return self.probe_calls + self.bisection_calls

    @property
    def budget_exhausted(self) -> bool:
        return self.calls >= self.budget


def search(
    judge: Callable[[Decimal, bool], Judgement],
    known: Mapping[tuple[Decimal, bool], Judgement],
    *,
    low: Decimal,
    high: Decimal,
    seed: int = DEFAULT_SEED,
    budget: int = DEFAULT_BUDGET,
    hints: tuple[Decimal, ...] = (),
) -> SearchOutcome:
    """Search the target. ``known`` holds judgements already made at the
    evaluated points; they bound gaps and edges but cost nothing. ``hints``
    are probed before everything else."""
    if isinstance(budget, bool) or not isinstance(budget, int) or not 0 <= budget <= MAX_BUDGET:
        raise ValueError(f"budget must be an integer from 0 to {MAX_BUDGET}")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")

    observed = dict(known)
    searched: set[tuple[Decimal, bool]] = set()
    calls = {"probe": 0, "bisection": 0}

    def call(amount: Decimal, dated: bool, kind: str) -> Judgement | None:
        if calls["probe"] + calls["bisection"] >= budget:
            return None
        calls[kind] += 1
        judgement = judge(amount, dated)
        observed[(amount, dated)] = judgement
        searched.add((amount, dated))
        return judgement

    probe_budget = budget - budget // BISECTION_SHARE
    for index, dated in enumerate((False, True)):
        share = probe_budget // 2 + (probe_budget % 2 if index else 0)
        evaluated = sorted(a for (a, d) in observed if d == dated)
        rng = random.Random(f"policyproof-target-search:{seed}:{dated}")
        for amount in _candidates(evaluated, low, high, rng, share, hints):
            call(amount, dated, "probe")

    def runs(dated: bool):
        """Disagreeing runs as (run, nearest agreeing below, nearest above)."""
        judged = sorted(
            (amount, j.agrees) for (amount, d), j in observed.items()
            if d == dated and j.agrees is not None
        )
        for run_start, run_end in _disagreeing_runs(judged):
            yield (
                [amount for amount, _ in judged[run_start:run_end + 1]],
                judged[run_start - 1][0] if run_start > 0 else None,
                judged[run_end + 1][0] if run_end + 1 < len(judged) else None,
            )

    def bound(dated: bool, run, below, above) -> DiscrepancyRange:
        lower = _lower_edge(call, dated, below, run[0], low)
        upper = _upper_edge(call, dated, run[-1], above, high)
        disagreeing = tuple(sorted(
            amount for (amount, d), j in observed.items()
            if d == dated and j.agrees is False and lower.inside <= amount <= upper.inside
        ))
        return DiscrepancyRange(
            dated, lower, upper, disagreeing,
            sum((amount, dated) in searched for amount in disagreeing),
        )

    # Ranges the search found are bounded first, so they keep the bisection
    # budget they had before evaluated-only runs were bounded too.
    ranges = []
    for dated in (False, True):
        for run, below, above in list(runs(dated)):
            if any((amount, dated) in searched for amount in run):
                ranges.append(bound(dated, run, below, above))
    # Runs of evaluated points only: bound their edges as well, and report
    # them as ranges only if the search evaluated one of their amounts or
    # edge neighbours (by probing or by this bisection).
    for dated in (False, True):
        for run, below, above in list(runs(dated)):
            if any(r.has_service_date == dated and r.lower.inside <= run[0] <= r.upper.inside
                   for r in ranges):
                continue
            found = bound(dated, run, below, above)
            evidence = (found.lower.outside, found.upper.outside, *found.disagreeing)
            if any((amount, dated) in searched for amount in evidence if amount is not None):
                ranges.append(found)
    ranges.sort(key=lambda r: (r.has_service_date, r.lower.inside))

    unjudged = tuple(sorted(key for key in searched if observed[key].agrees is None))
    return SearchOutcome(
        seed, budget, calls["probe"], calls["bisection"], len(unjudged),
        tuple(ranges), observed, unjudged,
    )


def _cents(amount: Decimal) -> int:
    return int(amount / CENT)


def _amount(cents: int) -> Decimal:
    return (Decimal(cents) * CENT).quantize(CENT)


def _candidates(evaluated, low, high, rng, limit, hints=()) -> list[Decimal]:
    taken = set(evaluated)
    chosen: list[Decimal] = []

    def take(amount: Decimal) -> None:
        if len(chosen) < limit and low <= amount <= high and amount not in taken:
            taken.add(amount)
            chosen.append(amount)

    for hint in hints:
        for amount in (hint - CENT, hint, hint + CENT):
            take(amount)

    for mantissa in LADDER_MANTISSAS:
        for exponent in LADDER_EXPONENTS:
            value = (mantissa * Decimal(10) ** exponent).quantize(CENT)
            for amount in (value - CENT, value, value + CENT):
                take(amount)

    anchors = sorted(set(evaluated) | set(chosen) | {low, high})
    bands = []
    for a, b in zip(anchors, anchors[1:]):
        lo_c, hi_c = _cents(a) + 1, _cents(b) - 1
        while lo_c <= hi_c:
            band_end = min(hi_c, 10 ** len(str(lo_c)) - 1)  # same number of digits
            bands.append((lo_c, band_end))
            lo_c = band_end + 1

    attempts = 0
    while bands and len(chosen) < limit and attempts < 4 * limit:
        for band_lo, band_hi in bands:
            if len(chosen) >= limit:
                break
            attempts += 1
            take(_amount(rng.randrange(band_lo, band_hi + 1)))
    return chosen


def _disagreeing_runs(judged):
    runs, start = [], None
    for index, (_, agrees) in enumerate(judged):
        if agrees is False and start is None:
            start = index
        elif agrees is not False and start is not None:
            runs.append((start, index - 1))
            start = None
    if start is not None:
        runs.append((start, len(judged) - 1))
    return runs


def _lower_edge(call, dated, below, inside, low) -> Edge:
    if below is None:
        return Edge(inside == low, inside, None)
    lo, hi = _cents(below), _cents(inside)
    while hi - lo > 1:
        mid = (lo + hi) // 2
        judgement = call(_amount(mid), dated, "bisection")
        if judgement is None or judgement.agrees is None:
            return Edge(False, _amount(hi), _amount(lo))
        if judgement.agrees:
            lo = mid
        else:
            hi = mid
    return Edge(True, _amount(hi), _amount(lo))


def _upper_edge(call, dated, inside, above, high) -> Edge:
    if above is None:
        return Edge(inside == high, inside, None)
    lo, hi = _cents(inside), _cents(above)
    while hi - lo > 1:
        mid = (lo + hi) // 2
        judgement = call(_amount(mid), dated, "bisection")
        if judgement is None or judgement.agrees is None:
            return Edge(False, _amount(lo), _amount(hi))
        if judgement.agrees:
            hi = mid
        else:
            lo = mid
    return Edge(True, _amount(lo), _amount(hi))
