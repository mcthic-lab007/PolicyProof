"""Run the adversarial-verification benchmark and score PolicyProof's
evidence reports against the corpus ground truth (benchmark/corpus.py).

Two parts:
  primary  every corpus case once, exactly as the CLI runs by default
           (isolated worker, 2 s per call, search budget 2000, default
           seed), twice, to check that reports are byte-identical.
  sweep    the defect cases only, in-process, at several search budgets
           and seeds, to show how detection depends on the budget.

Scoring reads only the JSON evidence report, the same artifact a person
inspects. Metrics and their denominators:
  detection            defective targets (defect + execution-failure groups,
                       excluding import-fails) with at least one
                       TARGET_DISCREPANCY_CONFIRMED finding at a truly
                       discrepant amount / defective targets
  interval recall      ground-truth intervals overlapped by a confirmed
                       finding / ground-truth intervals
  exact location       intervals whose first and last cent were both
                       evaluated and seen disagreeing, with the cent beyond
                       each edge evaluated and agreeing (or the domain end)
                       / ground-truth intervals
  false accusations    correct targets, and must-not-confirm scenarios,
                       with any confirmed finding / such cases
  spurious claims      claims in confirmed findings (a disagreeing point, a
                       range's first or last amount, an agreeing neighbour)
                       that the ground truth contradicts / all such claims
  point accuracy       evaluated points where the report's target-versus-
                       reference outcome matches the ground truth /
                       evaluated points with both a target and a reference
  verdict accuracy     cases whose exit code equals the expected one / cases

Every case uses the committed synthetic fixture, not a live Muse Spark
response. Results describe this small synthetic corpus only.

Usage:
    python -m benchmark.run [--output-dir DIR] [--label NAME] [--overwrite]
        [--seeds N] [--budgets 0,250,...] [--skip-sweep]
"""

import argparse
import dataclasses
import hashlib
import importlib
import json
import platform
import subprocess
import sys
import time
from decimal import Decimal
from pathlib import Path

from benchmark.corpus import CASES, CORPUS_VERSION, CORRECT, DEFECT, FAILURE, Case
from src.policyproof import reference as reference_module
from src.policyproof.muse_client import replay_proposal
from src.policyproof.rule_engine import NUMERIC_DOMAINS
from src.policyproof.target_search import DEFAULT_BUDGET, DEFAULT_SEED
from src.policyproof.verification import (
    DEFAULT_TARGET_TIMEOUT,
    DEFAULT_TIME_LIMIT,
    Implementation,
    verify,
)


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "examples" / "democo_meal_policy.txt"
FIXTURE = ROOT / "tests" / "fixtures" / "muse_democo_meal_response.json"
DEFAULT_OUTPUT = ROOT / "artifacts" / "benchmark"
SWEEP_BUDGETS = (0, 250, 1000, 2000, 8000)
SWEEP_SEEDS = 10
CENT = Decimal("0.01")
LOW, HIGH = NUMERIC_DOMAINS["amount"]

REFERENCE = Implementation(
    "democo-meal-reference", "Human-written reference (src/policyproof/reference.py).",
    reference_module.evaluate_meal_claim,
)


def _import(spec: str):
    module, _, name = spec.partition(":")
    try:
        return getattr(importlib.import_module(module), name)
    except Exception as exc:  # the import-fails case: only runnable in a worker
        def unavailable(case, _error=f"{type(exc).__name__}: {exc}"):
            raise RuntimeError(f"target could not be imported: {_error}")
        return unavailable


def _reference(case: Case):
    choice = case.options.get("reference", "democo")
    if choice is None:
        return None
    if choice == "exclusive":
        return Implementation(
            "exclusive-reference", "Conflicting human reading (benchmark/targets.py).",
            _import("benchmark.targets:exclusive_reference"),
        )
    return REFERENCE


def _proposal(case: Case, policy_text: str):
    proposal = replay_proposal(FIXTURE, policy_text)
    contradict = case.options.get("contradict_case")
    if contradict is None:
        return proposal
    document = proposal.document
    cases = tuple(
        dataclasses.replace(c, expected_decision="REJECT") if c.id == contradict else c
        for c in document.test_cases
    )
    return dataclasses.replace(proposal, document=dataclasses.replace(document, test_cases=cases))


# Probe amounts written in each target's source (verify(source_probes=...)).
# --no-source-probes turns it off, to measure the search without it.
SOURCE_PROBES = True


