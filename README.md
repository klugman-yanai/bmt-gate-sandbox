# bmt-cloud-dev

**Purpose:** This repo exists so you can **reliably test production CI locally using the real VM and GCS** — no mocks. That is the main goal. Supporting that goal are:

1. **Mirror of gcp (VM/GCS)** — The `gcp/` directory is the local mirror of the bucket namespace. Sync/pull from GCS so you develop against the same code and layout the VM uses. See [gcp/README.md](gcp/README.md).
2. **Test suite** — Unit and integration tests for BMT logic, gate, pointer/snapshot flow, and CI commands. Run without GCS/VM when possible; use real bucket/VM when you need to validate the full path.
3. **Dev QoL tools** — Just recipes, tools (sync, upload, validate, local BMT, monitor), and repo-vars/VM helpers for managing BMTs and debugging handoff.

Development repo for the BMT (Benchmark/Milestone Testing) cloud pipeline. This repo owns the BMT workflow, VM watcher and orchestrator logic, and the GCS bucket contract used by GitHub Actions.

## Features

- **Trigger-and-stop handoff** — CI writes one run trigger, starts the VM, waits for handshake ack, then exits. The VM runs BMT legs and posts final outcome.
- **Commit status and Check Run** — VM posts pending then success/failure commit status and creates/updates a Check Run for progress and results. Branch protection gates on the status context (`BMT_STATUS_CONTEXT`, from Terraform).
- **Pointer-based results** — `current.json` points to latest and last-passing run; per-run artifacts live under `snapshots/<run_id>/`. Baseline for gate comparison comes from last-passing snapshot.
- **PR closure and supersede** — Closed or superseded PR runs are skipped or cancelled without promoting pointers. See [docs/communication-flow.md](docs/communication-flow.md) and [docs/architecture.md](docs/architecture.md).

## Safety and reliability

