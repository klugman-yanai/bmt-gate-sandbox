# `.github` Layout

This repository keeps GitHub Actions logic in the native locations that GitHub executes.

## Workflow matrix (this repo)

Root **`.github/workflows/*.yml`** includes reusable CI (`build-and-test*.yml`, **`bmt-handoff.yml`**), thin triggers (**`trigger-ci.yml`**, **`trigger-ci-pr.yml`**), **`bmt-cancel-on-pr-close.yml`**, and **`clang-format-auto-fix.yml`**. Dev/ops-only workflows live under **`workflows/internal/`**. The **release bundle** (`.github-release/`) ships root workflows from `.github/workflows/` (excluding `*-dev.yml`) plus **`workflows/internal/`** from **`scripts/release_templates/workflows/`** only (e.g. **`trigger-ci.yml`** for **core-main**, **`code-owner-enforcement.yml`**). The in-repo **`internal/trigger-ci.yml`** (dev thin trigger) is **not** copied into the bundle.

| Workflow | Purpose |
| -------- | ------- |
| **`workflows/build-and-test-dev.yml`** | Reusable CI: **`workflow_dispatch`** + **`workflow_call`** only — same shape as **`build-and-test.yml`**. PR-driven runs use **`internal/trigger-ci.yml`** (`pull_request` into `dev` / `ci/check-bmt-gate` / `test/*`) which **`workflow_call`s** this file at the PR head ref; calls **`bmt-handoff.yml`** when `bmt_handoff.if` passes |
| **`workflows/build-and-test.yml`** | Reusable CI for **core-main** (and manual runs): `workflow_dispatch` + `workflow_call` only — release **`trigger-ci-pr.yml`** drives PRs to **`dev`** via `pull_request_target` (same-repo **`build` job** only); **`trigger-ci.yml`** is dispatch-only |
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