def run_case(case: Case, policy_text: str, *, isolated: bool, budget: int | None = None,
             seed: int = DEFAULT_SEED) -> dict:
    """Run one case and score its report. ``budget`` None: the case's own
    budget, or the CLI default."""
    if budget is None:
        budget = case.options.get("search_budget", DEFAULT_BUDGET)
    proposal = _proposal(case, policy_text)
    target = Implementation(case.id, case.why, _import(case.target), case.target)
    started = time.perf_counter()
    result = verify(
        proposal.document, policy_text, proposal=proposal,
        reference=_reference(case), target=target,
        search_budget=budget, search_seed=seed,
        target_timeout=DEFAULT_TARGET_TIMEOUT if isolated else None,
        target_time_limit=case.options.get("target_time_limit", DEFAULT_TIME_LIMIT),
        required_level=case.options.get("required_level"),
        source_probes=SOURCE_PROBES,
    )
    seconds = time.perf_counter() - started
    text = result.to_json()
    scored = score(case, result.report)
    scored.update(
        case=case.id, group=case.group, budget=budget, seed=seed, isolated=isolated,
        seconds=round(seconds, 3), report_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )
    return scored


def score(case: Case, report: dict) -> dict:
    points = {p["id"]: p for p in report["points"]}

    def disagrees(point) -> bool | None:
        ref, tgt = point["reference"], point["target"]
        # An unfinished call (skipped, never started, timed out, worker died)
        # is no judgement of the target, whatever the verifier made of it.
        if tgt is None or tgt.get("failure") in ("not_run", "worker_startup", "timeout", "worker_crash"):
            return None
        if ref is None:
            return None
        return tgt["decision"] != ref["decision"]

    def at(amount: Decimal, dated: bool):
        return next((p for p in points.values()
                     if Decimal(p["amount"]) == amount and p["has_service_date"] == dated), None)

    claims = spurious = 0
    hits = []  # (dated, first, last) claimed by confirmed findings
    confirmed = [f for f in report["findings"] if f["code"] == "TARGET_DISCREPANCY_CONFIRMED"]
    for finding in confirmed:
        d = finding["details"]
        if d.get("kind") == "range":
            dated = d["has_service_date"]
            claimed = [(Decimal(d["start"]), True), (Decimal(d["end"]), True)]
            for key in ("agrees_below", "agrees_above"):
                if d[key] is not None:
                    claimed.append((Decimal(d[key]), False))
            hits.append((dated, Decimal(d["start"]), Decimal(d["end"])))
        else:
            point = points[finding["points"][0]]
            dated, amount = point["has_service_date"], Decimal(point["amount"])
            claimed = [(amount, True)]
            hits.append((dated, amount, amount))
        for amount, says_discrepant in claimed:
            claims += 1
            spurious += case.discrepant(amount, dated) != says_discrepant

    # Ground truth is relative to the policy reference, so points can only be
    # scored in runs that use it.
    judged = correct_points = 0
    for point in points.values() if case.options.get("reference", "democo") == "democo" else ():
        seen = disagrees(point)
        if seen is None:
            continue
        judged += 1
        correct_points += seen == case.discrepant(Decimal(point["amount"]), point["has_service_date"])

    intervals = []
    for dated, first, last in case.intervals:
        found = any(d == dated and a <= last and first <= b for d, a, b in hits)

        def edge(inside: Decimal, outside: Decimal, at_end: bool) -> bool:
            p_in = at(inside, dated)
            if p_in is None or disagrees(p_in) is not True:
                return False
            if at_end:
                return True
            p_out = at(outside, dated)
            return p_out is not None and disagrees(p_out) is False

        exact = found and edge(first, first - CENT, first == LOW) and edge(last, last + CENT, last == HIGH)
        intervals.append({"has_service_date": dated, "first": str(first), "last": str(last),
                          "found": found, "exactly_located": exact})

    search = report.get("target_search", {})
    execution = report.get("target_execution", {})
    return {
        "exit_code": report["verification"]["result"]["exit_code"],
        "expected_exit": case.expected_exit,
        "level": report["verification"]["level"],
        "codes": sorted({f["code"] for f in report["findings"]}),
        "confirmed_findings": len(confirmed),
        "detected": any(case.discrepant(a, d) or case.discrepant(b, d) for d, a, b in hits),
        "claims": claims,
        "spurious_claims": spurious,
        "points_judged": judged,
        "points_correct": correct_points,
        "intervals": intervals,
        "search_calls": search.get("target_calls", 0),
        "budget_exhausted": search.get("budget_exhausted"),
        "unjudged_search_evaluations": search.get("unjudged_evaluations"),
        "worker": {k: execution.get(k) for k in ("calls", "timeouts", "worker_crashes", "not_run")}
        if execution.get("mode") == "isolated-worker-process" else None,
    }


