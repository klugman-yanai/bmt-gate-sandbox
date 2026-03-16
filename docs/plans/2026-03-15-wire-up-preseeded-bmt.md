# Wire Up Preseeded BMT Handoff — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Wire up the preseeded-runner path so the full BMT lifecycle works end-to-end: CI triggers the VM with the SK leg, the VM runs the real BMT, and reports results back via commit status, Check Run, and PR comment.

**Architecture:** The existing `filter_upload_matrix` already supports `BMT_RUNNERS_PRESEEDED_IN_GCS` — it checks GCS for `runner_meta.json`, writes upload markers, and produces an empty upload matrix. Three wiring gaps prevent end-to-end operation: the env var is never set, the empty upload matrix causes a GitHub Actions error, and `github_repos.json` references the old repo name. A fourth latent bug (handshake sparse-checkout missing `gcp`) is fixed opportunistically.

**Tech Stack:** GitHub Actions workflows (YAML), Python (`.github/bmt/ci/`), JSON config

---

### Task 1: Enable `BMT_RUNNERS_PRESEEDED_IN_GCS` in the filter step

**Files:**
- Modify: `.github/workflows/bmt-handoff.yml:170-177`

**Why:** `filter_upload_matrix` (`.github/bmt/ci/runner.py:131-133`) reads `BMT_RUNNERS_PRESEEDED_IN_GCS` from env. When truthy, it treats any runner with `runner_meta.json` in GCS as preseeded: writes a marker to `_workflow/uploaded/{run_id}/{project}.json` and excludes the row from the upload matrix. Currently the env var is never set, so the function falls through to artifact matching (which also fails because `AVAILABLE_ARTIFACTS` is `[]`).

**Step 1: Add the env var to the filter step**

In `.github/workflows/bmt-handoff.yml`, the `filter` step (id: `filter`, line 170) currently has this env block:

```yaml
      - id: filter
        env:
          GCS_BUCKET: ${{ env.GCS_BUCKET }}
          RUNNER_MATRIX: ${{ steps.prepare.outputs.runner_matrix }}
          HEAD_SHA: ${{ steps.prepare.outputs.head_sha }}
          GITHUB_RUN_ID: ${{ github.run_id }}
          AVAILABLE_ARTIFACTS: ${{ inputs.available_artifacts || '[]' }}
        run: uv run bmt write-context && uv run bmt filter-upload-matrix
```

Add `BMT_RUNNERS_PRESEEDED_IN_GCS: "true"` to the env block:

```yaml
      - id: filter
        env:
          GCS_BUCKET: ${{ env.GCS_BUCKET }}
          RUNNER_MATRIX: ${{ steps.prepare.outputs.runner_matrix }}
          HEAD_SHA: ${{ steps.prepare.outputs.head_sha }}
          GITHUB_RUN_ID: ${{ github.run_id }}
          AVAILABLE_ARTIFACTS: ${{ inputs.available_artifacts || '[]' }}
          BMT_RUNNERS_PRESEEDED_IN_GCS: "true"
        run: uv run bmt write-context && uv run bmt filter-upload-matrix
```

**Step 2: Verify the change is correct**

Trace the data flow mentally:
- `parse-release-runners` (in `bmt-prepare-context`) parses `CMakePresets.json` → produces `runner_matrix` with ~12 entries (SK, WOVEN, CONTINENTAL, etc.)
- `filter_upload_matrix` with `preseeded=True` → for each entry, checks `{runtime_root}/{project}/runners/{preset}/runner_meta.json` in GCS
- Only SK has a preseeded runner → marker written for SK, all others excluded (no artifact match either)
- Output: `matrix_need_upload={"include":[]}`, `matrix_need_upload_keys=[]`

**Step 3: Commit**

```bash
git add .github/workflows/bmt-handoff.yml
git commit -m "feat: set BMT_RUNNERS_PRESEEDED_IN_GCS=true in filter step"
```

---

### Task 2: Guard `upload-runners` job against empty matrix

**Files:**
- Modify: `.github/workflows/bmt-handoff.yml:215-225`

**Why:** With Task 1, `filter_upload_matrix` produces `matrix_need_upload={"include":[]}`. GitHub Actions fails with "Matrix vector does not contain any values" when a `strategy.matrix` evaluates to an empty include array. The `if` condition is evaluated **before** the matrix, so guarding with `if` prevents the error entirely — the job gets status `skipped` instead.

**Step 1: Add `if` guard to the upload-runners job**

Current (line 215-225):

```yaml
  upload-runners:
    name: Validate runner • ${{ matrix.project }}
    needs: setup
    runs-on: ubuntu-22.04
    continue-on-error: true
    permissions:
      id-token: write
    strategy:
      fail-fast: false
      max-parallel: 3
      matrix: ${{ fromJson(needs.setup.outputs.matrix_need_upload || '[]') }}
```

