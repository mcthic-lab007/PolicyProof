# Daily log

Times are given only where a commit or a tool records them. Commit times are +0530.

## 2026-10-27 to 2026-10-28 00:30: foundation (reconstructed from Git)

No log was kept that day; this entry is reconstructed from the commit history only.
- First commit 19:49 (`496bc75`), then the Muse Spark client, interpreter, verification pipeline, docs and CI, viewer, target search, worker isolation, confirmation semantics and `--require-level`. See [HACKATHON_CONTRIBUTIONS.md](HACKATHON_CONTRIBUTIONS.md).
- One live `muse-spark-1.3` call was saved at 15:11:37 UTC (local, git-ignored).
- Merged to `master` at `451e83b` (00:30). CI run 40565476862 succeeded.

## 2026-10-28: adversarial benchmark

**Start state (verified):** `master` = `origin/master` = `451e83b`, clean tree. CI succeeded on `451e83b`. The repository is public. 351 local tests passed (the saved live response is present). `META_MUSE_API_KEY` is not set in this shell, so no live call was made today.

**Done (branch `feat/adversarial-benchmark`, not merged):**
- `8d3b337`: corpus v1 with 26 cases, scorer and sweep. Committed before measuring.
- Baseline on the unmodified verifier: detection 13/15, false accusations 0/7, spurious claims 0/598, verdicts 23/26.
- Found a verifier bug: search calls skipped by the time limit were counted as agreement, giving a false L3 with exit 0.
- `1021823`: fix plus regression tests, which fail without the fix. The same commit fixes a benchmark-scorer bug, and the baseline was re-run on the unmodified verifier.
- `fb0f96f`: a search limitation said "no timeout" even for isolated runs. **That commit was made with 3 tests failing**, because a `grep` in the commit command hid the failure. `f326b83` restored the suite. No history was rewritten.
- After the fix: verdicts 24/26. Other metrics unchanged. Results are in [BENCHMARK.md](BENCHMARK.md).
- Added BENCHMARK.md, HACKATHON_CONTRIBUTIONS.md and DEMO_STORYBOARD.md, and updated the README.

**Validation:** 360 tests pass locally. Demo exits 0. CLI exit codes: buggy 3, fixed 0, no reference 4, loophole 3, loophole with budget 0 → 0, `--require-level L3` without a reference → 5. The saved live replay exits 3. No `python.exe` process was left running.

**Decisions:**
- Fixed the false-L3 bug first, rather than improving detection. It was the only *undisclosed* false assurance; the misses are disclosed sampling limits.
- The loophole narration must credit the round-number ladder, not random sampling.

**Open / blockers:**
- Confirm whether any of `496bc75` predates 2026-10-26.
- Choose the track and problem statement; this needs the official guide's exact wording.
- A live Muse take needs the key at recording time.
- Rename or avoid `artifacts/video/live-*.txt`; they are replays.

**Next action:** review and merge `feat/adversarial-benchmark`. Then measure ranked improvement #1 from BENCHMARK.md (bound discrepancies seen at evaluated points) on the identical corpus.

## 2026-10-28 (second session): provenance, review, bounded point discrepancies

**Start state (verified):** branch `feat/adversarial-benchmark` = `origin/feat/adversarial-benchmark` = `63e4b80`, clean tree. `master` = `origin/master` = `451e83b`. CI run 40634404707 on `63e4b80` succeeded (358 passed, 2 skipped). 360 local tests passed.

**Done:**
- **Provenance of `496bc75`:** investigated using records outside Git: the first Claude Code transcript and prompt history, file creation times, and the author's local planning documents. Every record dates the commit's content to 2026-10-27. The schema, its tests, and the policy and rules files were written with Claude Code (19:00–19:23). The prototype dates from about 17:04–17:26, and the tool that wrote it is not recorded. Committed as `045a74a` on `feat/adversarial-benchmark`, with two benchmark wording fixes.
- **Review of `feat/adversarial-benchmark`:**
  - The ground truth was committed at 10:03:55, before the first measurement at 10:05:32.
  - The corpus is unchanged since then; only the 3-line scorer fix touched the benchmark code.
  - The three regression tests fail on `8d3b337` and pass on HEAD (re-run in a temporary worktree, since removed).
  - No merge blockers.
