# Adversarial verification benchmark

A small, deterministic ground-truth corpus that measures how well PolicyProof's own verification machinery finds seeded defects, avoids false accusations, and classifies runs it cannot fully judge. It was built on 2026-10-28 during the hackathon.

**Scope:** 26 synthetic cases (corpus v1), 27 in corpus v2 against the fictional DemoCo meal policy. These results describe this corpus only. They are not a measure of production reliability, and they say nothing about other policies or schemas.

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

**Corpus v2** (`f21e7b0`, committed before its first measurement) adds one scenario: `slow-correct-at-threshold`. Its target is correct everywhere but takes 3 s for dated $40.00, longer than the 2 s per-call timeout. It must not be confirmed, so the false-accusation denominator becomes 8. It expects exit 3, because the run is incomplete. In the same commit, the scorer stopped counting timed-out or crashed calls as judgements of the target, for both the before and after measurements. The v1 cases are unchanged.

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

The first table below is corpus v1 (26 cases). Corpus v2 results come after it, under "Corpus v2: calls that do not finish"; v1 and v2 numbers are not directly comparable.

Environment: Python 3.12.14, Windows 11 (10.0.26200), corpus v1.

| Metric | Baseline: verifier at `8d3b337` | After the fix: `f326b83` | After bounding point discrepancies: `b434796` |
|---|---|---|---|
| Detection | 13/15 | 13/15 | 13/15 |
| Interval recall | 13/15 | 13/15 | 13/15 |
| Exact location | 12/15 | 12/15 | **13/15** |
| False accusations | **0/7** | **0/7** | **0/7** |
| Spurious claims | 0/598 | 0/598 | 0/606 |
| Point accuracy | 733/733 | 733/733 | 734/734 |
| Verdict accuracy | 23/26 | **24/26** | 24/26 |
| Reproducible | yes | yes | 25 of 26 cases; see below |
| Search calls / wall time (26 cases) | 38,044 / 14.9 s | 38,044 / 14.8 s | 38,046 / 13.2 s |

The baseline ran in a temporary worktree at `8d3b337` with one harness change: the scorer fix from `1021823`, described under "Threats to validity". It shows as a dirty tree in its results file for that reason. The verifier code was unmodified.

**Wrong verdicts in the baseline:**
1. `single-cent-777.77` exited 0; 3 was expected. This is a sampling miss.
2. `narrow-literal-range` exited 0; 3 was expected. This is a sampling miss.
3. `time-limit-exhausted` exited 0 **at L3**; 3 was expected. **This was a verifier bug, not a sampling limit.** The report stated that the target "agrees with the reference at every evaluated point and in all 1500 target-search evaluations", but 1421 of those 1500 calls were never run because the total time limit had been reached.

**Fix (`1021823`):** target-search calls that cannot be judged now produce one `UNSUPPORTED` error finding with counts by reason. They block L3 and are stated in the scope, the CLI summary and the viewer. After the fix, the same case exits 3 at L2. Two regression tests (`tests/test_target_search.py`, `tests/test_target_worker.py`) fail without the change and pass with it. The fix was not expected to change detection, and it did not.

**Bounding point discrepancies (`b434796`):** a disagreement seen only at evaluated boundary points used to be reported point by point. The search never looked for where it stopped. Such runs are now bisected like the ranges the search found. They are bisected after those ranges, so the ranges' calls are unchanged. A run is reported as a range only if the search evaluated one of its amounts or edge neighbours. Expected effect, stated in the session before the code was changed: primary exact location goes from 12/15 to 13/15 (`off-by-one-cent`); detection, false accusations and verdicts are unchanged; budget 0 is unchanged; and `off-by-one-cent`, `truncated-cents` and `bankers-rounding` improve in the sweep. All of that happened:
- 23 of 26 primary reports are byte-identical to the pre-change run (`results-baseline-A`, same corpus at `045a74a`). The three that differ:
  - `off-by-one-cent`: now a range from $40.01 to $40.01, with verified edges at $40.00 and $40.02, and 2 extra calls;
  - `odd-cents`: 4 more claims, all correct, and no extra calls;
  - `time-limit-exhausted` (below).