Add `if` after `needs`:

```yaml
  upload-runners:
    name: Validate runner • ${{ matrix.project }}
    needs: setup
    if: needs.setup.outputs.matrix_need_upload_keys != '[]'
    runs-on: ubuntu-22.04
    continue-on-error: true
    permissions:
      id-token: write
    strategy:
      fail-fast: false
      max-parallel: 3
      matrix: ${{ fromJson(needs.setup.outputs.matrix_need_upload || '{"include":[]}') }}
```

Note: also change the fallback from `'[]'` to `'{"include":[]}'` — a bare `[]` is not a valid matrix object and would error if ever reached.

**Step 2: Commit**

```bash
git add .github/workflows/bmt-handoff.yml
git commit -m "fix: guard upload-runners against empty matrix (preseeded path)"
```

---

### Task 3: Fix handshake job dependency chain

**Files:**
- Modify: `.github/workflows/bmt-handoff.yml:247-249`

**Why:** The `handshake` job has `needs: [setup, upload-runners]`. When `upload-runners` is skipped (Task 2), GitHub Actions skips all dependent jobs by default. Adding an `if` condition with `!cancelled()` allows the job to run when dependencies are skipped or succeeded, but not when cancelled or failed.

**Critical detail:** The job ID `upload-runners` contains a hyphen, so bracket notation (`needs['upload-runners']`) is required in expressions.

**Step 1: Add `if` condition to the handshake job**

Current (line 247-249):

```yaml
  handshake:
    name: Handshake with VM
    needs: [setup, upload-runners]
```

Change to:

```yaml
  handshake:
    name: Handshake with VM
    needs: [setup, upload-runners]
    if: >-
      !cancelled()
      && needs.setup.result == 'success'
      && (needs['upload-runners'].result == 'success' || needs['upload-runners'].result == 'skipped')
```

**Step 2: Commit**

```bash
git add .github/workflows/bmt-handoff.yml
git commit -m "fix: allow handshake to run when upload-runners is skipped"
```

---

### Task 4: Fix handshake sparse-checkout to include `gcp`

**Files:**
- Modify: `.github/workflows/bmt-handoff.yml:270-275`

**Why:** The handshake job checks out only `.github` (sparse-checkout). But the BMT CLI imports from `gcp.image.config.bmt_config`, and the root `pyproject.toml` (line 29) declares `gcp/image` as a workspace member. When `uv sync` runs (via `setup-gcp-uv`), it fails because the workspace member directory is missing. The handoff (failure-fallback) job already correctly checks out both `.github` and `gcp` (line 321-323). The handshake job needs the same fix.

**Step 1: Add `gcp` to the handshake checkout sparse-checkout**

Current (line 270-275):

```yaml
      - name: Checkout repo (for local actions)
        uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd # v6
        with:
          ref: ${{ inputs.head_sha || github.event.inputs.head_sha || github.sha }}
          fetch-depth: 1
          sparse-checkout: .github
```

Change `sparse-checkout` to a multiline value:

```yaml
      - name: Checkout repo (for local actions)
        uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd # v6
        with:
          ref: ${{ inputs.head_sha || github.event.inputs.head_sha || github.sha }}
          fetch-depth: 1
          sparse-checkout: |
            .github
            gcp
```

**Step 2: Commit**

```bash
git add .github/workflows/bmt-handoff.yml
git commit -m "fix: handshake sparse-checkout must include gcp (workspace member)"
```

---

### Task 5: Update repository identity (`bmt-gate-sandbox` → `bmt-gcloud`)

**Files:**
- Modify: `gcp/image/config/github_repos.json:4`
- Modify: `tools/bmt/bmt_monitor.py:35`
- Modify: `docs/configuration.md:282`

**Why:** The repo was renamed from `bmt-gate-sandbox` to `bmt-gcloud`. The VM uses `github_repos.json` to resolve GitHub App credentials for posting commit status, Check Runs, and PR comments. With the old name, `resolve_auth_for_repository("klugman-yanai/bmt-gcloud")` fails to match and the VM cannot report results.

**Step 1: Update `github_repos.json`**

In `gcp/image/config/github_repos.json`, change the key on line 4:

```json
{
  "version": "1.0",
  "repositories": {
    "klugman-yanai/bmt-gcloud": {
      "repo_env": "test",
      "description": "Test sandbox repository for BMT development",
      "secret_prefix": "GITHUB_APP_TEST",
      "enabled": true
    },
    "Kardome-org/core-main": {
      "repo_env": "prod",
      "description": "Production core-main repository",
      "secret_prefix": "GITHUB_APP_PROD",
      "enabled": true
    }
  }
}
```

