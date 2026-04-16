# `.github` Layout

This repository keeps GitHub Actions logic in the native locations that GitHub executes.

## Workflow matrix (this repo)

Only **four** workflow YAML files live at **`.github/workflows/*.yml`**: **`build-and-test-dev.yml`**, **`build-and-test.yml`**, **`bmt-handoff.yml`**, **`clang-format-auto-fix.yml`**. Everything else is under **`workflows/internal/`** (dev/ops tooling). Optional templates for consumer repos (e.g. **`trigger-ci.yml`**) live under **`scripts/release_templates/workflows/`** as references — production no longer uses a generated **`.github-release/`** bundle.

| Workflow | Purpose |
| -------- | ------- |
| **`workflows/build-and-test-dev.yml`** | **This repo’s CI** on `push` / `pull_request` (and `workflow_dispatch` / `workflow_call`); calls **`bmt-handoff.yml`** when `bmt_handoff.if` passes |
| **`workflows/build-and-test.yml`** | Reusable CI for **core-main** (and manual runs): `workflow_dispatch` + `workflow_call` only — thin **`trigger-ci.yml`** (template or copy) supplies `push` / `pull_request_target` |
| **`workflows/bmt-handoff.yml`** | Reusable BMT handoff: context, upload matrix, **Workflows** dispatch (`invoke-workflow`) |
| **`workflows/clang-format-auto-fix.yml`** | C/C++ format automation on selected branches |
| **`workflows/internal/bmt-handoff-dev.yml`** | `workflow_dispatch` wrapper: calls **`bmt-handoff.yml`** with **`use_mock_runner: true`** |
| **`workflows/internal/build-kardome-bmt-pex.yml`** | On tag **`bmt-v*`**: build **`dist/bmt.pex`** and attach to the GitHub Release on **klugman-yanai/bmt-gcloud** |
| **`workflows/internal/trigger-ci.yml`** | Manual: `gh workflow run` **build-and-test** on a chosen ref |
| **`workflows/internal/bmt-image-build.yml`** | Packer image build; also on path-filtered `push` |
| **`workflows/internal/trigger-image-build.yml`** | Manual: dispatch image build on a branch |

**BMT CLI:** `uv run bmt …` by default, or release **`bmt.pex`** when repo vars **`BMT_CLI=pex`** and **`BMT_PEX_TAG`** are set (see [`docs/configuration.md`](../docs/configuration.md)). Wrapper: [`.github/scripts/invoke-bmt.sh`](./scripts/invoke-bmt.sh). Package under **`ci/`** — see [`bmt/README.md`](bmt/README.md).

## Production (Kardome-org/core-main)

