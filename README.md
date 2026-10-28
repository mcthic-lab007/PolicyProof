# PolicyProof

**Muse Spark proposes; PolicyProof verifies.**

PolicyProof checks whether software follows the policy it is supposed to implement. Meta's Muse Spark reads a written policy and proposes machine-checkable rules and test cases. PolicyProof does not trust that proposal. It validates the proposal against the policy text, runs the rules in a deterministic interpreter, derives its own boundary tests, and compares four perspectives at every test point: the proposed rules, the model's own expectations, an independent human-written reference, and the software under test. The result is a JSON evidence report that states what was verified, at which inputs, and what was not.

Built for the Meta Global AI Developer Hackathon.

## The problem

Expense, claims and eligibility systems implement written policies in code, and the costly mistakes are small. A policy says *"Meal claims of $40.00 or less are approved automatically"*; the code says `amount < 40` instead of `amount <= 40`. Exactly one input breaks, and ordinary tests rarely include it.

A language model can read the policy and suggest tests, but its reading is itself unverified. It can paraphrase the policy, invent a threshold, or contradict its own test cases. PolicyProof is meant for engineers and QA or compliance teams who need evidence, not just an opinion, that an implementation matches its policy.

## Muse proposes; PolicyProof verifies

| Muse Spark (`muse-spark-1.3`) | PolicyProof |
|---|---|
| Reads the policy and proposes rules (conditions, decision, priority) | Accepts them only if every rule quotes the policy verbatim and every dollar threshold appears in its own quote |
| Proposes test cases with expected decisions | Treats those expectations as the model's claims, never as ground truth |
| — | Executes the rules in a deterministic interpreter (no `eval`, exact decimals) |
| — | Derives its own boundary tests from the rules and from `$` amounts in the policy text |
| — | Compares the proposed rules, the model's expectations, an independent reference and the target at every point |
| — | Reports findings and a verification level with an explicit scope |

## How it works

```
policy.txt ──► Muse Spark (Responses API) ──► proposed rules + test cases (JSON)
                                                     │
        schema.py       strict contract · verbatim evidence quotes · threshold grounding
                                                     │   (fails → VALIDATION_REJECTED)
        rule_engine.py  deterministic interpreter · boundary points t-0.01 / t / t+0.01
                                                     │
        test points  =  rule boundaries ∪ "$" amounts in the policy text ∪ model test cases
                                                     │
        at each point:  proposed rules │ model expectation │ reference │ target
                                                     │
        verification.py findings · levels L0–L3 · JSON evidence report
```

| Module | Role |
|---|---|
| `src/policyproof/muse_client.py` | Muse Spark Responses API client, prompt, response parsing, offline replay, provenance labels |
| `src/policyproof/schema.py` | Rule contract and validator: types, allowlists, verbatim evidence, threshold grounding |
| `src/policyproof/rule_engine.py` | Deterministic interpreter with full decision traces; independent boundary-point derivation |
| `src/policyproof/verification.py` | Four-perspective comparison, findings, verification levels, JSON report, CLI |
| `src/policyproof/viewer.py` | Renders a JSON report as a self-contained HTML evidence page (no JavaScript) |
| `src/policyproof/demo.py` | One-command offline demo: three verification runs plus linked evidence pages |
| `src/policyproof/target_search.py` | Seeded, budgeted search of the target between evaluated points, with edges located to the cent |
| `src/policyproof/reference.py` | Human-written reference for the fictional DemoCo meal policy |
| `examples/` | Synthetic DemoCo policy, example rules, and three engines: buggy at $40.00, fixed, and one with a loophole far from any policy threshold |
| `tests/fixtures/muse_democo_meal_response.json` | **Synthetic** Responses-API-shaped fixture for offline demos (not a real Muse output) |

## What is implemented today

- **Muse Spark client:**
  - talks to `https://api.meta.ai/v1/responses` with model `muse-spark-1.3`;
  - reads the key from `META_MUSE_API_KEY`;
  - handles refusals, error objects, incomplete responses and responses with several messages strictly;
  - can replay saved responses offline.
- **Proposal validation:**
  - closed JSON schema and exact decimal amounts;
  - each rule's evidence must be a verbatim, whole-word quote from the policy;
  - each dollar threshold must appear in that rule's own quote.
- **Deterministic interpreter:**
  - rules are evaluated in ascending priority, a rule's conditions all have to hold, and the first matching rule decides;
  - when no rule matches there is no decision, never a default approval;
  - every rule and condition is traced, so overlaps resolved only by priority stay visible.
