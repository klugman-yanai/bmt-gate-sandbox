# Hard Cutover Plan: Remove `BMT_BUCKET_PREFIX` End-to-End

## Summary

Breaking hard cutover: `BMT_BUCKET_PREFIX` is removed from workflows, VM runtime, tool interfaces, and active docs. The namespace model becomes fixed:

- Code root: `gs://<GCS_BUCKET>/code`
- Runtime root: `gs://<GCS_BUCKET>/runtime`

Fail-fast guards protect against leftover non-empty legacy prefix configuration in repo vars and VM metadata.

## Scope

**36 files** currently reference `BMT_BUCKET_PREFIX`; **20 files** reference `--bucket-prefix` CLI args. The codebase is already in a transition state (`bucket_prefix_parent` coexists with `bucket_prefix` in trigger payloads and several scripts). This plan completes that transition.

## Breaking Changes

1. **CLI interface removals** — Remove `--bucket-prefix` from:
   - `.github/scripts/ci/commands/run_trigger.py`
   - `.github/scripts/ci/commands/upload_runner.py`
   - `.github/scripts/ci/commands/wait_handshake.py`
   - `.github/scripts/ci/commands/wait_verdicts.py`
   - `tools/bmt_monitor.py`
   - `tools/bucket_*` tools via `shared_bucket_env.bucket_prefix_option`
   - `deploy/code/vm_watcher.py`
   - `deploy/code/root_orchestrator.py`
   - `deploy/code/sk/bmt_manager.py`
   - `deploy/code/sk/sk_bmt_manager.py`

2. **Trigger payload schema** — Remove `bucket_prefix_parent` and `bucket_prefix` fields. Keep `bucket`, `workflow_run_id`, `repository`, `sha`, `run_context`, `status_context`, `description_pending`, `legs`.

3. **CI model types** (`.github/scripts/ci/models.py`) — Remove parent-prefix helpers; make code/runtime root helpers fixed; remove `LegOutcome.bucket_prefix`.

4. **Env contract** (`config/env_contract.json`) — Remove `BMT_BUCKET_PREFIX` from all contexts, defaults, and consistency checks.

## Implementation Plan

### Phase 1: Contract and Config Baseline

- `config/env_contract.json`: remove `BMT_BUCKET_PREFIX` from all contexts, defaults, and `consistency_checks.repo_vs_vm_metadata`.
- `config/repo_vars.toml`: remove any `BMT_BUCKET_PREFIX` entry.
- Keep `GCS_BUCKET` as the canonical bucket identifier.

### Phase 2: CI Models and Shared Libraries

- `.github/scripts/ci/models.py`: remove parent-prefix helpers, make code/runtime root helpers fixed, remove `LegOutcome.bucket_prefix`.
- `tools/shared_bucket_env.py`: remove `get_bucket_prefix_from_env`, `bucket_prefix_option`, and parent-prefix helpers; keep fixed `code`/`runtime` helpers.
- `.github/scripts/workflows/lib/common.sh`: make `runtime_prefix()` return constant `runtime`.

### Phase 3: Workflow and CI Commands

- Shell wrappers `.github/scripts/workflows/cmd/{trigger.sh,upload.sh,handshake.sh}`: remove `--bucket-prefix` forwarding.
- `Justfile`: remove `BMT_BUCKET_PREFIX` logic from `wait-handshake` and `gcs-trigger`.
- CI Python commands (`run_trigger.py`, `upload_runner.py`, `wait_handshake.py`, `wait_verdicts.py`): remove `--bucket-prefix` options and parent-prefix derivations; resolve runtime root as `gs://<bucket>/runtime`.
- Fail-fast guard: in `.github/scripts/workflows/cmd/context.sh`, error if `BMT_BUCKET_PREFIX` is non-empty. In `.github/workflows/bmt.yml`, expose `vars.BMT_BUCKET_PREFIX` only for guard validation.
- `.github/scripts/ci/commands/sync_vm_metadata.py`: stop writing/verifying `BMT_BUCKET_PREFIX`. Add legacy guard (non-empty → fail-fast). Add metadata-key removal support in `.github/scripts/ci/adapters/gcloud_cli.py`.

### Phase 4: VM Runtime and Bootstrap

