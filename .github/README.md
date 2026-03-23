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

**BMT CLI:** `uv run bmt …` — package under **[`.github/bmt/`](bmt/)** (`ci/`, `config/`). See [`bmt/README.md`](bmt/README.md) for install name `bmt` vs import package `ci`.

## Production deliverables (Kardome-org/core-main, dev branch)

**core-main** already has `build-and-test.yml`, `clang-format-auto-fix.yml`, and a deprecated `code-owner-enforcement.yml` (must remain). To add the BMT gate to production you only need:

1. **Modifications to `build-and-test.yml`** — BMT-related jobs (e.g. `evaluate_bmt_gate`, `bmt_handoff` calling handoff).
2. **`bmt-handoff.yml`** — Reusable workflow invoked by build-and-test for the BMT gate.

**All other workflow files in this repo are for bmt-gcloud testing only** and are not part of the production set: `ops/*` (trigger-ci, trigger-image-build, bmt-image-build), `clang-format-auto-fix.yml`, etc. Do not add them to core-main.

## Will it work in production if only those two files are added?

**No.** Adding only modified `build-and-test.yml` and `bmt-handoff.yml` to core-main will cause the real workflow to fail. `bmt-handoff.yml` and the actions it uses depend on the rest of this repo:

- **Missing local actions** — `bmt-handoff.yml` uses `bmt-prepare-context`, `setup-gcp-uv`, `bmt-filter-handoff-matrix`, `bmt-failure-fallback`, and `bmt-write-summary` under `.github/actions/`. (`check-image-up-to-date` exists for optional image gates; it is not referenced by the current handoff workflow in this repo.)
- **Missing BMT CLI** — Steps run `uv run bmt …` (write-context, filter-upload-matrix, invoke-workflow, etc.). The package lives under `.github/bmt/` (pyproject.toml, ci/, config/); core-main needs it.
- **Missing `gcp/image`** — The failure-fallback path runs `from gcp.image.config.constants import STATUS_CONTEXT`. The handoff job does a sparse-checkout of `.github` and `gcp`, so at least `gcp/image/config/` (with `constants.py`) must exist in the repo.
- **Check image up to date** — Composite action `check-image-up-to-date` defaults to workflow `ops/bmt-image-build.yml` (input `image_build_workflow`). Override with `bmt-image-build.yml` if your layout keeps that file at the repo root (e.g. core-main). It fails when `infra/packer` or `gcp/image` change but no successful image build run exists for the ref.
- **Repo variables** — Handoff reads `vars.GCS_BUCKET`, `vars.GCP_WIF_PROVIDER`, `vars.GCP_SA_EMAIL`, `vars.GCP_PROJECT`, `vars.CLOUD_RUN_REGION`, and the Workflow / job names exported by Pulumi. These must be set in core-main (or the org).
- **Job graph in build-and-test** — Only release runners are sent to BMT; non-release builds run in parallel. Jobs: `build_release` (gates BMT), `build_non_release` (parallel), `evaluate_bmt_gate` → `bmt_handoff`. In core-main the same graph applies with real builds.

**For the real workflow to work in core-main you must:** add/copy the two workflow files **and** the required `.github/actions/` set, `.github/bmt/`, and enough of `gcp/image` for the fallback constant; set the repo vars; and either add `bmt-image-build.yml` (or equivalent) so the image check can pass, or make the image check skip when that workflow does not exist.

## File release checklist (Kardome-org/core-main)

Mechanical bundle: `just release` (requires `gcp/image/github/secrets/Kardome-org_core-main.pem` for a full copy), or **`just release --skip-secrets`** / **`RELEASE_SKIP_SECRETS=1`** when no local PEM (CI, or secrets-only promotion). Output: **`.github-release/`** (gitignored here). Copy into **`core-main/.github/`** as one atomic PR. **`bmt_release.json`** records **`source_sha`** from this repo for drift tracking.