- **Independent test points:**
  - boundaries derived from the rules;
  - `$` amounts found in the policy text, which probe thresholds the model may have left out;
  - the model's own test cases.
  - Each point records every source that produced it.
- **Target search:**
  - the target is a black box, so it can be wrong at amounts no rule mentions;
  - between the evaluated points, PolicyProof also tries round-number amounts and seeded samples, within a fixed call budget;
  - it then bisects to the exact cent where the target starts and stops disagreeing.
- **Findings and levels:**
  - confirmed, disputed or model-only target discrepancies (at a point, or across a range the search found), plus coverage gaps, precedence-dependent overlaps, unreachable rules, self-inconsistency and reference disagreement;
  - nested verification levels L0–L3, each with the reason it was or wasn't met.
- **Evidence report:** a deterministic JSON report with the policy hash, evidence quotes with their positions in the policy, point provenance, decision traces, every perspective's decision, the provenance label and the scope.
- **Evidence viewer:** a static HTML page rendered from that report. It has no JavaScript, escapes everything and recomputes nothing. A one-command offline demo produces the buggy, fixed and no-reference pages.

## Setup

**Requirements:**
- Python 3.12. Development used 3.12.14 and CI uses 3.12. The code needs at least 3.10 for its type syntax, but only 3.12 has been tested.
- Git.
- The only third-party dependency is `requests`, pinned in `requirements.txt`.

**Windows (PowerShell):**

```powershell
git clone https://github.com/mcthic-lab007/PolicyProof.git
cd PolicyProof
python -m venv .venv   # run this with your Python 3.12 interpreter
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

**macOS / Linux:** the same commands, but with `.venv/bin/python` in place of `.\.venv\Scripts\python.exe`.

Run every command from the repository root; modules are imported as `src.policyproof.*`.

## Offline demo (no API key, no network)

This demo uses the committed **synthetic** Muse-shaped fixture, the fictional DemoCo meal policy, the human-written reference, and an engine with a seeded bug: it rejects claims of exactly $40.00.

```powershell
.\.venv\Scripts\python.exe -m src.policyproof.verification examples/democo_meal_policy.txt --replay tests/fixtures/muse_democo_meal_response.json --reference democo-meal --target democo-buggy
```

Expected output, with exit code **3** (error-severity findings present):

```
REPLAY of a SYNTHETIC fixture: no API call was made and this is not Muse Spark output. Fixture note: Synthetic, hand-written in the Responses API shape for offline tests and demo replay. Not recorded from a live Muse Spark call.
Verification level: L2
  L0 met: The rules passed schema validation and evidence grounding, and the interpreter supports every construct they use.
  L1 met: 12 points executed; 0 without a decision; 7 of 7 model expectations agree; 0 precedence-dependent point(s) reported.
  L2 met: interpreted rules and reference agree at every evaluated point
  L3 not met: target does not agree with the reference at every evaluated point