- `deploy/code/vm_watcher.py`: remove `--bucket-prefix` arg; stop reading `bucket_prefix_parent`/`bucket_prefix` from trigger payload; use fixed namespaces.
- `deploy/code/root_orchestrator.py`, `deploy/code/sk/bmt_manager.py`: remove prefix args and compatibility fallbacks.
- `deploy/code/sk/sk_bmt_manager.py`: remove legacy prefix usage.
- Bootstrap scripts:
  - `startup_wrapper.sh`: stop reading/exporting `BMT_BUCKET_PREFIX`; derive fixed roots.
  - `startup_example.sh`: remove `BMT_BUCKET_PREFIX` metadata/env flow and watcher arg.
  - `ensure_uv.sh`: derive code root without parent prefix.
  - `setup_vm_startup.sh`, `rollback_vm_startup_to_inline.sh`, `ssh_install.sh`, `audit_vm_and_bucket.sh`, `bmt-watcher.service.example`: remove legacy variable usage.

### Phase 5: Devtools

- All `tools/bucket_*` scripts: remove `bucket_prefix` parameters and `bucket_prefix_parent` manifest fields.
- `tools/bmt_monitor.py`: remove `--bucket-prefix`; use fixed runtime root; remove prefix fields from monitor state.
- `tools/gh_show_env.py`: remove `BMT_BUCKET_PREFIX` from env display.
- `tools/gh_validate_vm_vars.py`: remove `BMT_BUCKET_PREFIX` validation.

### Phase 6: Tests

Update these test files to remove prefix-related fixtures, arguments, and assertions:

| Test file | Changes |
| --------- | ------- |
| `tests/test_sync_vm_metadata.py` | Remove prefix expectations; add non-empty legacy metadata fail case |
| `tests/test_run_trigger_guard.py` | Remove `--bucket-prefix` arg usage and payload field assertions |
| `tests/test_wait_handshake.py` | Remove prefix option and prefixed runtime-root expectations |
| `tests/test_ci_models.py` | Update helpers for fixed namespace; update `LegOutcome` shape |
| `tests/test_bootstrap_scripts.py` | Remove `BMT_BUCKET_PREFIX` env setup; add legacy non-empty guard test |
| `tests/test_vm_watcher_pr_closed.py` | Remove prefix payload fields from fixtures/assertions |
| `tests/test_vm_watcher_pointer.py` | Remove prefix payload fields from fixtures/assertions |

### Phase 7: Docs and CLAUDE.md

Update active docs only (do not modify `docs/plans/archive/**`):

- `docs/configuration.md`
- `docs/development.md`
- `docs/architecture.md`
- `docs/implementation.md`
- `docs/github-actions-and-cli-tools.md`
- `deploy/code/bootstrap/README.md`
- `docs/plans/migration-to-production.md`
- `CLAUDE.md`
- `README.md`

Remove `BMT_BUCKET_PREFIX` instructions and replace `<bucket>/<parent>/...` examples with fixed `/code` and `/runtime`.

**Note:** `docs/diagrams.md` is already deleted — no action needed.

## Validation

### Static checks (run after each phase)

```bash
uv run python -m pytest tests/ -v
ruff check .
ruff format --check .
basedpyright
```

### Grep verification (after all phases)

```bash
# Should return zero matches outside docs/plans/archive/ and PLAN.md
rg 'BMT_BUCKET_PREFIX' --glob '!docs/plans/archive/**' --glob '!docs/plans/PLAN.md' --glob '!.git/**'
rg '\-\-bucket-prefix' --glob '!docs/plans/archive/**' --glob '!docs/plans/PLAN.md' --glob '!.git/**'
```

### Acceptance criteria

- Zero functional references to `BMT_BUCKET_PREFIX` in active runtime/workflow/tooling paths.
- No CLI supports `--bucket-prefix`.
- Trigger/ack/status paths resolve only under `gs://<bucket>/runtime/...`.
- VM metadata sync no longer writes/verifies prefix key.
- Non-empty legacy prefix in repo var or VM metadata causes explicit fail-fast.

## Live Validation: PR Merge to `dev`

### Preflight (before testing the live PR)

Do these in order so the workflow and VM run the same code and bucket state you expect:

1. **Sync bucket first** — Upload local `deploy/code` and `deploy/runtime` to GCS so the bucket matches your working tree. Then commit/push so the pre-commit hook (advisory sync check) can verify successfully:
   ```bash
   just sync-deploy && just sync-runtime-seed && just verify-sync
   ```
   Requires `GCS_BUCKET` set. Do this before committing so that when you push, the VM will run the same assets you just synced.
