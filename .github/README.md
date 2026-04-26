# `.github` Layout

This repository keeps GitHub Actions logic in the native locations that GitHub executes.

## Workflow matrix (this repo)

Root `**.github/workflows/*.yml**` (non-`internal/`): `**build-and-test-dev.yml**`, `**build-and-test.yml**`, `**bmt-handoff.yml**`, `**build-kardome-bmt-pex.yml**`, `**clang-format-auto-fix.yml**`. Everything else is under `**internal/**` (dev/ops tooling). Optional templates for consumer repos (e.g. `**trigger-ci.yml**`) live under `**scripts/release_templates/workflows/**` as references — production no longer uses a generated `**.github-release/**` bundle.


| Workflow                                         | Purpose                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `**workflows/build-and-test-dev.yml**`           | **This repo’s CI** on `push` / `pull_request` to `**dev`** / `**ci/check-bmt-gate**` / `**test/***` (plus `workflow_dispatch` / `workflow_call`); one build matrix + one handoff per event, and calls `**bmt-handoff.yml**` when the gate passes. **Intended path for BMT:** open a **PR** into `ci/check-bmt-gate` so the full handoff + cloud BMT + BMT Gate run against the PR head with normal GitHub review UI; `push` remains so merges (and bots) still land CI after merge. |
| `**workflows/build-and-test.yml`**               | Reusable CI for **core-main** (and manual runs): `workflow_dispatch` + `workflow_call` only — thin `**trigger-ci.yml`** (template or copy) supplies `push` / `pull_request_target`                                                                                                                                                                                                                                                                                                  |
| `**workflows/bmt-handoff.yml**`                  | Reusable BMT handoff: context, upload matrix, **Workflows** dispatch (`invoke-workflow`)                                                                                                                                                                                                                                                                                                                                                                                            |
| `**workflows/clang-format-auto-fix.yml`**        | C/C++ format automation on selected branches                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| `**workflows/build-kardome-bmt-pex.yml**`        | On tag `**bmt-v***`: build `**dist/bmt.pex**` and attach to the GitHub Release on **klugman-yanai/bmt-gcloud** (must be top-level so push-tag triggers it; subdirs of `.github/workflows/` are not scanned for triggers)                                                                                                                                                                                                                                                            |
| `**workflows/internal/trigger-ci.yml`**          | Manual: `gh workflow run` **build-and-test** on a chosen ref                                                                                                                                                                                                                                                                                                                                                                                                                        |
| `**workflows/internal/bmt-image-build.yml`**     | Packer image build; also on path-filtered `push`                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `**workflows/internal/trigger-image-build.yml**` | Manual: dispatch image build on a branch                                                                                                                                                                                                                                                                                                                                                                                                                                            |


**BMT CLI:** the canonical CI entry point is the release `**bmt.pex`**, downloaded by `**[setup-bmt-pex](./actions/setup-bmt-pex/action.yml)**` and invoked via `**"$BMT_PEX_PATH" …**`. In `**bmt-handoff.yml**`, composites use **repo-relative** `./.github/actions/...` so the PEX tag matches the **same ref** as the reusable workflow (`@bmt-handoff` rolling tag or `@bmt-v*`). `**setup-bmt-pex`** resolves `github.action_ref`, with `**bmt-handoff` → latest `bmt-v***` for downloads. Self-CI image-build / dev-tooling workflows still use `**uv run**` + `**[setup-bmt-cli](./actions/setup-bmt-cli/action.yml)**` + `**[setup-gcp-uv](./actions/setup-gcp-uv/action.yml)**`, which sync the `**ci/**` workspace ([`ci/README.md`](../ci/README.md)).

### Orchestrator image (`runtime/` → Cloud Run)

Changes under `**runtime/**` ship in the `**bmt-orchestrator**` container (`runtime/Dockerfile`), not via bucket `plugins/` sync. After `**just image**` (or `**just docker-build**` + `**just docker-push**`), ensure `**bmt-control**`, `**bmt-task-standard**`, and `**bmt-task-heavy**` use the new image (e.g. `**pulumi up**` or `**gcloud run jobs update … --image=…:latest**` per region). Otherwise plan/task jobs can keep running an older digest.

## Production (Kardome-org/core-main)

**Preferred (cross-repo, zero vendoring):** In the production repo, call the reusable workflow directly:

```yaml
bmt-handoff:
  needs: build-release
  if: <gate>
  permissions:
    contents: read
    actions: read
    id-token: write
    statuses: write
    pull-requests: read
  uses: klugman-yanai/bmt-gcloud/.github/workflows/bmt-handoff.yml@bmt-handoff
  with:
    cloud_run_region: europe-west4
    bmt_status_context: BMT Gate
    bmt_pex_repo: klugman-yanai/bmt-gcloud
    force_pass: false
```

Use a **plain Git ref** on `uses:` (no `${{ }}`): `**@bmt-handoff`** is a rolling tag updated on every `bmt-v*` PEX release. Prefer `**@bmt-v***` to freeze. Docker-style `:latest` is not valid in Actions.

