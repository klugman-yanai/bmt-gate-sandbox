# `.github` Layout

This repository keeps GitHub Actions logic in the native locations that GitHub executes.

## Workflow matrix (this repo)

Only **four** workflow YAML files live at **`.github/workflows/*.yml`**: **`build-and-test-dev.yml`**, **`build-and-test.yml`**, **`bmt-handoff.yml`**, **`clang-format-auto-fix.yml`**. Everything else is under **`workflows/internal/`** (dev/ops tooling in this repo). The **release bundle** (`.github-release/`) ships root workflows from `.github/workflows/` (excluding `*-dev.yml`) plus **`workflows/internal/`** from **`scripts/release_templates/workflows/`** only (e.g. **`trigger-ci.yml`** for **core-main**, **`code-owner-enforcement.yml`**). The in-repo **`internal/trigger-ci.yml`** (dev thin trigger) is **not** copied into the bundle.

| Workflow | Purpose |
| -------- | ------- |
| **`workflows/build-and-test-dev.yml`** | Reusable CI: **`workflow_dispatch`** + **`workflow_call`** only — same shape as **`build-and-test.yml`**. PR-driven runs use **`internal/trigger-ci.yml`** (`pull_request` into `dev` / `ci/check-bmt-gate` / `test/*`) which **`workflow_call`s** this file at the PR head ref; calls **`bmt-handoff.yml`** when `bmt_handoff.if` passes |
| **`workflows/build-and-test.yml`** | Reusable CI for **core-main** (and manual runs): `workflow_dispatch` + `workflow_call` only — release **`trigger-ci.yml`** template supplies `pull_request_target` + `workflow_dispatch` on **`dev`** |
| **`workflows/bmt-handoff.yml`** | Reusable BMT handoff: context, upload matrix, **Workflows** dispatch (`invoke-workflow`) |
| **`workflows/clang-format-auto-fix.yml`** | C/C++ format automation on selected branches |
| **`workflows/internal/bmt-handoff-dev.yml`** | `workflow_dispatch` wrapper: calls **`bmt-handoff.yml`** with **`use_mock_runner: true`** |
| **`workflows/internal/validate-release-bundle.yml`** | Validates **`scripts/assemble_release.py`** output on path-filtered `push` / `pull_request` |
| **`workflows/internal/trigger-ci.yml`** | Thin trigger (mirrors release template): **`pull_request`** + **`workflow_dispatch`** → **`workflow_call`** **`build-and-test-dev.yml`** at head ref |
| **`workflows/internal/trigger-ci-dispatch.yml`** | Manual: `gh workflow run` **`build-and-test-dev.yml`** on a chosen ref and watch the run |
| **`workflows/internal/bmt-image-build.yml`** | Packer image build; also on path-filtered `push` |
| **`workflows/internal/trigger-image-build.yml`** | Manual: dispatch image build on a branch |

**BMT CLI:** `uv run bmt …` — package under **[`.github/bmt/`](bmt/)** (`ci/`, `config/`). See [`bmt/README.md`](bmt/README.md) for install name `bmt` vs import package `ci`.

## Production deliverables (Kardome-org/core-main, dev branch)

**core-main** already has `build-and-test.yml`, `clang-format-auto-fix.yml`, and a deprecated `code-owner-enforcement.yml` (must remain). To add the BMT gate to production you only need:

1. **Modifications to `build-and-test.yml`** — BMT-related jobs: `bmt_handoff` calls the reusable handoff workflow; eligibility is on `bmt_handoff.if` (no separate gate job).
2. **`bmt-handoff.yml`** — Reusable workflow invoked by build-and-test for the BMT gate.

**`workflows/internal/*`** (and `*-dev.yml` if ever at root) are for bmt-gcloud testing only and are **not** part of the production bundle. Do not copy **`internal/`** to core-main. **`clang-format-auto-fix.yml`** is a separate policy choice for the consumer repo.

## Will it work in production if only those two files are added?

**No.** Adding only modified `build-and-test.yml` and `bmt-handoff.yml` to core-main will cause the real workflow to fail. `bmt-handoff.yml` and the actions it uses depend on the rest of this repo:

- **Missing local actions** — `bmt-handoff.yml` uses `bmt-prepare-context`, `setup-gcp-uv`, `bmt-filter-handoff-matrix`, `bmt-failure-fallback`, and `bmt-write-summary` under `.github/actions/`. (`check-image-up-to-date` exists for optional image gates; it is not referenced by the current handoff workflow in this repo.)
- **Missing BMT CLI** — Steps run `uv run bmt …` (write-context, filter-upload-matrix, invoke-workflow, etc.). The package lives under `.github/bmt/` (pyproject.toml, ci/, config/); core-main needs it.
- **Missing `gcp/image`** — The failure-fallback path runs `from gcp.image.config.constants import STATUS_CONTEXT`. The handoff job does a sparse-checkout of `.github` and `gcp`, so at least `gcp/image/config/` (with `constants.py`) must exist in the repo.
- **Check image up to date** — Composite action `check-image-up-to-date` takes **`image_build_workflow`** (default **`internal/bmt-image-build.yml`** in this repo). On core-main, pass **`bmt-image-build.yml`** if the image workflow lives at the workflows root. It fails when `infra/packer` or `gcp/image` change but no successful image build run exists for the ref.
- **Repo variables** — Handoff reads `vars.GCS_BUCKET`, `vars.GCP_WIF_PROVIDER`, `vars.GCP_SA_EMAIL`, `vars.GCP_PROJECT`, `vars.CLOUD_RUN_REGION`, and the Workflow / job names exported by Pulumi. These must be set in core-main (or the org).
- **Job graph in build-and-test** — Only release runners are sent to BMT; non-release builds run in parallel. Jobs: `repo_snapshot` → `build_release` ∥ `build_non_release` → `bmt_handoff` (when `if` passes). In **this repo**, `bmt_handoff.if` uses **head ref** allowlisting (`dev`, `ci/check-bmt-gate`, `test/check-bmt-gate*`, other `test/*`) in PR-driven CI. Runner `runner-*` artifact names are listed inside handoff **Plan**, not in a separate CI job. In core-main the same graph applies with real builds.

**For the real workflow to work in core-main you must:** add/copy the two workflow files **and** the required `.github/actions/` set, `.github/bmt/`, and enough of `gcp/image` for the fallback constant; set the repo vars; and either add `bmt-image-build.yml` (or equivalent) so the image check can pass, or make the image check skip when that workflow does not exist.

## File release checklist (Kardome-org/core-main)

Mechanical bundle: **`just tools release`** (requires `gcp/image/github/secrets/Kardome-org_core-main.pem` for a full copy), or **`just tools release --skip-secrets`** / **`RELEASE_SKIP_SECRETS=1`** when no local PEM (CI, or secrets-only promotion). Output: **`.github-release/`** (gitignored here). Copy into **`core-main/.github/`** as one atomic PR. **`bmt_release.json`** records **`source_sha`** from this repo for drift tracking.

| Source in bmt-gcloud | On core-main | Mechanism |
| ---------------------- | ------------- | --------- |
| `.github/workflows/*.yml` at root (excl. `*-dev.yml`) | `.github/workflows/` | [assemble_release.py](../scripts/assemble_release.py) |
| `scripts/release_templates/workflows/*.yml` (excl. duplicate `clang-format-auto-fix.yml`) | `.github/workflows/internal/` | assembler |
| `.github/actions/*` (excl. `check-image-up-to-date`) | `.github/actions/` | assembler |
| `.github/bmt/` (`ci/`, `pyproject.toml`, `uv.lock`, `config/README.md`) | `.github/bmt/` | assembler |
| `scripts/release_templates/actionlint.yaml` | `.github/actionlint.yaml` | assembler |
| `gcp/image/**` needed for `gcp.image.*` imports | repo root `gcp/` | **Not** in assembler — keep in sync with bmt-gcloud or copy minimal tree separately (see above) |
| `bmt-gcloud` Python package for `uv sync` in `.github/bmt` | consumer resolution | Documented in [`bmt/README.md`](bmt/README.md) — git source or private index |

**Secrets:** Do **not** commit `*.pem` to `core-main`. Use **GitHub Secrets** for the GitHub App private key; optional local file paths are for dev only (see [`bmt/config/README.md`](bmt/config/README.md)).

## This repo’s workflow layout