- Six regression tests in `tests/test_target_search.py`. Five fail without the change. The sixth already passed at the default seed and guards the result.
- **First version was incomplete.** The first implementation reported such a run only if bisection made a call. That left `off-by-one-cent` at 9/10 seeds at budget 8000: a probe landed on $40.02, so no bisection was needed, and the agreeing neighbour never reached the report. The rule now counts any search evaluation. A test pins the case down using the $50.00 ladder probe. The table shows the corrected version.
- **Reproducibility:** in all three post-change benchmark runs, the two primary passes differed only in `time-limit-exhausted`. That case's not-run count depends on wall-clock time: 1421, 1423 and 1424 were observed. Both of its observed report hashes also occur with the pre-change code. In three pre-change runs the two passes happened to match. This difference in frequency is not explained. The case has no ranges, so the change doesn't touch its report content. Its exit code is 3 in every run.

### Corpus v2: calls that do not finish (`3def8c0`)

Before the fix, a call that timed out or whose worker died had no decision. When the reference decided, that was a confirmed discrepancy, so a correct but slow target was accused. Now timeouts and worker crashes count as **not evaluated**, like calls skipped by the time limit. They produce an `UNSUPPORTED` error with a count for each failure kind. The run exits 3 and cannot reach L3, and nothing is confirmed. A call that finished by raising, or by returning something other than a decision, is still the target's answer. Configuration, seed and budgets are identical in both runs.

| Metric (corpus v2) | Before: `f21e7b0` | After: `3def8c0` |
|---|---|---|
| False accusations | **1/8** (`slow-correct-at-threshold`) | **0/8** |
| Spurious claims | 1/607 | 0/605 |
| Detection | 13/15 | 12/15 |
| Interval recall / exact location | 13/15 / 12/15 | 12/15 / 12/15 |
| Point accuracy | 744/744 | 744/744 |
| Verdict accuracy | 25/27 | 25/27 |
| Reproducible | yes | yes |
| Search calls / wall time | 39,546 / 15.9 s | 39,546 / 16.1 s |

- **The trade-off is deliberate.** `hangs-at-40` (it never returns for $40.00) was a confirmed detection and is now reported as unfinished, so detection drops from 13/15 to 12/15. Its exit code is still 3. Seen from outside, a hang and a correct target slower than the timeout look the same: no answer within 2 s. One observation can't be a confirmed violation in one case and innocent in the other. The ground truth still says `hangs-at-40` is defective, so the metric counts it as a miss. That was not changed.
- Exact location is 12/15 in both columns, not v1's 13/15. The scorer no longer treats the timed-out $40.00 in `hangs-at-40` as judged.
- 23 of 27 primary reports are byte-identical. Of the other four:
  - `slow-correct-at-threshold` and `hangs-at-40`: `TARGET_DISCREPANCY_CONFIRMED` is replaced by `UNSUPPORTED`;
  - `import-fails` and `time-limit-exhausted`: only the finding text changed, which now counts failures by kind.

  Exit codes and levels are unchanged in all 27 cases. The sweep runs in-process, where there are no timeouts, and is unchanged.
- **Public behaviour change:** with no reference, a hang used to exit 4 (`TARGET_DISCREPANCY_MODEL_ONLY`) and now exits 3 (`UNSUPPORTED`).
- **Regression tests (`tests/test_target_worker.py`):**
  - Four are new: a slow correct target, a real discrepancy next to a timeout, and a timeout during the search all fail without the fix. The fourth, a long enough `--target-timeout` letting the slow target reach L3, already passed.
  - Three existing tests for a hang, an always-hanging target and a crash asserted the old behaviour and were updated. All three fail on the old code.
  - `tests/test_semantics.py` changes its hang and crash expectations from `CONFIRMED` to `UNSUPPORTED`.
  - The viewer test now also checks that unfinished calls aren't described as agreement.

### Narrow defects: three methods compared (corpus v2, unchanged)

**Why they were missed.** At the default budget, each date value gets 750 probes. 84 of them are ladder probes; the rest are spread round-robin over power-of-ten bands between neighbouring anchors.
- **$777.77:** the gap from $500.01 to $999.99 (49,997 cents) gets about 26 samples, so the chance of hitting the one wrong cent is roughly 0.05% per run.
- **The 33-cent range at $12,345.67:** it lies in a gap of about a million cents, which also gets about 26 samples, roughly a 0.09% chance per run.
- Measured over the 10 sweep seeds, the nearest sample came within $1.03 to $17.01 of $777.77, and within $11.97 to $468.45 of the range.
- More budget doesn't close this. Even at the 100,000 maximum, the chance of a hit stays at a few percent.

