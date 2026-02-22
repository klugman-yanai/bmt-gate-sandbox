---
name: Staging and Pointer-Based Promotion
overview: Migrate BMT result storage to run-scoped snapshots and a single canonical pointer file per (project, bmt_id), enabling atomic promotion, no mid-run canonical writes, and bounded storage with cleanup.
todos:
  - id: phase1
    content: Manager writes to snapshot prefix and reads baseline from pointer
    status: completed
  - id: phase2
    content: Watcher drives pointer updates and cleanup
    status: completed
  - id: phase3
    content: CI wait/gate adaptation to pointer-resolved paths
    status: completed
  - id: phase4
    content: Documentation and dead code cleanup
    status: completed
isProject: false
---

# Staging and Pointer-Based Promotion

## 1. Requirements

### 1.1 Problem

Today, each BMT manager writes results directly to canonical GCS paths (`results_prefix/latest.json`, `ci_verdicts/<run_id>.json`, etc.) as the run progresses. This means:

- A crash mid-run leaves canonical state partially updated.
- A superseded run (newer push for the same ref) can overwrite canonical with irrelevant data.
- There is no rollback mechanism.
- The gate reads `latest.json` from the same path being written to, creating a read-write race within a single run.

### 1.2 Goals

1. **Isolation during execution.** Each run writes results to a run-scoped prefix. Canonical state is never modified during execution.
2. **Atomic promotion.** Making a run's results canonical is a single file write (a pointer update), not a multi-object copy.
3. **No promotion on cancel/supersede.** If the run is abandoned, canonical state is untouched.
4. **Gate correctness.** Gate comparison reads baseline from the currently promoted (canonical) pointer, not from in-flight data.
5. **Bounded storage.** Only the latest and last-passing snapshots are retained per (project, bmt_id). Stale snapshots are deleted immediately after pointer update.
6. **Scalability.** The design must work for 10+ projects, each with multiple BMTs. Each (project, bmt_id) pair is an independent result stream with its own pointer and cleanup lifecycle.

### 1.3 Non-goals (separate efforts)

- Pub/Sub trigger delivery (compatible with this design; same payload, same VM flow).
- GitHub Check Run / PR comment (must run after pointer update; no conflict, documented as a constraint).
- Full SDK migration for `vm_watcher.py` (promotion logic will use the SDK; the rest of the watcher is unchanged).

---

## 2. Approach

### 2.1 Per-leg pointer file instead of tree copy

Each (project, bmt_id) gets a `current.json` pointer file at its canonical results prefix. This pointer contains references to the latest and last-passing snapshots, which live under a `snapshots/<run_id>/` subtree within that prefix.

**Why pointer over tree copy:**

- **Actually atomic.** Promotion is one file write. Tree copy (N objects) can fail partway, leaving half-promoted state — the exact problem we're solving.
- **Instant rollback.** Rewrite `current.json` to point at a previous snapshot.
- **No cross-leg coordination for cleanup.** Each (project, bmt_id) manages its own snapshots independently. With tree copy under a shared `runs/<workflow_run_id>/` prefix, cleanup requires checking whether any other leg still references that run prefix. Per-leg snapshots eliminate this entirely.
- **Readers do one extra GCS read.** Acceptable trade-off for correctness. A thin helper function resolves the pointer.

### 2.2 Per-leg storage layout

```
gs://{bucket}/[{prefix}/]{results_prefix}/
  current.json                              # pointer (the only "canonical" file)
  snapshots/
    {run_id}/                               # one per run that hasn't been cleaned up
      latest.json                           # full BMT results
      ci_verdict.json                       # gate verdict (source of truth)
      logs/
        {filename}.log
```

`current.json` schema:

```json
{
  "latest": "<run_id>",
  "last_passing": "<run_id or null>",
  "updated_at": "2026-02-22T10:00:00Z"
}
```

At most 2 distinct `run_id` snapshots exist at any time (latest and last_passing, which may be the same run). After updating `current.json`, any snapshot prefix under `{results_prefix}/snapshots/` not in that set is deleted.

### 2.3 What changes per component