- **Handshake validation** — Workflow waits for VM ack with clear failure reasons (`trigger_missing`, `vm_not_running`, `ack_not_written`, etc.). See [docs/implementation.md](docs/implementation.md#reliability-behavior).
- **PR closed/superseded** — Before pickup: run skipped. During execution: current leg finishes, remaining legs skipped, signals finalized as cancelled; no pointer promotion for superseded runs.
- **Fail-open** — PR state API errors do not block execution.
- **Workflow cleanup** — On handshake failure, workflow removes trigger/ack/status objects.

## Dev quality of life

- **Just recipes** — `just test`, `just lint`, `just sync-gcp`, `just verify-sync`, `just terraform-export-vars`, `just repo-vars-check`, `just repo-vars-apply`, `just show-env`, `just validate-vm-vars`. Run `just` for the full list.
- **GitHub CLI** — `gh pr checks --watch` to wait for BMT and other checks; `gh run watch <run_id>` to follow a workflow run.
- **Job summaries** — Workflow runs write handoff and routing summaries to the Actions run summary.

See [docs/development.md](docs/development.md) and [docs/github-actions-and-cli-tools.md](docs/github-actions-and-cli-tools.md).

## Monitoring (GitHub Actions and VM runtime)

- **Handoff vs BMT outcome** — Workflow run success = handoff completed. Final BMT pass/fail is VM-owned and appears in PR **Checks** and **Comments**.
- **Live TUI** — `just monitor` (or `just monitor --run-id <id>`) shows trigger, ack, status, and VM/GCS state; useful when handshake fails.
- **CLI inspection** — `just gcs-trigger <run_id>`, `just vm-serial`, `just check-vm-gcs <run_id>` for trigger/ack and VM serial output.

See [docs/communication-flow.md](docs/communication-flow.md) and [docs/github-actions-and-cli-tools.md](docs/github-actions-and-cli-tools.md).

## BMT management

- **Pointer** — `current.json` at `<runtime-root>/<results_prefix>/` holds `latest` and `last_passing` run IDs; updated by the watcher after all legs.
- **Snapshots** — Each run writes `snapshots/<run_id>/latest.json`, `ci_verdict.json`, and logs. Gate reads baseline from the last-passing snapshot.
- **Retention** — Only snapshots referenced by the pointer are kept; watcher prunes the rest.

See [docs/architecture.md](docs/architecture.md#results-contract).

## Performance and cost

- **VM self-stop** — VM runs with `--exit-after-run` and stops itself after one run so it does not idle.
- **Snapshot retention** — Only latest and last_passing snapshot dirs retained per results prefix; trigger/ack/status metadata trimmed to current + previous.
- **No long-tail history** — Run triggers deleted after processing; debugging uses workflow logs and Check Runs.

See [docs/github-actions-and-cli-tools.md](docs/github-actions-and-cli-tools.md#runtime-retention-policy-hard-delete-no-quarantine).

## Configuration

**Terraform is the source of truth** for all non-secret configuration. Apply Terraform, then export repo vars from Terraform outputs. Secrets are set manually (see [infra/README.md](infra/README.md)).

| Required (from Terraform) | Secrets (set manually) |
|---------------------------|------------------------|
| `GCS_BUCKET`, `GCP_PROJECT`, `GCP_ZONE`, `BMT_VM_NAME`, `GCP_SA_EMAIL`, `BMT_PUBSUB_SUBSCRIPTION` | `GCP_WIF_PROVIDER`, `BMT_DISPATCH_APP_ID`, `BMT_DISPATCH_APP_PRIVATE_KEY` |

Required vars (e.g. `GCS_BUCKET`, `BMT_VM_NAME`, `BMT_STATUS_CONTEXT`, `BMT_HANDSHAKE_TIMEOUT_SEC`, `BMT_PROJECTS`) are set from Terraform via `just terraform-export-vars-apply`; see [docs/configuration.md](docs/configuration.md).

Useful commands: `just terraform-export-vars`, `just terraform-export-vars-apply`, `just repo-vars-check`, `just repo-vars-apply`, `just show-env`, `just validate-vm-vars`, `just sync-vm-metadata`, `just start-vm`, `just wait-handshake <workflow_run_id>`.

See [docs/configuration.md](docs/configuration.md) and [infra/README.md](infra/README.md).

## GCS contract (summary)

- **Roots** — `<code-root> = gs://<bucket>/code`; `<runtime-root> = gs://<bucket>/runtime`.
- **Code root** — Deployable code/config/bootstrap from `gcp/code`; manual sync only.
- **Runtime root** — Triggers (`runs/`, `acks/`, `status/`), runner bundles, `current.json`, `snapshots/<run_id>/`.

See [docs/architecture.md](docs/architecture.md) and [docs/configuration.md](docs/configuration.md) for full layout.

## Local usage

**Testing production CI locally with real VM/GCS:** Follow [Testing production CI locally](docs/testing-production-ci-locally.md). Set repo vars (or export `GCS_BUCKET`, `GCP_PROJECT`, `GCP_ZONE`, `BMT_VM_NAME`), sync the mirror (`just sync-gcp`, `just verify-sync`), then run `just prod-ci-local` or the manual sequence in that doc. Use `just monitor` or `just gcs-trigger <run_id>` to inspect; verify in GCS or via Check Run. See also [docs/development.md](docs/development.md) and [docs/github-actions-and-cli-tools.md](docs/github-actions-and-cli-tools.md).

- **Local BMT batch** (no cloud): `uv run python tools/bmt_run_local.py --bmt-id ... --jobs-config ... --runner ... --runtime-root gcp/runtime --dataset-root ... --workers 4`. See [docs/development.md](docs/development.md).
- **Bucket tools** (set `GCS_BUCKET`): `just sync-gcp`, `just verify-sync`, `just sync-runtime-seed`, `just upload-runner`, `just upload-wavs <source_dir>`, `just validate-bucket`.

## Repository layout

- **gcp/code/** — Deployable VM code/config/templates; synced manually to `<code-root>`.
- **gcp/runtime/** — Runtime seed (runners + placeholders); synced to `<runtime-root>`.
- **data/** — Local-only datasets; upload explicitly.
- **infra/** — Terraform (source of truth for non-secret config), bootstrap scripts, and [infra/README.md](infra/README.md).
- **.github/** — Workflows and CI scripts.
- **tools/** — Bucket sync, upload, validation, local BMT, Terraform export, repo-vars.
- **.local/diagnostics/** — Ad-hoc diagnostics (gitignored).

See [gcp/README.md](gcp/README.md) for canonical mirror policy.

## Documentation

Full index: [docs/README.md](docs/README.md).

| Doc | Description |
|-----|--------------|
| [README.md](README.md) | This file — **purpose** (test prod CI locally with real VM/GCS), features, config, local usage. |
| [CLAUDE.md](CLAUDE.md) | AI/maintainer guide — purpose, code layout, time/clocks, devtools, lint/test, CI and VM layout, env vars. |
| [docs/architecture.md](docs/architecture.md) | Trigger-and-stop, GCS contract, script map, diagrams. |
| [docs/implementation.md](docs/implementation.md) | Data flow, reliability, limitations. |
| [docs/development.md](docs/development.md) | Setup, testing, lint/typecheck, Justfile, deploy. |
| [docs/configuration.md](docs/configuration.md) | Env contract, repo vars, VM metadata, secrets, bucket layout. |
| [docs/communication-flow.md](docs/communication-flow.md) | Commit status and Check Runs; failure handling. |
| [docs/github-app-permissions.md](docs/github-app-permissions.md) | GitHub App permissions and how to check them. |
| [docs/github-actions-and-cli-tools.md](docs/github-actions-and-cli-tools.md) | Actions summaries, re-run, debug; `gh` CLI; retention policy. |
| [docs/plans/future-architecture.md](docs/plans/future-architecture.md) | Planned changes (SDK, Pydantic, bmt_lib, PR comments). |
| [docs/plans/high-level-design-improvements.md](docs/plans/high-level-design-improvements.md) | Purpose-driven design improvements (first-class local prod CI test, doc flow, production surface, test tiers). |
| [docs/plans/migration-to-production.md](docs/plans/migration-to-production.md) | Enabling BMT in production repo. |
| [gcp/README.md](gcp/README.md) | Local bucket mirror policy. |
| [gcp/code/bootstrap/README.md](gcp/code/bootstrap/README.md) | VM bootstrap and auth. |

## Notes

- Ad-hoc diagnostics: use `.local/diagnostics/` only; do not commit.
- `uv run bmt ...` commands are for manual/local use only; `bmt.yml` drives normal CI execution.
- Manual VM start: `just start-vm` (debug/maintenance/testing only); routine starts come from `bmt.yml`.

## Test vs production

When moving to production: update GitHub App credentials and repo mapping (`gcp/code/config/github_repos.json`), and ensure Terraform (and thus `BMT_STATUS_CONTEXT`) matches branch protection. See [docs/plans/migration-to-production.md](docs/plans/migration-to-production.md).