- **New branch `feat/bound-point-discrepancies`**, stacked on `feat/adversarial-benchmark`, because the change needs the benchmark.
  - `b434796` bounds discrepancies seen only at evaluated points.
  - Exact location went from 12/15 to 13/15. In the sweep at budgets of 250 and above, 60–80 of 120 interval-runs were exactly located before; now every found interval is (90/90, 91/91, 91/91, 91/91). The other metrics are unchanged.
  - The first version missed one seed. That was found by the benchmark and fixed before the commit.

**Validation:**
- 369 tests pass locally.
- CLI exit codes: buggy 3, fixed 0, loophole 3, no reference 4, loophole with budget 0 → 0, fixed with `--require-level L3` → 0, no reference with L3 required → 5.
- The demo exits 0. It was written to the scratchpad, because the existing `artifacts/demo` files were kept.
- Benchmark reproducibility: 25 of 26 cases matched. Only the wall-clock-dependent `time-limit-exhausted` case differed.

**Decisions:**
- Chose A (bounding) over B and C. It was the only candidate that could be measured offline today, it reuses the existing bisection, and it changes no verdict.
- C (Muse-proposed probes) needs a live key and saved responses to be measured.

**Open / blockers:**
- The author should name the tool that wrote the prototype (17:04–17:26 on 10-27).
- The official participant guide's wording on tracks and problem statements is still not in the repository or in either session. Only the summary in the Day 3 prompt is available.
- Timeouts count as wrong answers. This is a threat to validity, listed in BENCHMARK.md.
- Neither branch is merged.

**Next action:**
1. Review and merge `feat/adversarial-benchmark`, then `feat/bound-point-discrepancies`.
2. With `META_MUSE_API_KEY` set, make and save a live call that asks Muse Spark for adversarial probe amounts (C).
3. Measure C against a deterministic literal-mining control (B) on corpus v1.

## 2026-10-28 (third session): merges, then timeouts are not evaluations

**Merges (authorized by the author; verified):**
- `fd19ffe` (docs only) was added to `feat/bound-point-discrepancies` before merging. It documented the timeout false-accusation limitation and corrected the README. CI run 40648468216 succeeded.
- `2dee2a6` merged `feat/adversarial-benchmark` into `master`. 360 local tests OK. CI run 40648694182: 358 passed, 2 skipped.
- `9a3adb1` merged `feat/bound-point-discrepancies`. 369 local tests OK. CI run 40648794074: 367 passed, 2 skipped.
- After each merge, master's tree was identical to the merged branch's. All documented CLI exit codes and the demo were checked.
- `master` = `origin/master` = `9a3adb1`. Both feature branches are kept.

**Start state for this session (verified):** `master` = `origin/master` = `9a3adb1`, clean tree. Branch `feat/timeout-not-violation` was created from `origin/master`.

**Done:**
- `f21e7b0`: corpus v2 adds `slow-correct-at-threshold`, and the scorer stops counting unfinished calls as judgements. Committed before measuring.
- Baseline on the unmodified verifier (`f21e7b0`): **1/8 false accusations**. The correct but slow target was confirmed wrong at $40.00 because its call timed out.
- `3def8c0`: timeouts and worker crashes are now not evaluated: `UNSUPPORTED`, exit 3, no L3. The viewer lists unfinished calls instead of saying the target agreed.
- After the fix: false accusations 0/8, spurious claims 0/605, verdicts 25/27, all exit codes unchanged. Detection fell from 13/15 to 12/15 by design, because `hangs-at-40` is now unfinished rather than confirmed. Public change: a hang with no reference exits 3 instead of 4.
- Three existing hang/crash tests and `test_semantics` were updated to the new semantics. Each is listed in BENCHMARK.md.

**Validation:** 373 local tests OK. CLI exit codes unchanged: buggy 3, fixed 0, loophole 3, no reference 4, loophole with budget 0 → 0, no reference with L3 required → 5. The saved-live replay exits 3 and is labelled REPLAY. The demo exits 0. CI run 40651237249 on `e1768c7`: 371 passed, 2 skipped.