| Method | Detection | False accusations | Exact location | Sweep, exactly located (budgets 250 / 1000 / 2000 / 8000, of 120) | Search calls (primary) | Verdicts |
|---|---|---|---|---|---|---|
| A: boundary points, ladder, sampling and bisection (`master`, `ba916b8`) | 12/15 | 0/8 | 12/15 | 90 / 91 / 91 / 91 | 39,546 | 25/27 |
| A, measured on the branch with `--no-source-probes` | 12/15 | 0/8 | 12/15 | 90 / 91 / 91 / 91 | 39,546 | 25/27 |
| **B: A plus amounts written in the target's source (`cbcad53`)** | **14/15** | **0/8** | **14/15** | **110 / 111 / 111 / 111** | 39,523 | **27/27** |
| C (policy only): Muse Spark's proposed test amounts from the 2026-10-27 response (replay of that saved live response) | adds 0 points to A | — | — | — | — | — |
| **E: B plus constant expressions folded from the source, no model (`c0a0fd8`, `eb79c45`)** | **14/15** | **0/8** | **14/15** | **120 / 120 / 120 / 120** | 39,510 | **27/27** |

Experiment C with the target's code (one live pilot call, 2026-10-31) and method E are reported separately below.

- **B** finds `single-cent-777.77` and `narrow-literal-range` in 40 of 40 search-enabled sweep runs (previously 0 of 40), all exactly located.
  - Both literal targets now exit 3; all other exit codes and levels are unchanged. Spurious claims stay at 0 (0/613 in the primary run, 0 in the sweep). Reproducible at `cbcad53`: yes. A review re-run at `e2f37b4` gave the same metrics and 26 of 27 identical reports; only the wall-clock-dependent `time-limit-exhausted` differed between its two passes.
  - In the primary run, B's 14/15 includes `narrow-computed-range`, found at the default seed exactly as with A. Over the sweep it is found in 1 of 10 seeds at budgets of 1000 and above, and 0 of 10 at 250, with or without B.
  - The remaining miss is `hangs-at-40`, which is by design (see corpus v2 above).
- **C (policy only)** was not run live in that session: `META_MUSE_API_KEY` was not available.
  - The one saved live `muse-spark-1.3` response (2026-10-27; 669 input and 6,231 output tokens, 5,525 of them reasoning) proposed test cases at $39.99, $40.00 and $40.01 only. All six of its test points are already derived boundary points, so they add no new probes.
  - Muse sees only the policy text, and neither $777.77 nor $12,345.67 appears in it. C cannot find these defects from the policy alone, however many trials are run.
  - Giving Muse the target's source would be a different method. It needs live calls and saved responses to be measured.
- **First version of B and its side effect.** At first, the source-amount probes also served as band boundaries for the random sampling. That moved the samples, and the computed-edge hold-out dropped from 1 of 10 seeds to 0 of 10. Measured in that first run: sweep 110/110/110/110, primary 13/15, and the hold-out missed at the default seed. `cbcad53` lays the bands out exactly as without source probes; the probes only use part of the budget. The table shows the corrected version.
- **What B is and isn't.** B is a grey-box step: it reads the target function's source, and the module constants it names, with `ast`, and never executes it. It only helps when the faulty amount is written as a literal. The computed-range hold-out shows the limit: its edges, `LIMIT * 50 + 0.37`, are not literals. A source amount is a place to look, never evidence. A correct target whose source mentions $777.77 is still L3 (`tests/test_source_literals.py`).
- **Corpus caveat.** Both literal targets were written by us, knowing that literal mining would be measured. On real engines, how often special cases are spelled as literals is unknown.

### Experiment C with the target's code: one live pilot call, then an offline seed sweep

**Status (2026-10-31): one live call made, for one target; the full run (63 calls) has not been made.** On 2026-10-28 no call was possible, because `META_MUSE_API_KEY` was not set. The harness is `benchmark/muse_probes.py`, on branch `feat/muse-probe-experiment`, which is stacked on `feat/source-literal-probes`. Its tests use only synthetic responses, labelled as such. They show that the mechanics work and say nothing about Muse.

#### The live pilot call

- **Call:** `python -B -m benchmark.muse_probes record --target benchmark.targets:narrow_computed_range --trials 1`. The key was read from the Git-ignored `.env` and never printed.
- **Response:** model `muse-spark-1.3`, response id `resp_6ae5b0b5ee523841844848fd`, status `completed`, created 2026-10-31 09:11:17 UTC and saved at 09:11:16 UTC (the two timestamps come from different clocks).
  - Usage: **473 input tokens and 2,873 output tokens**, 2,729 of them reasoning; 0 cached.