Target execution: isolated worker process, 2 s per call, 1512 calls, 0 timeout(s), 0 crash(es), 0 skipped; not a security sandbox.
Target search: 1500 target calls (1500 probes, 0 bisection) of a budget of 2000, seed 20261104; 0 discrepancy range(s) found, 0 evaluation(s) not judged. Sampling, not exhaustive.
Source amounts probed: $40.00 (read from fixed_engine.py:9 evaluate_meal_claim(); parsed, not executed).
ERROR   TARGET_DISCREPANCY_CONFIRMED: The target decides REJECT at amount $40.00 with a service date. The independent reference and the executed proposed rules both decide APPROVE (rule democo-meal-approve-40, citing "Meal claims of $40.00 or less are approved automatically."). [point-40.00-dated]
INFO    CHECKED: All available perspectives agree at 11 of 12 point(s).
Not established: semantic correctness; see the report's scope and not_established.
Result: FAILED (exit code 3): error findings: a confirmed target discrepancy, a defect in the proposal, or part of the verification that could not run
```

How to read it:
- **One confirmed discrepancy**, at exactly $40.00 with a service date. The reference and the executed rules both decide APPROVE, and the buggy target decides REJECT.
- **All other 11 points agree**, including $39.99 and $40.01.
- **Level L2:** the proposed rules agree with the reference at every evaluated point. L3 isn't reached because the target doesn't.

Check the exit code with `$LASTEXITCODE` in PowerShell, or `echo $?` in bash.

**Compare with the fixed engine,** which reaches L3 and exits with **0**:

```powershell
.\.venv\Scripts\python.exe -m src.policyproof.verification examples/democo_meal_policy.txt --replay tests/fixtures/muse_democo_meal_response.json --reference democo-meal --target democo-fixed
```

**Write the full JSON evidence report:**

```powershell
.\.venv\Scripts\python.exe -m src.policyproof.verification examples/democo_meal_policy.txt --replay tests/fixtures/muse_democo_meal_response.json --reference democo-meal --target democo-buggy --report artifacts/demo-report.json
```

`artifacts/` is ignored by Git. The CLI refuses to replace an existing report unless you pass `--overwrite`.

**Without a reference,** omit `--reference`. The same $40.00 difference is then only `TARGET_DISCREPANCY_MODEL_ONLY`, because the only thing contradicting the target is the model's own rules.
- The level stops at L1.
- The run ends **INCONCLUSIVE with exit code 4**. That means unresolved: it is not evidence that the target is wrong, and it doesn't pass silently either.

Every run ends with a `Result:` line, and the report records the same verdict under `verification.result`. The exit codes, highest precedence first:

| Exit code | Result | Meaning |
|---|---|---|
| 1 | `ERROR` | The run couldn't complete (unreadable file, missing API key, refused overwrite, invalid option); no verification result |
| 2 | `REJECTED` | The proposal failed schema and evidence validation (`VALIDATION_REJECTED`). argparse usage errors also exit with 2 |
| 3 | `FAILED` | Error findings: a confirmed target discrepancy, a defect in the proposal (coverage gap, self-inconsistency), or part of the verification that couldn't run (for example a target that couldn't be evaluated) |
| 4 | `INCONCLUSIVE` | No error findings, but the target's correctness is unresolved: a disputed or model-only discrepancy, or the reference and the proposed rules disagree. **Not** evidence that the target is wrong |
| 5 | `INSUFFICIENT_EVIDENCE` | Only with `--require-level`: the run would otherwise be `OK`, but its verification level is below the required one |
| 0 | `OK` | No error and no unresolved finding at the evaluated points. Check the level for how independent that evidence is: without a reference, 0 comes with L1 at most |

If findings of several kinds are present, the highest-precedence code wins. For example, a confirmed discrepancy plus a disputed one gives 3.

**For CI, add `--require-level L3`.** By default, a run with no reference can exit 0 at level L1, which is backed only by the model's own rules. `--require-level L3` turns such a run into exit 5. It then passes only when an independent reference was given, the proposed rules agree with it, and the target agrees with it at every evaluated point.

A required level never changes any other result: a failed run stays 3 and an inconclusive one stays 4. Without the option, nothing changes. The report records the requirement and the level reached under `verification.result`.

### Finding bugs away from the policy's thresholds

The evaluated points come from the rules, the policy text and the model, never from the target. A target can therefore be wrong somewhere none of them points to. `democo-loophole` is correct at every policy threshold, but it approves dated claims from $1,000.00 to $4,999.99, which should be rejected:

```powershell
.\.venv\Scripts\python.exe -m src.policyproof.verification examples/democo_meal_policy.txt --replay tests/fixtures/muse_democo_meal_response.json --reference democo-meal --target democo-loophole
```

Exit code **3**. Abridged output:

```
Verification level: L2
  L3 not met: target search found 1 range(s) where the target disagrees
