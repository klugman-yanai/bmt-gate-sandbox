# Migration Plan: BMT to Production Repo (`Kardome-org/core-main`)

## Overview

Enable BMT gating in `Kardome-org/core-main` with **minimal changes** to existing files. The dev repo owns all infrastructure (VM, GCS, config). The production repo downloads config from GCS at runtime.

**Changes to existing files:** Only `build-and-test.yml` (add 1 step + 1 job).
**New files:** `.github/scripts/` (CI package), `.github/workflows/bmt.yml`, `.github/actions/setup-gcp-uv/`.

---

## Architecture

```
Prod CI (build-and-test.yml)
  └─ uploads runner artifact
  └─ trigger-bmt job dispatches bmt.yml

Prod CI (bmt.yml)
  └─ downloads BMT config from GCS (no deploy/ dir in prod)
  └─ downloads runner artifact from build job
  └─ uploads runner to GCS
  └─ writes trigger, starts VM, waits for ack

VM (shared between dev + prod)
  └─ picks up trigger, runs BMT
  └─ posts commit status + Check Run to core-main
  └─ stops itself
```

---

## Pre-requisites (Manual / GCP Console)

### P1. Add `Kardome-org/core-main` to WIF Pool

The WIF pool (`bmt-gate-gha-dev`) currently only allows the sandbox repo. Add `core-main`:

```bash
# Get current attribute condition
gcloud iam workload-identity-pools providers describe github-oidc \
  --project=train-kws-202311 \
  --location=global \
  --workload-identity-pool=bmt-gate-gha-dev \
  --format='value(attributeCondition)'

# Update to include core-main (adjust the condition to OR both repos)
# Example: assertion.repository == 'klugman-yanai/bmt-gate-sandbox' || assertion.repository == 'Kardome-org/core-main'
```

### P2. Create Prod GitHub App (if not already done)

A separate GitHub App for `Kardome-org/core-main` with `actions:write` permission to dispatch `bmt.yml`. Note the App ID and generate a private key.

---

## Step 1: Dev Repo — Create `dispatch-workflow` Command

> Already done in this session. Files created:
> - `.github/scripts/ci/commands/dispatch_workflow.py`
> - Updated `.github/scripts/ci_driver.py` to register it

Commit and sync:

```bash
git add .github/scripts/ci/commands/dispatch_workflow.py .github/scripts/ci_driver.py
git commit -m "feat: add dispatch-workflow CI command for prod BMT trigger"
just sync-deploy
```

---

## Step 2: Production Repo — Copy `.github/scripts/`

Copy the entire CI package from dev to prod. From the **dev repo root**:

```bash
DEV=/home/yanai/sandbox/bmt-gcloud
PROD=/home/yanai/kardome/core-main

# Python CI package
mkdir -p "$PROD/.github/scripts/ci/adapters" "$PROD/.github/scripts/ci/commands"
cp "$DEV/.github/scripts/ci_driver.py" "$PROD/.github/scripts/"
cp "$DEV/.github/scripts/ci/__init__.py" "$PROD/.github/scripts/ci/"
cp "$DEV/.github/scripts/ci/models.py" "$PROD/.github/scripts/ci/"
cp "$DEV/.github/scripts/ci/config.py" "$PROD/.github/scripts/ci/"
cp "$DEV/.github/scripts/ci/github_output.py" "$PROD/.github/scripts/ci/"
cp "$DEV/.github/scripts/ci/adapters/__init__.py" "$PROD/.github/scripts/ci/adapters/"
cp "$DEV/.github/scripts/ci/adapters/gcloud_cli.py" "$PROD/.github/scripts/ci/adapters/"
cp "$DEV/.github/scripts/ci/commands/__init__.py" "$PROD/.github/scripts/ci/commands/"
cp "$DEV/.github/scripts/ci/commands/dispatch_workflow.py" "$PROD/.github/scripts/ci/commands/"
cp "$DEV/.github/scripts/ci/commands/filter_supported_matrix.py" "$PROD/.github/scripts/ci/commands/"
cp "$DEV/.github/scripts/ci/commands/job_matrix.py" "$PROD/.github/scripts/ci/commands/"
cp "$DEV/.github/scripts/ci/commands/release_runner_matrix.py" "$PROD/.github/scripts/ci/commands/"
cp "$DEV/.github/scripts/ci/commands/run_trigger.py" "$PROD/.github/scripts/ci/commands/"
cp "$DEV/.github/scripts/ci/commands/start_vm.py" "$PROD/.github/scripts/ci/commands/"
cp "$DEV/.github/scripts/ci/commands/sync_vm_metadata.py" "$PROD/.github/scripts/ci/commands/"
cp "$DEV/.github/scripts/ci/commands/upload_runner.py" "$PROD/.github/scripts/ci/commands/"
cp "$DEV/.github/scripts/ci/commands/verdict_gate.py" "$PROD/.github/scripts/ci/commands/"
cp "$DEV/.github/scripts/ci/commands/wait_handshake.py" "$PROD/.github/scripts/ci/commands/"
cp "$DEV/.github/scripts/ci/commands/wait_verdicts.py" "$PROD/.github/scripts/ci/commands/"

# Shell workflow scripts
mkdir -p "$PROD/.github/scripts/workflows/lib" "$PROD/.github/scripts/workflows/cmd"
cp "$DEV/.github/scripts/workflows/bmt_workflow.sh" "$PROD/.github/scripts/workflows/"
cp "$DEV/.github/scripts/workflows/lib/common.sh" "$PROD/.github/scripts/workflows/lib/"
cp "$DEV/.github/scripts/workflows/cmd/context.sh" "$PROD/.github/scripts/workflows/cmd/"
cp "$DEV/.github/scripts/workflows/cmd/failure.sh" "$PROD/.github/scripts/workflows/cmd/"
cp "$DEV/.github/scripts/workflows/cmd/handshake.sh" "$PROD/.github/scripts/workflows/cmd/"
cp "$DEV/.github/scripts/workflows/cmd/summary.sh" "$PROD/.github/scripts/workflows/cmd/"
cp "$DEV/.github/scripts/workflows/cmd/trigger.sh" "$PROD/.github/scripts/workflows/cmd/"
cp "$DEV/.github/scripts/workflows/cmd/upload.sh" "$PROD/.github/scripts/workflows/cmd/"

# Composite action
mkdir -p "$PROD/.github/actions/setup-gcp-uv"
cp "$DEV/.github/actions/setup-gcp-uv/action.yml" "$PROD/.github/actions/setup-gcp-uv/"

# Config (env contract — used by run_trigger.py for BMT_STATUS_CONTEXT default)
mkdir -p "$PROD/config"
cp "$DEV/config/env_contract.json" "$PROD/config/"
```

### Step 2b: Create prod-specific `repo_paths.py`

The dev version imports from `tools.repo_paths` which doesn't exist in prod. Create a **standalone version** at `$PROD/.github/scripts/ci/repo_paths.py`:

```python
"""Repo path constants for CI commands (production variant).

In production, config is downloaded from GCS to a temp dir and passed via
--config-root. These defaults are fallbacks only.
"""

from __future__ import annotations

# These defaults are only used when --config-root is not passed explicitly.
# In production, bmt.yml always passes --config-root "$BMT_CONFIG_ROOT".
DEFAULT_CONFIG_ROOT = "deploy/code"
DEFAULT_RUNTIME_ROOT = "deploy/runtime"
DEFAULT_ENV_CONTRACT_PATH = "config/env_contract.json"
DEFAULT_REPO_VARS_PATH = "config/repo_vars.toml"
```

### Step 2c: Create prod `pyproject.toml`

The CI scripts only need `click`. Create at `$PROD/pyproject.toml` (or merge into existing if one exists):

```toml
[build-system]
requires = ["setuptools"]
build-backend = "setuptools.build_meta"

[project]
name = "bmt-ci"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "click>=8.0",
]

[tool.setuptools.packages.find]
where = [".github/scripts"]
```