When this job runs **in the same workflow** as the build that uploaded `runner-*` artifacts, omit optional handoff inputs (`ci_run_id`, head SHA/branch, event, PR) — they resolve from the caller `github` context. **Always** pass `with:` for `cloud_run_region`, `bmt_status_context`, `bmt_pex_repo`, and `force_pass` (values live in caller YAML, not repo variables). For manual `workflow_dispatch` of handoff alone, set `ci_run_id` to the build run id.

The workflow is **PEX-only and caller-tree independent** — it loads `**[setup-bmt-pex](./actions/setup-bmt-pex/action.yml)`** and sibling composites from **the same ref** as the workflow file. Each `build-release` matrix leg that produces a `runner-<preset>` artifact in **this** repo may additionally use `**setup-bmt-pex`** to run `"$BMT_PEX_PATH" preset stage-release-runner` / `compute-info` before `actions/upload-artifact`.

**Caller repo variables** (minimal): `**GCS_BUCKET`**, `**GCP_WIF_PROVIDER**`, `**GCP_SA_EMAIL**`, `**GCP_PROJECT**` (see `[docs/configuration.md](../docs/configuration.md)`).

`**workflows/internal/***` here is for **bmt-gcloud** testing only — not required on core-main unless you copy a specific template (e.g. `**trigger-ci.yml`** from `**scripts/release_templates/workflows/**`).

## Will it work in production if only two workflow files are added?

**No.** Handoff depends on local **composite actions**, optional **`bmt-failure-fallback`**, and **repo variables**. The **BMT CLI** comes from `**bmt.pex`** (release) via `**setup-bmt-pex**` in normal integrations — the consumer does not vendor `**ci/**` under `.github/`, but workflows and actions must still exist in the consumer repo (or be referenced cross-repo). See the section above.

## This repo’s workflow layout

