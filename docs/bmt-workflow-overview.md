# BMT Workflow: Feature Overview & Implementation Reference

**Audience:** Dev team (Kardome-org/core-main)
**Date:** March 2026
**Status:** Active — pre-baked image rollout in sandbox validation; production cutover to follow

---

## What Is BMT?

BMT (Benchmark/Milestone Testing) is the automated audio-quality gating system for CI. Every PR opened against `core-main` triggers a full scored audio regression run on a dedicated GCP VM. Results are posted back to GitHub as a commit status and a live Check Run. If the gate fails, the PR cannot merge.

The gate check in GitHub is named **"BMT Gate"** and is enforced via branch protection on `core-main`. It is owned end-to-end by the BMT VM — the CI workflow itself just hands off and exits.

This system replaced the previous approach of running checks inline in CI, which blocked runners for the full duration of audio processing and had no structured baseline tracking.

---

## High-Level Architecture

```
PR opened / push to dev branch
         │
         ▼
  ┌────────────────────────────────┐
  │  GitHub Actions — bmt.yml      │
  │                                │
  │  Stage 01: Resolve matrix      │  ← which projects + BMT IDs apply
  │  Stage 02: Upload runners      │  ← push built binaries to GCS
  │  Stage 03: Classify handoff    │  ← any supported legs?
  │  Stage 04: Write trigger       │  ← one JSON payload, all legs
  │            Start VM            │  ← gcloud compute instances start
  │            Wait for ack        │  ← ~3 min timeout handshake
  │            Post "pending"      │  ← commit status on SHA
  │            Exit ✓              │  ← CI runner is done
  │  Stage 05: Failure fallback    │  ← diagnostics if handshake fails
  └────────────────────────────────┘
         │
         ▼  (async — CI runner is free; VM owns all subsequent status)
  ┌────────────────────────────────┐
  │  BMT VM — vm_watcher.py        │
  │                                │
  │  1. Poll GCS for trigger       │
  │  2. Validate + resolve legs    │  ← per-leg support check + reasons
  │  3. Write handshake ack        │  ← accepted/rejected legs
  │  4. For each accepted leg:     │
  │     a. Run root_orchestrator   │  ← downloads manager from GCS
  │     b. Manager runs tests      │  ← thread pool over WAV files
  │     c. Write snapshot to GCS   │  ← ci_verdict.json, latest.json
  │     d. Update Check Run        │  ← live progress in PR
  │  5. Aggregate all verdicts     │
  │  6. Promote result pointer     │  ← update current.json
  │  7. Prune stale snapshots      │  ← GCS cleanup
  │  8. Post final commit status   │  ← success / failure / cancelled
  │  9. Finalize Check Run         │
  │  10. Delete trigger            │
  │  11. Stop self ✓               │
  └────────────────────────────────┘
```

### Why Trigger-and-Stop?

The CI workflow does not wait for audio test results. It hands a trigger to the VM and exits. This was a deliberate design choice:

- **CI runner cost**: audio BMT runs can take several minutes; blocking a GitHub-hosted runner for that time is wasteful
- **Decoupled reliability**: if the VM crashes mid-run, the workflow has already exited cleanly — the gate stays `pending` and can be re-triggered manually without re-running the build
- **VM owns the verdict**: only one thing can post the final status, eliminating races between the workflow and the VM

---

## What Gets Tested

Runs are broken into **legs** — one per (project, BMT-ID) pair. Each leg is an independent scored audio regression:

| Project | BMT ID | Description |
|---------|--------|-------------|
| `sk` | `false_reject_namuh` | NAMUH counter scores vs. baseline on false-reject WAV dataset |

Legs are defined entirely in config. Adding a new test suite requires no workflow changes — only entries in `bmt_projects.json` and `bmt_jobs.json`. The leg matrix is computed dynamically at the start of every run.

### Leg Resolution & Partial Acceptance

The VM validates each requested leg against what it actually supports on boot (manager script present, jobs config valid, BMT ID defined and enabled). If some legs are not supported, the VM accepts and runs the rest and reports structured rejection reasons for the skipped ones. Possible rejection reasons include:

- `manager_missing` — project manager script not found in code root
- `jobs_config_missing` — jobs config file not present
- `bmt_disabled` — BMT ID exists but is disabled in config
- `bmt_not_defined` — BMT ID not found in jobs config at all

This means adding a new leg to the matrix before the VM image is updated will not break CI — it is skipped with a clear reason, not an error.

---

## Security Model

### GCP Authentication — Workload Identity Federation

CI never stores a GCP service account key. Instead:

1. GitHub Actions generates a short-lived OIDC token (scoped to the workflow run)
2. GCP's Workload Identity Federation exchanges it for a service account token
3. That token is used for the duration of the job, then expires

There is nothing to rotate, nothing to leak, and nothing that persists beyond a single CI run.

### GitHub App Credentials — Secret Manager, Not Env Vars

The VM needs GitHub App credentials to post commit statuses and Check Runs. These are stored in **GCP Secret Manager** and fetched at VM boot via `gcloud secrets versions access`. They are held in memory for the duration of the watcher process and never written to disk.

The startup script validates that all required credentials are present before starting the watcher. If any are missing, the VM logs the error and stops itself rather than starting in a broken state.

### Multi-Repo App Isolation

The system supports separate GitHub Apps for separate repos. The mapping lives in `remote/code/config/github_repos.json`:

```json
{
  "Kardome-org/core-main":           { "secret_prefix": "GITHUB_APP_PROD" },
  "klugman-yanai/bmt-gate-sandbox":  { "secret_prefix": "GITHUB_APP_TEST" }
}
```

Adding a new repo requires a config entry and the corresponding App installation — no code changes. Credentials for different repos are never mixed at runtime.

### Principle of Least Privilege

| Actor | What it can do |
|-------|---------------|
| CI service account (via WIF) | Read/write GCS bucket; start the BMT VM; nothing else |
| BMT VM service account | Read GCS code root; read/write GCS runtime root; access Secret Manager; stop itself |
| GitHub App (prod) | Post commit statuses and Check Runs on `core-main`; nothing else |
| GitHub App (test) | Same, scoped to sandbox repo only |

---

## Developer Experience

### Live Check Run in the PR

When the VM begins processing, it creates a GitHub Check Run visible directly from the PR checks tab. The Check Run updates in real time as each leg progresses:

```
BMT Gate — in_progress  (1/1 legs running)

| Project | BMT ID               | Status      | Progress    | Duration |
|---------|----------------------|-------------|-------------|----------|
| sk      | false_reject_namuh   | in_progress | 31/47 files | 18s      |
```

Once complete:

```
BMT Gate — success  (all legs passed)

| Project | BMT ID               | Status    | Progress    | Duration |
|---------|----------------------|-----------|-------------|----------|
| sk      | false_reject_namuh   | completed | 47/47 files | 42s      |
```

The Check Run conclusion (success / failure / cancelled / neutral) is set when all legs resolve. Clicking into it shows the full summary. Developers get a detailed view without leaving GitHub.

### Commit Status ("BMT Gate")

Separate from the Check Run, a commit status is posted directly on the SHA. This is what branch protection enforces. The lifecycle is:

| Status | When |
|--------|------|
| `pending` | VM picks up trigger and writes ack |
| `success` | All accepted legs passed gate |
| `failure` | One or more legs failed gate |
| `error` | VM encountered an unexpected error |
| `cancelled` | PR was closed or superseded before completion |

The commit status is owned entirely by the VM. The CI workflow posts an initial `pending` as a courtesy immediately after the handshake, but the VM overwrites it with the final verdict.

### PR State Awareness

The VM continuously tracks whether the underlying PR is still open and relevant during execution. It handles three edge cases gracefully:

**PR closed before VM picks up trigger**
The trigger is still processed and acked, but all legs are marked `skipped`. No spurious failure is posted. The VM stops cleanly.

**PR closed while a leg is running**
The current leg runs to completion (results are still useful for debugging). All remaining legs are cancelled. The final status is `cancelled`, not `failure`.

**New commit pushed while a leg is running**
The older run is marked `superseded`. The result pointer (`current.json`) is not promoted — the newer run's baseline is not overwritten by an older run. The older run's verdicts are still written to GCS for inspection.

### Per-Leg Heartbeating

Each leg writes progress updates to a status file in GCS (`runtime/triggers/status/{workflow_run_id}.json`) as it processes WAV files:

```json
{
  "legs": {
    "sk/false_reject_namuh": {
      "status": "running",
      "files_completed": 31,
      "files_total": 47,
      "last_heartbeat": "2026-03-04T14:23:11Z"
    }
  }
}
```

This makes it possible to detect stalled runs (missing heartbeats) and monitor progress from outside the VM without SSH access. The `devtools/bmt_monitor.py` TUI reads this in real time.

---

## Result Storage — Pointer-Based Versioning

Results are stored in GCS with a stable pointer architecture. The design goal: the gate always compares against the last *passing* run, never a failed one.