def summarize(rows: list[dict]) -> dict:
    by_case = {case.id: case for case in CASES}
    defective = [r for r in rows if by_case[r["case"]].group in (DEFECT, FAILURE)
                 and by_case[r["case"]].defective]
    no_accuse = [r for r in rows if by_case[r["case"]].group == CORRECT or by_case[r["case"]].must_not_confirm]
    intervals = [i for r in rows if by_case[r["case"]].group in (DEFECT, FAILURE) for i in r["intervals"]]

    def ratio(n, d):
        return {"numerator": n, "denominator": d}

    return {
        "detection": ratio(sum(r["detected"] for r in defective), len(defective)),
        "interval_recall": ratio(sum(i["found"] for i in intervals), len(intervals)),
        "exact_location": ratio(sum(i["exactly_located"] for i in intervals), len(intervals)),
        "false_accusations": ratio(sum(r["confirmed_findings"] > 0 for r in no_accuse), len(no_accuse)),
        "spurious_claims": ratio(sum(r["spurious_claims"] for r in rows), sum(r["claims"] for r in rows)),
        "point_accuracy": ratio(sum(r["points_correct"] for r in rows), sum(r["points_judged"] for r in rows)),
        "verdict_accuracy": ratio(sum(r["exit_code"] == r["expected_exit"] for r in rows), len(rows)),
        "missed": [r["case"] for r in defective if not r["detected"]],
        "wrong_verdicts": [f'{r["case"]}: got {r["exit_code"]}, expected {r["expected_exit"]}'
                           for r in rows if r["exit_code"] != r["expected_exit"]],
        "search_calls_total": sum(r["search_calls"] for r in rows),
        "seconds_total": round(sum(r["seconds"] for r in rows), 2),
    }


def sweep(policy_text: str, budgets, seeds: int) -> list[dict]:
    cases = [c for c in CASES if c.group == DEFECT]
    seed_values = [DEFAULT_SEED] + list(range(1, seeds))
    rows = []
    for budget in budgets:
        for case in cases:
            runs = [run_case(case, policy_text, isolated=False, budget=budget, seed=s) for s in seed_values]
            rows.append({
                "case": case.id, "budget": budget, "seeds": len(runs),
                "detected": sum(r["detected"] for r in runs),
                "intervals_found": sum(i["found"] for r in runs for i in r["intervals"]),
                "intervals_exact": sum(i["exactly_located"] for r in runs for i in r["intervals"]),
                "intervals_total": sum(len(r["intervals"]) for r in runs),
                "spurious_claims": sum(r["spurious_claims"] for r in runs),
                "mean_search_calls": round(sum(r["search_calls"] for r in runs) / len(runs), 1),
            })
    return rows