- **workflows/** — **Root (release-shaped):** **`build-and-test-dev.yml`**, **`build-and-test.yml`**, **`bmt-handoff.yml`**, **`clang-format-auto-fix.yml`**. **`internal/`** — dev-only: handoff mock, validate-release-bundle, **`trigger-ci`** (thin), **`trigger-ci-dispatch`**, bmt-image-build, trigger-image-build.
- **actions/** — Local composite actions: `bmt-prepare-context`, `bmt-filter-handoff-matrix`, `bmt-write-summary`, `bmt-failure-fallback`, `setup-gcp-uv`
- **`.github/bmt/`** — BMT CLI (`uv run bmt …`) and config used by workflows ([`README.md`](bmt/README.md))

## Which workflow runs CI?

- **bmt-gcloud (this repo):** **`internal/trigger-ci.yml`** is the event entry (`pull_request` into `dev` / `ci/check-bmt-gate` / `test/*`, plus **`workflow_dispatch`**). It **`workflow_call`s** **`build-and-test-dev.yml`** at the PR head ref — same **thin-trigger → reusable CI** pattern as production, but **`pull_request`** (same-repo) instead of **`pull_request_target`**. Optional: **`internal/trigger-ci-dispatch.yml`** to dispatch **`build-and-test-dev.yml`** on any ref via **`gh`**. **`build-and-test-dev.yml`** also accepts direct **`workflow_dispatch`** / **`workflow_call`**.
- **Production (core-main):** After release copy, CI is driven by bundle **`internal/trigger-ci.yml`** (source: **`scripts/release_templates/workflows/trigger-ci.yml`**) on **`pull_request_target`** to **`dev`** (and **`workflow_dispatch`**), which **`workflow_call`s** **`build-and-test.yml`** at the PR head ref. No **`push`** to **`dev`** — direct pushes to **`dev`** are assumed forbidden. **`build-and-test.yml`** then calls **`bmt-handoff.yml`** when eligible.

## Workflow and job triggers (inventory)

**Reusable workflow context:** For `workflow_call`, the **`github` context in the called workflow matches the caller** ([docs](https://docs.github.com/en/actions/reference/reusable-workflows-reference#github-context)). Expressions in **`build-and-test.yml`** / **`build-and-test-dev.yml`** that use `github.event_name` / `github.event.pull_request` therefore see the **caller’s** event (e.g. `pull_request_target` from the release thin trigger, or `pull_request` from the in-repo thin trigger).

### `build-and-test.yml`

| Trigger | Notes |
| ------- | ----- |
| `workflow_dispatch` | Manual |
| `workflow_call` | Invoked by release-template **`trigger-ci`** (core-main), or other callers |

**Job gate — `bmt_handoff`:** runs only if `build_release` succeeded or was skipped **and** (same-repo PR or not a PR) **and** either PR (`pull_request` or `pull_request_target`) with **`base_ref`** in `dev` \| `ci/check-bmt-gate`, or non-PR with **`ref_name`** in `dev` \| `ci/check-bmt-gate`. Checkouts honor **`pull_request_target`** head repo/SHA when that event applies.

### `build-and-test-dev.yml`

| Trigger | Notes |
| ------- | ----- |
| `workflow_dispatch` | Manual (or via **`internal/trigger-ci-dispatch`** dispatching this workflow file) |
| `workflow_call` | Invoked by in-repo **`internal/trigger-ci.yml`** (PR or manual thin trigger) |

PR merge gate: **`internal/trigger-ci.yml`** — **`pull_request`** with base branches `dev`, `ci/check-bmt-gate`, `test/*` (no **`push`**; direct pushes to **`dev`** assumed forbidden).

**Job gate — `bmt_handoff`:** same fork rule as above; branch eligibility uses **head ref** (`head.ref` or `ref_name`): `dev`, `ci/check-bmt-gate`, `test/check-bmt-gate*` prefix, or other **`test/*`** heads per the workflow expression. Checkouts use **`pull_request`** + head SHA when the caller event is a PR.

### `bmt-handoff.yml`

| Trigger | Notes |
| ------- | ----- |
| `workflow_dispatch` | Inputs: `ci_run_id`, `head_sha`, `head_branch`, `head_event`, `pr_number`, `available_artifacts`, region, status context, etc. |
| `workflow_call` | Same inputs from CI |

**Notable job `if`:** `publish_runners` when `matrix_publish_keys != '[]'`; `start_bmt_workflow` when not cancelled, context job succeeded, and `publish_runners` succeeded or skipped; steps gated on `matrix.bmt_supported`, `use_mock_runner`, and `invoke-workflow` outcome.

### `internal/bmt-handoff-dev.yml`

| Trigger | Notes |
| ------- | ----- |
| `workflow_dispatch` | Forwards to **`bmt-handoff.yml`** with **`use_mock_runner: true`** |

### `internal/validate-release-bundle.yml`

| Trigger | Notes |
| ------- | ----- |
| `push` / `pull_request` | Branches: `dev`, `ci/check-bmt-gate`; **paths:** `scripts/assemble_release.py`, `scripts/release_templates/**`, `.github/bmt/**`, `.github/workflows/**`, `.github/actions/**` |
| `workflow_dispatch` | Manual |

### `internal/bmt-image-build.yml`

| Trigger | Notes |
| ------- | ----- |
| `workflow_dispatch` / `workflow_call` | Packer inputs |
| `push` | Branches: `main`, `ci/check-bmt-gate`, `dev`; **paths:** `infra/packer/**`, `gcp/image/**` |

### `internal/trigger-image-build.yml` / `internal/trigger-ci.yml` / `internal/trigger-ci-dispatch.yml`

| Workflow | Trigger |
| -------- | ------- |
| **`internal/trigger-image-build.yml`** | `workflow_dispatch` (optional `branch` input; dispatches image build on that ref) |
| **`internal/trigger-ci.yml`** | **`pull_request`** (bases: `dev`, `ci/check-bmt-gate`, `test/*`) + **`workflow_dispatch`** → **`workflow_call`** **`build-and-test-dev.yml`** |
| **`internal/trigger-ci-dispatch.yml`** | **`workflow_dispatch`** (required `ref`; **`gh workflow run`** **`build-and-test-dev.yml`**) |

### `clang-format-auto-fix.yml`

| Trigger | Notes |
| ------- | ----- |
| `workflow_dispatch` | Manual |
| `push` | **`branches-ignore`:** `dev`, `main`, `master`; **paths:** C/C++ sources and `.clang-format` |

**Job `if`:** `github.actor != 'github-actions[bot]'`. Workflow uses **`contents: write`**.

### Release template `scripts/release_templates/workflows/trigger-ci.yml`

Shipped to **`.github-release/workflows/internal/trigger-ci.yml`**. On core-main it should live at **`workflows/internal/trigger-ci.yml`** (same relative **`uses:`** paths to root **`build-and-test.yml`**).

| Trigger | Notes |
| ------- | ----- |
| `workflow_dispatch` | Manual |
| `pull_request_target` | Branch: **`dev`** — default-branch workflow context; pair with care for untrusted forks |
| `push` | _none_ (aligns with no direct pushes to **`dev`**) |

Calls **`./.github/workflows/build-and-test.yml@${{ github.event_name == 'pull_request_target' && github.head_ref || github.ref_name }}`** so the **called** workflow file comes from the PR head on `pull_request_target`. **bmt-gcloud** uses a **parallel** in-repo **`internal/trigger-ci.yml`** (see above) that calls **`build-and-test-dev.yml`** with **`pull_request`** instead — it is **not** part of the assembler output.

### Security / semantics (summary)

- **`pull_request_target`** appears in the **release template** only; combining it with **`uses: …@head_ref`** matches “workflow definition from head, runner/token context from base.” **`bmt_handoff`** also excludes forks via **`head.repo.full_name == github.repository`** where applicable.
- **No root `trigger-ci.yml`** in this repo’s **`.github/workflows/`**. **Two** `internal/trigger-ci.yml` meanings: (1) **in-repo** thin trigger for **`build-and-test-dev.yml`**; (2) **bundle / core-main** file from **`scripts/release_templates/workflows/trigger-ci.yml`** for **`build-and-test.yml`**. The assembler ships only (2); see **`assemble_release.py`** docstring.

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

`pulumi`/GitHub var export runs via **`just workspace pulumi`** (local or approved runner), not from default CI here — keeps state credentials and blast radius off ephemeral runners. To add **`pulumi preview`** on PRs later, you need a chosen [state backend](https://www.pulumi.com/docs/iac/concepts/state-and-backends/) and secrets policy; treat **fork PRs** as untrusted for cloud tokens.

## Optional CODEOWNERS

To require review for specific paths (e.g. workflows or `gcp/image/`), add a `.github/CODEOWNERS` file and enable **Require review from Code Owners** on protected branches. See [About code owners](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners).

## Auth boundaries

- **WIF + service account** authenticate workflow jobs to GCP.
- **github.token / GITHUB_TOKEN** is only used in workflow paths that call GitHub APIs directly (for example gh workflow run, gh variable set, or fallback status posting).
- **GitHub App credentials** are runtime-only and are loaded by the **Cloud Run** runtime after dispatch; they are not part of the reusable workflow contract.
