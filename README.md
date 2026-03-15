# bmt-gcloud

**Purpose:** This repo exists so you can **reliably test production CI locally using the real VM and GCS** — no mocks. That is the main goal. Supporting that goal are:

1. **Mirror of gcp (VM/GCS)** — The `gcp/` directory is the local mirror of the bucket namespace. Sync/pull from GCS so you develop against the same code and layout the VM uses. See [gcp/README.md](gcp/README.md).
2. **Test suite** — Unit and integration tests for BMT logic, gate, pointer/snapshot flow, and CI commands. Run without GCS/VM when possible; use real bucket/VM when you need to validate the full path.
3. **Dev QoL tools** — Just recipes, tools (sync, upload, validate, local BMT, monitor), and repo-vars/VM helpers for managing BMTs and debugging handoff.

Development repo for the BMT (Benchmark/Milestone Testing) cloud pipeline. This repo owns the BMT workflow, VM watcher and orchestrator logic, and the GCS bucket contract used by GitHub Actions.

## Features

- **Trigger-and-stop handoff** — CI writes one run trigger, starts the VM, waits for handshake ack, then exits. The VM runs BMT legs and posts final outcome.
- **Commit status and Check Run** — VM posts pending then success/failure commit status and creates/updates a Check Run for progress and results. Branch protection gates on the status context (`BMT_STATUS_CONTEXT`, from Pulumi).
- **Pointer-based results** — `current.json` points to latest and last-passing run; per-run artifacts live under `snapshots/<run_id>/`. Baseline for gate comparison comes from last-passing snapshot.
- **PR closure and supersede** — Closed or superseded PR runs are skipped or cancelled without promoting pointers. See [docs/github-and-ci.md](docs/github-and-ci.md) and [docs/architecture.md](docs/architecture.md).

## Safety and reliability