| Component                                                | Current behavior                                                                                                                                               | New behavior                                                                                                                                                                                                                                                                                                                                 |
| -------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **CI trigger** (`run_trigger.py`)                        | Builds `verdict_uri` pointing at canonical `ci_verdicts/` path per leg.                                                                                        | Drops `verdict_uri` and `results_prefix` from leg payload. VM resolves these from config.                                                                                                                                                                                                                                                    |
| **VM watcher** (`vm_watcher.py`)                         | Reads `verdict_uri` from trigger to aggregate. Posts status. Releases `.lock`, deletes trigger.                                                                | Passes `--run-id` to orchestrator. After all legs: reads manager summaries for verdicts (in-memory, no extra GCS read). Updates each leg's `current.json`. Cleans up stale snapshots. Posts status. Deletes trigger.                                                                                                                         |
| **Orchestrator** (`root_orchestrator.py`)                | Invokes manager with bucket/prefix/project/bmt-id/run-id. No staging concept.                                                                                  | Unchanged args. Manager writes to `snapshots/{run_id}/` by default (this is now the standard path).                                                                                                                                                                                                                                          |
| **SK manager** (`sk_bmt_manager.py`)                     | Writes `latest.json`, `ci_verdicts/`, `last_passing.json`, archive, logs, sentinel to canonical `results_prefix`. Reads previous `latest.json` from same path. | Writes all outputs under `{results_prefix}/snapshots/{run_id}/`. Reads baseline by resolving `current.json` pointer → `last_passing` snapshot → `latest.json`. No `last_passing.json` copy (pointer handles this). No sentinel (pointer handles completion signaling). No archive copy (snapshots are the archive; old ones are cleaned up). |
| **CI wait/gate** (`wait_verdicts.py`, `verdict_gate.py`) | Polls `verdict_uri` from trigger payload.                                                                                                                      | Resolves `results_prefix` from config + project/bmt_id. Reads `current.json` → `latest` snapshot → `ci_verdict.json`. Or: receives verdict data from watcher's commit status description (no polling needed in trigger-and-stop model).                                                                                                      |


### 2.4 VM resolves paths (no verdict_uri in trigger)

The trigger payload currently includes `results_prefix` and `verdict_uri` per leg. Both are derivable from `project` + `bmt_id` + the jobs config on the VM. Removing them:

- Decouples CI from the GCS results layout. CI doesn't need to know about `snapshots/` or `current.json`.
- Reduces trigger payload size (minor benefit, but it's the right separation of concerns).
- Means the VM is the single owner of result path construction.

The watcher gets verdict data from the manager summary output (`manager_summary.json`), which the orchestrator already writes. The watcher parses the summary after each leg's orchestrator subprocess completes — no extra GCS read needed for aggregation.

### 2.5 Cleanup

After updating `current.json` for a leg, the watcher computes the set of referenced run_ids (`{latest, last_passing}`) and deletes any snapshot prefix under `{results_prefix}/snapshots/` not in that set. This is a list + delete scoped to one (project, bmt_id) — no global scan, no cross-leg coordination.

Worst case: watcher crashes after writing `current.json` but before deleting the old snapshot. On the next run, cleanup runs again and catches it. At most one extra snapshot lingers between runs. No GCS lifecycle rule needed.

---

## 3. Phases

### Phase 1: Manager writes to snapshot prefix

**Goal:** Manager writes all outputs under `{results_prefix}/snapshots/{run_id}/` and reads baseline from the `current.json` pointer.

**Task 1.1 — Add pointer resolution helper to manager.**
Add a function that reads `{results_prefix}/current.json` from GCS, parses it, and returns the `last_passing` run_id (or `None` if the file doesn't exist / has no `last_passing`). Use this to build the path to the baseline `latest.json`: `{results_prefix}/snapshots/{last_passing_run_id}/latest.json`.

**Task 1.2 — Change all GCS upload paths in the manager.**
Replace the current upload targets:


| Current path                                 | New path                                              |
| -------------------------------------------- | ----------------------------------------------------- |
| `{results_prefix}/latest.json`               | `{results_prefix}/snapshots/{run_id}/latest.json`     |
| `{results_prefix}/ci_verdicts/{run_id}.json` | `{results_prefix}/snapshots/{run_id}/ci_verdict.json` |
| `{results_prefix}/last_passing.json`         | *(removed — pointer handles this)*                    |
| `{archive_prefix}/{timestamp}.json`          | *(removed — snapshots are the archive)*               |
| `{results_prefix}/.run_complete_{run_id}`    | *(removed — pointer signals completion)*              |
| `{results_prefix}/.lock`                     | *(removed — no concurrent writes to canonical)*       |
| `{logs_prefix}/latest/`*                     | `{results_prefix}/snapshots/{run_id}/logs/`*          |
| `{logs_prefix}/archive/{ts}/`*               | *(removed — snapshot logs are the archive)*           |


**Task 1.3 — Update manager summary output.**
The `ci_verdict_uri` in the manager's summary JSON must point to the snapshot path: `gs://{bucket}/{results_prefix}/snapshots/{run_id}/ci_verdict.json`. The watcher uses this to locate the verdict (though it primarily uses the in-memory summary).

**Task 1.4 — Handle first run (no `current.json` exists).**
When `current.json` doesn't exist or has `last_passing: null`, the manager treats it as a bootstrap: no previous score, gate passes with reason `bootstrap_no_previous_result`. This is the existing behavior for missing `latest.json`, just triggered by a missing pointer instead.

**Task 1.5 — Unit test: pointer resolution and path construction.**
Test that given a `current.json` payload, the manager constructs the correct baseline read path and snapshot write paths. Test the bootstrap case (no pointer file). Mock GCS client.

---

### Phase 2: Watcher drives pointer updates and cleanup

**Goal:** After all legs complete, the watcher updates each leg's `current.json` pointer and deletes stale snapshots.

**Task 2.1 — Watcher reads verdicts from manager summaries, not GCS.**
Today `_aggregate_verdicts()` downloads each verdict from `verdict_uri`. Instead, have the watcher capture each manager's summary (already written to `manager_summary.json` by the orchestrator; the watcher reads it from the local workspace or parses orchestrator stdout). Build the aggregate from in-memory data. No GCS round-trip per leg for aggregation.

**Task 2.2 — Watcher updates `current.json` per leg after all legs complete.**
After aggregation and before posting commit status:

1. For each leg, read the existing `current.json` (to get previous `last_passing` and old snapshot references).
2. Build the new pointer: `latest` = this run's `run_id`. `last_passing` = this run's `run_id` if gate passed, else previous `last_passing`.
3. Write `current.json` to `{results_prefix}/current.json`.

**Task 2.3 — Watcher cleans up stale snapshots per leg.**
After writing `current.json`, compute referenced run_ids = `{new.latest, new.last_passing}`. List all prefixes under `{results_prefix}/snapshots/`. Delete any snapshot prefix whose run_id is not in the referenced set.

**Task 2.4 — Remove lock/sentinel logic from watcher.**
Remove `_release_locks()`. Remove sentinel file checks. These are superseded by the pointer mechanism.

**Task 2.5 — Remove `verdict_uri` and `results_prefix` from trigger payload.**
In `run_trigger.py`: stop including `verdict_uri` and `results_prefix` in each leg. The trigger leg now contains only `project`, `bmt_id`, `run_id`, `triggered_at`.

The watcher resolves `results_prefix` from the manager summary's `ci_verdict_uri` field (already available after the orchestrator subprocess completes).

**Task 2.6 — Update `_aggregate_verdicts` to use verdict status from manager summaries.**
The watcher needs each leg's `status`, `reason_code`, and `aggregate_score` for the commit status description. These are all in the manager summary JSON. Map them to the existing aggregation logic (`decision_for_counts`).

**Task 2.7 — Test: pointer update and cleanup.**
Test that after a passing run, `current.json` has both `latest` and `last_passing` pointing to the new run_id, and old snapshots are deleted. Test that after a failing run, `last_passing` is unchanged and the old passing snapshot is retained. Test cleanup when `latest == last_passing` (only one snapshot retained). Test crash recovery: stale snapshot from a previous crashed run is cleaned up on the next run.

---

### Phase 3: CI wait/gate adaptation

**Goal:** The CI-side `wait` and `gate` commands (used for manual/local runs, not the main workflow) can read results from the new layout.

**Task 3.1 — Update `wait_verdicts.py` to resolve verdict from pointer.**
Instead of polling a `verdict_uri`, resolve `results_prefix` from config, read `current.json`, and check if `latest` matches the expected `run_id`. If yes, read the verdict from `snapshots/{run_id}/ci_verdict.json`.

**Task 3.2 — Update `verdict_gate.py` if it reads canonical verdict paths.**
Ensure it uses the same pointer-resolution path as wait.

**Task 3.3 — Update `ci/models.py`: remove `verdict_uri()`, `sentinel_uri()`, `lock_uri()` helpers.**
These produce paths that no longer exist in the new layout. Remove them. Add a `snapshot_verdict_path()` helper if needed by CI commands.

---

### Phase 4: Documentation and dead code cleanup

**Task 4.1 — Update CLAUDE.md.**

- New GCS layout (snapshots, `current.json`).
- Remove references to `last_passing.json`, sentinel files, `.lock` files, archive prefix.
- Document constraint: Check Run / PR comment must run after pointer update.

**Task 4.2 — Update ARCHITECTURE.md.**

- New GCS bucket structure diagram.
- Updated data flow (pointer update replaces tree copy/promotion).
- Remove staging/promotion copy language.

**Task 4.3 — Update README.md.**

- Remove references to old result paths.

**Task 4.4 — Remove dead code.**

- Manager: remove archive upload, `last_passing.json` upload, sentinel write, lock write.
- Watcher: remove `_release_locks()`, old `_aggregate_verdicts()` GCS download loop.
- CI models: remove `lock_uri()`, `sentinel_uri()`, legacy `trigger_uri()`.
- Config: remove `archive_prefix` from jobs config schema if no longer referenced.

---

## 4. Constraints for future work

- **Check Run / PR comment:** Must be produced after the watcher updates `current.json` (after all legs complete). Must read result data from the pointer-resolved snapshot path or from in-memory aggregation data. Must not assume any file exists at the bare `results_prefix/` root other than `current.json`.
- **Pub/Sub trigger:** Same payload as GCS trigger (minus `verdict_uri`/`results_prefix`). Same watcher processing flow. Pointer update and cleanup are trigger-source agnostic.
- **Cancel/supersede:** If a newer trigger arrives for the same ref, the watcher can skip pointer update for the older run. The old run's snapshot sits orphaned until the next run's cleanup deletes it (it won't be referenced by `current.json`). No special cancel logic needed — just don't update the pointer.

