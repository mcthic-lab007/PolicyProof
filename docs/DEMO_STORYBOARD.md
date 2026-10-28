# Three-minute demo storyboard

Status: **draft, revised 2026-10-28 (fourth session). Not yet recorded or rehearsed.** Update this file whenever the product changes. Every shot must be real recorded product behaviour.

Causal chain the video must show: **Muse proposal → independent verification → adversarial counterexample → comparison with the fixed implementation → inspectable evidence.**

Common prefix for the commands (PowerShell, repository root):

```powershell
$py = ".\.venv\Scripts\python.exe"; $pol = "examples/democo_meal_policy.txt"
```

| Time | Visual / interaction | Narration (draft) | Evidence shown | Fallback |
|---|---|---|---|---|
| 0:00–0:15 | The policy text file (three short rules) | "Policies are written in prose. The software that enforces them is written in code. When the two disagree, nobody notices until money moves." | `examples/democo_meal_policy.txt` | None needed |
| 0:15–0:45 | `& $py -m src.policyproof.verification $pol --live --reference democo-meal --target democo-buggy --report artifacts/video/rec-buggy.json` with the first output line in view | "Meta's Muse Spark reads the policy and proposes machine-checkable rules, each quoting the sentence it came from. This is a live call." | First line: `LIVE: Muse Spark API response (muse-spark-1.3, response id …)` | No key or quota: run with `--replay artifacts/muse_live_001.json` and **say "recorded earlier today from a live call"**. The screen then shows `REPLAY of a saved response`. Never call that live. |
| 0:45–1:15 | The same output, scrolled to the findings | "PolicyProof doesn't trust Muse. It re-validates every quote, runs the rules in its own interpreter, and tests one cent either side of every threshold. The buggy engine rejects exactly $40.00, which the policy approves. A test at $39.99 and $41 would pass." | `ERROR TARGET_DISCREPANCY_CONFIRMED` at $40.00 citing "Meal claims of $40.00 or less…"; exit code 3 | Use a pre-recorded terminal take of the same command |
| 1:15–1:50 | The loophole engine, twice: first with `--search-budget 0` (exit 0, L3), then the default | "This engine passes every threshold test. With search off, it looks perfect. With search on, PolicyProof probes round numbers, the amounts written in the engine's own code (it reads the code, never runs it), and seeded samples. It pins a loophole to the cent: $1,000.00 to $4,999.99 gets approved." | Exit 0 vs exit 3; the `Source amounts probed: $40.00, $1000.00, $4999.99` line; range with verified edges $999.99/$1,000.00 and $4,999.99/$5,000.00. Say: "verified edge" means both cents were run; the 88 amounts inside were sampled, not all checked | **Narration must not overclaim.** These edges are hit by the ladder and the source probes, not by random sampling (0 bisection calls). Do not say "it would find any loophole". |
| 1:50–2:05 | The fixed engine (`--target democo-fixed`) | "The fix passes at level L3: rules, an independent human reference and the target agree at every evaluated point, plus 1,500 sampled amounts. That is sampling, not proof." | Exit 0, `Verification level: L3` | Pre-recorded take |
| 2:05–2:30 | The evidence viewer in a browser (`python -m src.policyproof.demo --open`) | "Every conclusion is inspectable: which rule, which quote, which inputs, who said what, and what we can't establish." | The HTML page: headline, edges, the "not established" list | Show the static `artifacts/demo/evidence-*.html` already rendered |
| 2:30–2:50 | `docs/BENCHMARK.md` results tables | "We benchmarked the verifier itself against 27 seeded cases. Zero false accusations. 14 of 15 defects confirmed, each pinned to the cent. One-cent and 33-cent bugs far from any threshold were invisible to sampling, 0 of 40 runs. Reading the amounts written in the target's code finds them in 40 of 40, and a probe is still only a place to look. A bug at a computed amount is still found in only 1 of 10 seeds, and we say so. A hang is reported as unfinished, never as wrong." | Corpus v2: narrow literal defects 0/40 → 40/40; detection 12/15 → 14/15; false accusations 0/8; the computed-range miss | Same, as a static slide made from the file |
| 2:50–3:00 | `docs/HACKATHON_CONTRIBUTIONS.md` | "Muse proposes; PolicyProof verifies. All of this was built during the hackathon, with AI coding assistants, and the contribution log lists each piece and its evidence." | The inventory table and the provenance section | None |

**Possible addition, only if a live run succeeds:** a shot of Muse Spark reading the computed-range engine and proposing $2,000.37, followed by PolicyProof confirming the range. It would show Muse doing what literal mining can't. Use it only with a real saved live response, labelled REPLAY if it is replayed. If Muse doesn't find it, say so or leave the shot out. Today no such run exists.

## Before recording

- [ ] **Live take:** `META_MUSE_API_KEY` set in the recording shell only; not on screen, not in history and not in the report. Check that the first output line reads `LIVE:`.
- [ ] Live output may differ from the saved response, because the model is not deterministic. Re-check that the $40.00 discrepancy still appears, and narrate what actually happens.
- [ ] **Do not use the files in `artifacts/video/live-*.txt` as live footage.** They are **replays** of the saved response; their own first line says so.
- [ ] Re-verify the Meta API requirements and the hackathon rules (permitted models, attribution) against the official sources on the recording day.
- [ ] Provenance: records outside Git date all of `496bc75` to 2026-10-27 (see HACKATHON_CONTRIBUTIONS.md). Before saying the closing line, the author confirms it and names the tool that wrote the prototype.
- [ ] Time the full run-through and keep it at 3:00 or under.