- **Handshake validation** — Workflow waits for VM ack with clear failure reasons (`trigger_missing`, `vm_not_running`, `ack_not_written`, etc.). See [docs/architecture.md](docs/architecture.md#implementation--data-flow).
- **PR closed/superseded** — Before pickup: run skipped. During execution: current leg finishes, remaining legs skipped, signals finalized as cancelled; no pointer promotion for superseded runs.
- **Fail-open** — PR state API errors do not block execution.
- **Workflow cleanup** — On handshake failure, workflow removes trigger/ack/status objects.

## Dev quality of life

- **Unified CLI** — `uv run python -m tools --help` for all dev commands (bucket, pulumi, repo, build, bmt). **Just recipes** are thin wrappers: `just test`, `just deploy`, `just monitor`, etc. Run `just` for the list.
- **GitHub CLI** — `gh pr checks --watch` to wait for BMT and other checks; `gh run watch <run_id>` to follow a workflow run.
- **Job summaries** — Workflow runs write handoff and routing summaries to the Actions run summary.

See [docs/development.md](docs/development.md) and [docs/github-and-ci.md](docs/github-and-ci.md).

## Monitoring (GitHub Actions and VM runtime)

- **Handoff vs BMT outcome** — Workflow run success = handoff completed. Final BMT pass/fail is VM-owned and appears in PR **Checks** and **Comments**.
- **Live TUI** — `just monitor` (or `just monitor --run-id <id>`) shows trigger, ack, status, and VM/GCS state; useful when handshake fails.
- **CLI inspection** — `just vm-check <run_id>` shows trigger, ack, and VM serial output for a run (read-only; does not start the VM).

See [docs/github-and-ci.md](docs/github-and-ci.md).

## BMT management

- **Pointer** — `current.json` at `<runtime-root>/<results_prefix>/` holds `latest` and `last_passing` run IDs; updated by the watcher after all legs.
- **Snapshots** — Each run writes `snapshots/<run_id>/latest.json`, `ci_verdict.json`, and logs. Gate reads baseline from the last-passing snapshot.
- **Retention** — Only snapshots referenced by the pointer are kept; watcher prunes the rest.

See [docs/architecture.md](docs/architecture.md#results-contract).

## Performance and cost

- **VM idle-then-terminate** — The VM runs with `--exit-after-run` and `--idle-timeout-sec` (default 600). After each run it stays up for up to that many seconds waiting for another trigger; if none arrives, it exits and the startup script stops the instance. Set `BMT_IDLE_TIMEOUT_SEC` (e.g. in VM metadata) to tune; use `0` to exit immediately after one run.
- **Reuse RUNNING VMs** — When no TERMINATED VM is available, the workflow reuses a RUNNING VM (no stop/start): it writes the trigger only; the already-running watcher picks it up. Consecutive runs within the idle window avoid cold boot. Handshake uses `BMT_HANDSHAKE_TIMEOUT_SEC_REUSE_RUNNING` when reusing.
- **Snapshot retention** — Only latest and last_passing snapshot dirs retained per results prefix; trigger/ack/status metadata trimmed to current + previous.
- **No long-tail history** — Run triggers deleted after processing; debugging uses workflow logs and Check Runs.

See [docs/github-and-ci.md](docs/github-and-ci.md#actions-and-cli-tools).

## Configuration

**Pulumi is the source of truth** for all non-secret configuration. Run `just pulumi` to apply infra and export repo vars. Secrets are set manually (see [infra/README.md](infra/README.md)).

| Required (from Terraform) | Secrets (set manually) |
|---------------------------|------------------------|
| `GCS_BUCKET`, `GCP_PROJECT`, `GCP_ZONE`, `BMT_LIVE_VM`, `GCP_SA_EMAIL`, `BMT_PUBSUB_SUBSCRIPTION` | `GCP_WIF_PROVIDER`, `BMT_DISPATCH_APP_ID`, `BMT_DISPATCH_APP_PRIVATE_KEY` |

Required vars (e.g. `GCS_BUCKET`, `BMT_LIVE_VM`, `BMT_STATUS_CONTEXT`, `BMT_HANDSHAKE_TIMEOUT_SEC`) are set from Pulumi; run `just pulumi` to apply infra and push repo vars to GitHub. See [docs/configuration.md](docs/configuration.md).

See [docs/configuration.md](docs/configuration.md) and [infra/README.md](infra/README.md).

## GCS contract (summary)

- **Roots** — `<code-root> = gs://<bucket>/code`; `<runtime-root> = gs://<bucket>/runtime`.
- **Code root** — Deployable code/config/bootstrap from `gcp/image`; manual sync only.
- **Runtime root** — Triggers (`runs/`, `acks/`, `status/`), runner bundles, `current.json`, `snapshots/<run_id>/`.

See [docs/architecture.md](docs/architecture.md) and [docs/configuration.md](docs/configuration.md) for full layout.

## Local usage

**Testing production CI locally with real VM/GCS:** Follow [Testing production CI locally](docs/development.md#testing-production-ci-locally). Set repo vars (or export `GCS_BUCKET`, `GCP_PROJECT`, `GCP_ZONE`, `BMT_LIVE_VM`), run `just deploy`, then trigger a workflow (e.g. push or manual dispatch). Use `just monitor` or `just vm-check <run_id>` to inspect. See also [docs/development.md](docs/development.md) and [docs/github-and-ci.md](docs/github-and-ci.md).

- **Local BMT batch** (no cloud): `uv run python -m tools.bmt.bmt_run_local` (env: `BMT_ID`, `BMT_JOBS_CONFIG`, `BMT_RUNNER`, `BMT_RUNTIME_ROOT`, `BMT_DATASET_ROOT`, etc.). See [docs/development.md](docs/development.md).
- **Bucket tools** (set `GCS_BUCKET`): `uv run python -m tools.remote.bucket_sync_gcp`, `uv run python -m tools.remote.bucket_verify_gcp_sync`, `uv run python -m tools.remote.bucket_sync_runtime_seed`, `uv run python -m tools.remote.bucket_upload_runner`, `uv run python -m tools.remote.bucket_upload_wavs`, `uv run python -m tools.remote.bucket_validate_contract`.

## Repository layout

- **gcp/image/** — Deployable VM code/config/templates; synced manually to `<code-root>`.
- **gcp/remote/** — Runtime seed (runners + placeholders); synced to `<runtime-root>`.
- **data/** — Local-only datasets; upload explicitly.
- **infra/** — Pulumi (source of truth for non-secret config), bootstrap scripts, and [infra/README.md](infra/README.md).
- **.github/** — Workflows and CI scripts.
- **tools/** — Bucket sync, upload, validation, local BMT, Pulumi export, repo-vars.
- **.local/diagnostics/** — Ad-hoc diagnostics (gitignored).

See [gcp/README.md](gcp/README.md) for canonical mirror policy.

## Documentation

Full index: [docs/README.md](docs/README.md).

| Doc | Description |
| --- | --- |
| [README.md](README.md) | This file — purpose, features, config, local usage. |
| [CLAUDE.md](CLAUDE.md) | AI/maintainer guide — layout, devtools, lint/test, CI/VM, env vars. |
| [docs/architecture.md](docs/architecture.md) | Trigger-and-stop, GCS contract, script map. |
| [docs/configuration.md](docs/configuration.md) | Env contract, repo vars, VM metadata, secrets. |
| [docs/development.md](docs/development.md) | Setup, testing, Justfile, deploy. |
| [docs/development.md](docs/development.md#testing-production-ci-locally) | Canonical how-to: test prod CI locally. |
| [gcp/README.md](gcp/README.md) | Bucket mirror policy. [gcp/image/scripts/README.md](gcp/image/scripts/README.md) — VM bootstrap. |

## Notes

- Ad-hoc diagnostics: use `.local/diagnostics/` only; do not commit.
- **BMT CLI from repo root:** Run `uv sync` then `uv run bmt <command>`. No `--project` is needed: the root workspace depends on the `bmt` package (`.github/bmt`), so the `bmt` script is available. In CI, the setup action runs `uv sync` from repo root, so steps use `uv run bmt ...` the same way.
- **Shorthand scripts:** You can run `uv run bmt-matrix`, `uv run bmt-trigger`, `uv run bmt-wait`, `uv run bmt-write-context`, `uv run bmt-write-summary`, `uv run bmt-select-vm`, `uv run bmt-start-vm` instead of `uv run bmt matrix`, `uv run bmt write-run-trigger`, etc. (see `[project.scripts]` in `.github/bmt/pyproject.toml`).
- `uv run bmt ...` commands are for manual/local use only; `bmt-handoff.yml` drives normal CI execution.
- Manual VM start: run `uv run bmt start-vm --allow-manual-start` (debug/maintenance only); routine starts come from `bmt-handoff.yml`.

## Test vs production

When moving to production: update GitHub App credentials and repo mapping (`gcp/image/config/github_repos.json`), and ensure Pulumi (and thus `BMT_STATUS_CONTEXT`) matches branch protection. See [docs/plans/migration-to-production.md](docs/plans/migration-to-production.md).
