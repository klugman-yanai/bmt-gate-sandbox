# Implementation (Current)

This document describes how the system runs today, with the current split storage contract and manual code sync model. See [architecture.md](architecture.md) for layout, contracts, and script map.

## Runtime model

1. CI uploads runner artifacts to `<runtime-root>` and writes one trigger file to `<runtime-root>/triggers/runs/<workflow_run_id>.json`.
2. CI syncs VM metadata, starts the VM, waits for handshake ack, posts pending commit status, and exits.
3. VM watcher polls runtime triggers, writes ack/status files, runs orchestrator per leg, updates pointers, posts final status/check run, and deletes the trigger.
4. For PR-context runs, watcher checks PR state and head SHA:
   - PR already closed at pickup: writes handshake/status skip metadata and exits without running legs.
   - Trigger SHA != current PR head SHA at pickup: marks run skipped as `superseded_by_new_commit`.
   - PR closes or a newer PR head SHA appears during execution: completes current leg, marks remaining legs skipped, finalizes check/status as cancelled (`check=neutral`, `status=error`), and skips pointer promotion.

## Storage contract

- `<code-root> = gs://<bucket>/code`
- `<runtime-root> = gs://<bucket>/runtime`

Ownership:

- `deploy/code` is source of truth for deployable code/config/bootstrap only.
- `deploy/code` is manually synced to `<code-root>` (`just sync-deploy && just verify-sync`).
- `deploy/runtime` is source of truth for runtime seed artifacts and is manually synced to `<runtime-root>` (`just sync-runtime-seed`).
- Runtime artifacts must live under `<runtime-root>` only.

## Data flow

1. `run_trigger.py` writes trigger payload with `bucket`, `workflow_run_id`, `repository`, `sha`, `legs`, etc. (no prefix fields).
2. `vm_watcher.py` discovers triggers from runtime root, writes ack/status in runtime root.
3. `vm_watcher.py` downloads `root_orchestrator.py` from code root.
4. `root_orchestrator.py` downloads project config + manager from code root.
5. `sk/bmt_manager.py`:
   - template from code root
   - runner + dataset from runtime root
   - outputs/verdict/logs/current pointer artifacts in runtime root
6. Watcher updates `current.json` and snapshot retention, then posts final GitHub status/check.

## Component roles

| Component | Responsibility |
|---|---|
| `.github/workflows/bmt.yml` | Trigger-and-stop control plane; no final gate wait. |
| `.github/scripts/ci/commands/run_trigger.py` | Writes runtime trigger payload. |
| `.github/scripts/ci/commands/start_vm.py` | Starts VM and verifies RUNNING + `lastStartTimestamp` advancement. |
| `.github/scripts/ci/commands/wait_handshake.py` | Waits for ack; emits reasoned diagnostics and serial output on failure. |
| `deploy/code/vm_watcher.py` | Trigger polling, orchestrator execution, pointer promotion, GitHub reporting. |
| `deploy/code/root_orchestrator.py` | Per-leg orchestrator; code/runtime aware fetch/upload. |
| `deploy/code/sk/bmt_manager.py` | Runner execution + snapshot outputs + verdict generation. |
| `deploy/code/lib/status_file.py` | Runtime-prefix-aware status heartbeat/progress API. |

## Canonical runtime object layout

- `<runtime-root>/triggers/runs/<workflow_run_id>.json`
- `<runtime-root>/triggers/acks/<workflow_run_id>.json` (includes optional `run_disposition`, `skip_reason`, `pr_state`, `pr_merged`, `pr_state_checked_at`, `pr_head_sha`, `superseded_by_sha`)
- `<runtime-root>/triggers/status/<workflow_run_id>.json` (includes optional `run_outcome`, `cancel_reason`, `cancelled_at`, `superseded_by_sha`, per-leg `skip_reason`)
- `<runtime-root>/<project>/runners/<preset>/...`
- `<runtime-root>/<results_prefix>/current.json`
- `<runtime-root>/<results_prefix>/snapshots/<run_id>/latest.json`
- `<runtime-root>/<results_prefix>/snapshots/<run_id>/ci_verdict.json`
- `<runtime-root>/<results_prefix>/snapshots/<run_id>/logs/...`

## Reliability behavior

- `start-vm` validates post-start readiness, not only start command acceptance.
- `wait-handshake` verifies trigger existence first and reports root-cause categories:
  - `trigger_missing`
  - `status_path_mismatch`
  - `vm_not_running`
  - `ack_unreadable`
  - `ack_not_written`
- Workflow cleanup removes current run trigger/ack/status objects on failure.
- PR closure/head-state handling is fail-open for PR-state API errors (`unknown` state does not block execution).
- PR triggers are queueable; stale-trigger deletion/restart preflight is non-destructive for PR context.

## Not implemented

- GCP SDK migration (CLI-first is still current).
- Automatic CI code sync to `<code-root>` (manual sync is intentional for now).
