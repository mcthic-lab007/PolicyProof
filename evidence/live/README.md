# Saved live Muse Spark responses

These are the raw responses from every live `muse-spark-1.3` call made during the hackathon: nine calls, nine distinct response ids. They are byte-identical copies of files that were saved, git-ignored, under `artifacts/` at the time of each call. They were published here on 2026-11-04 after a review:
- The API key appears in none of them (searched for the full key and its last eight characters).
- No local paths, user names, e-mail addresses or account fields were found.
- What they contain is the synthetic DemoCo policy or a benchmark target excerpt (both already in this repository), the request settings, Muse's output and the usage record.

These files are evidence that the calls happened and what Muse answered. They are **not** cryptographic proof of origin: anyone could write a file in this shape. The response ids, timestamps and usage come from Meta's API response as received.

Anything computed from these files now is a replay. PolicyProof labels it `REPLAY_SAVED_LIVE_RESPONSE`, never `LIVE`.

| File | Response id | Created (UTC, from the API) | Call | What it was used for |
|---|---|---|---|---|
| `muse_live_001.json` | `resp_6ae0bf2955b662d487a44ecb` | 2026-10-27 15:11:37 | `muse_client --save-response` | Rules and test cases for the DemoCo policy |
| `muse_probes/narrow-computed-range.trial-1.json` | `resp_6ae5b0b5ee523841844848fd` | 2026-10-31 09:11:17 | `benchmark.muse_probes record` (pilot) | Probe amounts for one corpus v2 target |
| `muse_live_002.json` | `resp_6ae63743a8b7a612db3b4fc2` | 2026-10-31 18:45:23 | `verification --live --save-response` | Live verification run; report `live-002-report.json`, terminal output `live-002-output.txt` |
| `muse_probes_v3/loop-assembled-cent.trial-1.json` | `resp_6ae73c75261e9d5dd2ef4fbd` | 2026-11-01 13:19:49 | `benchmark.muse_probes record --corpus 3` | Proposed $1,500.07 |
| `muse_probes_v3/converted-rounding-window.trial-1.json` | `resp_6ae73c850ffb802a50e14920` | 2026-11-01 13:20:05 | same | Proposed $2,007.49 and $2,008.57 |
| `muse_probes_v3/imported-constant-cent.trial-1.json` | `resp_6ae73c9b3e231cc83d62493e` | 2026-11-01 13:20:27 | same | `incomplete`: hit the output cap, no proposals |
| `muse_probes_v3/helper-computed-range.trial-1.json` | `resp_6ae73ca765f153802e3d4b3e` | 2026-11-01 13:20:39 | same | Probe amounts |
| `muse_probes_v3/encoded-string-range.trial-1.json` | `resp_6ae73cb09a41e7ddb3774076` | 2026-11-01 13:20:48 | same | Probe amounts |
| `muse_probes_v3/integer-cents-table.trial-1.json` | `resp_6ae73cb9900612e4424a4bc9` | 2026-11-01 13:20:57 | same | Probe amounts |
| `muse_probes_v3/cost-ledger.json` | — | — | written by the harness | Per-call token bounds, usage and the estimated cost of the six v3 calls |

## Replaying them

```powershell
# Live verification run, replayed: prints "REPLAY of a saved response" and exits 3
.\.venv\Scripts\python.exe -m src.policyproof.verification examples/democo_meal_policy.txt --replay evidence/live/muse_live_002.json --reference democo-meal --target democo-buggy
```

The probe harness expects its original directory layout (`<target-module>-<target>/trial-1.json`). To score the v3 responses offline, copy them back into that layout, for example `evidence/live/muse_probes_v3/loop-assembled-cent.trial-1.json` → `artifacts/muse_probes_v3/benchmark-targets-v3-loop-assembled-cent/trial-1.json`, then run `python -m benchmark.muse_probes sweep --corpus 3 --output artifacts/benchmark/muse-v3-sweep.json`.

## SHA-256

```
d5e0af8eb1728834016c740c9babe7c43b54d47fd440806f93d3b82275525355  muse_live_001.json
f81c3ab8aea2c3ec965e89b3f4582f260c583bdfed3f39223a362629e67fd665  muse_live_002.json
b56ebc8c3ea1c978b7890f9d3e6381254bbdf19b2c2b1c4ae60255a32d013bba  live-002-report.json
caf0d4d03d8f4464e9c2efeea000ff43e4b9d52249d566345db6651976f47f70  live-002-output.txt
0f3ecfd3a123ab659f221787d674d98f43f6adcad36d43bf8c36590f2674f74f  muse_probes/narrow-computed-range.trial-1.json
282e134a7be1b48d2efc67b0abc8476e953ca4368c1ff2df29f9e766ad1b54c4  muse_probes_v3/loop-assembled-cent.trial-1.json
1a70524064248e3c1eefb9c006527226d923094ec677aa6418c3fb93bb817432  muse_probes_v3/converted-rounding-window.trial-1.json
48bf6e2528e1dd5a24e218e6583188546c7ddbec26b5a9189ed87781ef5ea23a  muse_probes_v3/imported-constant-cent.trial-1.json
8ad56cb0874930ff2aa337e5f66a52bd601bcdd775ceecd9f1912ad525f0d024  muse_probes_v3/helper-computed-range.trial-1.json
0152d8b745174f17d6c9bdd5dbad5edf6778327676c3cb9693e66595a92d4350  muse_probes_v3/encoded-string-range.trial-1.json
ec88b08135a17e03f1924af95eb9f9e65bac780ee641391af8d57d57555b7bf1  muse_probes_v3/integer-cents-table.trial-1.json
bb366acb932518593e660840d85fc9cb89ba0b3981cf3dda86198288a5fa1a02  muse_probes_v3/cost-ledger.json
```

`muse_live_002.json` matches the SHA-256 prefix and suffix recorded on 2026-10-31 in [HACKATHON_CONTRIBUTIONS.md](../../docs/HACKATHON_CONTRIBUTIONS.md) (`f81c3ab8…fd665`).

All responses report `"store": true` from the API, so Meta retained them as well. Only synthetic policies were ever sent.