- **Saved file:** `artifacts/muse_probes/benchmark-targets-narrow-computed-range/trial-1.json` (Git-ignored), SHA-256 `0f3ecfd3…f74f`. It carries the live-recording label and no synthetic-fixture note.
  - It also records the exact 1,984-character prompt and its SHA-256 (`db1bc01b…bba`). That hash matches, and the prompt is byte-identical to what the harness builds today.
- **Proposals: seven amounts**, all valid, 0 issues: $2,000.36, $2,000.37, $2,000.38, $2,000.44, $2,000.51, $2,000.52 and $2,000.53. Its reasons name the "hidden low edge `_LOW`" and "hidden high edge `_HIGH`".
- **No answer leak:** none of the seven amounts appears in the prompt. The excerpt shows `_BASE = LIMIT * 50`, `_LOW = _BASE + Decimal(37) * CENT` and `_HIGH = _LOW + Decimal(15) * CENT`, with the `# 2000.37` comments removed. Muse computed the edges.
- **Offline replay of this live evidence, primary configuration** (`evaluate`, isolated worker, budget 2000, default seed; output in `artifacts/benchmark/muse-pilot.json`):
  - C: 12/15 detection, 0/8 false accusations, the same misses as A.
  - D: 14/15 detection, 0/8 false accusations, the same misses as B.
  - **No aggregate improvement.** Only one target has a Muse response, and at the default seed A already finds that target.

#### Controlled seed sweep (offline replay of the live evidence)

`python -B -m benchmark.muse_probes sweep --output artifacts/benchmark/muse-sweep.json`. It writes per-seed tables to `muse-sweep.md`; the network was blocked during both runs.