```
gs://{bucket}/runtime/sk/results/false_rejects/
├── current.json                     ← stable pointer
└── snapshots/
    ├── leg-001-false_reject_namuh/  ← last passing run
    │   ├── ci_verdict.json
    │   ├── latest.json
    │   └── logs/
    └── leg-002-false_reject_namuh/  ← latest run (may have failed)
        ├── ci_verdict.json
        ├── latest.json
        └── logs/
```

**`current.json` structure:**

```json
{
  "latest": "leg-002-false_reject_namuh",
  "last_passing": "leg-001-false_reject_namuh",
  "updated_at": "2026-03-04T14:25:00Z"
}
```

**Baseline resolution chain:**

```
new run starts
   → read current.json → last_passing: "leg-001-..."
   → load snapshots/leg-001-.../ci_verdict.json as baseline
   → run tests, write new snapshot under snapshots/leg-002-.../
   → if passed:  update current.json (last_passing = leg-002-...)
   → if failed:  update current.json (latest = leg-002-..., last_passing unchanged)
```

This means:
- A regression does not corrupt the baseline for the next run
- Any historical snapshot can be inspected (until pruned)
- The pointer is the single source of truth — nothing else at the results root is canonical

**Snapshot retention:** After updating the pointer, the VM deletes all snapshots not referenced by `current.json`. This is automatic.

**Important constraint:** The manager never writes to `current.json`. Only the watcher does, after all legs for a run are complete. This ensures the pointer is never in a partial state.

---

## VM Bootstrap & Startup Contract

The VM runs through a layered startup sequence on every boot:

```
GCP startup script
   → startup_wrapper.sh
       → sync code root from GCS to /opt/bmt/code
       → exec startup_example.sh
           → resolve uv binary (env → PATH → pinned GCS artifact + checksum)
           → check dependency fingerprint
               → if mismatch: run install_deps.sh (uv sync --extra vm --frozen)
               → if match:    skip (fast path)
           → fetch GitHub App credentials from Secret Manager
           → validate credentials present
           → run vm_watcher.py
           → stop VM when watcher exits
```

### Dependency Fingerprinting

At each boot, the startup script computes:

```
fingerprint = SHA256( pyproject.toml + uv.lock )
```

This fingerprint is stored at `.venv/.bmt_dep_fingerprint`. If it matches, the `uv sync` step is skipped entirely. If it does not (e.g. the lockfile was updated in the code root), dependencies are reinstalled and the stamp is updated.

This provides safe incremental updates — deploying a new lockfile to the bucket is enough to trigger a reinstall on next boot, without rebuilding the image.

### uv Binary Resolution

The startup script resolves `uv` through a fallback chain:

1. `BMT_UV_BIN` env var (explicit override)
2. `uv` on PATH (already installed)
3. Pinned binary at `code/_tools/uv/linux-x86_64/uv` — fetched from GCS, SHA256-verified before execution

The pinned artifact ensures the VM can always bootstrap even on a fresh image with no pre-installed tooling.

---

## Pre-Baked VM Images (Active Rollout)

### Problem

Cold-start time on a stock image includes `uv sync` (dependency install), which adds variability and delays the start of actual test execution. On the current setup the fingerprint check skips the install on repeat boots, but the first boot after a code change still pays the full cost.

### Solution: Pre-Baked Images

A custom GCP image is built with all Python dependencies pre-installed. The bake process:

1. Spin up a temporary builder VM from a pinned Ubuntu base
2. Sync code root from GCS
3. Run `install_deps.sh` to build `.venv`
4. Write an image manifest (`_tools/image_manifest.json`) with provenance: bake timestamp, source image digest, lockfile hash, `uv` checksum
5. Create a custom GCP image in family `bmt-runtime` (e.g. `bmt-runtime-20260304-1430`)
6. Delete the builder VM

At boot, the fingerprint check still runs — if the lockfile has changed since the image was baked, dependencies are reinstalled and the stamp updated. The baked image is the fast path; the fingerprint check is the safety net.

### Blue/Green Cutover

| Role | Instance name | How it's selected |
|------|--------------|------------------|
| Blue (current) | `bmt-watcher` | `BMT_VM_NAME` repo variable |
| Green (new image) | `bmt-watcher-v2` | Smoke-tested, ready to receive traffic |

**To cut over to green:** Update `BMT_VM_NAME` to `bmt-watcher-v2`. Takes effect on the next triggered run.

**To roll back:** Revert `BMT_VM_NAME` to `bmt-watcher`. Done — no code change, no deployment.

### Rollout Status

