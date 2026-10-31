# Hackathon contributions

What was built for the Meta Global AI Developer Hackathon (2026-10-26 to 2026-11-04), as far as the repository can show it. Every claim below points to a commit in this repository.

## Evidence and its limits

- The repository has **no commit before 2026-10-27 19:49 +0530**. All commits are dated 2026-10-27 or later, inside the event window.
- Git dates are set by the committer's machine and are **not proof** of when code was written. This document does not infer authorship dates beyond what the commits show.
- **AI assistance.** Commits from `9ad4b4a` onward carry a `Co-Authored-By: Claude Opus 5.5` trailer. They were written with Claude Code as a development assistant. Part of `496bc75` was also written with Claude Code, although that commit has no trailer (see below).

## Provenance of the first commit, `496bc75`

`496bc75` ("Establish PolicyProof validation baseline", 2026-10-27 19:49 +0530, 16 files, 1,702 lines) arrived as one block. It was investigated on 2026-10-28 using records kept outside Git, not the commit date alone. All times are IST (+0530) on 2026-10-27, one day after the event started.

**Evidence:**

| Source | What it shows |
|---|---|
| Claude Code transcript of the first session in this project (local, not committed) | Starts at 18:56:59. The user's first prompt lists `models.py`, `reference.py`, `verifier.py`, `generator.py`, `reporting.py`, `examples/buggy_engine.py` and `tests/test_verifier.py` as **existing files** that "previously passed three unit tests". |
| The same transcript | Claude Code **created** `.gitignore` and the `__init__.py` files (19:00), `examples/democo_meal_policy.txt` and `examples/democo_meal_rules.json` (19:05), `src/policyproof/schema.py` (19:06) and `tests/test_schema.py` (19:06). It edited them after a review until 19:23. The user made the commit at 19:49. |
| Claude Code prompt history (local) | No prompt in this project before 18:56:59. No other local Claude Code transcript mentions PolicyProof. |
| File creation times in the working tree | `.venv` 17:04, then `models.py` 17:07, `reference.py` 17:10, `buggy_engine.py` 17:11, `verifier.py` 17:12, `reporting.py` 17:13, `test_verifier.py` 17:16 (last modified 17:26) and `generator.py` 17:18. |
| The author's planning documents (local, not committed) | A project write-up saved at 16:25 lists "build a tiny synthetic DemoCo engine" as a **next step**, after a manual Muse Spark smoke test. A workflow write-up saved at 17:38 describes the prototype with three passing tests. |
| The author's other local projects | A search for PolicyProof identifiers found no shared code (only matches inside third-party packages). |

**What this establishes:**
- The schema validator, its tests, the DemoCo policy text and rules file, and `.gitignore` (1,485 of the 1,702 lines) were written with Claude Code on 2026-10-27 between 19:00 and 19:23. That is inside the event.
- Every independent record dates the prototype (seven files, 217 lines) to 2026-10-27 between about 17:04 and 17:26. All of them are consistent with it being written during the event. **No record suggests anything predates 2026-10-26.**

**What remains uncertain:**
- File creation times are file-system metadata. Copying or restoring a file can change them, so they corroborate but do not prove.
- The planning documents' save times are the only independent record of when they were written. Their embedded metadata is a library default and carries no information.
- **Who or what wrote the prototype is not recorded.** It was not written in Claude Code. The 17:38 write-up describes it as "code created in this session", which suggests an assistant chat session. Before submission, the author should name the tool here.

## Contribution inventory