**Preferred:** In the production repo, add a step that uses **[`bmt-get-pex`](./actions/bmt-get-pex/action.yml)** (or an equivalent `gh release download`) to fetch **`bmt.pex`** from a **GitHub Release on [klugman-yanai/bmt-gcloud](https://github.com/klugman-yanai/bmt-gcloud)** (tags like **`bmt-v0.1.0`**). Run **`./bmt.pex`** with Python 3.12 on the runner, or wire **`vars.BMT_CLI=pex`** / **`vars.BMT_PEX_TAG`** if you reuse workflows from this repo.

You still need to **vendor** what GitHub cannot pull from another repo by magic:

1. **Reusable workflows and composites** — Copy or submodule **[`.github/workflows/bmt-handoff.yml`](./workflows/bmt-handoff.yml)** and **[`.github/actions/`](./actions/)** (and any caller like **`build-and-test.yml`**) into the production repo, **or** use `workflow_call` / `uses: org/repo/.github/...` if your org allows cross-repo reusable workflows.
2. **Sparse / partial tree** — `bmt-handoff` may sparse-checkout **`runtime`**, **`ci`**, **`sdk`**, **`gcp/image`** (for fallback imports). Keep those paths consistent with this repo or adjust the checkout step.
3. **Repo variables** — `GCS_BUCKET`, `GCP_WIF_PROVIDER`, `GCP_SA_EMAIL`, `GCP_PROJECT`, `CLOUD_RUN_REGION`, job names from Pulumi, etc. (see [`docs/configuration.md`](../docs/configuration.md)).

**`workflows/internal/*`** here is for **bmt-gcloud** testing only — not required on core-main unless you copy a specific template (e.g. **`trigger-ci.yml`** from **`scripts/release_templates/workflows/`**).

## Will it work in production if only two workflow files are added?

**No.** Handoff depends on local **composite actions**, optional **`gcp/image`** for failure fallback, and **repo variables**. The **BMT CLI** can come from **`bmt.pex`** (upstream release) instead of vendoring **`ci/`** under `.github/bmt/`, but workflows and actions must still exist in the consumer repo (or be referenced cross-repo). See the section above.

## This repo’s workflow layout

- **workflows/** — **Root:** **`build-and-test-dev.yml`**, **`build-and-test.yml`**, **`bmt-handoff.yml`**, **`clang-format-auto-fix.yml`**. **`internal/`** — dev-only: handoff mock, PEX build, trigger-ci, bmt-image-build, trigger-image-build.
- **actions/** — `bmt-prepare-context`, `bmt-filter-handoff-matrix`, `bmt-write-summary`, `bmt-failure-fallback`, `setup-gcp-uv`, **`bmt-get-pex`**, `setup-bmt-cli`
- **`ci/`** — BMT CLI package ([`bmt/README.md`](bmt/README.md))

## Which workflow runs CI?

- **bmt-gcloud (this repo):** Day-to-day CI is **`build-and-test-dev.yml`** (`push`, `pull_request`, `workflow_dispatch`, `workflow_call`). It is **not** wired through **`pull_request_target`**.
- **Production (core-main):** Typically **`internal/trigger-ci.yml`** (from **`scripts/release_templates/workflows/trigger-ci.yml`**) on `push` / `pull_request_target` to **`dev`**, which **`workflow_call`s** **`build-and-test.yml`**. **`build-and-test.yml`** then calls **`bmt-handoff.yml`** when eligible.
- **Manual / sandbox:** **`internal/trigger-ci.yml`** dispatches **`build-and-test.yml`** on an arbitrary ref.

## Workflow and job triggers (inventory)

**Reusable workflow context:** For `workflow_call`, the **`github` context in the called workflow matches the caller** ([docs](https://docs.github.com/en/actions/reference/reusable-workflows-reference#github-context)). Expressions in **`build-and-test.yml`** that use `github.event_name` / `github.event.pull_request` therefore see the **caller’s** event (e.g. `pull_request_target` from the template trigger).

### `build-and-test.yml`

| Trigger | Notes |
| ------- | ----- |
| `workflow_dispatch` | Manual |
| `workflow_call` | Invoked by template **`trigger-ci`**, **`internal/trigger-ci`**, or other callers |

**Job gate — `bmt_handoff`:** runs only if `build_release` succeeded or was skipped **and** (same-repo PR or not a PR) **and** either PR (`pull_request` or `pull_request_target`) with **`base_ref`** in `dev` \| `ci/check-bmt-gate`, or non-PR with **`ref_name`** in `dev` \| `ci/check-bmt-gate`. Checkouts honor **`pull_request_target`** head repo/SHA when that event applies.

### `build-and-test-dev.yml`

| Trigger | Notes |
| ------- | ----- |
| `push` | Branches: `dev`, `ci/check-bmt-gate`, `test/check-bmt-gate-*`, `test/workflow-optimizations`, `test/*` |
| `pull_request` | Same branch set (aligned with `push`) |
| `workflow_dispatch` | Manual |
| `workflow_call` | Reusable entry |

**Job gate — `bmt_handoff`:** same fork rule as above; branch eligibility uses **head ref** (`head.ref` or `ref_name`): `dev`, `ci/check-bmt-gate`, `test/check-bmt-gate*` prefix, or other **`test/*`** heads per the workflow expression. Checkouts use **`pull_request`** + head SHA.

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

### `internal/bmt-image-build.yml`

| Trigger | Notes |
| ------- | ----- |
| `workflow_dispatch` / `workflow_call` | Packer inputs |
| `push` | Branches: `main`, `ci/check-bmt-gate`, `dev`; **paths:** `infra/packer/**`, `gcp/image/**` |

### `internal/trigger-image-build.yml` / `internal/trigger-ci.yml`

| Workflow | Trigger |
| -------- | ------- |
| **`internal/trigger-image-build.yml`** | `workflow_dispatch` (optional `branch` input; dispatches image build on that ref) |
| **`internal/trigger-ci.yml`** | `workflow_dispatch` (required `ref`; dispatches **`build-and-test.yml`**) |

### `clang-format-auto-fix.yml`

| Trigger | Notes |
| ------- | ----- |
| `workflow_dispatch` | Manual |
| `push` | **`branches-ignore`:** `dev`, `main`, `master`; **paths:** C/C++ sources and `.clang-format` |

**Job `if`:** `github.actor != 'github-actions[bot]'`. Workflow uses **`contents: write`**.

### Template `scripts/release_templates/workflows/trigger-ci.yml`

Use on core-main at **`workflows/internal/trigger-ci.yml`** (same relative **`uses:`** paths to root **`build-and-test.yml`**).

| Trigger | Notes |
| ------- | ----- |
| `push` | Branch: **`dev`** |
| `pull_request_target` | Branch: **`dev`** — default-branch workflow context; pair with care for untrusted forks |

Calls **`./.github/workflows/build-and-test.yml@${{ github.event_name == 'pull_request_target' && github.head_ref || github.ref_name }}`** so the **called** workflow file comes from the PR head on `pull_request_target`.

### Security / semantics (summary)

- **`pull_request_target`** appears in the **template** only; combining it with **`uses: …@head_ref`** matches “workflow definition from head, runner/token context from base.” **`bmt_handoff`** also excludes forks via **`head.repo.full_name == github.repository`** where applicable.

## Why there is no `.github/jobs/`

GitHub Actions does not execute files from `.github/jobs/`. Use native `workflow_call` reusable workflows under `workflows/` for reusable job-level logic.

## Repo variables vs composite inputs

Repository variables (`vars.*`, synced from Pulumi) are the **source of truth**. Workflows usually map them once on a workflow or job `env:` block (for example `GCP_PROJECT: ${{ vars.GCP_PROJECT }}`). Composite actions cannot rely on `vars` the same way, so actions such as `setup-gcp-uv` take an explicit **`gcp_project`** input — pass **`${{ env.GCP_PROJECT }}`** when the job already defines `env` from `vars`. That is one value threaded through two mechanisms, not two different project IDs.

## Why `actions/setup-gcp-uv` exists

`actions/setup-gcp-uv/action.yml` centralizes:

1. `google-github-actions/auth` (Workload Identity Federation) with **`project_id`**
2. `google-github-actions/setup-gcloud` with the same **`project_id`** and a default **`gcloud_version`** constraint for WIF
3. BMT CLI install (**`setup-bmt-cli`**: uv or release PEX)

Third-party action bumps: **Dependabot** (`.github/dependabot.yml`). Per-job `permissions` stay in each workflow job.

## GitHub Actions and Pulumi

`pulumi`/GitHub var export runs via **`just pulumi`** (local or approved runner), not from default CI here — keeps state credentials and blast radius off ephemeral runners. To add **`pulumi preview`** on PRs later, you need a chosen [state backend](https://www.pulumi.com/docs/iac/concepts/state-and-backends/) and secrets policy; treat **fork PRs** as untrusted for cloud tokens.