> **Note:** If `core-main` already has a `pyproject.toml`, add the `click` dependency and the `[tool.setuptools.packages.find]` entry to it instead.

---

## Step 3: Production Repo — Copy `bmt.yml` (with GCS config download)

Copy `$DEV/.github/workflows/bmt.yml` to `$PROD/.github/workflows/bmt.yml`.

**Two modifications needed:**

### 3a. Add GCS config download steps

In the `classify-handoff` job (job 03), **after** "Setup GCP and uv" and **before** "Build BMT matrix", add:

```yaml
      - name: Download BMT config from GCS
        run: |
          mkdir -p /tmp/bmt-config/sk
          ROOT="gs://${GCS_BUCKET}/code"
          gcloud storage cp "${ROOT}/bmt_projects.json" /tmp/bmt-config/ --quiet
          gcloud storage cp -r "${ROOT}/sk/config" /tmp/bmt-config/sk/ --quiet
          echo "BMT_CONFIG_ROOT=/tmp/bmt-config" >>"$GITHUB_ENV"
```

Also add the same step in `handoff-run` (job 04B), **after** "Setup GCP and uv" and **before** "Write run trigger to GCS".

### 3b. Update `--config-root` references

Change this line in `classify-handoff` → "Build BMT matrix":

```yaml
# FROM:
run: uv run python ./.github/scripts/ci_driver.py matrix --config-root deploy/code --project-filter "${BMT_PROJECTS:-}"

# TO:
run: uv run python ./.github/scripts/ci_driver.py matrix --config-root "$BMT_CONFIG_ROOT" --project-filter "${BMT_PROJECTS:-}"
```

Add `CONFIG_ROOT` env to the "Write run trigger to GCS" step in `handoff-run`:

```yaml
      - name: Write run trigger to GCS
        id: trigger
        env:
          FILTERED_MATRIX_JSON: ${{ needs.classify-handoff.outputs.filtered_matrix }}
          RUN_CONTEXT: ${{ needs.prepare.outputs.head_event == 'pull_request' && 'pr' || 'dev' }}
          HEAD_EVENT: ${{ needs.prepare.outputs.head_event }}
          PR_NUMBER: ${{ needs.prepare.outputs.pr_number }}
          CONFIG_ROOT: /tmp/bmt-config           # ← ADD THIS
        run: bash .github/scripts/workflows/bmt_workflow.sh write-run-trigger
```

> `trigger.sh` reads `config_root="${CONFIG_ROOT:-deploy/code}"` — setting this env var overrides the default.

---

## Step 4: Production Repo — Modify `build-and-test.yml`

**This is the only existing file that changes.** Two additions:

### 4a. Upload runner artifact (in `build` job)

Add this step **after** the "Build" step (line ~140) and **before** "Soft check" (line ~143). Must be before the "Cleanup heavy dirs" step which deletes `build/`:

```yaml
      # ---- upload runner binary for BMT (release presets only) ----------
      - name: Upload runner artifact for BMT
        if: endsWith(matrix.short, '_gcc_Release')
        uses: actions/upload-artifact@v4
        with:
          name: runner-${{ matrix.short }}
          path: build/${{ matrix.short }}/Runners/
          retention-days: 1
          if-no-files-found: warn
```

> **Path derivation:** For `SK_gcc_Release`, the configure preset `binaryDir` is `${sourceDir}/build/SK/gcc_Release`. The build preset name is `SK_gcc_Release-build`, and `matrix.short` = `SK_gcc_Release`. However, the runner is at `build/SK/gcc_Release/Runners/kardome_runner`. The `matrix.short` value is `SK_gcc_Release` — verify that `build/SK_gcc_Release/Runners/` vs `build/SK/gcc_Release/Runners/` is the correct path. Based on your example (`build/SK/gcc_Release/Runners/kardome_runner`), the path should be derived from `binaryDir` not `matrix.short`.

**⚠️ Verify the artifact path.** You said the runner is at `build/SK/gcc_Release/Runners/kardome_runner`. The `matrix.short` is `SK_gcc_Release`. Since the CMake `binaryDir` for `SK_gcc_Release` is `build/SK/gcc_Release`, not `build/SK_gcc_Release`, you may need a different expression. Options:

