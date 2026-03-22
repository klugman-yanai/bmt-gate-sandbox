# `.github` Layout

This repository keeps GitHub Actions logic in the native locations that GitHub executes.

## Workflow matrix (this repo)

| Workflow | Purpose |
| -------- | ------- |
| **`workflows/build-and-test.yml`** | Main CI: build, tests, and calls **`bmt-handoff.yml`** for the BMT gate |
| **`workflows/bmt-handoff.yml`** | Reusable BMT handoff: context, upload matrix, **Workflows** dispatch (`invoke-workflow`) |
| **`workflows/ops/trigger-ci.yml`** | Manual / branch CI trigger (sandbox) |
| **`workflows/ops/bmt-image-build.yml`** | Image build pipeline |
| **`workflows/ops/trigger-image-build.yml`** | Trigger image build |
| **`workflows/clang-format-auto-fix.yml`** | Formatting automation |

**BMT CLI:** `uv run bmt …` — package under **`bmt/`** (`ci/`, `config/`).

## Production deliverables (Kardome-org/core-main, dev branch)

**core-main** already has `build-and-test.yml`, `clang-format-auto-fix.yml`, and a deprecated `code-owner-enforcement.yml` (must remain). To add the BMT gate to production you only need:

1. **Modifications to `build-and-test.yml`** — BMT-related jobs (e.g. decide-bmt, bmt calling handoff).
2. **`bmt-handoff.yml`** — Reusable workflow invoked by build-and-test for the BMT gate.

**All other workflow files in this repo are for bmt-gcloud testing only** and are not part of the production set: `ops/*` (trigger-ci, trigger-image-build, bmt-image-build), `clang-format-auto-fix.yml`, etc. Do not add them to core-main.

## Will it work in production if only those two files are added?

**No.** Adding only modified `build-and-test.yml` and `bmt-handoff.yml` to core-main will cause the real workflow to fail. `bmt-handoff.yml` and the actions it uses depend on the rest of this repo:

- **Missing local actions** — Handoff uses: `check-image-up-to-date`, `bmt-prepare-context`, `setup-gcp-uv`, `bmt-filter-handoff-matrix`, `bmt-failure-fallback`, and `bmt-write-summary`. All must exist under `.github/actions/`.
- **Missing BMT CLI** — Steps run `uv run bmt …` (write-context, filter-upload-matrix, invoke-workflow, etc.). The package lives under `.github/bmt/` (pyproject.toml, ci/, config/); core-main needs it.
- **Missing `gcp/image`** — The failure-fallback path runs `from gcp.image.config.constants import STATUS_CONTEXT`. The handoff job does a sparse-checkout of `.github` and `gcp`, so at least `gcp/image/config/` (with `constants.py`) must exist in the repo.
- **Check image up to date** — The first handoff job calls `check-image-up-to-date`, which expects a workflow named `bmt-image-build.yml` and fails if image-affecting paths changed but no successful run exists. If core-main does not have that workflow, the check will fail whenever `infra/packer` or `gcp/image` change (or the action must be made optional when the workflow is absent).
- **Repo variables** — Handoff reads `vars.GCS_BUCKET`, `vars.GCP_WIF_PROVIDER`, `vars.GCP_SA_EMAIL`, `vars.GCP_PROJECT`, `vars.CLOUD_RUN_REGION`, and the Workflow / job names exported by Pulumi. These must be set in core-main (or the org).
- **Job graph in build-and-test** — Only release runners are sent to BMT; non-release builds run in parallel. Jobs: `build-release` (gates BMT), `build-nonrelease` (parallel), `decide-bmt` → `bmt`. In core-main the same graph applies with real builds.

**For the real workflow to work in core-main you must:** add/copy the two workflow files **and** the required `.github/actions/` set, `.github/bmt/`, and enough of `gcp/image` for the fallback constant; set the repo vars; and either add `bmt-image-build.yml` (or equivalent) so the image check can pass, or make the image check skip when that workflow does not exist.

## This repo’s workflow layout

- **workflows/** — **`build-and-test.yml`** (main CI; structure aligned with core-main), **`bmt-handoff.yml`** (BMT handoff, called by build-and-test). **Test-only (not for core-main):** **`ops/`** — trigger-ci, trigger-image-build, bmt-image-build; **`clang-format-auto-fix.yml`**.
- **actions/** — Local composite actions: `bmt-prepare-context`, `bmt-filter-handoff-matrix`, `bmt-write-summary`, `bmt-failure-fallback`, `setup-gcp-uv`
- **bmt/** — BMT CLI (`uv run bmt …`) and config used by workflows
- **docs/** — Notes and references: `action-versions.md`, `dry-and-organization.md`

## Which workflow runs CI?

- **Production (core-main):** **`build-and-test.yml`** runs on push/pull_request and calls **`bmt-handoff.yml`** for the BMT gate. Only those two files (with build-and-test modified) are added to core-main.
- **bmt-gcloud (this repo) only:** **`ops/trigger-ci.yml`** runs CI from a chosen branch; **`ops/bmt-image-build.yml`** for image tooling; **`clang-format-auto-fix.yml`** for formatting. None of these are production deliverables.

## Why there is no `.github/jobs/`

GitHub Actions does not execute files from `.github/jobs/`. Use native `workflow_call` reusable workflows under `workflows/` for reusable job-level logic.

## Why `actions/setup-gcp-uv` exists

`actions/setup-gcp-uv/action.yml` centralizes:

1. `google-github-actions/auth` (Workload Identity Federation)
2. `google-github-actions/setup-gcloud`
3. Optional `astral-sh/setup-uv`

That keeps auth and toolchain versions in one place. Per-job `permissions` are still set in each workflow job.

## Auth boundaries

- **WIF + service account** authenticate workflow jobs to GCP.
- **github.token / GITHUB_TOKEN** is only used in workflow paths that call GitHub APIs directly (for example gh workflow run, gh variable set, or fallback status posting).
- **GitHub App credentials** are runtime-only and are loaded by the VM/Cloud Run runtime after dispatch; they are not part of the reusable workflow contract.

