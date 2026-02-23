# bmt-cloud-dev

Development repo for the BMT cloud pipeline. This repo owns the BMT workflow, VM watcher/orchestrator logic, and bucket contract used by GitHub Actions.

## What Lives Here

1. VM and bucket-side runtime code in `remote/`.
2. GitHub workflows in `.github/workflows/` (`ci.yml` and `bmt.yml`).
3. CI command entrypoints in `.github/scripts/ci_driver.py` and `ci/commands/`.
4. Local devtools for sync/upload/validation in `devtools/`.

`remote/` is synchronized to `gs://<bucket>/` (optionally under `BMT_BUCKET_PREFIX`).

## Workflow Topology

This repo uses two workflows:

1. `ci.yml`:
Build-oriented workflow, intentionally lightweight in this repo. It mirrors `resources/core-main-workflow.yml` structure, creates runner artifacts for selected projects, and dispatches `bmt.yml`.
2. `bmt.yml`:
BMT control-plane workflow. It uploads runners to GCS, writes the VM run trigger, starts the VM, waits for handshake ack, posts pending status, and exits.

`ci.yml` triggers `bmt.yml` via `workflow_dispatch` and passes `ci_run_id`, `head_sha`, `head_branch`, `head_event`, and optional `pr_number`.

## `bmt.yml` End-To-End Flow

1. Resolve context from dispatch inputs (`bmt-context`).
2. Parse `CMakePresets.json` for non-embedded `*_gcc_Release` presets filtered by `BMT_PROJECTS` (`extract-bmt-presets`).
3. Download runner artifacts from the CI run and upload successful ones to GCS (`upload-runners` + `ci_driver.py upload-runner`).
4. Resolve uploaded projects from marker files (`resolve-uploaded-projects`).
5. Build project/BMT matrix from `remote/bmt_projects.json` and per-project jobs config (`ci_driver.py matrix`), then filter to uploaded projects.
6. Write one run trigger payload (`ci_driver.py trigger`) to `triggers/runs/<workflow_run_id>.json`.
7. Start VM (`ci_driver.py start-vm`).
8. Wait for VM handshake ack (`ci_driver.py wait-handshake`) at `triggers/acks/<workflow_run_id>.json`.
9. Post pending commit status (`BMT_STATUS_CONTEXT`, default `BMT Gate`) and finish.

The workflow intentionally does not wait for final verdicts. Final pass/fail is posted by the VM.

## VM Runtime Behavior

`remote/vm_watcher.py` is the VM control loop:

1. Polls `triggers/runs/` for run payloads.
2. Resolves GitHub auth per repository via `remote/lib/github_auth.py` and `remote/config/github_repos.json`.
3. Writes handshake ack to `triggers/acks/<workflow_run_id>.json`.
4. Initializes live progress status at `gs://<bucket>/triggers/status/<workflow_run_id>.json` and updates heartbeat every 15s.
5. Creates/updates GitHub Check Run and posts pending commit status.
6. Downloads `root_orchestrator.py` from bucket root and runs one leg per trigger entry.
7. `remote/root_orchestrator.py` downloads project config + manager and executes the manager for one `(project, bmt_id, run_id)`.
8. `remote/sk/bmt_manager.py` runs the runner over WAV inputs, evaluates gate vs baseline (`current.json -> last_passing`), uploads snapshot artifacts (`latest.json`, `ci_verdict.json`, logs), and writes `manager_summary.json`.
9. After all legs, watcher updates each `current.json` pointer (`latest`, `last_passing`) and deletes stale snapshots not referenced by either pointer.
10. Watcher posts final commit status (`success` or `failure`), completes the Check Run, removes the trigger file, and exits if started with `--exit-after-run`.

`remote/bootstrap/startup_example.sh` runs watcher with `--exit-after-run` and then stops the VM instance.

## GCS Contract (Current)

Use `<bucket-root> = gs://<bucket>[/<BMT_BUCKET_PREFIX>]`.

- `<bucket-root>/triggers/runs/<workflow_run_id>.json`: CI-to-VM trigger payload.
- `<bucket-root>/triggers/acks/<workflow_run_id>.json`: VM handshake response.
- `gs://<bucket>/triggers/status/<workflow_run_id>.json`: live VM progress file.
- `<bucket-root>/<project>/runners/<preset>/...`: uploaded runner bundle from `bmt.yml`.
- `<bucket-root>/<results_prefix>/snapshots/<run_id>/...`: per-run artifacts from manager.
- `<bucket-root>/<results_prefix>/current.json`: canonical pointer maintained by watcher.

## Local Usage

Run local SK BMT batch (no cloud VM):

```bash
python3 devtools/run_sk_bmt_batch.py \
  --bmt-id false_reject_namuh \
  --jobs-config remote/sk/config/bmt_jobs.json \
  --runner remote/sk/runners/kardome_runner \
  --dataset-root data/sk/inputs/false_rejects \
  --workers 4
```

Bucket tools:

```bash
BUCKET="<bucket>" python3 devtools/sync_remote_to_bucket.py
BUCKET="<bucket>" python3 devtools/upload_runner.py --runner-path <path>
BUCKET="<bucket>" python3 devtools/upload_wavs.py --source-dir <dir>
BUCKET="<bucket>" python3 devtools/validate_bucket_contract.py [--require-runner]
```

## Notes

- `ci.yml` in this repo is a development mirror with simplified build steps; `resources/core-main-workflow.yml` tracks the upstream build structure it mirrors.
- Require the status context configured by `BMT_STATUS_CONTEXT` (default `BMT Gate`) in branch protection.
- `ci_driver.py wait` and `ci_driver.py gate` are retained for manual/local validation flows, not used in `bmt.yml`.
- See `remote/bootstrap/README.md` for VM bootstrap/auth setup and `ARCHITECTURE.md` for deeper architecture context.
