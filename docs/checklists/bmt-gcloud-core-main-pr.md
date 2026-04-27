# bmt-gcloud + core-main PR workflow

**Maintainer:** development agent (update this file when steps complete or scope changes).  
**Last updated:** 2026-04-27 (status pass)

End goal: **stable bmt-gcloud** (tested, validated, E2E) and a **core-main PR to `dev`** with universal runner JSON results + PEX-based CI aligned with bmt-gcloud’s DAG.

## Checklist


| #   | Area       | Task                                                                                                                 | Done |
| --- | ---------- | -------------------------------------------------------------------------------------------------------------------- | ---- |
| 1   | bmt-gcloud | Confirm and **push** all **local** bmt-gcloud changes                                                                | [ ]  |
| 2   | bmt-gcloud | **Preflight** checks + PEX / BMT **runtime image** / **infra** / **plugin** architecture validation                  | [ ]  |
| 3   | bmt-gcloud | **E2E** with a **real PR** and **cloud** job                                                                         | [ ]  |
| 4   | core-main  | **New clean branch** from `**dev` @ `HEAD`** (local)                                                                 | [x]  |
| 5   | core-main  | Implement **universal** `kardome_runner` **JSON results** logic + **schema**                                         | [ ]  |
| 6   | core-main  | **Commit** (implementation)                                                                                          | [ ]  |
| 7   | core-main  | **Repo hygiene** under `.github/`** *before* adding BMT CI PEX bits                                                  | [ ]  |
| 8   | core-main  | **Commit** (hygiene)                                                                                                 | [ ]  |
| 9   | core-main  | Update `**build-and-test.yml*`* and add **action(s)** to **checkout + use PEX** BMT binary; **DAG** ≈ **bmt-gcloud** | [ ]  |
| 10  | core-main  | **Commit** (workflow + PEX integration)                                                                              | [ ]  |
| 11  | core-main  | **Draft PR body**                                                                                                    | [ ]  |


## Notes

- Reorder or split rows here if the plan changes; keep the table the single source of truth.
- After each session that advances the work, the agent should mark `[x]`, adjust wording, and bump **Last updated**.

### Status (agent, local tree)

**bmt-gcloud** (`chore/open-pipeline-view-20260421`): **1 not done** — dirty tree (~14 paths: modified + untracked schemas, `docs/checklists/`, etc.); upstream remote ref **gone**. Nothing indicates a successful full push of current work.

**2–3**: No local evidence of preflight/E2E completion (requires your runs + GitHub).

**core-main** (`feat/bmt-telemetry-v2-sidecar`): **4 done** — `merge-base(dev, HEAD) == dev` at `8b570a58f`; one commit on top (`65430c447`).

**5–6**: **Partial** — `bmt_runner_case_metrics_json` + `sanity_tests` call are **committed**; working tree still **dirty** on the C/H files (e.g. `RUNNER_CASE_JSON_FORMAT_V1` / v1 string), so latest implementation is **not** fully committed.

**5 “universal”**: Only **sanity_tests** path is in this commit; other runner entrypoints unchanged until you extend.

**7–11**: `**git diff dev -- .github/`** is **empty** on this branch — hygiene + PEX workflow + draft PR **not** started in repo.