2. **Commit and push your branch** — All cutover changes must be committed and pushed. The BMT workflow is triggered from the branch head; uncommitted or unpushed changes will not run on the VM. Syncing before commit ensures the pre-commit hook (see `.pre-commit-config.yaml` and `scripts/hooks/pre-commit-sync-deploy.sh`) sees the bucket in sync.
3. **Verify repo vars** — `just repo-vars-check` passes with no `BMT_BUCKET_PREFIX` drift.
4. **Confirm VM state** — VM is in `TERMINATED` state (so the next trigger will start it cleanly).

### PR validation (before merge)

- Open PR with this cutover.
- Expected `bmt.yml` behavior:
  - `01 Prepare Context` succeeds.
  - `04B Handoff Run` writes trigger and receives handshake ack.
  - Ack URI is `gs://<bucket>/runtime/triggers/acks/<run_id>.json`.
- No logs mention parent prefix derivation.

### Post-merge live run

- Trigger live run on `dev`.
- Monitor: `just monitor --run-id <run_id>`, `just gcs-trigger <run_id>`, `just vm-serial`.

#### GCS paths (no prefix in any path)

- Trigger: `gs://<bucket>/runtime/triggers/runs/<run_id>.json`
- Ack: `gs://<bucket>/runtime/triggers/acks/<run_id>.json`
- Status: `gs://<bucket>/runtime/triggers/status/<run_id>.json`
- VM serial shows watcher startup without prefix-parent logs.

#### Check run — Checks tab content (critical)

The **Checks tab** on the PR is the primary documentation of BMT results. Verify the full lifecycle:

1. **Creation**: Check run named `BMT_STATUS_CONTEXT` (e.g. `BMT Gate`) created as `in_progress` when the VM picks up the trigger.
2. **Live progress updates**: During execution, the check run summary is updated via `render_progress_markdown()` with a live table showing per-leg status, files completed/total, elapsed time, and ETA:

   ```
   **Running — 1/2 legs complete** · Elapsed: 3m 12s · ETA: ~2m left

   | Project | BMT | Status | Progress | Duration |
   |---------|-----|--------|----------|----------|
   | sk | false_reject_namuh | ✅ pass | 10/10 files | 3m 05s |
   | sk | another_test | 🔵 running | 5/10 files | 1m 30s |
   ```

3. **Final results**: On completion, check run transitions to `completed` with `conclusion` = `success` or `failure`. The summary is replaced by `render_results_table()` with per-leg verdict, average score, and duration:

   ```
   ## ✅ BMT Complete: PASS
   **Decision:** success

   | Project | BMT | Verdict | Score | Duration |
   |---------|-----|---------|-------|----------|
   | sk | false_reject_namuh | ✅ PASS | 85.5 | 5m 30s |
   ```

**Verify:** Open the PR Checks tab and confirm the final results table is populated with actual scores and verdicts — not just a status string.

#### Commit status

- `pending` during run → terminal `success`/`failure` (or `error` for cancellation).

#### PR comment

PR comments are implemented via `github_pr_comment.upsert_pr_comment_by_marker()`:

- Marker: `<!-- bmt-vm-comment-sha:<sha> -->`
- On success: "All tests passed." with link to Checks tab for details.
- On failure: Lists failed legs (e.g. "Failed: **SK · False Rejects**") with link to Checks tab.
- On superseding commit: Comment indicates superseded result with superseding commit link.

**Verify:** The PR has exactly one VM-authored comment per tested SHA, and it directs to the Checks tab for full results.

#### VM lifecycle

- VM returns to `TERMINATED` (self-stop with `BMT_SELF_STOP=1`).
- If VM remains `RUNNING` after completion, treat as regression.

### Edge-case verification (post-cutover)

Confirm these existing behaviors are unaffected by the prefix removal:

- **PR closure mid-run**: Check run finalized as `neutral`, commit status `error`, no PR comment posted, no pointer promotion.
- **Superseding commit mid-run**: Check run finalized as `neutral`, PR comment upserted with superseding SHA, no pointer promotion.
- **Startup failure**: Check run created at completion time via `_finalize_check_run_resilient()` fallback if initial creation failed.

## Assumptions

- Hard cutover — no backward compatibility for `--bucket-prefix`.
- Archived docs remain historical and unchanged.
- `BMT_STATUS_CONTEXT` remains branch-rule sourced and unchanged.
- Runtime/data roots fixed to `/runtime` and `/code` under `GCS_BUCKET`.
