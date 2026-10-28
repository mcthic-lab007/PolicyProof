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
