# Hackathon contributions

What was built for the Meta Global AI Developer Hackathon (2026-10-26 to 2026-11-04), as far as the repository can show it. Every claim below points to a commit in this repository.

## Evidence and its limits

- The repository has **no commit before 2026-10-27 19:49 +0530**. All commits are dated 2026-10-27 or later, inside the event window.
- Git dates are set by the committer's machine and are **not proof** of when code was written. This document does not infer authorship dates beyond what the commits show.
- **Open question for the author to confirm.** The first commit, `496bc75` ("Establish PolicyProof validation baseline", 16 files, 1,702 lines), arrived as one block. It contains the strict schema validator (`schema.py`, 710 lines) and its tests, plus the small prototype (`models.py`, `reference.py`, `generator.py`, `verifier.py`, `reporting.py`, `examples/buggy_engine.py`). If any of that code was written before 2026-10-26, it must be listed here as a pre-existing foundation. **Until confirmed, treat `496bc75` as "provenance unconfirmed".**
- **AI assistance.** Commits from `9ad4b4a` onward carry a `Co-Authored-By: Claude Opus 5.5` trailer. They were written with Claude Code as a development assistant.

## Contribution inventory

| # | Component | Commits (date, +0530) | What it does | Tests / demonstration |
|---|---|---|---|---|
| 0 | Prototype and strict proposal schema | `496bc75` (10-27 19:49), **provenance unconfirmed** | Closed JSON contract, exact decimals, verbatim evidence quotes, threshold grounding, plus a minimal reference/buggy-engine comparison | `tests/test_schema.py`, `tests/test_verifier.py` |
| 1 | Muse Spark client | `9ad4b4a` (10-27 20:51) | Responses API client for `muse-spark-1.3`: prompt construction, strict response parsing, refusals and errors, key redaction, save/replay, provenance labels | `tests/test_muse_client.py`; one live call saved locally (see below) |
| 2 | Deterministic rule interpreter | `138c455` (10-27 21:03) | First-match priority semantics, NO_MATCH instead of default approval, full traces, boundary-point derivation | `tests/test_rule_engine.py` |
| 3 | Verification pipeline | `8e94bdd` (10-27 21:16) | Four perspectives per point, the finding taxonomy, levels L0–L3, JSON evidence report, CLI | `tests/test_verification.py` |
| 4 | Documentation and CI | `fffc954` (10-27 21:37) | README and the GitHub Actions unit-test workflow | CI run 40538523329 (success) |
| 5 | Evidence viewer and offline demo | `e8b057e` (10-27 22:18) | Static, script-free HTML page rendered from the report; one-command demo | `tests/test_viewer.py`; `python -m src.policyproof.demo` |
| 6 | Budgeted target search | `691d0de` (10-27 22:27) | Round-number ladder, seeded band sampling, bisection to the cent, discrepancy ranges | `tests/test_target_search.py`; loophole demo |
| 7 | Worker-process target execution | `66bbfcf` (10-27 22:39) | Per-call timeout, total time limit, crash and hang handling, key removed from the worker's environment. Process isolation, **not a security sandbox** | `tests/test_target_worker.py` |
| 8 | Confirmation semantics | `f1e805f` (10-27 23:54) | Model expectations can withhold a confirmation but never create one; exit 4 for inconclusive runs | `tests/test_semantics.py` |
| 9 | Viewer for search, isolation and verdicts; loophole engine | `ce1c845` (10-28 00:00) | Renders the new evidence; adds `examples/loophole_engine.py` | `tests/test_viewer.py` |
| 10 | `--require-level`; CI test-count annotations | `e2de657` (10-28 00:07) | Exit 5 when the required level isn't reached; public CI counts | CI run 40565476862 (success, on `451e83b`) |
| 11 | Adversarial benchmark, corpus v1 | `8d3b337` (10-28) | 26-case ground-truth corpus, scorer, budget/seed sweep | `tests/test_benchmark.py`; [BENCHMARK.md](BENCHMARK.md) |
| 12 | Fix: unjudged search calls counted as agreement | `1021823` (10-28) | A run whose search was cut short no longer reaches L3 or exits 0 | Regression tests in `test_target_search.py` and `test_target_worker.py` |
| 13 | Fix: search limitation text matches the execution mode | `fb0f96f`, `f326b83` (10-28) | The report no longer says "no timeout" for isolated runs | `test_target_worker.py` |

Merge commits (`9dcfe54`, `5cc0f07`, `129433b`, `b2f75b9`, `7918fcb`, `7921aa3`, `e48006d`, `451e83b`) integrate the feature branches above and add no code of their own.

## Meta model usage: what Muse Spark does and what it does not

| | Muse Spark (`muse-spark-1.3`, Meta Responses API) | PolicyProof's own code |
|---|---|---|
| Role | Reads the policy text and **proposes** rules and test cases as JSON | Validates, executes, derives test points, compares, searches, decides the verdict |
| Where | `src/policyproof/muse_client.py`, reached by `--live` | Everything else in `src/policyproof/` |
| Influence on results | Its thresholds seed the boundary test points; its rules and test cases are two of the four perspectives; it can **withhold** a confirmation | All findings, levels and exit codes |

- **Live evidence:** one live call was made on 2026-10-27 at 15:11:37 UTC (`artifacts/muse_live_001.json`, `status: completed`, `model: muse-spark-1.3`). That file is git-ignored because it quotes the policy text and the API reported `store: true`. Replaying it is labelled `REPLAY_SAVED_LIVE_RESPONSE`, never `LIVE`.
- **Offline evidence:** the committed fixture is hand-written and labelled `REPLAY_SYNTHETIC`. It is not Muse output. The benchmark and offline demo use it so that anyone can reproduce them.

## Third-party dependencies and services

- Python 3.12 standard library.
- `requests==2.34.2`, used only by the Muse client.
- The Meta Muse Spark API (`https://api.meta.ai/v1/responses`), only in `--live` mode.
- GitHub Actions: `actions/checkout@v4`, `actions/setup-python@v5`.
- Development assistant: Claude Code (see the commit trailers).