| # | Component | Commits (date, +0530) | What it does | Tests / demonstration |
|---|---|---|---|---|
| 0a | Differential-testing prototype | `496bc75` (10-27 19:49). Written about 17:07–17:26 on 10-27 by a tool not recorded (see above) | Hand-written reference, buggy engine at $40.00, seven fixed cases, JSON report | `tests/test_verifier.py` (3 tests) |
| 0b | Strict proposal schema and validator; DemoCo policy and rules | `496bc75` (10-27 19:49). Written with Claude Code 19:00–19:23 on 10-27 | Closed JSON contract, exact decimals, verbatim evidence quotes, threshold grounding | `tests/test_schema.py` |
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
| 14 | Provenance audit of `496bc75` | `045a74a` (10-28) | Records outside Git checked; findings in this document | — |
| 15 | Bounded edges for discrepancies seen only at evaluated points | `b434796` (10-28) | The edges of an off-by-one-cent bug are located and both sides are shown as evaluated | Six tests in `test_target_search.py`; benchmark exact location 12/15 → 13/15 |
| 16 | Benchmark corpus v2; timeouts and crashes are not evaluations | `f21e7b0`, `3def8c0` (10-28) | A correct target slower than the timeout is no longer accused; the viewer lists unfinished calls | Tests in `test_target_worker.py`, `test_semantics.py` and `test_viewer.py`; false accusations 1/8 → 0/8 |
| 17 | Source-amount probes (grey-box, parse-only) | `5c5d7db`, `cbcad53`, `deeef62` (10-28) | Probes the numeric literals in the target's own source before sampling; listed in the report, CLI and viewer | `tests/test_source_literals.py`; literal narrow defects 0/40 → 40/40 search-enabled runs |
| 18 | Experiment harness: Muse Spark proposes probe amounts | `622588c` (10-28), pilot option `472257c` | Records live `muse-spark-1.3` proposals with prompt and usage, then scores them offline on the frozen corpus; proposals are only probes. One live pilot call on 2026-10-31 (see below) | `tests/test_muse_probes.py` (synthetic responses only) |
| 19 | Constant-folding probes, method E (parse-only, opt-in) | `c0a0fd8` (10-31) | A bounded AST evaluator folds constant expressions in the target's source (`_BASE + Decimal(37) * CENT`) into probe amounts with derivations; unsupported expressions are reported; target code is never run | `tests/test_constant_folding.py`; computed-edge range 1/10 → 10/10 seeds, deterministic |
| 20 | Muse probe seed sweep and evidence checks; `.env` key loading | `eb79c45` (10-31) | Offline methods A–F at equal budgets and the same ten seeds, correct-target controls, probe origins, fingerprint; stricter refusal of saved responses; key read only for live `record`, never printed | `tests/test_muse_probes.py`, `tests/test_muse_client.py`; [BENCHMARK.md](BENCHMARK.md) |

Merge commits (`9dcfe54`, `5cc0f07`, `129433b`, `b2f75b9`, `7918fcb`, `7921aa3`, `e48006d`, `451e83b`) integrate the feature branches above and add no code of their own.

## Meta model usage: what Muse Spark does and what it does not

| | Muse Spark (`muse-spark-1.3`, Meta Responses API) | PolicyProof's own code |
|---|---|---|
| Role | Reads the policy text and **proposes** rules and test cases as JSON | Validates, executes, derives test points, compares, searches, decides the verdict |
| Where | `src/policyproof/muse_client.py`, reached by `--live` | Everything else in `src/policyproof/` |
| Influence on results | Its thresholds seed the boundary test points; its rules and test cases are two of the four perspectives; it can **withhold** a confirmation | All findings, levels and exit codes |

- **Live evidence:** one live call was made on 2026-10-27 at 15:11:37 UTC (`artifacts/muse_live_001.json`, `status: completed`, `model: muse-spark-1.3`). That file is git-ignored because it quotes the policy text and the API reported `store: true`. Replaying it is labelled `REPLAY_SAVED_LIVE_RESPONSE`, never `LIVE`.
- **Second live call (probe proposals):** one call on 2026-10-31.
  - Model `muse-spark-1.3`, response `resp_6ae5b0b5ee523841844848fd`, saved 09:11:16 UTC, 473 input and 2,873 output tokens.
  - Saved, git-ignored, as `artifacts/muse_probes/benchmark-targets-narrow-computed-range/trial-1.json`, with the exact prompt and its SHA-256.
  - Muse proposed the computed edges $2,000.37 and $2,000.52, among seven amounts. Their evaluation is an offline replay labelled `REPLAY_SAVED_LIVE_RESPONSE`.
  - PolicyProof's deterministic constant folding (row 19) finds the same edges without a model, so Muse added no measured value beyond it on this corpus ([BENCHMARK.md](BENCHMARK.md)).
- **Offline evidence:** the committed fixture is hand-written and labelled `REPLAY_SYNTHETIC`. It is not Muse output. The benchmark and offline demo use it so that anyone can reproduce them.

## Third-party dependencies and services

- Python 3.12 standard library.
- `requests==2.34.2`, used only by the Muse client.
- The Meta Muse Spark API (`https://api.meta.ai/v1/responses`), only in `--live` mode.
- GitHub Actions: `actions/checkout@v4`, `actions/setup-python@v5`.
- Development assistant: Claude Code (see the commit trailers).
