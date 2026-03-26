# Goal
Cancel active Cloud Workflows BMT execution when a PR is closed, using a dedicated GitHub workflow and minimal, explicit CI plumbing.

# Approach
Record the dispatched Workflow execution name for PR-triggered runs in GCS, then handle `pull_request.closed` by looking up that record and calling the Workflows cancel API. After a successful cancel, run `bmt-control` in `finalize-failure` mode so the **BMT Gate** check and commit status are closed cleanly. Keep behavior idempotent and non-blocking when no active execution record exists.

# Files
- `.github/bmt/ci/workflow_dispatch.py` — persist and resolve per-PR active execution metadata; cancel + finalize-failure.
- `.github/bmt/ci/cloud_run_api.py` — Cloud Run Jobs v2 `:run` helper (wait for LRO).
- `.github/bmt/ci/workflows_api.py` — add execution cancel API helper.
- `.github/bmt/ci/driver.py` — expose new Typer command under `dispatch`.
- `.github/workflows/bmt-cancel-on-pr-close.yml` — `pull_request.closed`; pass `CLOUD_RUN_REGION`, `BMT_CONTROL_JOB`, optional `BMT_FAILURE_REASON`.
- `tests/ci/test_workflow_dispatch.py` — unit tests for record write and cancel behavior.
- `tests/ci/test_workflow_root_layout.py` — allow the new root workflow file.

# Tasks

## 1) Add Workflows cancel + PR execution index support
- [x] Implement a Workflows cancel helper in `ci.workflows_api`.
- [x] In `WorkflowDispatchManager.invoke`, write a PR execution index record to GCS when `pr_number` is numeric.
- [x] Add a dispatch manager method to load PR execution index, validate it, and issue cancel.
- [x] Keep operations idempotent (no record / mismatched SHA / already cancelled -> safe success with reason output).
- Run: `uv run python -m pytest tests/ci/test_workflow_dispatch.py -q`
- Expected: tests pass, including new cancel/index scenarios.

## 2) Add a dedicated PR-close workflow
- [x] Create `bmt-cancel-on-pr-close.yml` with `on: pull_request: [closed]`.
- [x] Authenticate with existing setup action and run new CLI cancel command.
- [x] Keep permissions minimal (`contents: read`, `id-token: write`).
- Run: `actionlint -config-file .github/actionlint.yaml`
- Expected: no workflow lint errors.

## 3) Update guard tests for root workflows
- [x] Add the new workflow filename to allowed root workflow set.
- Run: `uv run python -m pytest tests/ci/test_workflow_root_layout.py -q`
- Expected: layout test passes.

## 4) Full verification
- [x] Run focused workflow test set and actionlint.
- Run: `uv run python -m pytest tests/ci/test_workflow_dispatch.py tests/ci/test_workflow_hardening.py tests/ci/test_workflow_root_layout.py -q && actionlint -config-file .github/actionlint.yaml`
- Expected: all pass.

## 5) Finalize-failure after cancel
- [x] After successful Workflows cancel, invoke Cloud Run job `BMT_CONTROL_JOB` with `BMT_MODE=finalize-failure` and `BMT_WORKFLOW_RUN_ID` from the PR index payload.
- [x] Emit `finalize_requested` / `finalize_outcome` on `GITHUB_OUTPUT` for observability.
- [x] Extend unit tests for finalize success, skip without job name, and run-job failure.