Target search: 1500 target calls (1500 probes, 0 bisection) of a budget of 2000, seed 20261104; 1 discrepancy range(s) found, 0 evaluation(s) not judged. Sampling, not exhaustive.
Source amounts probed: $40.00, $1000.00, $4999.99 (read from loophole_engine.py:13 evaluate_meal_claim(); parsed, not executed).
ERROR   TARGET_DISCREPANCY_CONFIRMED: Target search: the target disagrees with the reference at every one of 87 evaluated amounts from $1000.00 to $4999.99 with a service date. The lower edge is verified: it agrees at $999.99 and disagrees at $1000.00. The upper edge is verified: it agrees at $5000.00 and disagrees at $4999.99. At $1000.00 the target decides APPROVE; the independent reference and the executed proposed rules both decide REJECT (rule democo-meal-reject-above-40, citing "Meal claims above $40.00 are rejected."). Amounts between evaluated points were sampled, not all checked. [search-999.99-dated, search-1000.00-dated, search-4999.99-dated, search-5000.00-dated]
```

Add `--search-budget 0` to see the problem this solves: without the search, the same engine reaches **L3** with exit code 0.

In this demo, all four edge amounts are round-number probes (step 1 below), so no bisection was needed. The engine's edges fall on round numbers, so this demo does not show random sampling finding a loophole.

**How the search works.** It runs once with a service date and once without. It runs only when a target is given; without a target there is nothing to search.
1. **Round numbers:** it probes 1, 2, 2.5 and 5 × 10ᵏ dollars and one cent either side, where hand-written thresholds tend to sit.
2. **Seeded samples:** it probes whole-cent amounts spread across each power-of-ten band between neighbouring evaluated amounts. It uses only integer arithmetic, so the same seed gives the same amounts on every platform.
3. **Edges:** for every run of disagreeing amounts, it bisects against the nearest agreeing amount until the two are one cent apart. A reported edge is "verified" only when both sides were actually evaluated; otherwise it is given as an interval. This includes a discrepancy seen only at a boundary point. For example, a target that approves up to $40.01 is reported as a range from $40.01 to $40.01, with $40.00 and $40.02 shown as agreeing. Ranges the search found are bisected first, so this extra step never takes budget from them.

**Settings and cost:**
- `--search-budget N` caps target calls; the default is 2000, 0 turns the search off, and the maximum is 100000. A quarter of the budget is kept for bisection.
- `--search-seed S` changes the samples; the default is 20261104.
- The seed, budget, calls used and every range found are recorded under `target_search` in the JSON report.
- Measured in-process with the DemoCo engines: about 50–60 ms at the default budget, about 0.3 s at 10,000 and about 3.6 s at 100,000. With the CLI's default worker process (next section), a default-budget run takes about 0.4 s.

### Targets that hang or crash

The CLI runs the target in a separate worker process (`src/policyproof/target_worker.py`), never inside the verifier:
- **Timeouts:** a call that doesn't answer within `--target-timeout` seconds (default 2) is abandoned, and the worker is killed and restarted. The outcome is recorded as `timeout`.
- **Crashes:** a target that exits the process or writes garbage over the protocol is recorded as `worker_crash`.
- **Neither counts as a wrong decision.** A call that never finished is reported as **not evaluated** (`UNSUPPORTED`, an error, so exit 3), with its cause and a count per kind. A timeout can't tell a hang from a correct but slow target, and a dead worker can't tell a target bug from the environment. A discrepancy established by calls that did finish stays confirmed. Raise `--target-timeout` (at most 60 s) if your target is legitimately slow.
- **Total time limit:** `--target-time-limit` (default 120 s) caps the time spent on target calls. Calls after that are skipped, and reported as **not evaluated** (`UNSUPPORTED`), never as wrong.
- **Targets that can't start:** if the target can't even be imported, it's started once, and every point is reported as not evaluated.
- **Ctrl+C** stops the run and kills the worker.
- **`--target-timeout 0`** runs the target in-process, as before, with no timeout. The report's `target_execution` section records the mode, timeout, limit, calls, timeouts, crashes and skipped calls.

Measured on Windows:
- timeouts fire within about 15 ms of the configured value;
- a worker starts in about 0.1 s;
- one call takes about 0.1 ms;
- a target that hangs on every call, with a 0.5 s timeout and a 3 s limit, finished 2,000 calls in 3.1 s, leaving no worker process behind.

**Not a security sandbox.** The worker runs with your user's permissions and can read files, use the network or start processes. It isolates the verifier from hangs and crashes; it doesn't contain hostile code. The Muse API key variable is removed from the worker's environment.

**Exchange format:** each request and answer is one line of JSON, with amounts as decimal strings, so nothing is unpickled. The target's own `print` output can't corrupt the protocol.

**API users:** `verify(..., target_timeout=…)` needs the target's `Implementation` to have an `import_path` such as `"examples.loophole_engine:evaluate_meal_claim"`. Lambdas and nested functions can only run in-process, which is the default when `target_timeout` is omitted.

**Limits:**
- This is sampling, not proof. A bug confined to a few isolated amounts can be missed: a target wrong only at exactly $33.33 still reaches L3, while one wrong only at a round number such as $2,500.00 is found.
- Inside a reported range, only the listed evaluated amounts were checked. Two nearby ranges separated by an agreeing gap that no probe landed in are reported as one range.
- On the DemoCo loophole, the round-number probes land on both edges directly. On ranges with arbitrary edges, such as $1,234.56 to $4,321.09, the bisection step locates them; the tests check both.

## Evidence viewer demo (one command)

This command runs four scenarios through the same verification CLI and renders each JSON report as a readable HTML evidence page: the buggy target, the fixed target, the buggy target with no reference, and the loophole target.

```powershell
.\.venv\Scripts\python.exe -m src.policyproof.demo
```

It prints each verification run's output and exit code (3, 0, 4 and 3, as documented above), then the address of the main page. It writes `report-*.json` and `evidence-*.html` for each scenario to `artifacts/demo/`, which Git ignores. The command exits with 0 when everything was produced as documented.

Add `--open` to open the main page in your browser, or open `artifacts/demo/evidence-buggy.html` yourself. If the files already exist, the command refuses to replace them unless you pass `--overwrite`. Use `--output-dir DIR` to write somewhere else.

The main page shows, without any raw JSON:
- the provenance label;
- the verification level and why each level was or wasn't met;
- the confirmed $40.00 finding, with the reference, executed rules, target and model's expectation side by side;
- the evidence chain: the policy quote and its position, the rule and threshold, and why this point was tested;
- the rule-by-rule trace;
- the precedence assumption, and the fact that the reference shares it;
- what the result doesn't establish;
- the run's result (`OK`, `FAILED`, `INCONCLUSIVE`, …) with its exit code;
- how the target was run, and what the target search covered;
- for discrepancy ranges, the exact edges and whether each was verified;
- for disputed findings, why they couldn't be confirmed;
- links to the other three runs.

To render any report yourself:

```powershell
.\.venv\Scripts\python.exe -m src.policyproof.viewer artifacts/demo-report.json --output artifacts/demo-report.html
```

The viewer only displays the report; it never recalculates findings or levels. Every value from the report is HTML-escaped. The page contains no JavaScript, and its Content Security Policy blocks scripts and remote resources, so policy or model text can't run and the page makes no network requests.

## Reading the results

### Findings

| Finding | Meaning |
|---|---|
| `TARGET_DISCREPANCY_CONFIRMED` | At this point the target differs from the reference, the executed proposed rules agree with the reference, **and** none of the proposal's own test cases at this point expects something else. For a range found by the target search, this holds at every evaluated amount in the range |
| `TARGET_DISCREPANCY_DISPUTED` | The target differs from the reference, but either the proposed rules disagree with the reference, or the proposal's own expected decision at that point contradicts it. The details list which, in `disputed_because`, with every perspective's decision. A person must decide |
| `TARGET_DISCREPANCY_MODEL_ONLY` | There's no usable reference; the target differs from the proposed rules only. Not independent evidence |
| `REFERENCE_DISAGREEMENT` | The proposed rules and the reference decide differently: two interpretations conflict |
| `SELF_INCONSISTENT` | The proposal's own test case contradicts its own rules |
| `COVERAGE_GAP` | No proposed rule decides this point |
| `PRECEDENCE_DEPENDENT` | Several rules match with different decisions and priority alone picks the result. It's `info` when the proposal records this as an assumption and no reference contradicts it, otherwise `warning`. Not a defect in itself |
| `UNREACHABLE_RULE` | A rule never decides any input in the domain |
| `VALIDATION_REJECTED` / `UNSUPPORTED` | The proposal failed validation, or something couldn't be evaluated |
| `CHECKED` | Every available perspective agreed |

### Verification levels

Each level requires the ones below it. Levels show how far the evidence reaches; they are not a quality grade.

| Level | Meaning |
|---|---|
| L0 | The rules passed schema validation and evidence grounding against this policy text, and the interpreter supports them |
| L1 | The rules decide every evaluated point and agree with every model expectation; overlaps are reported |
| L2 | An independent reference was supplied, and the proposed rules agree with it at every evaluated point |
| L3 | A target was supplied; it agrees with the reference at every evaluated point, and the target search found no range where it disagrees |

### What these results do not claim

- **No level states semantic correctness.** PolicyProof shows agreement between perspectives at specific inputs. It does not show that anyone has read the policy as its author intended.
- **Confirmations are per point.** A confirmed discrepancy means that, *at that input*, two independent perspectives agree and the target differs. The proposed rules can still be wrong elsewhere; the level and the other findings show that.
- **The model can withhold a confirmation, never create one.** If the proposal's own test case at a point contradicts the reference, the model disagrees with itself there, so a discrepancy at that point is only `DISPUTED`. This catches a shared misreading: a reference and rules that both misread "$40.00 or less" would otherwise "confirm" a bug in a correct target. Two judgement calls remain:
  - when the model's expectation, the reference and the target all decide differently, PolicyProof still chooses `DISPUTED`, the conservative option;
  - a disagreement between the reference and the rules, on its own, makes the run `INCONCLUSIVE`, because the policy's interpretation is unresolved.
- **The reference shares an assumption.** The DemoCo policy never says whether "missing service date → review" takes precedence over "$40.00 or less → approve". The reference (`src/policyproof/reference.py`) and the proposed rules both *assume* it does. On undated claims, their agreement isn't independent evidence on that question, and PolicyProof reports it as a precedence assumption.
- **Scope of L2 and L3.** For the rule document, the derived boundary points cover every distinct behaviour it has within the domain: whole-cent amounts from 0.00 to 1,000,000.00, with and without a service date. The reference is checked only at the evaluated points. The target is checked there, plus at the amounts the target search sampled. Neither is checked at every amount, so L3 is strong evidence within a budget, not a proof.

## Live mode (optional)

Live mode calls Meta's API. It needs a key in the `META_MUSE_API_KEY` environment variable, it sends the policy text to Meta, and it may be billed.

To avoid leaving the key in PowerShell history, enter it at a hidden prompt rather than on the command line:

```powershell
$env:META_MUSE_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR((Read-Host -AsSecureString "Muse key")))
.\.venv\Scripts\python.exe -m src.policyproof.verification examples/democo_meal_policy.txt --live --reference democo-meal --target democo-buggy
.\.venv\Scripts\python.exe -m src.policyproof.muse_client examples/democo_meal_policy.txt --save-response artifacts/muse_live_001.json
Remove-Item Env:META_MUSE_API_KEY
```

You can then replay a saved response offline with `--replay artifacts/muse_live_001.json`.

During development, one live `muse-spark-1.3` call produced 3 rules and 6 test cases, and the validator accepted them. Replayed, they confirm the same $40.00 discrepancy, plus two `PRECEDENCE_DEPENDENT` findings: Muse's amount rules omit the date condition and rely on the review rule's priority, and Muse recorded that as an assumption. That saved response is **not** in this repository. The documented demo uses the synthetic fixture so anyone can reproduce it.

## Security and provenance

- **API key handling:**
  - the key is read only from `META_MUSE_API_KEY`;
  - it must be visible ASCII and is never echoed;
  - errors are redacted and carry no underlying exception, so request headers can't appear in tracebacks;
  - the tests use only fake keys.
- **No dynamic execution.** Model output is parsed as data and checked against allowlists; there is no `eval`, `exec` or generated code. Tests check this by parsing the source.
- **Allowlisted targets only.** `--reference` and `--target` accept fixed names (`democo-meal`, `democo-buggy`, `democo-fixed`, `democo-loophole`) that map to local code. Nothing proposed by the model is ever executed.
- **Target failures are recorded, not fatal:**
  - a target that raises an exception, calls `sys.exit()` or returns something other than a decision has answered, and is recorded as disagreeing at that input;
  - a call that never finished (it timed out, its worker crashed, the time limit was reached, or the target can't be imported) is recorded as not evaluated, never as a wrong decision;
  - Ctrl+C stops the run.
  - In the worker, a `KeyboardInterrupt` raised by the target itself only ends that worker and is reported as a crash.
- **Provenance labels.** Every result is labelled `LIVE`, `REPLAY_SAVED_LIVE_RESPONSE`, `REPLAY_SYNTHETIC` or `REPLAY_UNKNOWN_ORIGIN`. The labels come from the call path or the file and are **not** cryptographic proof of origin.
- **Policy text is untrusted.** In the prompt it's fenced as data. Instructions inside it can't make a rule cite text that isn't in the policy, or a threshold the policy doesn't state, because validation would reject it.
- **What the report contains:** a hash of the policy, not its text. It does include evidence quotes and rule descriptions, which are excerpts of the policy, so treat reports like the policy itself.
- **Data retention:** the live response received during development reported `"store": true`. Use synthetic policies with live mode.
- **Git exclusions:** `.gitignore` excludes `.env*` (except `.env.example`), `.venv/`, caches and `artifacts/`, where live responses and reports are saved.

## Limitations and non-goals

- **Schema:** it has two fields, `amount` and `has_service_date`. One fictional policy is included.
- **Policy-text thresholds:** only `$` amounts are recognised (not "40 dollars", other currencies or percentages), and at most 100 distinct amounts are used. Finding none doesn't prove the policy has no other thresholds.
- **One reference:** a human-written reference exists only for the DemoCo policy. Without a reference, verification stops at L1.
- **Target execution:** by default the CLI runs the target in a worker process with a per-call timeout and a total time limit. That protects the verifier from hangs and crashes, but it isn't a security sandbox, so only trusted local code can be selected.
  - The reference still runs in-process.
  - Worker isolation has been tested on Windows only; CI covers Linux once the branch is pushed.
  - **Timeouts are not evaluations.** Until 2026-10-28, a correct target slower than `--target-timeout` was falsely accused. Now a timed-out call is reported as not evaluated: the run exits 3, below L3, and is never confirmed as wrong. The trade-off is that a target that genuinely hangs is no longer *confirmed* wrong at that input; it is reported as unfinished instead. Exit-code change: with no reference, a hang used to exit 4 (`TARGET_DISCREPANCY_MODEL_ONLY`) and now exits 3 (`UNSUPPORTED`). Exceptions and non-decision return values still count as the target's answer and can be confirmed; the failure kind is recorded with the finding.
- **Target search:** it samples within a budget, as described above, and can miss isolated faulty amounts. In the [benchmark](docs/BENCHMARK.md), a single wrong cent and a 33-cent range were missed in all 40 search-enabled runs (budgets 250 to 8000, 10 seeds each). A discrepancy found at an evaluated point is bisected to its edges like any other range, as long as the search budget isn't 0. A verified edge means both cents were evaluated; amounts inside a range are sampled, not all checked. Search calls that cannot be judged (for example, skipped by the time limit) produce an error finding and block L3.
- **Live API contract:** the request and success-response shape were confirmed by one live call. Refusal, error and incomplete-response shapes follow the OpenAI-compatible format and haven't been seen live. The client makes no retries and the 120-second timeout applies per read, not to the whole request.
- **Legacy modules:** `verifier.py`, `reporting.py` and `generator.py` are the original prototype and are kept for their existing tests.
- **Non-goals:**
  - proving that a policy is correct or complete;
  - replacing human judgement about how a policy should be interpreted;
  - running untrusted code;
  - processing confidential policies.

## Benchmark

`python -m benchmark.run` scores PolicyProof against a 27-case ground-truth corpus of correct, defective and failing targets and evidence scenarios. See [docs/BENCHMARK.md](docs/BENCHMARK.md) for the design, metrics, results and limitations. Current results on corpus v2: no false accusations (0/8), 12 of 15 defects confirmed, 25 of 27 exit codes as expected. A target that hangs is reported as unfinished rather than confirmed wrong; see the benchmark's corpus v2 section.

What was built during the hackathon, and how Muse Spark is used, is documented in [docs/HACKATHON_CONTRIBUTIONS.md](docs/HACKATHON_CONTRIBUTIONS.md).

## Running the tests

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -t . -v
```

The suite has 373 tests, and none of them call the network. Two of them replay the saved live response in `artifacts/muse_live_001.json`, which is local and ignored by Git. They run only where that file exists. On a fresh clone and in CI they are reported as skipped (`OK (skipped=2)`); they never pass silently.

GitHub Actions (`.github/workflows/tests.yml`) runs the same command on Python 3.12 for every push and pull request.

## Roadmap

**Implemented:**
- the Muse Spark client and offline replay;
- strict, grounded validation;
- the deterministic interpreter and boundary derivation;
- four-perspective verification with findings and levels;
- budgeted target search with edges located to the cent;
- worker-process target execution with per-call timeouts and a total time limit;
- the JSON evidence report;
- the HTML evidence viewer and the one-command offline demo;
- the allowlisted CLI;
- CI.

**Not implemented (future work):**
- richer rule schemas (more fields and types), and a second, more complex synthetic policy;
- running targets in a real security sandbox, for example a remote, isolated environment. Hang and crash isolation already exists; containment of hostile code doesn't;
- several Muse runs per policy, to measure how stable its interpretation is;
- recognising thresholds beyond `$` amounts in the policy text.