def _environment() -> dict:
    def git(*args):
        try:
            return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                                  check=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            return None
    status = git("status", "--porcelain")
    return {
        "corpus_version": CORPUS_VERSION,
        "source_probes": SOURCE_PROBES,
        "commit": git("rev-parse", "HEAD"),
        "working_tree_dirty": None if status is None else bool(status),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "proposal": "committed synthetic fixture (REPLAY_SYNTHETIC), not a live Muse Spark response",
        "started_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def _pct(r: dict) -> str:
    n, d = r["numerator"], r["denominator"]
    return f"{n}/{d}" + (f" ({100 * n / d:.0f}%)" if d else "")


def render(results: dict) -> str:
    env, primary, summary = results["environment"], results["primary"], results["summary"]
    lines = [
        f"PolicyProof benchmark, corpus v{env['corpus_version']}, commit {env['commit']}"
        f"{' (dirty working tree)' if env['working_tree_dirty'] else ''}",
        f"Python {env['python']} on {env['platform']}; proposal: {env['proposal']}",
        "",
        "| case | group | exit (expected) | detected | intervals found/exact | spurious claims | search calls | s |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in primary:
        iv = r["intervals"]
        lines.append(
            f"| {r['case']} | {r['group']} | {r['exit_code']} ({r['expected_exit']})"
            f"{'' if r['exit_code'] == r['expected_exit'] else ' ✗'} | "
            f"{'yes' if r['detected'] else 'no'} | "
            f"{sum(i['found'] for i in iv)}/{sum(i['exactly_located'] for i in iv)} of {len(iv)} | "
            f"{r['spurious_claims']}/{r['claims']} | {r['search_calls']} | {r['seconds']} |"
        )
    lines += [
        "",
        f"Detection (defective targets):        {_pct(summary['detection'])}",
        f"Interval recall:                      {_pct(summary['interval_recall'])}",
        f"Exact location of both edges:         {_pct(summary['exact_location'])}",
        f"False accusations (must not confirm): {_pct(summary['false_accusations'])}",
        f"Spurious claims in confirmed findings: {_pct(summary['spurious_claims'])}",
        f"Point-level judgement accuracy:       {_pct(summary['point_accuracy'])}",
        f"Verdict accuracy (exit codes):        {_pct(summary['verdict_accuracy'])}",
        f"Missed: {', '.join(summary['missed']) or 'none'}",
        f"Wrong verdicts: {'; '.join(summary['wrong_verdicts']) or 'none'}",
        f"Reproducible (two primary runs, identical report hashes): {results['reproducible']}",
        f"Total search calls {summary['search_calls_total']}, total {summary['seconds_total']} s",
    ]
    if results.get("sweep"):
        budgets = sorted({r["budget"] for r in results["sweep"]})
        seeds = results["sweep"][0]["seeds"]
        lines += ["", f"Sweep (defect group, in-process, {seeds} seeds): intervals found / exactly located",
                  "| case | " + " | ".join(f"budget {b}" for b in budgets) + " |",
                  "|---|" + "---|" * len(budgets)]
        for case in dict.fromkeys(r["case"] for r in results["sweep"]):
            cells = []
            for b in budgets:
                r = next(x for x in results["sweep"] if x["case"] == case and x["budget"] == b)
                cells.append(f"{r['intervals_found']}/{r['intervals_exact']} of {r['intervals_total']}")
            lines.append(f"| {case} | " + " | ".join(cells) + " |")
        totals = []
        for b in budgets:
            rs = [x for x in results["sweep"] if x["budget"] == b]
            totals.append(f"{sum(x['intervals_found'] for x in rs)}/{sum(x['intervals_exact'] for x in rs)}"
                          f" of {sum(x['intervals_total'] for x in rs)}")
        lines.append("| **all** | " + " | ".join(totals) + " |")
        calls = [str(next(x["mean_search_calls"] for x in results["sweep"] if x["budget"] == b
                          and x["case"] == "exclusive-boundary")) for b in budgets]
        lines.append("| mean search calls (exclusive-boundary) | " + " | ".join(calls) + " |")
        lines.append(f"Spurious claims across the sweep: {sum(x['spurious_claims'] for x in results['sweep'])}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the PolicyProof adversarial-verification benchmark.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--label", default="run", help="file name label (results-LABEL.json/.md)")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--seeds", type=int, default=SWEEP_SEEDS)
    parser.add_argument("--budgets", default=",".join(map(str, SWEEP_BUDGETS)))
    parser.add_argument("--skip-sweep", action="store_true")
    parser.add_argument("--no-source-probes", action="store_true",
                        help="do not probe amounts written in the targets' source")
    args = parser.parse_args(argv)

    json_path = args.output_dir / f"results-{args.label}.json"
    md_path = args.output_dir / f"results-{args.label}.md"
    if not args.overwrite and (json_path.exists() or md_path.exists()):
        print(f"error: {json_path} or {md_path} exists; pass --overwrite", file=sys.stderr)
        return 1

    global SOURCE_PROBES
    SOURCE_PROBES = not args.no_source_probes
    policy_text = POLICY.read_text(encoding="utf-8")
    results = {"environment": _environment()}
    first = [run_case(case, policy_text, isolated=True) for case in CASES]
    second = [run_case(case, policy_text, isolated=True) for case in CASES]
    results["primary"] = first
    results["reproducible"] = [r["report_sha256"] for r in first] == [r["report_sha256"] for r in second]
    results["nondeterministic_cases"] = [a["case"] for a, b in zip(first, second)
                                         if a["report_sha256"] != b["report_sha256"]]
    results["summary"] = summarize(first)
    if not args.skip_sweep:
        budgets = [int(b) for b in args.budgets.split(",")]
        results["sweep"] = sweep(policy_text, budgets, args.seeds)

    text = render(results)
    print(text, end="")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(text, encoding="utf-8")
    print(f"\nWrote {json_path} and {md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