- **Missing local actions** — `bmt-handoff.yml` uses `bmt-prepare-context`, `setup-gcp-uv`, **`setup-uv-repo`** (via `setup-gcp-uv`), `bmt-filter-handoff-matrix`, `bmt-failure-fallback`, and `bmt-write-summary` under `.github/actions/`. (`check-image-up-to-date` exists for optional image gates; it is not referenced by the current handoff workflow in this repo.)
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
- **actions/** — Local composite actions: `bmt-prepare-context`, `bmt-filter-handoff-matrix`, `bmt-write-summary`, `bmt-failure-fallback`, `setup-gcp-uv`, **`setup-uv-repo`** (single pin for `astral-sh/setup-uv` + uv CLI `version:`; `setup-gcp-uv` calls it), **`upload-artifact-repo`** / **`download-artifact-repo`** (SHA pins for `actions/upload-artifact` v7 and `actions/download-artifact` v5), **`cache-repo`** (SHA pin for `actions/cache` v4). **`actions/checkout@…`** is pinned **in each workflow** (not a composite): the runner must materialize the repo with the official checkout action **before** any `uses: ./.github/actions/...` step can load.
- **`.github/bmt/`** — BMT CLI (`uv run bmt …`) and config used by workflows ([`README.md`](bmt/README.md))

## Which workflow runs CI?

- **bmt-gcloud (this repo):** **`internal/trigger-ci.yml`** is the event entry (`pull_request` into `dev` / `ci/check-bmt-gate` / `test/*`, plus **`workflow_dispatch`**). It **`workflow_call`s** **`build-and-test-dev.yml`** at the PR head ref — same **thin-trigger → reusable CI** pattern as production, but **`pull_request`** (same-repo) instead of **`pull_request_target`**. Optional: **`internal/trigger-ci-dispatch.yml`** to dispatch **`build-and-test-dev.yml`** on any ref via **`gh`**. **`build-and-test-dev.yml`** also accepts direct **`workflow_dispatch`** / **`workflow_call`**.
- **Production (core-main):** After release copy, **PR** CI is driven by bundle **`internal/trigger-ci-pr.yml`** (source: **`scripts/release_templates/workflows/trigger-ci-pr.yml`**) on **`pull_request_target`** to **`dev`**, which **`workflow_call`s** **`build-and-test.yml`** then **`bmt-handoff.yml`**. **`internal/trigger-ci.yml`** (source: **`scripts/release_templates/workflows/trigger-ci.yml`**) is **`workflow_dispatch`**-only for ad-hoc builds. No **`push`** to **`dev`** — direct pushes to **`dev`** are assumed forbidden.

### `pull_request_target`, forks, and why the release PR trigger gates `build`

GitHub documents that **`pull_request_target` runs in the base repo context** (default branch ref for `GITHUB_REF` / `GITHUB_SHA`) while still exposing the PR head in **`github.event.pull_request`**. That combination is appropriate for **commenting / labeling** on fork PRs without checking out the fork, but it is **risky to check out and build the PR head** on this event while the workflow also has **broad permissions or `secrets: inherit`**, because the job runs **untrusted code** with those credentials ([events: `pull_request_target`](https://docs.github.com/en/actions/using-workflows/events-that-trigger-workflows)).

**Release template** [`scripts/release_templates/workflows/trigger-ci-pr.yml`](../scripts/release_templates/workflows/trigger-ci-pr.yml) uses **Option A**: the **`build` job runs only when** `github.event.pull_request.head.repo.full_name == github.repository` (same-repo PRs). **Fork PRs** therefore do not execute **`build-and-test.yml`** on that trigger; provide fork CI via a separate workflow on **`pull_request`** (build from the merge ref / head in a restricted token model) if you need it — **Option B** for consumers who want all PRs built without using `pull_request_target` for the build path.

The **`bmt` job** in the same template also requires the same-repo condition before calling **`bmt-handoff.yml`**, so BMT never runs for fork PRs from this file. **`build-and-test.yml`** still uses head repo/SHA in `actions/checkout` when the caller event is **`pull_request_target`**, so same-repo PRs behave as before.

### Caching and PRs

**Gradle** (and similar) caches use **`actions/cache`** via **`cache-repo`**. Cache keys are scoped by lockfiles and `runner.os`; do not store secrets in cached paths. For **fork PRs** on any workflow, treat caches as **untrusted input** where GitHub allows PRs to populate or influence keys ([dependency caching](https://docs.github.com/en/actions/using-workflows/caching-dependencies-to-speed-up-workflows)) — the release **`build` gate** above avoids running the heavy build path for forks on `pull_request_target`.

### Hosted runner image

Linux jobs use **`ubuntu-22.04`** (pinned LTS) for reproducible toolchains (CMake/apt installs in **`build-and-test.yml`**). Prefer bumping this label intentionally (and re-smoking builds) rather than using **`ubuntu-latest`**.

### Standard GCP handoff job permissions

Jobs in **`bmt-handoff.yml`** that call **`setup-gcp-uv`** need **`id-token: write`** for WIF plus the least extra scopes those steps use (typically **`contents: read`**, **`actions: read`**, **`pull-requests: read`** where the BMT CLI lists PRs). Keep **`permissions:`** at **job** level; composites cannot replace job-level `permissions`. Copy the block from an existing handoff job when adding a new job that authenticates to GCP the same way.

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

#### BMT run IDs and GCS paths (operators)

- **`workflow_run_id`** (also `BMT_WORKFLOW_RUN_ID` in Cloud Run) is the GitHub Actions **dispatch job** run id: `WORKFLOW_RUN_ID` or `GITHUB_RUN_ID` on the **`bmt-handoff.yml` `dispatch` job** that runs `uv run bmt dispatch invoke-workflow`. It is **not** the caller build workflow’s `ci_run_id`.
- **`ci_run_id`** (handoff input / `BMT_CI_RUN_ID` in Plan) is the **caller** workflow run used to list **`runner-*`** artifacts and correlate the upstream CI build.
- **GCS** (bucket root = stage mirror): execution plan `triggers/plans/{workflow_run_id}.json`; reporting metadata `triggers/reporting/{workflow_run_id}.json`; PR “active execution” pointer `triggers/reporting/pr-active/{pr_number}.json`.

#### Cloud Logging (Cloud Run jobs)

Each container run logs one JSON line with `"bmt_run_bootstrap":true`, `bmt_mode`, `workflow_run_id`, `task_profile`, `task_index`, and `github_repository` when present. In **Logs Explorer** (Cloud Run job logs), use a query that matches log text, e.g. `textPayload=~"bmt_run_bootstrap"` or `textPayload=~"\"workflow_run_id\":\"12345\""` for a known GitHub Actions dispatch run id.

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

## Why `actions/setup-gcp-uv` and `actions/setup-uv-repo` exist

**`setup-uv-repo`** is the **only** place that pins **`astral-sh/setup-uv@…`** and the **uv CLI** `version:` string. Workflows and composites that need `uv` without GCP (e.g. **`validate-release-bundle.yml`**, **`bmt-prepare-context`**) call **`setup-uv-repo`** directly. Bump the action SHA / CLI version there only.

**`build-and-test.yml`** runs **`actions/checkout@…`** (pinned SHA) then later **`setup-uv-repo`** for the BMT packaging phase.

**`setup-gcp-uv`** chains WIF + gcloud, then **`setup-uv-repo`** when **`install_uv`** is true:

1. `google-github-actions/auth` (Workload Identity Federation) with **`project_id`**
2. `google-github-actions/setup-gcloud` with the same **`project_id`** and a default **`gcloud_version`** constraint for WIF
3. **`setup-uv-repo`** (cached **`uv sync`**)

Third-party action bumps: **Dependabot** (`.github/dependabot.yml`). Per-job `permissions` stay in each workflow job.

**`actions/checkout@…`** cannot be wrapped as the **first** step by a **local** composite: GitHub needs the official action to populate `$GITHUB_WORKSPACE` before **`uses: ./.github/actions/...`** resolves. Keep the same **full commit SHA** in every workflow that checks out (search the tree when bumping).

**Still duplicated by design (GitHub limitations):** `ubuntu-22.04`, the checkout SHA lines above, and repeated **`workload_identity_provider` / `service_account` / `gcp_project`** `with:` blocks on each **`setup-gcp-uv`** step — workflows cannot import shared YAML fragments.

## GitHub Actions and Pulumi

`pulumi`/GitHub var export runs via **`just workspace pulumi`** (local or approved runner), not from default CI here — keeps state credentials and blast radius off ephemeral runners. To add **`pulumi preview`** on PRs later, you need a chosen [state backend](https://www.pulumi.com/docs/iac/concepts/state-and-backends/) and secrets policy; treat **fork PRs** as untrusted for cloud tokens.

## Optional CODEOWNERS

To require review for specific paths (e.g. workflows or `gcp/image/`), add a `.github/CODEOWNERS` file and enable **Require review from Code Owners** on protected branches. See [About code owners](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners).

## Auth boundaries

- **WIF + service account** authenticate workflow jobs to GCP.
- **github.token / GITHUB_TOKEN** is only used in workflow paths that call GitHub APIs directly (for example gh workflow run, gh variable set, or fallback status posting).
- **GitHub App credentials** are runtime-only and are loaded by the **Cloud Run** runtime after dispatch; they are not part of the reusable workflow contract.