**Step 2: Update the default repo constant in `bmt_monitor.py`**

In `tools/bmt/bmt_monitor.py` line 35, change:

```python
_DEFAULT_REPO_TEST = "klugman-yanai/bmt-gcloud"
```

**Step 3: Update `docs/configuration.md`**

In `docs/configuration.md` line 282, replace `bmt-gate-sandbox` with `bmt-gcloud`:

```
**Single source of truth:** bmt-gcloud. Author workflows here; deploy to bmt-gcloud to validate; propose to core-main via PR. **Drift:** Diff `.github/workflows/bmt-handoff.yml`, `.github/actions/bmt-*`, `setup-gcp-uv`, and `.github/bmt/` between core-main and bmt-gcloud. Only in bmt-gcloud → PR to core-main or dev-only. Only in core-main → add to bmt-gcloud to mirror. **Sandbox** (klugman-yanai/bmt-gcloud): full control; keep workflow shape and BMT condition in sync with production. **Production** (Kardome-org/core-main): propose changes via PR; branch protection and credentials are prod-specific.
```

**Step 4: Commit**

```bash
git add gcp/image/config/github_repos.json tools/bmt/bmt_monitor.py docs/configuration.md
git commit -m "fix: rename bmt-gate-sandbox to bmt-gcloud in config and docs"
```

---

### Task 6: Run tests

**Step 1: Run the full test suite**

```bash
uv run python -m pytest tests/ -v
```

Expected: all tests pass. No test currently exercises the preseeded env var (`BMT_RUNNERS_PRESEEDED_IN_GCS`), so the existing tests validate that nothing was broken by the repo-identity change.

**Step 2: Run linting**

```bash
ruff check .
ruff format --check .
```

Expected: clean. No Python logic was changed — only YAML, JSON, and a string constant.

**Step 3: Run type checking**

```bash
basedpyright
```

Expected: clean (only a string constant changed in Python files).

---

### Task 7: Archive the old `bmt-handoff.yml` as v0.0.1

**Files:**
- Modify: `docs/archive/bmt-handoff-v0.0.1.yml` (currently empty)

**Why:** The file was created but left empty. Copy the current pre-change `bmt-handoff.yml` content into it before the changes, so there's a reference to the state before the preseeded wiring.

**Step 1: Save the current workflow as the v0.0.1 archive**

```bash
git show HEAD:.github/workflows/bmt-handoff.yml > docs/archive/bmt-handoff-v0.0.1.yml
```

**Step 2: Commit**

```bash
git add docs/archive/bmt-handoff-v0.0.1.yml
git commit -m "docs: archive bmt-handoff.yml as v0.0.1 (pre-preseeded wiring)"
```

---

## Reference: End-to-End Data Flow

```
CMakePresets.json
  ↓ parse-release-runners
runner_matrix: {include: [{project:sk, preset:sk_gcc_release}, {project:woven,...}, ...]}
  ↓ filter_upload_matrix (BMT_RUNNERS_PRESEEDED_IN_GCS=true)
  │  for each row: check gs://<bucket>/runtime/{project}/runners/{preset}/runner_meta.json
  │  SK found → write marker to _workflow/uploaded/{run_id}/sk.json
  │  Others not found → excluded
  ↓
matrix_need_upload: {"include":[]}          → upload-runners SKIPPED
matrix_need_upload_keys: []
  ↓ resolve_uploaded_projects
  │  list _workflow/uploaded/{run_id}/*.json → finds sk.json
  │  also scans RUNNER_MATRIX against GCS runner_meta.json → finds SK
  ↓
accepted_projects: ["sk"]
  ↓ filter_supported_matrix
filtered_matrix: {include: [{project:sk, bmt_id:sk_gcc_release, ...}]}
  ↓ write-run-trigger
trigger → gs://<bucket>/runtime/triggers/runs/<workflow_run_id>.json (1 SK leg)
  ↓ VM picks up trigger
handshake ack → gs://<bucket>/runtime/triggers/acks/<workflow_run_id>.json
  ↓ root_orchestrator → sk/bmt_manager → runs WAVs → scores → gate
  ↓ vm_watcher aggregates
commit status + Check Run + PR comment → GitHub API (via GitHub App)
```

## Reference: GitHub Actions Job Dependency Behavior

| `upload-runners` result | `handshake` runs? | Why |
|------------------------|-------------------|-----|
| `success` | Yes | `needs.setup.result == 'success'` and `needs['upload-runners'].result == 'success'` |
| `skipped` (empty matrix) | Yes | `needs['upload-runners'].result == 'skipped'` allowed by `if` |
| `failure` | No | Neither `success` nor `skipped` |
| `cancelled` | No | `!cancelled()` catches workflow cancellation |
