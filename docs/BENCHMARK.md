# Adversarial verification benchmark

A small, deterministic ground-truth corpus that measures how well PolicyProof's own verification machinery finds seeded defects, avoids false accusations, and classifies runs it cannot fully judge. It was built on 2026-10-28 during the hackathon.

**Scope:** 26 synthetic cases against the fictional DemoCo meal policy. These results describe this corpus only. They are not a measure of production reliability, and they say nothing about other policies or schemas.

## Reproduce

```powershell
.\.venv\Scripts\python.exe -B -m benchmark.run --label mine
```

The command takes about 90 s on the machine below. It needs no API key and no network. Every case replays the committed **synthetic** fixture `tests/fixtures/muse_democo_meal_response.json`, which is labelled `REPLAY_SYNTHETIC` and is not Muse Spark output. That keeps the benchmark focused on PolicyProof's deterministic code. Results are written to `artifacts/benchmark/` (git-ignored) as JSON and Markdown.

## Corpus v1 (`benchmark/corpus.py`)

The corpus was committed in `8d3b337` **before** any measurement. The ground truth is declared per case as inclusive whole-cent intervals, or as a predicate. `tests/test_benchmark.py` checks each declaration against the target's actual behaviour at every edge, one cent beyond each edge, 50 interior samples and about 4,000 seeded samples per target. That is a consistency check, not an exhaustive proof.

| Group | Cases | What they test |
|---|---|---|
| correct | 4 | `fixed_engine`, integer cents, reordered checks, float comparison. Any confirmed discrepancy here is a false accusation. |
| defect | 12 | Exclusive boundary at $40.00, off-by-one-cent, `int()` truncation, banker's rounding, lost date precedence, the $1,000–$4,999.99 loophole, a single wrong cent ($777.77), a 33-cent literal range, a 16-cent range whose edges are *computed* (no literal equals them), a range running to the domain end, two disconnected ranges, and odd cents above $40 (no interval structure). |
| execution failure | 4 | An exception above $500, a hang at $40.00, the lowercase `"approve"`, and an import failure. The import failure must not be accused. |
| scenario | 6 | No reference, a contradicting model expectation, a conflicting reference, `--require-level L3` without a reference, an exhausted total time limit, and search budget 0. |

## Metrics (defined before the first run)

| Metric | Numerator / denominator |
|---|---|
| Detection | Defective targets with ≥1 `TARGET_DISCREPANCY_CONFIRMED` at a truly discrepant amount / defective targets in the defect and execution-failure groups, excluding import-fails (15) |
| Interval recall | Ground-truth intervals overlapped by a confirmed finding / intervals (15) |
| Exact location | Intervals whose first and last cents were both evaluated and disagreeing, with the cent beyond each edge evaluated and agreeing (or the domain end) / intervals (15) |
| False accusations | Correct targets plus must-not-confirm scenarios with any confirmed finding / those cases (7) |
| Spurious claims | Claims inside confirmed findings that the ground truth contradicts (disagreeing points, range ends, agreeing neighbours) / all such claims |
| Point accuracy | Evaluated points where the report's target-versus-reference outcome matches the ground truth / judged points in runs that use the policy reference |
| Verdict accuracy | Cases whose exit code equals the expected one / 26. A missed defect is scored as wrong (expected 3), except budget 0, where the contract says the defect is invisible (expected 0). |
| Reproducibility | The SHA-256 of every report is identical across two back-to-back primary runs |

Primary configuration: CLI defaults, meaning an isolated worker with a 2 s per-call timeout, search budget 2000 and seed 20261104. The sweep covers the 12 defect cases in-process at budgets {0, 250, 1000, 2000, 8000}, each with 10 seeds (20261104 and 1–9).

## Results

Environment: Python 3.12.14, Windows 11 (10.0.26200), corpus v1.

| Metric | Baseline: verifier at `8d3b337` | After the fix: `f326b83` |
|---|---|---|
| Detection | 13/15 | 13/15 |
| Interval recall | 13/15 | 13/15 |
| Exact location | 12/15 | 12/15 |
| False accusations | **0/7** | **0/7** |
| Spurious claims | 0/598 | 0/598 |
| Point accuracy | 733/733 | 733/733 |
| Verdict accuracy | 23/26 | **24/26** |
| Reproducible | yes | yes |
| Search calls / wall time (26 cases) | 38,044 / 14.9 s | 38,044 / 14.8 s |

The baseline ran in a temporary worktree at `8d3b337` with one harness change: the scorer fix from `1021823`, described under "Threats to validity". It shows as a dirty tree in its results file for that reason. The verifier code was unmodified.

**Wrong verdicts in the baseline:**
1. `single-cent-777.77` exited 0; 3 was expected. This is a sampling miss.
2. `narrow-literal-range` exited 0; 3 was expected. This is a sampling miss.
3. `time-limit-exhausted` exited 0 **at L3**; 3 was expected. **This was a verifier bug, not a sampling limit.** The report stated that the target "agrees with the reference at every evaluated point and in all 1500 target-search evaluations", but 1421 of those 1500 calls were never run because the total time limit had been reached.

