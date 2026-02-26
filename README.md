# bmt-cloud-dev

Development repo for the BMT (Benchmark/Milestone Testing) cloud pipeline. This repo owns the BMT workflow, VM watcher and orchestrator logic, and the GCS bucket contract used by GitHub Actions. Local devtools provide sync, upload, and validation against the bucket.

## What Lives Here

- **remote/code/** — Source of truth for deployable VM code/config/templates (watcher, orchestrator, managers, bootstrap). Synced manually to `gs://<bucket>/<parent>/code/`.
- **remote/runtime/** — Source of truth for runtime seed artifacts (runner binaries + input placeholders only; no local WAV corpora).
- **data/** — Local-only large datasets used for local runs and explicit upload operations.
- **.github/workflows/** — `build-and-test.yml` (prod-locked build workflow with append-only BMT tail) and `bmt.yml` (BMT handoff control-plane).
- **.github/scripts/** — `ci_driver.py` and `ci/commands/` for matrix, trigger, start-vm, handshake, etc. All GCP interaction is via `gcloud` CLI (subprocess), not an SDK.
- **devtools/** — Local scripts for bucket sync, runner/wav upload, contract validation, local BMT runs, and env/repo-vars inspection.

## Repository Layout Contract

This repository uses a strict layout contract:

- **Authoritative source trees**
  - `remote/code` => deployable VM code/config/bootstrap mirrored to bucket `code/`.
  - `remote/runtime` => runtime seed mirror for bucket `runtime/` (runners + placeholders only).
- **Local-only trees**
  - `data` => large WAV corpora (not stored under `remote/runtime` locally).
  - `.local/diagnostics` => ad-hoc diagnostics and baseline snapshots (non-authoritative, gitignored).
- **Operational code**
  - `.github/` => workflows and CI command wrappers.
  - `devtools/` => local operator tooling.
  - `docs/` => contracts, runbooks, reference artifacts.

If a file does not fit these categories, it should not be added at repo root.

## Workflow (Current)

1. **build-and-test.yml** — Prod-locked workflow: immutable base mirrors `original_build-and-test.yml`; only append-only BMT extension is editable. It produces runner artifacts and dispatches `bmt.yml` via `workflow_dispatch` with `ci_run_id`, `head_sha`, `head_branch`, `head_event`, optional `pr_number`.
2. **bmt.yml** — Handoff workflow only: uploads runners to runtime namespace, writes one run trigger to `<runtime-root>/triggers/runs/<workflow_run_id>.json`, syncs VM metadata, starts the VM, waits for handshake ack, writes handoff summary, then **exits**. It does not post final BMT verdicts.
3. **VM** — Runs independently: polls for the trigger, runs legs via `root_orchestrator` and per-project `bmt_manager`, updates `current.json` pointers and prunes snapshots, posts final commit status and completes the Check Run, then deletes the trigger. Optionally exits after one run so the VM can stop itself.

Final pass/fail is always posted by the VM. Branch protection should require the status context named by `BMT_STATUS_CONTEXT` (default: `BMT Gate`). Use PR checks/comments for the BMT outcome; the workflow run indicates handoff health only.

Manual VM starts are permitted only for debugging, maintenance, or testing. Routine starts should come from `bmt.yml`.

`build-and-test.yml` run summary in the BMT tail reports dispatch handoff health only. Final BMT pass/fail/completion is VM-owned and appears in PR checks/comments.

## Configuration

Configuration is defined in **config/env_contract.json**. Optional overrides: **config/repo_vars.toml**.

| Required repo vars | Optional (common) |
|--------------------|-------------------|
| `GCS_BUCKET`, `GCP_WIF_PROVIDER`, `GCP_SA_EMAIL`, `GCP_PROJECT`, `GCP_ZONE`, `BMT_VM_NAME` | `BMT_BUCKET_PREFIX`, `BMT_PROJECTS`, `BMT_STATUS_CONTEXT`, `BMT_HANDSHAKE_TIMEOUT_SEC` |

- `BMT_PROJECTS` default: all non-embedded `*_gcc_Release` presets.
- Tooling enforces consistency between repo vars and VM metadata for `GCS_BUCKET` and `BMT_BUCKET_PREFIX`. Use canonical names only (no aliases like `VM_NAME`/`BUCKET`); set `GCP_PROJECT` explicitly.
- VM GitHub auth is App-only: each enabled repository mapping in `remote/code/config/github_repos.json` must have `<prefix>_ID`, `<prefix>_INSTALLATION_ID`, and `<prefix>_PRIVATE_KEY` available on the VM.

Useful commands:

```bash
just sync-vm-metadata
just start-vm
just wait-handshake <workflow_run_id>
just repo-vars-check
just repo-vars-apply
just show-env
just validate-vm-vars
just check-build-and-test-base
```

See [docs/configuration.md](docs/configuration.md) for full env contract, VM metadata, and secrets.

## GCS Contract

Use:
- `<parent> = normalize(BMT_BUCKET_PREFIX)` (may be empty)
- `<code-root> = gs://<bucket>/<parent>/code` (or `gs://<bucket>/code` when parent is empty)
- `<runtime-root> = gs://<bucket>/<parent>/runtime` (or `gs://<bucket>/runtime` when parent is empty)

`remote/code` sync is manual and authoritative for `<code-root>` only.
Runtime artifacts must stay under `<runtime-root>` only.

- **`<code-root>/...`** — deployable code/config/templates mirrored from local `remote/code`.
- **`<code-root>/_tools/uv/linux-x86_64/uv`** — pinned UV artifact uploaded during manual sync.
- **`<code-root>/_tools/uv/linux-x86_64/uv.sha256`** — pinned UV checksum tracked in repo and verified at VM boot.
- **`<runtime-root>/triggers/runs/<workflow_run_id>.json`** — CI writes one run trigger; VM deletes after processing.
- **`<runtime-root>/triggers/acks/<workflow_run_id>.json`** — VM handshake ack.
- **`<runtime-root>/triggers/status/<workflow_run_id>.json`** — VM progress heartbeat.
- **`<runtime-root>/<project>/runners/<preset>/...`** — Runner bundles uploaded by workflow/devtools.
- **`<runtime-root>/<results_prefix>/current.json`** — Canonical pointer (`latest`, `last_passing`); updated by watcher after all legs.
- **`<runtime-root>/<results_prefix>/snapshots/<run_id>/...`** — Per-run artifacts from manager (`latest.json`, `ci_verdict.json`, logs).

## Local Usage

**Local BMT batch** (no cloud VM):

```bash
uv run python devtools/bmt_run_local.py \
  --bmt-id false_reject_namuh \
  --jobs-config remote/code/sk/config/bmt_jobs.json \
  --runner remote/runtime/sk/runners/kardome_runner \
  --runtime-root remote/runtime \
  --dataset-root data/sk/inputs/false_rejects \
  --workers 4
```

**Bucket tools** (set `GCS_BUCKET`):

```bash
GCS_BUCKET="<bucket>" uv run python devtools/bucket_sync_remote.py
GCS_BUCKET="<bucket>" uv run python devtools/bucket_verify_remote_sync.py
GCS_BUCKET="<bucket>" uv run python devtools/bucket_sync_runtime_seed.py
GCS_BUCKET="<bucket>" uv run python devtools/bucket_verify_runtime_seed_sync.py
GCS_BUCKET="<bucket>" uv run python devtools/bucket_upload_runner.py --runner-path <path>
GCS_BUCKET="<bucket>" uv run python devtools/bucket_upload_wavs.py --source-dir data/sk/inputs/false_rejects
GCS_BUCKET="<bucket>" uv run python devtools/bucket_validate_contract.py [--require-runner]
```

Set `BMT_UV_TOOL_PATH=/path/to/uv` to override which local uv binary is uploaded to `<code-root>/_tools/...` (must match pinned checksum in `remote/code/_tools/uv/linux-x86_64/uv.sha256`).

More: [docs/development.md](docs/development.md) for setup, testing, and Justfile recipes.

## Local Diagnostics Runbook

- Write ad-hoc diagnostics to `.local/diagnostics/` only.
- Do not commit local diagnostics artifacts.
- Retain only what is needed for active incident triage; prune old snapshots periodically.

## Notes

- `build-and-test.yml` base is locked to `original_build-and-test.yml`; only the append-only BMT extension block is editable.
- `ci_driver.py wait` and `ci_driver.py gate` exist for manual/local validation only; they are not used in `bmt.yml`.
- VM bootstrap and auth: [remote/code/bootstrap/README.md](remote/code/bootstrap/README.md).

## Test vs Production

When moving to production, expect to change:

- GitHub App credentials and repo mapping (`remote/code/config/github_repos.json`).
- Status context name (`BMT_STATUS_CONTEXT`) for branch protection.

## Documentation

| Doc | Description |
|-----|--------------|
| [README.md](README.md) | This file — overview, workflow, config, local usage. |
| [CLAUDE.md](CLAUDE.md) | AI/maintainer guide — code layout, time/clocks, devtools, lint/test, CI and VM layout, env vars. |
| [docs/architecture.md](docs/architecture.md) | Current architecture — trigger-and-stop, GCS contract, client/VM scripts. |
| [docs/implementation.md](docs/implementation.md) | How it works today — CLI-first, data structures, auth, limitations. |
| [docs/development.md](docs/development.md) | Setup, testing, lint/typecheck, Justfile, deploy. |
| [docs/configuration.md](docs/configuration.md) | Env contract, repo vars, VM metadata, secrets, bucket layout. |
| [docs/communication-flow.md](docs/communication-flow.md) | How commit status and Check Runs reach the PR; failure handling. |
| [docs/diagrams.md](docs/diagrams.md) | Mermaid and diagram sources. |
| [docs/github-app-permissions.md](docs/github-app-permissions.md) | GitHub App permissions and how to check them. |
| [docs/github-actions-and-cli-tools.md](docs/github-actions-and-cli-tools.md) | Actions job summaries, re-run, debug; `gh` CLI. |
| [docs/plans/future-architecture.md](docs/plans/future-architecture.md) | Planned changes (SDK, Pydantic, bmt_lib, PR comments). |
| [remote/README.md](remote/README.md) | Canonical local bucket mirror policy (`remote/code`, `remote/runtime`). |
