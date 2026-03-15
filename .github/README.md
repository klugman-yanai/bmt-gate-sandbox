# `.github` Layout

This repository keeps GitHub Actions logic in the native locations that GitHub executes:

- **workflows/** — `build-and-test.yml` (CI + BMT call), `bmt-handoff.yml` (BMT handoff), `bmt-vm-image-build.yml`, `bmt-vm-provision.yml`
- **actions/** — Local composite actions: `bmt-runner-env`, `bmt-prepare-context`, `bmt-filter-handoff-matrix`, `bmt-handoff-run`, `bmt-write-summary`, `bmt-failure-fallback`, `setup-gcp-uv`
- **bmt/** — BMT CLI (`uv run bmt …`) and config used by workflows
- **docs/** — Notes and references: `action-versions.md`, `dry-and-organization.md`

## Why there is no `.github/jobs/`

GitHub Actions does not execute files from `.github/jobs/`. Use native `workflow_call` reusable workflows under `workflows/` for reusable job-level logic.

## Why `actions/setup-gcp-uv` exists

`actions/setup-gcp-uv/action.yml` centralizes:

1. `google-github-actions/auth` (Workload Identity Federation)
2. `google-github-actions/setup-gcloud`
3. Optional `astral-sh/setup-uv`

That keeps auth and toolchain versions in one place. Per-job `permissions` are still set in each workflow job.