| Phase | Description | Status |
|-------|-------------|--------|
| 0 | Export blue VM spec; safety rails | ✅ Complete |
| 1 | `build_bmt_image.sh` written and validated | ✅ Complete |
| 2 | `create_bmt_green_vm.sh` implemented | ✅ Complete |
| 3 | Sandbox cutover validation | 🔄 In progress (`verify/prebake-timeout-20260304`) |
| 4 | Production cutover (`core-main`) | Pending Phase 3 sign-off |
| 5 | Rollback path documented and tested | Documented |
| 6 | Automated image builds via Cloud Build | Planned |

---

## Configuration Reference

| File | Purpose |
|------|---------|
| `remote/code/bmt_projects.json` | Project registry — which projects are active, manager path, jobs config path |
| `remote/code/sk/config/bmt_jobs.json` | Per-BMT definitions: runner binary, dataset URI, gate comparison mode, score regex, cache TTLs |
| `remote/code/sk/config/input_template.json` | Runner JSON config template with `REF_PATH`, `MICS_PATH`, output path placeholders |
| `remote/code/config/github_repos.json` | GitHub App installation mapping per repository |
| `.github/bmt/config/.env.prod` | Production CI env var values (bucket, zone, VM name) |

---

## GitHub Repository Variables (Settings → Variables → Actions)

| Variable | Purpose | Notes |
|----------|---------|-------|
| `GCS_BUCKET` | GCS bucket for all code and runtime storage | |
| `GCP_WIF_PROVIDER` | Workload Identity Federation provider resource name | |
| `GCP_SA_EMAIL` | Service account for WIF token exchange | |
| `GCP_PROJECT` | GCP project ID | |
| `GCP_ZONE` | Compute zone for the BMT VM | e.g. `europe-west4-a` |
| `BMT_VM_NAME` | VM instance name | **Blue/green cutover switch** |
| `BMT_STATUS_CONTEXT` | Commit status label in GitHub | Default: `BMT Gate` |
| `BMT_HANDSHAKE_TIMEOUT_SEC` | How long CI waits for ack before failing | Default: `180` |
| `BMT_PROJECTS` | Filter which projects run | Default: `all` |

---

## Local Development Tools (`devtools/`)

| Tool | What it does |
|------|-------------|
| `bmt_run_local.py` | Run a BMT batch locally — no GCS, no VM; useful for runner and score logic |
| `bmt_monitor.py` | Live TUI dashboard showing workflow, VM, and GCS runtime status |
| `bucket_sync_remote.py` | Manually sync `remote/` to the GCS code root |
| `bucket_upload_runner.py` | Upload a built runner binary to GCS runtime root |
| `bucket_upload_wavs.py` | Upload WAV datasets to GCS |
| `bucket_validate_contract.py` | Validate required bucket objects are present (preflight check) |
| `gh_show_env.py` | Print all env var names used by CI, VM, and devtools |

Run `just` from the repo root to see available recipes.

---

## What's Not Yet Implemented

| Item | Notes |
|------|-------|
| PR comments with result tables | Stub exists in `remote/code/lib/github_pr_comment.py`; wiring pending |
| Google Cloud Python SDK | Currently uses `gcloud` CLI via subprocess; SDK migration planned |
| Pydantic models | Config and verdict validation uses plain dataclasses; Pydantic migration planned |
| Automated image builds | Manual scripts today; Cloud Build automation is Phase 6 |

---

## Incident & Rollback Guide

| Scenario | What to do |
|----------|-----------|
| BMT Gate stuck on `pending` | Check the VM is running in GCP console; inspect `runtime/triggers/acks/{workflow_run_id}.json` in GCS — if absent, handshake never completed; re-trigger the workflow manually |
| Ack written but no further progress | VM picked up trigger but stalled; SSH in and check the watcher process; restart if needed |
| Gate shows `failure` but looks like a fluke | Re-trigger `bmt.yml` from the GitHub Actions UI; if it passes, the first run was a transient issue |
| False failure blocking a known-good PR | Manually post a `success` status on the SHA via the GitHub API, or temporarily pause branch protection; investigate root cause in the snapshot logs in GCS |
| Green VM misbehaves after cutover | Set `BMT_VM_NAME` back to the blue VM name in repo variables; takes effect on next run; no code change needed |
| Dependency reinstall loop on VM | Verify `pyproject.toml` and `uv.lock` in the GCS code root are stable; check `.venv/.bmt_dep_fingerprint` on the VM |
| uv binary fails checksum | The pinned artifact in GCS may be corrupted; re-upload via `devtools/` or re-sync with `bucket_sync_remote.py` |
| Need to re-run BMT on a specific SHA | Trigger `bmt.yml` manually from the Actions tab on the target branch |
| Snapshot accumulation in GCS | Watcher prunes automatically after each run; if it crashed mid-cleanup, manually remove `runtime/.../snapshots/` dirs not referenced by `current.json` |
