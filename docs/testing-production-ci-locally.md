# Testing production CI locally

This is the **canonical guide** for testing production BMT CI locally using the real VM and GCS (no mocks). Follow it when you want to validate the full handoff path before pushing to production.

## Prerequisites

- **Repo variables** set: at least `GCS_BUCKET`, `GCP_PROJECT`, `GCP_ZONE`, `BMT_VM_NAME`, and the Terraform-exported vars (`just terraform-export-vars-apply`), including `BMT_STATUS_CONTEXT`, `BMT_HANDSHAKE_TIMEOUT_SEC`, `BMT_PROJECTS`. Optional for local override: `GCP_WIF_PROVIDER`, `GCP_SA_EMAIL`, `BMT_PUBSUB_TOPIC`. Use `gh variable list` or Settings → Secrets and variables → Actions → Variables.
- **gcloud** authenticated and able to access the bucket and VM (`gcloud auth list`, `gcloud storage ls gs://<bucket>`).
- **Python 3.12** and **uv** (`uv sync` and `uv pip install -e .` from repo root).

Confirm env: run `just show-env` to print the variable names used by CI, VM, and devtools.

## Strict prerequisite: sync the mirror

**Before** running any workflow steps, sync the local mirror to the bucket so the VM runs the same code and layout you have locally:

```bash
just sync-gcp
just verify-sync
```

Skipping this can cause the VM to run stale code. Re-run after changing anything under `remote/`.

## Option A: One command (recommended)

After prerequisites and sync:

```bash
just prod-ci-local
```

This runs the full sequence (sync-verify → matrix → trigger → sync-vm-metadata → start-vm → wait-handshake) and prints next steps. Use the same run id for `just wait-handshake <run_id>` and `just gcs-trigger <run_id>`.

## Option B: Manual sequence (same as workflow)

Use this when you need to run steps individually or debug a specific step.

1. **Sync mirror** (if not already done):
   ```bash
   just sync-gcp
   just verify-sync
   ```

2. **Matrix** — build the job matrix and write to `GITHUB_OUTPUT`:
   ```bash
   export GITHUB_OUTPUT="$(pwd)/.local/prod-ci-matrix.out"
   mkdir -p .local
   BMT_CONFIG_ROOT=gcp/code uv run --project .github/bmt bmt matrix
   ```
   The matrix JSON is in the output file under the key `matrix` (or `BMT_OUTPUT_KEY`).

3. **Trigger** — write the run trigger to GCS (and to Pub/Sub if `BMT_PUBSUB_TOPIC` is set). Pick a workflow run id (e.g. `local-$(date +%s)`) and use it for both trigger and wait-handshake:
   ```bash
   RUN_ID="local-$(date +%s)"
   echo "$RUN_ID" > .local/prod-ci-run-id.txt
   export GITHUB_RUN_ID="$RUN_ID"
   export GITHUB_OUTPUT="$(pwd)/.local/prod-ci-trigger.out"
   export FILTERED_MATRIX_JSON="$(grep '^matrix=' .local/prod-ci-matrix.out | cut -d= -f2-)"
   export RUN_CONTEXT=dev
   export GITHUB_REPOSITORY="${GITHUB_REPOSITORY:-$(gh repo view --json nameWithOwner -q .nameWithOwner)}"
   # Optional: enable Pub/Sub so the VM gets the trigger without GCS polling
   export BMT_PUBSUB_TOPIC="${BMT_PUBSUB_TOPIC:-$(gh variable get BMT_PUBSUB_TOPIC 2>/dev/null || true)}"
   uv run --project .github/bmt bmt write-run-trigger
   ```
   If `BMT_PUBSUB_TOPIC` is set you should see `Published trigger to Pub/Sub topic '...'`; the VM (with `BMT_PUBSUB_SUBSCRIPTION` set) will then receive the trigger via Pub/Sub instead of polling GCS.

4. **Sync VM metadata** (so the VM sees the bucket and repo root):
   ```bash
   just sync-vm-metadata
   ```

5. **Start the VM** (if not already running):
   ```bash
   just start-vm
   ```

6. **Wait for handshake** — VM must write the ack file; workflow would exit here:
   ```bash
   just wait-handshake "$(cat .local/prod-ci-run-id.txt)"
   ```

7. **Verify** — VM runs BMT legs, updates pointers, posts commit status and Check Run. Inspect:
   - `just monitor` or `just monitor --run-id $(cat .local/prod-ci-run-id.txt)`
   - `just gcs-trigger $(cat .local/prod-ci-run-id.txt)` — trigger and ack JSON in GCS
   - GitHub PR/commit **Checks** for the BMT Gate status and Check Run
   - GCS: `gs://<bucket>/runtime/<results_prefix>/current.json` and `snapshots/<run_id>/`

## Verify

- **Trigger and ack:** `just gcs-trigger <run_id>` shows the trigger file and the VM’s ack file (VM writes ack when it picks up the trigger).
- **Live TUI:** `just monitor` or `just monitor --run-id <run_id>` for trigger/ack/status and VM state.
- **Outcome:** Check Run and commit status in GitHub; `current.json` and snapshot dirs in GCS at the results prefix for each (project, bmt_id).

## See also

- [Development](development.md) — setup, test tiers, lint, deploy
- [Architecture](architecture.md) — trigger-and-stop flow, GCS contract, production surface
- [High-level design improvements](plans/high-level-design-improvements.md) — strategy and rationale