- **workflows/** — **Root:** `**build-and-test-dev.yml`**, `**build-and-test.yml**`, `**bmt-handoff.yml**`, `**build-kardome-bmt-pex.yml**`, `**clang-format-auto-fix.yml**`. `**internal/**` — dev-only: trigger-ci, bmt-image-build, trigger-image-build.
- **actions/** — `bmt-prepare-context`, `bmt-filter-handoff-matrix`, `bmt-write-summary`, `bmt-failure-fallback`, `**setup-bmt-pex`** (PEX-only; cross-repo callable), `setup-bmt-cli` + `setup-gcp-uv` (uv-mode for self-CI), `bmt-get-pex`
- `**ci/**` — **`kardome-bmt`** package ([`ci/README.md`](../ci/README.md))

## Which workflow runs CI?

- **bmt-gcloud (this repo):** `**build-and-test-dev.yml`** runs on `push` / `pull_request` / `workflow_dispatch` / `workflow_call` (branches `dev`, `ci/check-bmt-gate`, `test/*`). One workflow per event — no `**pull_request_target**`, no sibling PR trigger. **Use a PR into `ci/check-bmt-gate` as the default way to trigger and inspect the full BMT pipeline** (Checks tab, PR annotations); rely on `push` for post-merge continuity, not as the primary substitute for a PR when you are validating a change.
- **Production (core-main):** Typically `**internal/trigger-ci.yml`** (from `**scripts/release_templates/workflows/trigger-ci.yml**`) on `push` / `pull_request_target` to `**dev**`, which `**workflow_call`s** `**build-and-test.yml`**. `**build-and-test.yml**` then calls `**bmt-handoff.yml**` when eligible.
- **Manual / sandbox:** `**internal/trigger-ci.yml`** dispatches `**build-and-test.yml**` on an arbitrary ref.

## Workflow and job triggers (inventory)

**Reusable workflow context:** For `workflow_call`, the `**github` context in the called workflow matches the caller** ([docs](https://docs.github.com/en/actions/reference/reusable-workflows-reference#github-context)). Expressions in `**build-and-test.yml`** that use `github.event_name` / `github.event.pull_request` therefore see the **caller’s** event (e.g. `pull_request_target` from the template trigger).

### `build-and-test.yml`


| Trigger             | Notes                                                                             |
| ------------------- | --------------------------------------------------------------------------------- |
| `workflow_dispatch` | Manual                                                                            |
| `workflow_call`     | Invoked by template `**trigger-ci`**, `**internal/trigger-ci**`, or other callers |


**Job gate — `bmt_handoff`:** runs only if `build_release` succeeded or was skipped **and** (same-repo PR or not a PR) **and** either PR (`pull_request` or `pull_request_target`) with `**base_ref`** in `dev`  `ci/check-bmt-gate`, or non-PR with `**ref_name**` in `dev`  `ci/check-bmt-gate`. Checkouts honor `**pull_request_target**` head repo/SHA when that event applies.

### `build-and-test-dev.yml`


| Trigger             | Notes                                          |
| ------------------- | ---------------------------------------------- |
| `push`              | Branches: `dev`, `ci/check-bmt-gate`, `test/*` |
| `pull_request`      | Same branch set (aligned with `push`)          |
| `workflow_dispatch` | Manual                                         |
| `workflow_call`     | Reusable entry                                 |


**Job gate — `bmt_handoff`:** same fork rule as `**build-and-test.yml`**. **PRs** (`pull_request`) into `dev`, `ci/check-bmt-gate`, or `test/*` fire handoff from this workflow. **Push / `workflow_dispatch`:** handoff when `**ref_name`** is `dev`, `ci/check-bmt-gate`, or starts with `**test/**`. Checkouts use `**pull_request**` + head SHA when applicable.

### `bmt-handoff.yml`


| Trigger             | Notes                                                                                                                          |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| `workflow_dispatch` | Inputs: `ci_run_id`, `head_sha`, `head_branch`, `head_event`, `pr_number`, `available_artifacts`, region, status context, etc. |
| `workflow_call`     | Same inputs from CI                                                                                                            |


**Notable job `if`:** `publish_runners` when `matrix_publish_keys != '[]'`; `start_bmt_workflow` when not cancelled, context job succeeded, and `publish_runners` succeeded or skipped; steps gated on `matrix.bmt_supported` and `invoke-workflow` outcome.

### `internal/bmt-image-build.yml`


| Trigger                               | Notes                                                                                      |
| ------------------------------------- | ------------------------------------------------------------------------------------------ |
| `workflow_dispatch` / `workflow_call` | Packer inputs                                                                              |
| `push`                                | Branches: `main`, `ci/check-bmt-gate`, `dev`; **paths:** `infra/packer/`**, `runtime/**` |


### `internal/trigger-image-build.yml` / `internal/trigger-ci.yml`


| Workflow                               | Trigger                                                                           |
| -------------------------------------- | --------------------------------------------------------------------------------- |
| `**internal/trigger-image-build.yml**` | `workflow_dispatch` (optional `branch` input; dispatches image build on that ref) |
| `**internal/trigger-ci.yml**`          | `workflow_dispatch` (required `ref`; dispatches `**build-and-test.yml**`)         |


### `clang-format-auto-fix.yml`


| Trigger             | Notes                                                                                        |
| ------------------- | -------------------------------------------------------------------------------------------- |
| `workflow_dispatch` | Manual                                                                                       |
| `push`              | `**branches-ignore`:** `dev`, `main`, `master`; **paths:** C/C++ sources and `.clang-format` |


**Job `if`:** `github.actor != 'github-actions[bot]'`. Workflow uses `**contents: write`**.

### Template `scripts/release_templates/workflows/trigger-ci.yml`

Use on core-main at `**workflows/internal/trigger-ci.yml**` (same relative `**uses:**` paths to root `**build-and-test.yml**`).


| Trigger               | Notes                                                                                   |
| --------------------- | --------------------------------------------------------------------------------------- |
| `push`                | Branch: `**dev**`                                                                       |
| `pull_request_target` | Branch: `**dev**` — default-branch workflow context; pair with care for untrusted forks |


Calls `**./.github/workflows/build-and-test.yml@${{ github.event_name == 'pull_request_target' && github.head_ref || github.ref_name }}**` so the **called** workflow file comes from the PR head on `pull_request_target`.

### Security / semantics (summary)

- `**pull_request_target`** appears in the **template** only; combining it with `**uses: …@head_ref`** matches “workflow definition from head, runner/token context from base.” `**bmt_handoff**` also excludes forks via `**head.repo.full_name == github.repository**` where applicable.

## Why there is no `.github/jobs/`

GitHub Actions does not execute files from `.github/jobs/`. Use native `workflow_call` reusable workflows under `workflows/` for reusable job-level logic.

## Repo variables vs composite inputs

Repository variables (`vars.*`, synced from Pulumi) are the **source of truth**. Workflows usually map them once on a workflow or job `env:` block (for example `GCP_PROJECT: ${{ vars.GCP_PROJECT }}`). Composite actions cannot rely on `vars` the same way, so actions such as `setup-gcp-uv` take an explicit `**gcp_project`** input — pass `**${{ env.GCP_PROJECT }}**` when the job already defines `env` from `vars`. That is one value threaded through two mechanisms, not two different project IDs.

## Why `actions/setup-gcp-uv` exists

`actions/setup-gcp-uv/action.yml` centralizes:

1. `google-github-actions/auth` (Workload Identity Federation) with `**project_id**`
2. `google-github-actions/setup-gcloud` with the same `**project_id**` and a default `**gcloud_version**` constraint for WIF
3. BMT CLI install (`**setup-bmt-cli**`: uv or release PEX)

Third-party action bumps: **Dependabot** (`.github/dependabot.yml`). Per-job `permissions` stay in each workflow job.

## GitHub Actions and Pulumi

`pulumi`/GitHub var export runs via `**just pulumi`** (local or approved runner), not from default CI here — keeps state credentials and blast radius off ephemeral runners. To add `**pulumi preview**` on PRs later, you need a chosen [state backend](https://www.pulumi.com/docs/iac/concepts/state-and-backends/) and secrets policy; treat **fork PRs** as untrusted for cloud tokens.