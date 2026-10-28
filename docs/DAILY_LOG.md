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