A) If the binary dir always follows `build/<PROJECT>/gcc_Release/`:
```yaml
          path: build/${{ matrix.configure }}/Runners/
```
(where `matrix.configure` = `SK_gcc_Release` and CMake uses that as `--preset` name, outputting to the `binaryDir`)

B) Better: extract `binary_dir` from `CMakePresets.json` in the matrix and use it:
```yaml
          path: ${{ matrix.binary_dir }}/Runners/
```
This requires adding `binary_dir` to the `extract-presets` output (see note below).

**Recommended:** Modify the `extract-presets` step to include `binaryDir`:
```yaml
      - name: Parse CMakePresets.json
        id: parse
        run: |
          presets=$(jq -c '
            [ .buildPresets[]
              | .config = (.configurePreset as $cp | input | .configurePresets[] | select(.name == $cp))
              | { build: .name
                , configure: .configurePreset
                , short: (.name | sub("-build$"; ""))
                , binary_dir: .config.binaryDir }
            ]' CMakePresets.json CMakePresets.json)
          echo "presets=$presets" >>"$GITHUB_OUTPUT"
```
Or simpler — just hardcode the known pattern since all gcc_Release presets follow `build/<PROJECT>/gcc_Release`:
```yaml
          path: build/${{ matrix.configure | replace('_gcc_Release', '') }}/gcc_Release/Runners/
```

> **⚠️ GitHub Actions expressions don't support `replace()`.** Use a shell step instead:
```yaml
      - name: Upload runner artifact for BMT
        if: endsWith(matrix.short, '_gcc_Release')
        uses: actions/upload-artifact@v4
        with:
          name: runner-${{ matrix.short }}
          path: build/${{ matrix.configure }}/Runners/
          retention-days: 1
          if-no-files-found: warn
```
> This works if `matrix.configure` is used as the CMake configure preset name AND the build output goes to `binaryDir` which is defined relative to sourceDir. Verify by checking the actual build output path for one release preset.

### 4b. Add `trigger-bmt` job

Add this job after the `build` job (at the end of the file):

```yaml
  # ─────────────────────── 3) trigger BMT handoff ──────────────────────
  trigger-bmt:
    name: Trigger BMT
    needs: [extract-presets, build]
    if: success()
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4
        with:
          repository: ${{ github.event_name == 'pull_request_target' && github.event.pull_request.head.repo.full_name || github.repository }}
          ref: ${{ github.event_name == 'pull_request_target' && github.event.pull_request.head.sha || github.sha }}
          fetch-depth: 1

      - name: Generate GitHub App token
        id: app-token
        uses: actions/create-github-app-token@v2
        with:
          app-id: ${{ secrets.BMT_DISPATCH_APP_ID }}
          private-key: ${{ secrets.BMT_DISPATCH_APP_PRIVATE_KEY }}

      - name: Install uv
        uses: astral-sh/setup-uv@v7
        with:
          python-version: "3.12"

      - name: Dispatch BMT workflow
        env:
          GITHUB_APP_TOKEN: ${{ steps.app-token.outputs.token }}
        run: |
          uv run python ./.github/scripts/ci_driver.py dispatch-workflow \
            --workflow bmt.yml \
            --ref "${{ github.ref }}" \
            --ci-run-id "${{ github.run_id }}" \
            --head-sha "${{ github.event_name == 'pull_request_target' && github.event.pull_request.head.sha || github.sha }}" \
            --head-branch "${{ github.event_name == 'pull_request_target' && github.event.pull_request.head.ref || github.ref_name }}" \
            --head-event "${{ github.event_name }}" \
            --pr-number "${{ github.event.pull_request.number || '' }}"
```

---

## Step 5: GitHub Settings (Production Repo)

### 5a. Repository Variables

