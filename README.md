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
| `src/policyproof/reference.py` | Human-written reference for the fictional DemoCo meal policy |
| `examples/` | Synthetic DemoCo policy, example rules, a deliberately buggy engine and a fixed engine |
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
- **Findings and levels:**
  - confirmed, disputed or model-only target discrepancies, plus coverage gaps, precedence-dependent overlaps, unreachable rules, self-inconsistency and reference disagreement;
  - nested verification levels L0–L3, each with the reason it was or wasn't met.
- **Evidence report:** a deterministic JSON report with the policy hash, evidence quotes with their positions in the policy, point provenance, decision traces, every perspective's decision, the provenance label and the scope.

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
ERROR   TARGET_DISCREPANCY_CONFIRMED: The target decides REJECT at amount $40.00 with a service date. The independent reference and the executed proposed rules both decide APPROVE (rule democo-meal-approve-40, citing "Meal claims of $40.00 or less are approved automatically."). [point-40.00-dated]
INFO    CHECKED: All available perspectives agree at 11 of 12 point(s).
Not established: semantic correctness; see the report's scope and not_established.
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

**Without a reference,** omit `--reference`. The same $40.00 difference is then only `TARGET_DISCREPANCY_MODEL_ONLY`, a warning, because the only thing contradicting the target is the model's own rules. The level stops at L1, and the exit code is 0, since only error-severity findings set exit code 3.

| Exit code | Meaning |
|---|---|
| 0 | Verification ran; no error-severity findings |
| 1 | Operational error (unreadable file, missing API key, refused overwrite, …) |
| 2 | The proposal was rejected by validation (`VALIDATION_REJECTED`); also used by argparse for invalid arguments |
| 3 | Verification ran and produced error-severity findings (for example a confirmed discrepancy) |

## Reading the results

### Findings

| Finding | Meaning |
|---|---|
| `TARGET_DISCREPANCY_CONFIRMED` | At this point the target differs from the reference, **and** the reference and the executed proposed rules agree |
| `TARGET_DISCREPANCY_DISPUTED` | The target differs from the reference, but the reference and the proposed rules disagree, so a person must decide |
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
| L3 | A target was supplied, and it agrees with the reference at every evaluated point |

### What these results do not claim

- **No level states semantic correctness.** PolicyProof shows agreement between perspectives at specific inputs. It does not show that anyone has read the policy as its author intended.
- **Confirmations are per point.** A confirmed discrepancy means that, *at that input*, two independent perspectives agree and the target differs. The proposed rules can still be wrong elsewhere; the level and the other findings show that.
- **The reference shares an assumption.** The DemoCo policy never says whether "missing service date → review" takes precedence over "$40.00 or less → approve". The reference (`src/policyproof/reference.py`) and the proposed rules both *assume* it does. On undated claims, their agreement isn't independent evidence on that question, and PolicyProof reports it as a precedence assumption.
- **Scope of L2 and L3.** For the rule document, the derived boundary points cover every distinct behaviour it has within the domain: whole-cent amounts from 0.00 to 1,000,000.00, with and without a service date. The reference and the target are checked only at the evaluated points; their behaviour between those points isn't tested.

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
- **Allowlisted targets only.** `--reference` and `--target` accept fixed names (`democo-meal`, `democo-buggy`, `democo-fixed`) that map to local code. Nothing proposed by the model is ever executed.
- **Provenance labels.** Every result is labelled `LIVE`, `REPLAY_SAVED_LIVE_RESPONSE`, `REPLAY_SYNTHETIC` or `REPLAY_UNKNOWN_ORIGIN`. The labels come from the call path or the file and are **not** cryptographic proof of origin.
- **Policy text is untrusted.** In the prompt it's fenced as data. Instructions inside it can't make a rule cite text that isn't in the policy, or a threshold the policy doesn't state, because validation would reject it.
- **What the report contains:** a hash of the policy, not its text. It does include evidence quotes and rule descriptions, which are excerpts of the policy, so treat reports like the policy itself.
- **Data retention:** the live response received during development reported `"store": true`. Use synthetic policies with live mode.
- **Git exclusions:** `.gitignore` excludes `.env*` (except `.env.example`), `.venv/`, caches and `artifacts/`, where live responses and reports are saved.

## Limitations and non-goals

- **Schema:** it has two fields, `amount` and `has_service_date`. One fictional policy is included.
- **Policy-text thresholds:** only `$` amounts are recognised (not "40 dollars", other currencies or percentages), and at most 100 distinct amounts are used. Finding none doesn't prove the policy has no other thresholds.
- **One reference:** a human-written reference exists only for the DemoCo policy. Without a reference, verification stops at L1.
- **Target execution:** targets run in-process. There is no sandbox and no protection against hangs, so only trusted local code can be selected.
- **Live API contract:** the request and success-response shape were confirmed by one live call. Refusal, error and incomplete-response shapes follow the OpenAI-compatible format and haven't been seen live. The client makes no retries and the 120-second timeout applies per read, not to the whole request.
- **Legacy modules:** `verifier.py`, `reporting.py` and `generator.py` are the original prototype and are kept for their existing tests.
- **Non-goals:**
  - proving that a policy is correct or complete;
  - replacing human judgement about how a policy should be interpreted;
  - running untrusted code;
  - processing confidential policies.

## Running the tests

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -t . -v
```

The suite has 257 tests, and none of them call the network. Two of them replay the saved live response in `artifacts/muse_live_001.json`, which is local and ignored by Git. They run only where that file exists. On a fresh clone and in CI they are reported as skipped (`OK (skipped=2)`); they never pass silently.

GitHub Actions (`.github/workflows/tests.yml`) runs the same command on Python 3.12 for every push and pull request.

## Roadmap

**Implemented:**
- the Muse Spark client and offline replay;
- strict, grounded validation;
- the deterministic interpreter and boundary derivation;
- four-perspective verification with findings and levels;
- the JSON evidence report;
- the allowlisted CLI;
- CI.

**Not implemented (future work):**
- richer rule schemas (more fields and types), and a second, more complex synthetic policy;
- running targets in a sandbox (for example a remote, isolated environment) with timeouts;
- several Muse runs per policy, to measure how stable its interpretation is;
- a human-readable HTML report alongside the JSON;
- recognising thresholds beyond `$` amounts in the policy text.