**Controls:**
- **Same work for every method:** the same corpus v2 case and ground truth (unchanged), the same target, the same budgets (0, 250, 1000, 2000, 8000) and the same ten seeds as `benchmark.run`'s sweep (20261104 and 1–9). Runs are in-process, like that sweep.
- **Same budget:** probe amounts use part of the same call budget and never add calls. Over the target's search-enabled runs, C and D made 84,380 search calls against 84,425 for A and B.
- **Deduplication and origin:** an amount proposed twice, or proposed and also found in the source, is probed once. Each row records which probe amounts came from the source, which from Muse, and which from both.
- **Correct targets as false-accusation controls:** the four correct targets are probed with the same seven amounts.
- **Evidence:** saved files with a missing or inconsistent input record (trial, target, model, corpus version, or a prompt that doesn't match its hash) are refused. So are duplicates, synthetic files without `--allow-synthetic`, and files of unknown origin. If an evidence file changes during the sweep, the results are discarded.

**Results on `narrow-computed-range`** (detected / exactly located, of 10 seeds):

| Budget | A: search | B: + source amounts | C: + Muse | D: + source + Muse |
|---|---|---|---|---|
| 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| 250 | 0 / 0 | 0 / 0 | **10 / 10** | **10 / 10** |
| 1000 | 1 / 1 | 1 / 1 | **10 / 10** | **10 / 10** |
| 2000 | 1 / 1 | 1 / 1 | **10 / 10** | **10 / 10** |
| 8000 | 1 / 1 | 1 / 1 | **10 / 10** | **10 / 10** |

- **The earlier 1-of-10 claim is reproduced.** A finds the range only at the default seed, at budgets of 1000 and above, and at no seed at 250. B is identical to A on every seed, because B finds $37.00, $15.00 and $50.00 in the source but not the computed edges.
- **Seed by seed:**
  - C gains the 9 seeds A misses at budgets 1000, 2000 and 8000, and all 10 at 250. It loses none.
  - D against B is identical.
  - Every found range is $2,000.37 to $2,000.52 with both edges exact.
- **False accusations:** 0 in 800 control runs (4 correct targets × 10 seeds × 5 budgets × 4 methods). All controls ended at L3 with exit 0.
- **Spurious claims on the target:** 0 of 160 claims for C and for D, and 0 of 12 for A and for B. Each method had 40 search-enabled runs on the target, with 4 claims per detection.
- **Runtime:** about 132 s for the whole sweep (1,000 runs). C and D took within 0.5 s per budget of A and B.
- **Reproducible:** a second full run gave the same fingerprint (`b78c87b5…5a35`) and 1,000 of 1,000 identical report hashes. The evidence file's hash was unchanged.

**What this does and doesn't show:**
- On this one target, one live Muse Spark response turned a 0–1 in 10 detection rate into 10 in 10, at equal budget, with no false accusations. That is the only improvement measured.
- It is **one target and one trial**. The corpus-level metrics don't change.
- The result measures the quality of a single response. Because the response named the exact edges, the bisection's success once they were probed is mechanical. Whether Muse proposes them reliably is unknown until more trials are run.
- The target and the prompt were written by us. The prompt asks for "edges that the code computes from constants", knowing that this hold-out exists.
- **A deterministic extension of B, method E (below), finds the same edges without a model, with identical results on every seed and budget.** So this measurement does not show that Muse is needed.
- Every finding still comes from the target's and the reference's observed decisions. A proposal is a place to look.

#### Method E: deterministic constant folding, the control for Muse

**Design** (`src/policyproof/constant_folding.py`, `verify(constant_probes=True)`, `benchmark.run --constant-probes`; measured on the working tree that was then committed unchanged as `c0a0fd8` and `eb79c45`):
- **Reads, never runs.** The target's source file is parsed with `ast`. Nothing from it is imported, called, `eval`-ed or `exec`-ed. A test forbids `eval`, `exec` and new imports during extraction.
- **A bounded evaluator, not a Python interpreter:**
  - int, float and `Decimal` literals;
  - `Decimal(x)` only when `Decimal` provably comes from the `decimal` module;
  - `+ - * / // %`, unary `-` and `+`, and `**` with an integer exponent of 0–12;
  - Python's own type rules (`Decimal + float` is unsupported, as it would raise), in a context equal to `decimal`'s default;
  - nesting, magnitude and candidate-count limits.
- **Name resolution:** module-level and function-local names bound exactly once, followed transitively. Parameters, loop and except variables are runtime values.
- **Reported, never guessed:** other calls, attributes and methods (`.quantize()`), imported names, names bound more than once or rebound by `global` or augmented assignment, cycles, division by zero, oversized values. Each comes with its line in the report's `constant_amounts.unsupported`.
- **Provenance:** every folded amount lists the expressions it came from, for example `2000.37 ← line 103: _BASE + Decimal(37) * CENT`. E's candidates are B's literals plus the folded amounts. They are probed like any other hint, inside the same call budget.
- **On the corpus:** E adds amounts beyond B only on `narrow_computed_range` ($0.15, $0.37, $2,000.00, $2,000.37, $2,000.52). On every other target it adds nothing.

**Seed sweep, `narrow-computed-range`** (same evidence, budgets, seeds and controls as above; `artifacts/benchmark/muse-sweep-ef.json`):

| Budget | A | B | C: + Muse | D: B + Muse | E: B + folding | F: E + Muse |
|---|---|---|---|---|---|---|
| 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 250 | 0 | 0 | 10 | 10 | **10** | 10 |
| 1000 | 1 | 1 | 10 | 10 | **10** | 10 |
| 2000 | 1 | 1 | 10 | 10 | **10** | 10 |
| 8000 | 1 | 1 | 10 | 10 | **10** | 10 |

(Each cell counts seeds of 10 that both detected and exactly located the range.)

- **E against B:** E gains every seed B misses and loses none.
- **C against E:** no seed differs, at any budget.
- **F against E:** no seed differs; Muse adds nothing on top of E.
- **Search calls:** C, D, E and F made 84,380 calls over the target's 40 search-enabled runs each, against 84,425 for A and B.
- **Runtime:** E took 5.0 s against 4.5 s for C over the same runs. Extraction cost is small.
- **False accusations:** 0 in 1,200 control runs (4 correct targets × 10 seeds × 5 budgets × 6 methods), all at L3.
- **Spurious claims:** 0 of 160 for each of C, D, E and F.
- **Unique candidates:**
  - Muse proposed five amounts that E did not: $2,000.36, $2,000.38, $2,000.44, $2,000.51 and $2,000.53. Counting the one-cent neighbours, that is 7 probe points E does not make.
  - All of them lie inside or next to a range whose edges E's probes already locate, so none changed a result.
  - E's own extra candidates ($0.15, $0.37, $2,000.00, …) found nothing either.
- **Reproducible:** two full A–F runs gave the same fingerprint (`8d510c36…69c0`) and 1,500 of 1,500 identical report hashes. The A–D rows are identical to the earlier A–D sweep (1,000 of 1,000), so adding E changed nothing else. The evidence file's hash was unchanged.

**Across the corpus, E alone** (`benchmark.run --constant-probes`, `artifacts/benchmark/results-v2-E.*`):
- **Primary run:** 14/15 detection, 0/8 false accusations, 0/613 spurious claims, 27/27 verdicts, 39,510 search calls. That is the same as B. B already finds this target at the default seed.
- **Sweep:** 120/120 intervals exactly located at budgets 250, 1000, 2000 and 8000, against B's 110 / 111 / 111 / 111. Every interval B missed belongs to this target: 10 at budget 250 and 9 at each of the others. Spurious claims are 0 across the sweep.
- **A and B unchanged:** with the flag off, every report is byte-identical to the run before E was wired in, except the wall-clock case `time-limit-exhausted`.

**Conclusion:**
- On frozen corpus v2, **Muse Spark's code-based proposals add no measured value beyond deterministic constant folding.** E matches C and D on every seed and budget, and F equals E.
- The live call shows that Muse can read this code correctly. It does not show that Muse is necessary.
- A Muse advantage could appear only on defects whose edges E cannot fold:
  - computed through calls, methods (`.quantize()`) or loops;
  - imported from other modules;
  - written as strings, or held in data structures.

  None of the corpus v2 targets is like that. Measuring such targets would need a new corpus version, committed before any measurement.
- **Found during this work:** `examples/buggy_engine.py` begins with a UTF-8 byte-order mark. B's literal reader cannot parse it, so B reports "source could not be parsed" for that engine. E reads the mark correctly. This doesn't change B's results, because $40.00 is already a derived boundary point. B was not modified, to keep its results frozen.

**Design, fixed before any live data:**
- **Input to Muse:** the policy text, plus a code excerpt regenerated from the target's syntax tree (`source_literals.source_excerpt`):
  - it covers the same function and module constants that method B reads;
  - the function is renamed to `decide`;
  - comments and docstrings are removed.

  The removal matters: the corpus targets' docstrings and comments state their own bugs (for example "Approves dated $2,000.37 to $2,000.52"), and so do their function names. Each saved file records the exact prompt and its SHA-256.
- **Calls:** `record` makes one live `muse-spark-1.3` call per distinct corpus target and trial, with 3 trials by default. That is 21 importable targets, so 63 calls. It never overwrites a saved trial, and it saves the API's `usage` record. Cost is not known in advance.
- **Methods**, scored on the frozen corpus v2 with its primary configuration (isolated worker, budget 2000, seed 20261104), one run per trial:
  - **C:** Muse's amounts as extra probes, without source amounts;
  - **D:** Muse's amounts plus source amounts (B).

  Both are compared with A and B above.
- **Primary question:** is `narrow-computed-range` found? Its edges are computed (`LIMIT * 50 + 37 cents`, so $2,000.37 to $2,000.52). B cannot see them, and sampling finds them in only 1 of 10 seeds.
- **Must hold:** 0/8 false accusations.
- **Also reported:** detection; exact location; new unique probes beyond the derived points, the ladder and B; search calls; tokens from `usage`; and, per target, agreement between trials.
- **What any result can and cannot show:** a proposal is only a probe. Every finding still comes from the target's and the reference's observed decisions. A Muse success on this corpus would show that it can reason about this code. It would not show reliability on real engines.
- **Cost estimate (2026-10-28):** Meta's pricing page lists `muse-spark-1.3` standard mode at $1.25 per million input tokens, $0.15 cached input and $4.25 output. It doesn't say whether reasoning tokens are billed. The one saved live response counted its 5,525 reasoning tokens inside `output_tokens` (6,231), so this estimate assumes they are billed as output.
  - **Input:** the probe prompts are 1,774 to 1,999 characters. At the 4.27 characters per token measured on the saved call, that is about 465 tokens for the pilot and about 9,180 for all 21 targets per trial.
  - **Output** is the uncertain part.

  | Output tokens per call | Pilot (1 call) | Full run (63 calls) |
  |---|---|---|
  | Same as the saved response | about $0.03 | about $1.70 |
  | 2 × | about $0.05 | about $3.37 |
  | 5 × | about $0.13 | about $8.38 |

  These are estimates, not measurements. The pilot's `usage` record will replace the output assumption.
- **Pilot first:** `python -m benchmark.muse_probes record --target benchmark.targets:narrow_computed_range --trials 1` makes exactly one live call. The full run waits for a cost review.
- **Commands:**
  1. `python -m benchmark.muse_probes record`, with the key set in that shell only;
  2. `python -m benchmark.muse_probes evaluate --output artifacts/benchmark/muse-probes.json`;
  3. `python -m benchmark.muse_probes sweep --output artifacts/benchmark/muse-sweep.json` (offline: methods A–D per seed and budget).

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
| **all, after `b434796`** | 70/20 | **90/90** | **91/91** | **91/91** | **91/91** |

The rows above are from before `b434796`; this sweep is identical before and after the fix in `1021823`. After `b434796`, `off-by-one-cent`, `truncated-cents` and `bankers-rounding` are 10/10 exactly located at every budget from 250 up. They stay 10/0 at budget 0, where search is off by contract. Every other row is unchanged. Every interval found at a nonzero budget is now exactly located. No spurious claims were made anywhere in either sweep.

## What the evidence says

1. **No false accusations and no spurious claims** (0/7 cases, 0/598 claims). When PolicyProof says "confirmed", the ground truth agreed every time in this corpus. The model-only, contradicting-expectation and conflicting-reference scenarios were correctly *not* confirmed.
2. **Discrepancies found only at evaluated points were never bounded.** Before `b434796`, `off-by-one-cent` was found in 50/50 runs but exactly located in 0/50: the verifier reported $40.01 and never checked whether $40.02 agreed. `bankers-rounding` was exactly located in only 4/10 seeds at the default budget. The cause was that bisection ran only for disagreement the search itself had found. **Fixed in `b434796`.** "Exactly located" means both sides of each edge were evaluated. The cents between the edges are still sampled, not all checked.
3. **Narrow defects far from any threshold are missed at every budget tested.** The single cent and the 33-cent range were found in 0 of 40 runs each with search enabled (budgets 250–8000, 10 seeds each); budget 0 disables search by contract. The computed 16-cent range was found in 1/10 seeds at budgets of 1000 or more. This is the documented limitation of sampling, now quantified.
4. **The loophole demo is found by the round-number ladder, not by random sampling.** Its edges ($999.99/$1,000.00 and $4,999.99/$5,000.00) are ladder probes; the run uses 0 bisection calls. The demo narration must say this rather than imply that the random search found it.

## Threats to validity

- **Corpus design:** the corpus is small and synthetic, written by the same team that built the verifier. The defects are single-mechanism seeds. Real engines have more inputs, and their defects interact.
- **Ground truth:** it is declared, then checked at edges and samples, not exhaustively over about 200 million inputs.
- **Scorer fix after the first run:** the first baseline scored points in `conflicting-reference` against that run's deliberately conflicting reference instead of the ground truth, which gave 744/745. That is a harness bug. It was fixed and the baseline was re-run on the unmodified verifier before any comparison. No ground truth or expected verdict was changed.
- **Timing dependence:** `time-limit-exhausted` and `hangs-at-40` depend on wall-clock time. The not-run count was 1421 in these runs and 1422 in one earlier run, so their reports are reproducible only per machine and load. Every other case is deterministic.
- **Timeouts (fixed in `3def8c0`):** until corpus v2, a timeout was a confirmed discrepancy, and a correct but slow target would have been reported as wrong. A timeout is now not evaluated. What remains: a target that is genuinely slow everywhere is reported as unfinished, never as correct, until `--target-timeout` is raised. The 2 s default is not tuned to any real engine.
- **Platform:** all runs were on Windows. CI covers the unit tests on Linux, but it does not run the benchmark.

## Ranked next improvements (from this evidence)

1. ~~Bound discrepancies seen at evaluated points.~~ Done in `b434796`; see above.
2. ~~Close the narrow-defect gap for literal amounts.~~ Done with source-amount probes (B, `cbcad53`); see above. Narrow defects at computed amounts (1 of 10 seeds with B) are closed by method E (10 of 10, deterministic). One live Muse Spark response found the same edges, but added nothing beyond E (see experiment C and method E above). **Still open:** defects whose edges E cannot fold. Whether Muse helps there needs new targets in a new corpus version, committed before measurement, and live calls.
3. ~~Stop counting timeouts as wrong answers.~~ Done in `3def8c0` (corpus v2); see above.