**Fix (`1021823`):** target-search calls that cannot be judged now produce one `UNSUPPORTED` error finding with counts by reason. They block L3 and are stated in the scope, the CLI summary and the viewer. After the fix, the same case exits 3 at L2. Two regression tests (`tests/test_target_search.py`, `tests/test_target_worker.py`) fail without the change and pass with it. The fix was not expected to change detection, and it did not.

### Budget and seed sweep (defect group, intervals found / exactly located)

| Case | 0 | 250 | 1000 | 2000 | 8000 |
|---|---|---|---|---|---|
| exclusive-boundary | 10/10 of 10 | 10/10 | 10/10 | 10/10 | 10/10 |
| off-by-one-cent | 10/0 of 10 | 10/0 | 10/0 | 10/0 | 10/0 |
| truncated-cents | 10/0 of 10 | 10/0 | 10/5 | 10/9 | 10/10 |
| bankers-rounding | 10/0 of 10 | 10/0 | 10/2 | 10/4 | 10/9 |
| date-after-amount | 10/10 of 10 | 10/10 | 10/10 | 10/10 | 10/10 |
| loophole-1000-4999 | 0/0 of 10 | 10/10 | 10/10 | 10/10 | 10/10 |
| single-cent-777.77 | 0/0 of 10 | 0/0 | 0/0 | 0/0 | 0/0 |
| narrow-literal-range | 0/0 of 10 | 0/0 | 0/0 | 0/0 | 0/0 |
| narrow-computed-range | 0/0 of 10 | 0/0 | 1/1 | 1/1 | 1/1 |
| approves-from-900k | 10/0 of 10 | 10/10 | 10/10 | 10/10 | 10/10 |
| two-disconnected | 10/0 of 20 | 20/20 | 20/20 | 20/20 | 20/20 |
| **all (120 interval-runs)** | 70/20 | 90/60 | 91/68 | 91/74 | 91/80 |

This sweep is identical before and after the fix. No spurious claims were made anywhere in the sweep.

## What the evidence says

1. **No false accusations and no spurious claims** (0/7 cases, 0/598 claims). When PolicyProof says "confirmed", the ground truth agreed every time in this corpus. The model-only, contradicting-expectation and conflicting-reference scenarios were correctly *not* confirmed.
2. **Discrepancies found only at evaluated points are never bounded.** `off-by-one-cent` is found in 50/50 runs but exactly located in 0/50: the verifier reports $40.01 and never checks whether $40.02 agrees. `bankers-rounding` is exactly located in only 4/10 seeds at the default budget, because bisection runs only for disagreement the search itself found.
3. **Narrow defects far from any threshold are missed at every budget tested.** The single cent and the 33-cent range were found in 0/50 runs each, even at budget 8000. The computed 16-cent range was found in 1/10 seeds at budgets of 1000 or more. This is the documented limitation of sampling, now quantified.
4. **The loophole demo is found by the round-number ladder, not by random sampling.** Its edges ($999.99/$1,000.00 and $4,999.99/$5,000.00) are ladder probes; the run uses 0 bisection calls. The demo narration must say this rather than imply that the random search found it.

## Threats to validity

- **Corpus design:** the corpus is small and synthetic, written by the same team that built the verifier. The defects are single-mechanism seeds. Real engines have more inputs, and their defects interact.
- **Ground truth:** it is declared, then checked at edges and samples, not exhaustively over about 200 million inputs.
- **Scorer fix after the first run:** the first baseline scored points in `conflicting-reference` against that run's deliberately conflicting reference instead of the ground truth, which gave 744/745. That is a harness bug. It was fixed and the baseline was re-run on the unmodified verifier before any comparison. No ground truth or expected verdict was changed.
- **Timing dependence:** `time-limit-exhausted` and `hangs-at-40` depend on wall-clock time. The not-run count was 1421 in these runs and 1422 in one earlier run, so their reports are reproducible only per machine and load. Every other case is deterministic.
- **Platform:** all runs were on Windows. CI covers the unit tests on Linux, but it does not run the benchmark.

## Ranked next improvements (from this evidence)

1. **Bound discrepancies seen at evaluated points.** Bisect outward from evaluated-only disagreeing runs as well. This targets exact location (sweep: 74/120 at the default budget) and costs about 2 × log₂(gap) calls per edge.
2. **Close the narrow-defect gap** (0/50 for the single cent and the 33-cent range). There are two candidates, and both should be measured on this corpus, including the computed-edge hold-out:
   - mine numeric literals from the target's source (deterministic grey-box probing). It should catch the two literal cases but not the computed range;
   - have **Muse Spark propose adversarial probe amounts**, which PolicyProof then judges. Muse could only add test points, never decide an outcome. Replayed responses would keep the benchmark reproducible.
