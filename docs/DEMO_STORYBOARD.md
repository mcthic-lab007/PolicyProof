# Three-minute demo storyboard

Status: **revised 2026-11-04 for the release on `master`. Not yet recorded or rehearsed.** Every shot must be real recorded product behaviour. The expected outputs below were checked on the release commit on 2026-11-04 with the offline fixture or a saved live response. No live call was made for this revision.

Causal chain the video must show: **Muse proposal → independent verification → adversarial counterexample → comparison with the fixed implementation → where Muse adds something the deterministic analyzers do not → inspectable evidence.**

Common prefix for the commands (PowerShell, repository root):

```powershell
$py = ".\.venv\Scripts\python.exe"; $pol = "examples/democo_meal_policy.txt"; $fx = "tests/fixtures/muse_democo_meal_response.json"
```

| Time | Visual / interaction | Narration (draft) | Evidence shown (checked 2026-11-04) | Fallback |
|---|---|---|---|---|
| 0:00–0:15 | The policy text file (three short rules) | "Policies are written in prose. The software that enforces them is written in code. When the two disagree, nobody notices until money moves." | `examples/democo_meal_policy.txt` | None needed |
| 0:15–0:45 | **Only if a live call is authorized for the recording:** `& $py -m src.policyproof.verification $pol --live --reference democo-meal --target democo-buggy --save-response artifacts/video/rec-live.json --report artifacts/video/rec-buggy.json`, first output line in view | "Meta's Muse Spark reads the policy and proposes machine-checkable rules, each quoting the sentence it came from. This is a live call." | First line: `LIVE: Muse Spark API response (muse-spark-1.3, response id …)` | **Without authorization, or if the call fails:** `--replay evidence/live/muse_live_002.json` instead of `--live …`. Say "this is Muse's answer from a live call on October 31st, replayed". The screen shows `REPLAY of a saved response: no API call was made now`. Never call that live. |
| 0:45–1:10 | The same output, scrolled to the findings | "PolicyProof doesn't trust Muse. It re-validates every quote, runs the rules in its own interpreter, and tests one cent either side of every threshold. The buggy engine rejects exactly $40.00, which the policy approves. A test at $39.99 and $41 would pass." | `ERROR TARGET_DISCREPANCY_CONFIRMED` at $40.00; `Source amounts probed: $40.00 (read from buggy_engine.py:6 …)`; `Verification level: L2`; exit code 3 | A take of the same command recorded earlier |
| 1:10–1:40 | The loophole engine, twice: `& $py -m src.policyproof.verification $pol --replay $fx --reference democo-meal --target democo-loophole --search-budget 0`, then without `--search-budget 0` | "This engine passes every threshold test. With search off, it looks perfect. With search on, PolicyProof probes round numbers, the amounts written in the engine's own code (it reads the code, never runs it), and seeded samples. It pins a loophole to the cent: $1,000.00 to $4,999.99 gets approved." | Budget 0: L3, exit 0. Default: L2, exit 3; `Source amounts probed: $40.00, $1000.00, $4999.99`; a discrepancy at every one of 88 evaluated amounts from $1,000.00 to $4,999.99 | **Narration must not overclaim.** The edges come from the ladder and the source probes (0 bisection calls), not from random sampling. "Verified edge" means both cents were run; the amounts inside were sampled, not all checked. |
| 1:40–1:55 | The fixed engine: `--replay $fx --reference democo-meal --target democo-fixed` | "The fix passes at level L3: the rules, an independent human reference and the target agree at every evaluated point, plus 1,500 sampled amounts. That is sampling, not proof." | `Verification level: L3`, exit 0 | A take recorded earlier |
| 1:55–2:25 | **Where Muse adds something.** (1) `benchmark/targets_v3.py`, `loop_assembled_cent` and the loop that builds `_LOOP_EDGE`. (2) `evidence/live/muse_probes_v3/loop-assembled-cent.trial-1.json`, scrolled to the answer. (3) The v3 table in `docs/BENCHMARK.md` | "This engine is deliberately artificial: the special amount is built by a loop, so no constant in the code equals it. Our deterministic analyzers don't find it. On November 1st, Muse read this code and proposed $1,500.07. PolicyProof ran the engine and the reference there and confirmed a one-cent bug. Across the v3 corpus, our best deterministic baseline finds 17 of 21 defects; with Muse's proposals, 19, with no false accusations. That is one response per target, so we don't claim a rate." | The saved answer reads `{"amount": "1500.07", "reason": "LOOP_EDGE sum tiers plus 0.07 approved vs reject"}` (response `resp_6ae73c75261e9d5dd2ef4fbd`). v3: E+G+H 17/21, E+G+H+Muse 19/21. The file view is a saved live response, not a live call: say "on November 1st" | Show the same files as stills |
| 2:25–2:45 | The evidence viewer: `& $py -m src.policyproof.demo --open` | "Every conclusion is inspectable: which rule, which quote, which inputs, who said what, and what we can't establish." | The HTML page: headline, findings at $40.00, edges, the "not established" list. No scripts; strict content-security policy | The pages already rendered in `artifacts/demo/` |
| 2:45–3:00 | The README "Results at a glance" table, then `docs/HACKATHON_CONTRIBUTIONS.md` | "We benchmark the verifier itself on frozen synthetic corpora: on the main one, 14 of 15 defects confirmed and no correct engine accused. Muse proposes; PolicyProof verifies. It was built during the hackathon with AI coding assistants, and the contribution record lists every piece and its evidence." | v2: 14/15, 0/8 accused, 27/27 exit codes. The inventory table | None |

**Why this Muse beat and not the earlier pilot:** the 2026-10-31 pilot (`resp_6ae5b0b5ee523841844848fd`) proposed the computed edges $2,000.37 and $2,000.52, but deterministic constant folding (method E) finds the same edges without a model. Do not use it as evidence that Muse adds anything.

**Lines not to say:**
- That Muse is generally better than code analysis, or that PolicyProof finds every loophole.
- That the replayed or saved responses are live.
- Any rate for Muse: it is one response per target, on synthetic engines.

## Before recording

- [ ] **Live take** (only with the author's explicit authorization; it is a billed call): `META_MUSE_API_KEY` set in the recording shell only, not on screen, not in history and not in the report. Check that the first output line reads `LIVE:`.
- [ ] Live output may differ from the saved response, because the model is not deterministic. Check that the $40.00 discrepancy still appears, and narrate what actually happens.
- [ ] **Do not present `artifacts/video/live-*.txt` as live footage.** They are replays of a saved response, and their own first line says so.
- [ ] `evidence/live/live-002-output.txt` is the real terminal output of the 2026-10-31 live run (first line `LIVE:`, L2, exit 3). It is text, not a screen recording, so it can be shown only as a saved record of a live run. It predates the byte-order-mark fix, so its `Source amounts probed` line shows a parse error that current code no longer prints.
- [ ] Rehearse the whole sequence twice with the offline commands; time it at 3:00 or under.
- [ ] Provenance: the closing line says "built during the hackathon". HACKATHON_CONTRIBUTIONS.md dates all of `496bc75` to 2026-10-27, but the tool that wrote the seven-file prototype is still unnamed. The author should name it there, or the line should leave the prototype out.
- [ ] Re-check the submission form's video requirements (length, hosting) before uploading.