**Open:**
- A target that is slow everywhere is reported as unfinished, never as correct, until `--target-timeout` is raised. The 2 s default isn't tuned to a real engine.
- The prototype's authoring tool still has to be named.
- The participant guide's exact wording is still needed.

**Next action:** review `feat/timeout-not-violation` (not merged). Then, with `META_MUSE_API_KEY` set, make a saved live call for Muse-proposed probe amounts (C) and measure it against literal mining (B).

## 2026-10-28 (fourth session): source-amount probes for narrow defects

**Merge recorded (verified at session start):** `feat/timeout-not-violation` was merged as `ba916b8`, after a docs-only README commit `375342a` (CI run 40652471927 succeeded). CI run 40652731402 on `ba916b8`: 371 passed, 2 skipped. `master` = `origin/master` = `ba916b8`, clean tree. Branch `feat/source-literal-probes` was created from `origin/master`.

**Done:**
- **Reproduced:** at the default budget, about 26 samples land in the gaps holding $777.77 (49,997 cents) and the 33-cent range (about a million cents). The nearest sample over 10 seeds came within $1.03 and $11.97 respectively. Both were missed in 0 of 40 search-enabled runs.
- **Compared three methods on frozen corpus v2:**
  - A (`master`) and A with probes off give identical metrics.
  - **B** (literals in the target's source) finds both in 40 of 40. Detection 12/15 → 14/15, verdicts 25/27 → 27/27, false accusations 0/8, spurious claims 0.
  - C: the saved live Muse response's six test points are all already derived, so it adds 0 probes. C was not run live because `META_MUSE_API_KEY` was not set.
- `5c5d7db` added B. **Its first version made the computed-edge hold-out worse** (1/10 → 0/10 seeds), because the probes re-split the sampling bands. `cbcad53` fixed that before any documentation; the hold-out is back to 1/10.
- `deeef62`: the probed amounts appear in the CLI summary and on the evidence page.

**Validation:** 385 local tests OK. CLI exit codes unchanged: buggy 3, fixed 0, loophole 3, no reference 4, loophole with budget 0 → 0, no reference with L3 required → 5. The saved-live replay exits 3 and is labelled REPLAY. The demo exits 0. Benchmark B reproducible on a clean tree at `cbcad53`.

**Open:**
- Narrow defects at computed amounts.
- B only helps Python targets whose source can be read.
- A live Muse experiment (probes proposed from the target's source, with saved responses, measured against B) needs the key.
- Branch not merged.

**Next action:** review `feat/source-literal-probes`. With the key available, record and save live Muse probe proposals and measure them against B.

## 2026-10-28 (fifth session): review of method B; experiment C prepared

**Start state (verified):**
- `master` = `origin/master` = `ba916b8`.
- `feat/source-literal-probes` = its remote = `e2f37b4`, clean. CI run 40657124464 belongs to `e2f37b4` and succeeded.
- `artifacts/` is ignored by Git and intact.
- `META_MUSE_API_KEY` is not set at process, user or machine scope, so **no live call was made**.

**Review of B:**
- Parsing is safe on decorated functions, methods, nested functions, `functools.partial`, callable instances, builtins, a malformed file and a deleted file. It never raised, and it never ran the target.
- Re-ran the benchmark at `e2f37b4`: the same metrics, and 26 of 27 reports identical to the `cbcad53` run (`time-limit-exhausted` is wall-clock dependent).
- Checked the 40/40 per budget from the sweep records.
- The BENCHMARK.md tables are well formed. One wording correction was committed as `3b90f85`.

**Experiment C prepared** on `feat/muse-probe-experiment`, stacked on the B branch:
- `622588c` adds `record` (live) and `evaluate` (offline), the proposed-probe support in `verify()`, and `MuseClient.complete()`.
- Muse receives code with comments and docstrings removed and the function renamed, because the corpus targets' docstrings state their bugs.

**Validation:** 394 local tests OK. Benchmark B unchanged on this branch (14/15, 0/8, 27/27, reproducible). CLI exit codes unchanged: buggy 3, fixed 0, loophole 3, no reference 4, loophole with budget 0 → 0, no reference with L3 required → 5. The saved-live replay exits 3 and is labelled REPLAY. The demo exits 0.

**Blocker:** a live key.

**Next action:**
1. With the key set in one shell, run `python -m benchmark.muse_probes record` (63 calls by default; check the cost first).
2. Then run `evaluate`, and report C and D against A and B.
3. Review the two branches in order.

## 2026-10-28 (sixth session): live pilot blocked; pilot path and cost estimate prepared

**Start state (verified):** `master` = `origin/master` = `ba916b8`. `feat/source-literal-probes` = `3b90f85` and `feat/muse-probe-experiment` = `fdcf289`, both matching their remotes and clean. The B branch is an ancestor of the experiment branch.

**Live call: none.** `META_MUSE_API_KEY` is not set at process, user or machine scope.

**Done:**
- Added `record --target` for a one-call pilot, with a test, and a token summary printed after each live call.
- Dry-ran `evaluate` on one labelled synthetic file: refused without `--allow-synthetic`, then labelled `REPLAY_SYNTHETIC`. The proposed edge located the computed range, and the fixed engine stayed at L3. One trial takes about 33 s.
- **Pricing:** checked against Meta's pricing page. Cost estimated from real prompt sizes; see BENCHMARK.md.

**Next decision (the author's):**
1. Set the key in one shell and run the one-call pilot (about $0.03–$0.13 estimated).
2. After the pilot's measured usage, decide on the full 63 calls (about $1.70–$8.40 estimated) and choose the tier. Contributor mode is cheaper but allows Meta to use the content for training.

## 2026-10-31: first live Muse probe call; offline seed sweep A–D

**Start state (verified):** branch `feat/muse-probe-experiment` = `origin/feat/muse-probe-experiment` = `472257c`, clean. `master` = `origin/master` = `ba916b8`. `feat/source-literal-probes` (`3b90f85`) is an ancestor of the branch. The author created a Git-ignored root `.env` holding `META_MUSE_API_KEY`. Nothing in the code loaded it, and the key was not set in the shell, user or machine environment.

**Done (committed in the second session as `b60b386` and `9f8ee66`):**
- **`.env` loader:** `muse_client.load_api_key_from_dotenv`, standard library only.
  - It reads `META_MUSE_API_KEY` alone, never overrides a key already set, and never prints it.
  - Only `muse_probes record` calls it; `evaluate` and `sweep` never read `.env`.
  - Target workers still have the key removed from their environment.
  - An existing test now points at a missing file, so it can never read the real `.env`.
- **Live pilot (one call):** `muse-spark-1.3`, response `resp_6ae5b0b5ee523841844848fd`, saved 09:11:16 UTC (14:41 +0530).
  - Usage: 473 input and 2,873 output tokens (2,729 reasoning).
  - **Cost estimate** at the standard-mode prices recorded on 2026-10-28, assuming reasoning is billed as output: about $0.013. Not checked against an invoice.
  - Seven amounts proposed, $2,000.36–$2,000.53, including both computed edges. None of them appears in the prompt.
- **Offline replay, primary configuration** (`evaluate`): C 12/15 and D 14/15, 0/8 false accusations. Identical to A and B, because only one target has a response.
- **`sweep`:** methods A–D at the same budgets and the same ten seeds, with the correct targets as controls, the origin of every probe amount, and a reproducibility fingerprint.
  - `load_trials` now refuses inconsistent input records, duplicates and non-object files.
  - `benchmark.run` gained `sweep_seeds()` and an opt-in `keep_report`. Primary-run report hashes match the earlier B run made on this branch (`results-v2-B-harness`), except the wall-clock case.
- **Sweep result on `narrow-computed-range`:**
  - A and B: 0/10 at budget 250 and 1/10 at 1000, 2000 and 8000 (default seed only). This reproduces the earlier claim.
  - C and D: 10/10 at every budget from 250 up, all exactly located.
  - 0/800 false accusations in the control runs; 0 spurious claims.
  - Two full runs were identical (1,000 of 1,000 report hashes). The evidence file's hash was unchanged.

**Validation:** 419 tests OK locally (27 in `test_muse_probes`). `benchmark.run --skip-sweep` on this branch, started 09:24:48 UTC: 14/15 detection, 0/8 false accusations, 0/613 spurious claims, 27/27 verdicts, 39,523 search calls, the same as B. Only `time-limit-exhausted` differed between its two passes, as before. No CI run yet for these changes.

**Limits stated in BENCHMARK.md:**
- One target and one trial.
- The target and the prompt were written by us.
- A constant-folding extension of B has not been measured as a control.
- The corpus-level metrics are unchanged.

**Next decision (the author's):**
1. Review and commit these changes on the branch (not merged).
2. Decide whether to make more live calls. The cheapest informative step is 2 more trials on `narrow_computed_range`, to measure whether Muse repeats the edges. The full 63 calls are about $0.80 if each call's usage matches the pilot (an estimate).
3. Optionally, measure a deterministic constant-folding control before claiming that a model is needed for computed edges.
4. Update DEMO_STORYBOARD.md only with recorded behaviour.

## 2026-10-31 (second session): deterministic control E against Muse

**Start state (verified):** branch `feat/muse-probe-experiment` = its remote = `472257c`, with the first session's 7 files uncommitted. `master` = `origin/master` = `ba916b8`. The B branch (`3b90f85`) is an ancestor. The saved live response's SHA-256 is `0f3ecfd3…f74f`. **No API call was made this session.**

**Reproduced first:** the A–D sweep re-run from the frozen evidence, before any E code was written.
- Same fingerprint (`b78c87b5…5a35`) and 1,000 of 1,000 identical report hashes.
- 800 control runs with 0 false accusations.
- C and D: 40 search-enabled target runs each, 0 of 160 claims spurious. The earlier "0/160" counted claims, not runs; BENCHMARK.md now says so.

**Done:**
- **Method E**, `src/policyproof/constant_folding.py`: a bounded AST evaluator that folds constant expressions in the target's source to probe amounts, with provenance for each amount. It never runs target code; unsupported expressions are reported.
  - Wired as `verify(constant_probes=False)` by default. With the flag off, reports are byte-identical.
  - Added `benchmark.run --constant-probes`, and methods E (B + folding) and F (E + Muse) in `muse_probes sweep`.
  - 31 new tests in `tests/test_constant_folding.py`, plus updated sweep tests.
- **Sweep A–F** (offline replay of the live evidence):
  - E finds `narrow-computed-range` in 10/10 seeds at every budget from 250 up, all exactly located, the same as C.
  - C vs E and F vs E: no seed differs.
  - 0/1,200 false accusations in the control runs.
  - Reproducible: 1,500 of 1,500 identical report hashes.
- **Corpus-wide E** (`benchmark.run --constant-probes`, started 11:10:21 UTC): 14/15 detection, 0/8 false accusations, 0/613 spurious claims, 27/27 verdicts. Sweep 120/120 exactly located at every budget from 250 up, against B's 110/111/111/111.
- **Default B re-run** (started 11:12:06 UTC): identical to before, except `time-limit-exhausted`.
- **Found:** `examples/buggy_engine.py` has a UTF-8 BOM that B's literal reader cannot parse. It has no effect on results, and B was not changed.

**Conclusion:** on corpus v2, Muse's proposals add no measured value beyond deterministic constant folding. The live call shows that Muse read the code correctly, not that it is needed.

**Validation:** 453 tests OK locally. `b60b386` alone passes in a clean worktree (426 OK, 2 skipped: the git-ignored live replay).

**Live calls:** not made; they need the author's authorization. Two more trials on `narrow_computed_range` would measure only Muse's consistency on a target where E already reaches the ceiling. They cannot show incremental value.

**Next decision (the author's):**
1. Review E and the documentation.
2. If Muse's value is to be tested, first add targets that E cannot fold (corpus v3, committed before any measurement), then make live calls on those.
3. Decide how the demo presents Muse: as a proposer whose output PolicyProof checks, not as the source of a detection that E does not also make.