```bash
cd /home/yanai/kardome/core-main

gh variable set GCS_BUCKET -b "train-kws-202311-bmt-gate"
gh variable set GCP_WIF_PROVIDER -b "projects/416686035248/locations/global/workloadIdentityPools/bmt-gate-gha-dev/providers/github-oidc"
gh variable set GCP_SA_EMAIL -b "bmt-runner-sa@train-kws-202311.iam.gserviceaccount.com"
gh variable set GCP_PROJECT -b "train-kws-202311"
gh variable set GCP_ZONE -b "europe-west4-a"
gh variable set BMT_VM_NAME -b "bmt-performance-gate"
gh variable set BMT_STATUS_CONTEXT -b "BMT Gate"
gh variable set BMT_PROJECTS -b "all"
```

### 5b. Repository Secrets

Use the same secret names as in the test repo; set values to the **prod** App credentials:

```bash
gh secret set BMT_DISPATCH_APP_ID < /path/to/prod-app-id.txt
gh secret set BMT_DISPATCH_APP_PRIVATE_KEY < /path/to/prod-app-private-key.pem
```

### 5c. Branch Protection

Settings → Branches → `dev`:
- [x] Require status checks to pass before merging
- [x] Status checks: **BMT Gate**

---

## Step 6: Verification

1. Push a test branch to `Kardome-org/core-main`, open PR to `dev`
2. `build-and-test.yml` runs:
   - `build` job uploads runner artifacts for `*_gcc_Release` presets
   - `trigger-bmt` job dispatches `bmt.yml`
3. `bmt.yml` runs:
   - Downloads config from GCS (no `deploy/` needed)
   - Downloads runner artifact from build run
   - Uploads runner to GCS, writes trigger, starts VM
4. VM picks up trigger, runs BMT, posts commit status + Check Run
5. Verify Check Run shows "Current Score | Last Passing Score" columns
6. First run bootstraps (no baseline → auto-pass)
7. Second PR validates gate comparison with tolerance

---

## Troubleshooting

| Issue | Check |
|-------|-------|
| WIF auth fails | Verify `core-main` is in WIF pool attribute condition |
| `dispatch-workflow` 403 | App needs `actions:write` permission on `core-main` |
| Runner artifact not found | Verify artifact name casing matches between upload and download |
| `repo_paths` import error | Verify prod uses standalone `repo_paths.py`, not the `tools` import |
| Config download fails | Verify `GCS_BUCKET` var is set and WIF auth succeeded |
| `build/` deleted before upload | Ensure upload step is before "Cleanup heavy dirs" step |

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Config from GCS, not local `deploy/` | Prod repo needs no config files; dev repo owns them |
| Separate prod GitHub App | Different trust boundary than test App |
| Upload artifact before cleanup | `build-and-test.yml` `rm -rf ./**/build` deletes runner |
| `dispatch-workflow` command | Keeps trigger job to ~20 lines, reusable |
| Standalone `repo_paths.py` in prod | Avoids dependency on `tools/` package |
| Only 1 existing file modified | `build-and-test.yml` gets 1 step + 1 job; everything else is new files |

---

## Execution Checklist

| # | Action | Repo | Status |
|---|--------|------|--------|
| P1 | Add `core-main` to WIF pool | GCP Console | ☐ |
| P2 | Create/configure prod GitHub App | GitHub | ☐ |
| 1 | Create `dispatch_workflow.py` + register | Dev | ✅ Done |
| 2 | Copy `.github/scripts/` (Python + shell) | Prod | ☐ |
| 2b | Create standalone `repo_paths.py` | Prod | ☐ |
| 2c | Create/update `pyproject.toml` | Prod | ☐ |
| 3 | Copy `bmt.yml` + add GCS config download | Prod | ☐ |
| 4a | Add upload-artifact step to `build-and-test.yml` | Prod | ☐ |
| 4b | Add trigger-bmt job to `build-and-test.yml` | Prod | ☐ |
| 5a | Set repository variables (8) | Prod | ☐ |
| 5b | Set repository secrets (2) | Prod | ☐ |
| 5c | Configure branch protection | Prod | ☐ |
| 6 | Test with PR to `dev` | Prod | ☐ |
