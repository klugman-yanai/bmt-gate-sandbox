# E2E CI Validation — Push, Mock Run, PR to Dev

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Push the current `ci/check-bmt-gate` commit, validate the pipeline end-to-end with the mock runner, then open a PR to `dev`.

**Architecture:** Push triggers the CI workflow (`build-and-test.yml`). The `bmt_handoff` job calls `bmt-handoff.yml` which writes a run trigger to GCS and dispatches the BMT VM. We use `workflow_dispatch` with `use_mock_runner: true` to exercise the full handoff and reporting path without burning real GCP compute.

**Tech Stack:** GitHub Actions, `gh` CLI, Python/uv, GCS, BMT Cloud Run

---

## Context

Branch `ci/check-bmt-gate` is 1 commit ahead of `origin/ci/check-bmt-gate` (commit `66751bb` — "pre e2e test", 86 files). All local checks pass: `ruff`, `ty`, `pytest` (145 passed, 5 xfailed). The last two CI runs on this branch failed at `confirm_cloud_job_start / Run ./.github/actions/bmt-filter-handoff-matrix` on the previous commit (`2522c8567`); those runs used the real runner. We'll use `use_mock_runner: true` first to validate pipeline plumbing cheaply.

**Previous run context:** The `.github/actions/bmt-start-runtime-reporting/action.yml` was deleted in the current commit; `bmt-filter-handoff-matrix` action still exists at `.github/actions/bmt-filter-handoff-matrix/`. If that step fails again, see the Triage section below.

---

## Task 1: Push to `ci/check-bmt-gate`

**Files:** none (git push only)

**Step 1: Verify clean state before push**

```bash
git status
git log --oneline -3
```

Expected: "nothing to commit, working tree clean", latest commit is `66751bb pre e2e test`.

**Step 2: Push**

```bash
git push origin ci/check-bmt-gate
```

Expected: `Branch 'ci/check-bmt-gate' set up to track remote branch` or `Everything up-to-date` / `1 commit pushed`.

**Step 3: Confirm CI triggered**

```bash
gh run list --branch ci/check-bmt-gate --limit 3
```

Expected: A new run appears for the `CI` workflow with status `queued` or `in_progress`.

---

## Task 2: Trigger with Mock Runner via `workflow_dispatch`

The push will trigger CI with `use_mock_runner: false` (real runner). To also validate pipeline plumbing cheaply:

**Step 1: Dispatch mock run**

```bash
gh workflow run bmt-handoff.yml \
  --ref ci/check-bmt-gate \
  --field use_mock_runner=true
```

Expected: `✓ Created workflow_dispatch event for bmt-handoff.yml at ci/check-bmt-gate`

**Step 2: Get the run ID**

```bash
sleep 5 && gh run list --workflow bmt-handoff.yml --branch ci/check-bmt-gate --limit 3
```

Note the run ID of the new dispatch.

---

## Task 3: Monitor Both Runs

**Step 1: Watch the mock runner dispatch run**

```bash
gh run watch <MOCK_RUN_ID>
```

This blocks and streams live status. Expected terminal state: all jobs green.

**Step 2: Check the push-triggered CI run**

```bash
gh run watch <PUSH_RUN_ID>
```

Expected: `checkout_snapshot`, `build_release`, `build_non_release` all green; `bmt_handoff` green (confirm_cloud_job_start succeeds).

**Step 3: If a run fails — triage**

```bash
gh run view <RUN_ID> --log-failed 2>&1 | head -80
```

Common failure modes:

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `bmt-filter-handoff-matrix` fails | Python error in `ci/workflow_dispatch.py` or `ci/config.py` | Check log for traceback, fix locally, push again |
| `bmt-start-runtime-reporting` missing | Stale reference in `bmt-handoff.yml` | `grep -n "bmt-start-runtime-reporting" .github/workflows/bmt-handoff.yml` — remove the step if found |
| GCP auth failure | WIF token expired or permission missing | Check `GCP_WIF_PROVIDER` and `GCP_SA_EMAIL` repo vars: `gh variable list` |
| `uv sync` fails | Lock file or dep conflict | Run `uv sync` locally, fix and push |

---

## Task 4: Open PR to `dev`

Only do this after Task 3 confirms at least the mock runner dispatch succeeds.

**Step 1: Create the PR**

```bash
gh pr create \
  --base dev \
  --head ci/check-bmt-gate \
  --title "Orchestration clarity pass + pre-E2E infra updates" \
  --body "$(cat <<'EOF'
## Summary

- Sections A–D of the Orchestration Clarity Pass: guard chain improvements, exception logging, `_HandoffEnv` dataclass, `gh_repo_vars` decomposition
- Supporting infra changes baked into the \"pre e2e test\" commit (86 files)
- All local checks pass: ruff, ty, pytest (145 passed, 5 xfailed)
- Mock runner workflow_dispatch validated pipeline plumbing on `ci/check-bmt-gate`

## Test plan

- [ ] Mock runner dispatch (Task 2) completed green
- [ ] Push-triggered CI (`build_release`, `bmt_handoff`) completed green
- [ ] PR checks show BMT Gate status

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Expected: PR URL printed (e.g. `https://github.com/klugman-yanai/bmt-gcloud/pull/NN`).

**Step 2: Verify PR CI triggered**

```bash
gh pr checks <PR_NUMBER> --watch
```

Expected: All checks pass including `BMT Gate` commit status.

---

## Verification Summary

After all tasks complete:

```bash
# Confirm branch pushed
git log --oneline origin/ci/check-bmt-gate -1

# Confirm mock run passed
gh run list --workflow bmt-handoff.yml --branch ci/check-bmt-gate --limit 1

# Confirm PR exists and checks passing
gh pr view <PR_NUMBER> --json state,statusCheckRollup
```
