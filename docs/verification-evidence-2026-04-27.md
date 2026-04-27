# Verification evidence (2026-04-27)

Operational check per repo sync + E2E plan. **Do not treat as CI.**

## Git: `origin` = `klugman-yanai/bmt-gcloud` (SSH)

After `git fetch origin --prune`, local **main**, **dev**, and **ci/check-bmt-gate** were updated with `git pull --ff-only` where behind. Verified:

| Branch | SHA (matches `origin/<branch>`) |
|--------|----------------------------------|
| `main` | `3f3a27d50ba18c3ed832cc518eee51672de36ceb` |
| `dev` | `47c834738c4f124d0dd98c50ebfbf4225bbf1100` |
| `ci/check-bmt-gate` | `0e7a3e056db6301f57f805149cd732c41f52e3d4` |

**Working tree:** Current branch `chore/open-pipeline-view-20260421` had local modifications (uncommitted); long-lived branches above match remotes.

## Local full gate

| Step | Result |
|------|--------|
| `uv sync` | exit 0 |
| `just test` (1st) | exit 0 |
| `just test` (2nd) | exit 0 |

**Python:** `python --version` reported 3.14.4 in this environment; [pyproject.toml](../pyproject.toml) requires `>=3.12,<3.13`. Use a 3.12 venv for reproducible CI parity.

## GitHub Actions (E2E-relevant)

`gh` authenticated. Recent runs (manual spot check):

| Branch | Run ID | Conclusion | Notes |
|--------|--------|------------|--------|
| `dev` | [24963940393](https://github.com/klugman-yanai/bmt-gcloud/actions/runs/24963940393) | success | CI workflow; includes Handoff / Plan, Handoff / Dispatch, matrix builds |
| `ci/check-bmt-gate` | [24965517168](https://github.com/klugman-yanai/bmt-gcloud/actions/runs/24965517168) | success | `feat(ci): require dispatch for force-pass path (#102)` push |
| `main` | (see below) | mixed | **Scheduled** `CI` runs on `main` show `failure` (10s) in recent list; they are not tied to the current `main` HEAD in the same way as push. Last **push** workflow on `main` in the sampled list: `trigger-ci` / `ci(register): add bmt-handoff-dev.yml…` [24618272424](https://github.com/klugman-yanai/bmt-gcloud/actions/runs/24618272424). Investigate scheduled workflow if `main` should stay green on cron. |

**Action:** If “green main” is required, open Actions → `CI` on `main` (schedule) and fix or disable the schedule job; do not conflate with `dev` / `ci/check-bmt-gate` BMT handoff path.

## GCS / `gcp/stage` vs bucket

**Not run:** `GCS_BUCKET` was unset in the verification shell. To complete layer: set bucket + auth per [configuration.md](configuration.md), then `just deploy` (or the sync recipe you use) and re-run gcp/ sync checks from CONTRIBUTING.

## Commands used (record)

```text
git fetch origin --prune
git pull --ff-only origin dev
git pull --ff-only origin ci/check-bmt-gate
# main already matched origin
just test  # x2
gh run list --repo klugman-yanai/bmt-gcloud --branch <branch> --limit 5
gh run view 24963940393 --repo klugman-yanai/bmt-gcloud
```
