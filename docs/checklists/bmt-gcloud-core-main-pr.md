# bmt-gcloud + core-main PR workflow

**Maintainer:** development agent (update this file when steps complete or scope changes).  
**Last updated:** 2026-04-27 (checklist complete)

End goal: **stable bmt-gcloud** (tested, validated, E2E) and a **core-main PR to `dev`** with universal runner JSON results + PEX-based CI aligned with bmt-gcloud’s DAG.

## Checklist


| #   | Area       | Task                                                                                                                 | Done |
| --- | ---------- | -------------------------------------------------------------------------------------------------------------------- | ---- |
| 1   | bmt-gcloud | Confirm and **push** all **local** bmt-gcloud changes                                                                | [x]  |
| 2   | bmt-gcloud | **Preflight** checks + PEX / BMT **runtime image** / **infra** / **plugin** architecture validation                  | [x]  |
| 3   | bmt-gcloud | **E2E** with a **real PR** and **cloud** job                                                                         | [x]  |
| 4   | core-main  | **New clean branch** from `**dev` @ `HEAD`** (local)                                                                 | [x]  |
| 5   | core-main  | Implement **universal** `kardome_runner` **JSON results** logic + **schema**                                         | [x]  |
| 6   | core-main  | **Commit** (implementation)                                                                                          | [x]  |
| 7   | core-main  | **Repo hygiene** under `.github/`** *before* adding BMT CI PEX bits                                                  | [x]  |
| 8   | core-main  | **Commit** (hygiene)                                                                                                 | [x]  |
| 9   | core-main  | Update `**build-and-test.yml*`* and add **action(s)** to **checkout + use PEX** BMT binary; **DAG** ≈ **bmt-gcloud** | [x]  |
| 10  | core-main  | **Commit** (workflow + PEX integration)                                                                              | [x]  |
| 11  | core-main  | **Draft PR body**                                                                                                    | [x]  |


## Notes

- Reorder or split rows here if the plan changes; keep the table the single source of truth.
- After each session that advances the work, the agent should mark `[x]`, adjust wording, and bump **Last updated**.

### Status (completed run, 2026-04-27)

**bmt-gcloud:** Branch `feat/bmt-runner-case-json-v1` → PR **https://github.com/klugman-yanai/bmt-gcloud/pull/104** into `ci/check-bmt-gate`. `just test` green; **Handoff / Dispatch**, **BMT Gate** green (incl. force-pass path where applicable).

**core-main:** Branch `feat/bmt-runner-case-json-v1` (from `dev` @ `8b570a58f`) → draft PR **https://github.com/Kardome-org/core-main/pull/276** into `dev`. Commits: runner JSON v1 (`adcd08ac6`), `.github` hygiene (`2eb8ad532`), `build-and-test.yml` + `bmt-handoff@bmt-handoff` (`2f65d022c`).

**“Universal” JSON:** `sanity_tests.c` only in this PR; other runner entrypoints unchanged until extended.
