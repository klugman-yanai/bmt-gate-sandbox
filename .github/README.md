# `.github` Layout

This repository keeps GitHub Actions logic in the native locations that GitHub executes:

- `workflows/`: workflow entrypoints (`dummy-build-and-test.yml`, `bmt.yml`)
- `actions/`: local composite actions used by workflows
- `scripts/`: shell/Python helpers used by workflow steps

## Why there is no `.github/jobs/`

GitHub Actions does not execute files from `.github/jobs/`. Using that directory as an execution layer would require a custom generation/preprocessing system and add maintenance overhead.

If reusable job-level logic is needed, use native `workflow_call` reusable workflows under `.github/workflows/`.

## Why `actions/setup-gcp-uv` exists

`actions/setup-gcp-uv/action.yml` is a local composite action that centralizes repeated setup:

1. `google-github-actions/auth@v2` (Workload Identity Federation)
2. `google-github-actions/setup-gcloud@v2`
3. Optional `astral-sh/setup-uv@v7`

This keeps auth/toolchain versions in one place and removes duplicated setup blocks from workflows. Per-job `permissions` are still defined in each workflow job.