| Source in bmt-gcloud | On core-main | Mechanism |
| ---------------------- | ------------- | --------- |
| `.github/workflows/` (non-`*-dev`, non-`ops/`) + `scripts/release_templates/workflows/` | `.github/workflows/` | [assemble_release.py](../scripts/assemble_release.py) |
| `.github/actions/*` (excl. `check-image-up-to-date`) | `.github/actions/` | assembler |
| `.github/bmt/` (`ci/`, `pyproject.toml`, `uv.lock`, `config/README.md`) | `.github/bmt/` | assembler |
| `scripts/release_templates/actionlint.yaml` | `.github/actionlint.yaml` | assembler |
| `gcp/image/**` needed for `gcp.image.*` imports | repo root `gcp/` | **Not** in assembler — keep in sync with bmt-gcloud or copy minimal tree separately (see above) |
| `bmt-gcloud` Python package for `uv sync` in `.github/bmt` | consumer resolution | Documented in [`bmt/README.md`](bmt/README.md) — git source or private index |

**Secrets:** Do **not** commit `*.pem` to `core-main`. Use **GitHub Secrets** for the GitHub App private key; optional local file paths are for dev only (see [`bmt/config/README.md`](bmt/config/README.md)).

## This repo’s workflow layout

- **workflows/** — **`build-and-test.yml`** (main CI; structure aligned with core-main), **`bmt-handoff.yml`** (BMT handoff, called by build-and-test). **Test-only (not for core-main):** **`ops/`** — trigger-ci, trigger-image-build, bmt-image-build; **`clang-format-auto-fix.yml`**.
- **actions/** — Local composite actions: `bmt-prepare-context`, `bmt-filter-handoff-matrix`, `bmt-write-summary`, `bmt-failure-fallback`, `setup-gcp-uv`
- **`.github/bmt/`** — BMT CLI (`uv run bmt …`) and config used by workflows ([`README.md`](bmt/README.md))

## Which workflow runs CI?

- **Production (core-main):** **`build-and-test.yml`** runs on push/pull_request and calls **`bmt-handoff.yml`** for the BMT gate. Only those two files (with build-and-test modified) are added to core-main.
- **bmt-gcloud (this repo) only:** **`ops/trigger-ci.yml`** runs CI from a chosen branch; **`ops/bmt-image-build.yml`** for image tooling; **`clang-format-auto-fix.yml`** for formatting. None of these are production deliverables.

## Why there is no `.github/jobs/`

GitHub Actions does not execute files from `.github/jobs/`. Use native `workflow_call` reusable workflows under `workflows/` for reusable job-level logic.

## Repo variables vs composite inputs

Repository variables (`vars.*`, synced from Pulumi) are the **source of truth**. Workflows usually map them once on a workflow or job `env:` block (for example `GCP_PROJECT: ${{ vars.GCP_PROJECT }}`). Composite actions cannot rely on `vars` the same way, so actions such as `setup-gcp-uv` take an explicit **`gcp_project`** input — pass **`${{ env.GCP_PROJECT }}`** when the job already defines `env` from `vars`. That is one value threaded through two mechanisms, not two different project IDs.

## Why `actions/setup-gcp-uv` exists

`actions/setup-gcp-uv/action.yml` centralizes:

1. `google-github-actions/auth` (Workload Identity Federation) with **`project_id`**
2. `google-github-actions/setup-gcloud` with the same **`project_id`** and a default **`gcloud_version`** constraint for WIF
3. Optional `astral-sh/setup-uv` with **`enable-cache: true`** for faster `uv sync`

Third-party action bumps: **Dependabot** (`.github/dependabot.yml`). Per-job `permissions` stay in each workflow job.

## GitHub Actions and Pulumi

`pulumi`/GitHub var export runs via **`just pulumi`** (local or approved runner), not from default CI here — keeps state credentials and blast radius off ephemeral runners. To add **`pulumi preview`** on PRs later, you need a chosen [state backend](https://www.pulumi.com/docs/iac/concepts/state-and-backends/) and secrets policy; treat **fork PRs** as untrusted for cloud tokens.

## Optional CODEOWNERS

To require review for specific paths (e.g. workflows or `gcp/image/`), add a `.github/CODEOWNERS` file and enable **Require review from Code Owners** on protected branches. See [About code owners](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners).

## Auth boundaries

- **WIF + service account** authenticate workflow jobs to GCP.
- **github.token / GITHUB_TOKEN** is only used in workflow paths that call GitHub APIs directly (for example gh workflow run, gh variable set, or fallback status posting).
- **GitHub App credentials** are runtime-only and are loaded by the **Cloud Run** runtime after dispatch; they are not part of the reusable workflow contract.
