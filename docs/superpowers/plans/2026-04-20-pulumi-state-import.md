# Pulumi State Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. This is an infrastructure adoption exercise — **every live resource touched costs downtime risk** — do not batch-commit speculative changes; commit after each task.

**Goal:** Adopt ~24 existing GCP resources into the Pulumi GCS state backend so `pulumi up` becomes a safe, drift-preview-only operation in CI, unblocking the `pulumi` job of [`release.yml`](./2026-04-18-ci-driven-release.md) (Phase B/C of the CI-driven release plan).

**Architecture:** Live resources (SAs, Cloud Run Jobs, Secrets, Workflow, AR repo, IAM bindings) were created outside Pulumi and `gs://train-kws-202311-bmt-gate/pulumi/bmt-vm/` state is empty. We run `pulumi import` from an admin workstation for each declared resource (Pulumi URN ↔ live GCP resource ID pair), reconcile program-vs-reality drift by updating `infra/pulumi/__main__.py` (not the live resources), and end with `pulumi preview` reporting `0 create / 0 update / 0 delete`. Once clean, CI can run `pulumi up` as a no-op gate, and minimum-required project IAM roles on `bmt-runner-sa` (or a dedicated deployer SA) can be narrowed based on the observed diff.

**Tech Stack:** Pulumi 3.224+ (Python runtime), `pulumi-gcp` provider, `gcloud` admin credentials, GCS-backed Pulumi state, KMS-backed secrets provider (`gcpkms://…/pulumi/bmt-vm`).

**Context:** Discovery session on 2026-04-20 found `.latest.resources = []` in both primary and backup state files. All ~24 declared resources exist on GCP via prior gcloud/console/manual Pulumi-with-lost-filestate. One declared resource (`bmt-dataset-transfer` Cloud Run Job + its `developer-invokes-transfer-job` IamMember) was **never deployed** — partial gdrive integration work from April 14. See `CHANGELOG.md` and the Phase A/B work in `2026-04-18-ci-driven-release.md` for surrounding context.

---

## File Map

| File | Action |
|---|---|
| `infra/pulumi/__main__.py` | **Modify** — remove declarations for `bmt-dataset-transfer` + `developer-invokes-transfer-job` + transfer-image URI; reconcile drift for every other resource so `preview` is clean. Explicit comment block noting these are removed pending completion of the gdrive transfer feature. |
| `tools/repo/vars_contract.py` | **Modify** — remove `PULUMI_KEY_CLOUD_RUN_JOB_DATASET_TRANSFER` from `PULUMI_KEY_TO_ENV`, remove `ENV_BMT_DATASET_TRANSFER_JOB` from the required tuple (it's aspirational — keep the constant defined for when the feature ships). |
| `runtime/config/constants.py` | **Modify** — keep `ENV_BMT_DATASET_TRANSFER_JOB` + `PULUMI_KEY_CLOUD_RUN_JOB_DATASET_TRANSFER` constants defined (dormant) so future revival is a one-line diff. Add a `# DORMANT — pending gdrive transfer feature completion` comment. |
| `tools/pulumi/import_state.sh` | **Create** — idempotent bash script containing all 24 `pulumi import --yes` commands with documented URNs and GCP resource IDs. One-shot to reconstitute state on a fresh backend; also serves as documentation. |
| `tests/pulumi/test_pulumi_preview_clean.py` | **Create** — integration test that runs `pulumi preview --json` in `infra/pulumi/` and asserts `steps` contains only `same` operations (0 create / 0 update / 0 delete / 0 replace). Marked `@pytest.mark.requires_pulumi_state` so it's opt-in, not part of `just test`. |
| `CHANGELOG.md` | **Modify** — `Unreleased` entry noting the Pulumi state reconciliation and the declaration removals. |
| `docs/architecture.md` | **Modify (small)** — add one paragraph under infra section: *"Pulumi state lives at `gs://$BUCKET/pulumi/bmt-vm/`. It was reconstituted from existing resources on 2026-04-20 via `tools/pulumi/import_state.sh`. Direct resource mutations outside Pulumi should be imported or removed afterward to keep preview clean."* |
| `.github/workflows/release.yml` | **Modify** — re-enable `pulumi` job with expected no-op semantics (flip from descoped state in Phase B.2 follow-up). Only after Gate 3 of this plan passes. |

---

## Phases and gates

This plan has three phases. **Each phase's gate must pass before the next starts.**

---

## Phase 1 — Prepare program for import (no live-resource changes)

**Goal:** Remove declarations that don't correspond to existing live resources (`bmt-dataset-transfer` + its IAM member), so the import set matches reality 1:1. No GCP mutations yet.

### Task 1.1: Remove bmt-dataset-transfer declarations from Pulumi program

**Files:**
- Modify: `infra/pulumi/__main__.py:117-210` (remove `cloud_run_image_transfer_uri`, `cloud_run_job_dataset_transfer`, `developer-invokes-transfer-job`, and its export)

- [ ] **Step 1.1.1: Confirm no live resource exists**

```bash
gcloud run jobs describe bmt-dataset-transfer --region europe-west4 --project train-kws-202311 2>&1 | head -3
```

Expected: `ERROR: ... Cannot find job [bmt-dataset-transfer].`

- [ ] **Step 1.1.2: Remove the three declarations and the export**

Delete (exact ranges, verify line numbers before editing — code may have shifted):
- `cloud_run_image_transfer_uri` assignment (lines ~117-120)
- `cloud_run_job_dataset_transfer = gcp.cloudrunv2.Job(...)` block (lines ~143-172)
- `gcp.cloudrunv2.JobIamMember("developer-invokes-transfer-job", ...)` block (lines ~201-208)
- `pulumi.export("cloud_run_job_dataset_transfer", ...)` line (line ~210)

Add a short comment block in place of the removed `_job_dataset_transfer` assignment:

```python
# NOTE: bmt-dataset-transfer Cloud Run Job and its IAM member were declared
# as part of the gdrive connection work (commit bfabb42, 2026-04-14) but the
# corresponding image (bmt-transfer) was never built and pushed, and the job
# was never deployed. Re-introduce these declarations when the gdrive transfer
# feature is completed end-to-end. See tools/remote/bucket_upload_dataset.py
# for the partial consumer-side code.
```

- [ ] **Step 1.1.3: Remove DATASET_TRANSFER from the required repo vars tuple**

In `tools/repo/vars_contract.py`:
- Remove `PULUMI_KEY_CLOUD_RUN_JOB_DATASET_TRANSFER: ENV_BMT_DATASET_TRANSFER_JOB,` from `PULUMI_KEY_TO_ENV` (around line 65)
- Remove `ENV_BMT_DATASET_TRANSFER_JOB,` from the required vars tuple at around line 79
- Keep the `from runtime.config.constants import … ENV_BMT_DATASET_TRANSFER_JOB …` import (no harm; the constant stays defined for the future).

In `runtime/config/constants.py`, add a trailing comment on the `ENV_BMT_DATASET_TRANSFER_JOB` and `PULUMI_KEY_CLOUD_RUN_JOB_DATASET_TRANSFER` lines:

```python
ENV_BMT_DATASET_TRANSFER_JOB = "BMT_DATASET_TRANSFER_JOB"  # DORMANT: pending gdrive transfer feature completion.
...
PULUMI_KEY_CLOUD_RUN_JOB_DATASET_TRANSFER = "cloud_run_job_dataset_transfer"  # DORMANT: pending gdrive transfer feature completion.
```

- [ ] **Step 1.1.4: Verify lint + types + tests still pass**

Run: `just test`

Expected: `361 tests pass` (baseline). All of: pytest, ruff, `ty check`, actionlint, shellcheck, layout policies. If `vars_contract.py`'s change breaks a test that asserts DATASET_TRANSFER is required, update the test to match the new contract.

- [ ] **Step 1.1.5: Commit**

```bash
git add infra/pulumi/__main__.py tools/repo/vars_contract.py runtime/config/constants.py
git commit -m "$(cat <<'EOF'
chore(infra): remove dormant bmt-dataset-transfer declarations

The bmt-dataset-transfer Cloud Run Job (+ its IAM member and export) was
declared in Pulumi on 2026-04-14 (bfabb42) but never deployed: the
bmt-transfer image was never built/pushed, and no CI or workflow consumes
the resulting BMT_DATASET_TRANSFER_JOB repo var. Removing the declarations
aligns the program with reality so Pulumi state import produces a clean
no-op preview. Constants stay defined (marked DORMANT) so reviving the
feature is a one-line diff.
EOF
)"
```

### Gate 1 — Clean program, reality-aligned

- [ ] `just test` green
- [ ] `grep -n bmt-dataset-transfer infra/pulumi/__main__.py` returns only the comment block
- [ ] No dangling references to `cloud_run_image_transfer_uri`: `rg cloud_run_image_transfer_uri --type py` returns 0 results
- [ ] `PULUMI_KEY_TO_ENV` no longer maps `DATASET_TRANSFER`: `rg DATASET_TRANSFER tools/repo/vars_contract.py` returns 0 matches

---

## Phase 2 — Import live resources into state

**Goal:** Run `pulumi import` for 24 resources, reconciling any program-vs-reality drift by editing the program (not the live resources). End state: `pulumi preview` shows 0 operations.

**Execution prerequisite:** Run from a workstation with **owner-level GCP credentials** (`gcloud auth list` shows a user with `roles/owner` or equivalent). Not CI. GCS backend KMS secrets provider (`gcpkms://…/pulumi/bmt-vm`) must be usable — requires the caller to have `cloudkms.cryptoKeyEncrypterDecrypter` on that key (owner covers it).

### Task 2.1: Create the import script

**Files:**
- Create: `tools/pulumi/import_state.sh`

- [ ] **Step 2.1.1: Write the script skeleton**

```bash
#!/usr/bin/env bash
# tools/pulumi/import_state.sh — Bulk import existing GCP resources into Pulumi state.
#
# Context: State at gs://train-kws-202311-bmt-gate/pulumi/bmt-vm/ was empty as
# of 2026-04-20 despite all declared resources existing on GCP. This script
# reconstitutes state by running `pulumi import --yes` once per resource.
#
# Preconditions:
#   - Caller has owner / admin on GCP project train-kws-202311
#   - `pulumi` CLI on PATH; version >= 3.224
#   - cwd is repo root
#   - `uv sync` has run (pulumi-gcp provider resolvable)
#
# Safety:
#   - `pulumi import` does NOT mutate the live resource. It only writes the
#     resource into state. Drift, if any, surfaces on the next `preview`.
#   - If an import fails, the script exits. Re-run after investigating; imports
#     that already succeeded will be skipped by Pulumi with "resource already
#     imported" (idempotent).
#
# Post-import:
#   - Run: (cd infra/pulumi && pulumi preview --diff)
#   - Reconcile any attribute drift by editing __main__.py to match reality.
#   - Re-run preview until it reports "no changes".

set -euo pipefail

cd "$(dirname "$0")/../.."
PULUMI_DIR=infra/pulumi
PROJECT=train-kws-202311
REGION=europe-west4
BUCKET=train-kws-202311-bmt-gate

export PULUMI_CONFIG_PASSPHRASE="${PULUMI_CONFIG_PASSPHRASE:-}"

cd "${PULUMI_DIR}"
pulumi login "gs://${BUCKET}/pulumi/bmt-vm"
pulumi stack select prod

import() {
  # usage: import <type> <pulumi-name> <gcp-id>
  local type="$1" name="$2" id="$3"
  echo "::group::pulumi import ${type}::${name}"
  pulumi import --yes --skip-preview "${type}" "${name}" "${id}" || {
    echo "::error::Failed import: ${type} ${name} ${id}"
    return 1
  }
  echo "::endgroup::"
}
```

- [ ] **Step 2.1.2: Append the 24 `import` calls grouped by type**

Append to the script (each block commented with the URN-to-ID mapping). **Exact IDs follow provider docs (`pulumi-gcp` README per-resource `Import` sections). Do not guess — run the script, and if any single resource fails, look up the correct format and re-run that single line.**

```bash
# ============================================================================
# Artifact Registry
# ============================================================================
# URN: urn:pulumi:prod::bmt-vm::gcp:artifactregistry/repository:Repository::bmt-images
# Import format: projects/{project}/locations/{location}/repositories/{name}
import gcp:artifactregistry/repository:Repository bmt-images \
  "projects/${PROJECT}/locations/${REGION}/repositories/bmt-images"

# ============================================================================
# Service Accounts
# ============================================================================
# Import format: projects/{project}/serviceAccounts/{email}
import gcp:serviceaccount/account:Account bmt-job-runner-sa \
  "projects/${PROJECT}/serviceAccounts/bmt-job-runner@${PROJECT}.iam.gserviceaccount.com"

import gcp:serviceaccount/account:Account bmt-workflow-sa \
  "projects/${PROJECT}/serviceAccounts/bmt-workflow-sa@${PROJECT}.iam.gserviceaccount.com"

# ============================================================================
# Cloud Run Jobs
# ============================================================================
# Import format: projects/{project}/locations/{location}/jobs/{name}
import gcp:cloudrunv2/job:Job bmt-control \
  "projects/${PROJECT}/locations/${REGION}/jobs/bmt-control"

import gcp:cloudrunv2/job:Job bmt-task-standard \
  "projects/${PROJECT}/locations/${REGION}/jobs/bmt-task-standard"

import gcp:cloudrunv2/job:Job bmt-task-heavy \
  "projects/${PROJECT}/locations/${REGION}/jobs/bmt-task-heavy"

# ============================================================================
# Secret Manager Secrets (Drive OAuth)
# ============================================================================
# Import format: projects/{project}/secrets/{name}
import gcp:secretmanager/secret:Secret bmt-drive-bmt-drive-client-id-secret \
  "projects/${PROJECT}/secrets/BMT_DRIVE_CLIENT_ID"

import gcp:secretmanager/secret:Secret bmt-drive-bmt-drive-client-secret-secret \
  "projects/${PROJECT}/secrets/BMT_DRIVE_CLIENT_SECRET"

import gcp:secretmanager/secret:Secret bmt-drive-bmt-drive-refresh-token-secret \
  "projects/${PROJECT}/secrets/BMT_DRIVE_REFRESH_TOKEN"

# ============================================================================
# SecretIamMember bindings (Drive)
# ============================================================================
# Import format: projects/{project}/secrets/{secret_id} {role} {member}
JOB_RUNNER_MEMBER="serviceAccount:bmt-job-runner@${PROJECT}.iam.gserviceaccount.com"

import gcp:secretmanager/secretIamMember:SecretIamMember \
  job-runner-drive-bmt-drive-client-id-secret \
  "projects/${PROJECT}/secrets/BMT_DRIVE_CLIENT_ID roles/secretmanager.secretAccessor ${JOB_RUNNER_MEMBER}"

import gcp:secretmanager/secretIamMember:SecretIamMember \
  job-runner-drive-bmt-drive-client-secret-secret \
  "projects/${PROJECT}/secrets/BMT_DRIVE_CLIENT_SECRET roles/secretmanager.secretAccessor ${JOB_RUNNER_MEMBER}"

import gcp:secretmanager/secretIamMember:SecretIamMember \
  job-runner-drive-bmt-drive-refresh-token-secret \
  "projects/${PROJECT}/secrets/BMT_DRIVE_REFRESH_TOKEN roles/secretmanager.secretAccessor ${JOB_RUNNER_MEMBER}"

# ============================================================================
# Workflow
# ============================================================================
# Import format: projects/{project}/locations/{region}/workflows/{name}
import gcp:workflows/workflow:Workflow bmt-workflow \
  "projects/${PROJECT}/locations/${REGION}/workflows/bmt-workflow"

# ============================================================================
# Bucket + AR repo IAM
# ============================================================================
# BucketIAMMember import: {bucket} {role} {member}
import gcp:storage/bucketIAMMember:BucketIAMMember job-runner-bucket-writer \
  "b/${BUCKET} roles/storage.objectAdmin ${JOB_RUNNER_MEMBER}"

# RepositoryIamMember import: {location}/{repo} {role} {member}
import gcp:artifactregistry/repositoryIamMember:RepositoryIamMember \
  job-runner-artifact-registry-writer \
  "projects/${PROJECT}/locations/${REGION}/repositories/bmt-images roles/artifactregistry.writer ${JOB_RUNNER_MEMBER}"

# ============================================================================
# GITHUB_APP_* secret accessor bindings (6 total)
# ============================================================================
for secret in GITHUB_APP_ID GITHUB_APP_INSTALLATION_ID GITHUB_APP_PRIVATE_KEY \
              GITHUB_APP_DEV_ID GITHUB_APP_DEV_INSTALLATION_ID GITHUB_APP_DEV_PRIVATE_KEY; do
  lower="$(echo "${secret}" | tr '[:upper:]_' '[:lower:]-')"
  import gcp:secretmanager/secretIamMember:SecretIamMember \
    "job-runner-secret-${lower}" \
    "projects/${PROJECT}/secrets/${secret} roles/secretmanager.secretAccessor ${JOB_RUNNER_MEMBER}"
done

# ============================================================================
# JobIamMember bindings (workflow-invokes-*) — 3 total
# ============================================================================
WORKFLOW_MEMBER="serviceAccount:bmt-workflow-sa@${PROJECT}.iam.gserviceaccount.com"

# Import format for JobIamMember: {location}/{job} {role} {member}
# Note: the project is implicit in the location prefix for cloudrunv2.
for job_name in bmt-control bmt-task-standard bmt-task-heavy; do
  case "${job_name}" in
    bmt-control)         resource_name=workflow-invokes-control-job ;;
    bmt-task-standard)   resource_name=workflow-invokes-standard-job ;;
    bmt-task-heavy)      resource_name=workflow-invokes-heavy-job ;;
  esac
  import gcp:cloudrunv2/jobIamMember:JobIamMember "${resource_name}" \
    "projects/${PROJECT}/locations/${REGION}/jobs/${job_name} roles/run.jobsExecutorWithOverrides ${WORKFLOW_MEMBER}"
done

# ============================================================================
# Workflow-SA bucket + project log writer
# ============================================================================
import gcp:storage/bucketIAMMember:BucketIAMMember workflow-sa-bucket-reader \
  "b/${BUCKET} roles/storage.objectViewer ${WORKFLOW_MEMBER}"

# IAMMember at project scope import: {project} {role} {member}
import gcp:projects/iAMMember:IAMMember workflow-sa-log-writer \
  "${PROJECT} roles/logging.logWriter ${WORKFLOW_MEMBER}"

echo "All imports complete. Next:"
echo "  1. (cd ${PULUMI_DIR} && pulumi preview --diff)"
echo "  2. Update __main__.py for each attribute drift until preview is clean."
```

- [ ] **Step 2.1.3: Shellcheck the script**

Run: `shellcheck tools/pulumi/import_state.sh`

Expected: No errors. Fix any SC2086 (unquoted variables) or SC2154 (unassigned) warnings that appear.

- [ ] **Step 2.1.4: chmod and commit**

```bash
chmod +x tools/pulumi/import_state.sh
git add tools/pulumi/import_state.sh
git commit -m "$(cat <<'EOF'
chore(infra): add tools/pulumi/import_state.sh

Reconstitute Pulumi state for bmt-vm/prod by importing every resource
declared in infra/pulumi/__main__.py. State at gs://.../pulumi/bmt-vm/
was discovered empty on 2026-04-20; live resources exist and must be
adopted so `pulumi up` becomes a safe no-op gate in CI.

Script is idempotent: re-running after a partial success resumes from
the first missing import (Pulumi treats already-imported resources as
no-ops). Run from a workstation with project-owner credentials.
EOF
)"
```

### Task 2.2: Run the import script

- [ ] **Step 2.2.1: Prepare environment**

```bash
cd /home/yanai/dev/projects/bmt-gcloud
uv sync  # ensure pulumi-gcp provider is resolvable
gcloud auth application-default login  # if ADC not already set
gcloud config set project train-kws-202311
```

Verify:
- `gcloud auth list` shows an owner account as ACTIVE
- `gcloud auth application-default print-access-token | head -c 20` prints a token (ADC works)
- `pulumi version` reports `3.224.0` or newer

- [ ] **Step 2.2.2: Decrypt state-provider passphrase (if passphrase-backed)**

State is KMS-backed (`secretsprovider: gcpkms://…/pulumi/bmt-vm` per `Pulumi.prod.yaml`), so no `PULUMI_CONFIG_PASSPHRASE` is required when KMS decrypt permission is present. If KMS access fails, you'll see `error: failed to decrypt secret` — in that case:

```bash
gcloud kms keys add-iam-policy-binding bmt-vm \
  --location=europe-west4 --keyring=pulumi \
  --member="user:$(gcloud config get-value account)" \
  --role=roles/cloudkms.cryptoKeyEncrypterDecrypter --project=train-kws-202311
```

- [ ] **Step 2.2.3: Execute script, capture log**

```bash
tools/pulumi/import_state.sh 2>&1 | tee /tmp/pulumi_import.log
```

Expected: 24 `Import succeeded` messages. If any fails, fix the individual import (wrong ID format is the most common culprit — consult `pulumi-gcp` provider source at <https://github.com/pulumi/pulumi-gcp> for the exact import syntax for that resource type), then re-run the script.

**Do not edit state directly. Do not run `pulumi up` between imports.**

- [ ] **Step 2.2.4: Verify state now has 24 resources**

```bash
(cd infra/pulumi && pulumi stack --show-urns | head -40)
```

Expected: The stack output lists every URN from the script plus the `pulumi:pulumi:Stack` + provider entries (26-27 URNs total).

### Task 2.3: Reconcile drift

- [ ] **Step 2.3.1: Generate a diff preview**

```bash
(cd infra/pulumi && pulumi preview --diff --show-replacement-steps 2>&1) | tee /tmp/pulumi_preview.log
```

Expected: **Not yet clean.** Typical drift sources to expect in the preview output:
- Cloud Run Job `envs` order, `annotations` added by gcloud
- Workflow `source_contents` whitespace or `crypto_key_name`
- SA descriptions (empty vs explicit)
- IAM bindings with extra members populated by other teams
- Bucket/project IAM with members we don't manage

- [ ] **Step 2.3.2: Reconcile each drift by editing `__main__.py`**

For every `~ update` operation in the preview:
1. Read the diff line ("from: X / to: Y").
2. Decide: is our declaration wrong (update the code) or is the live state wrong (update the live resource)?
   - **Default rule: update the code to match the live state.** Changing live resources during this adoption could cause downtime or break existing consumers.
   - **Exception: if drift is a secret or key that must not be weakened** (e.g., `roles/owner` where we declare `roles/viewer`), investigate first and consult user before modifying.
3. Edit `infra/pulumi/__main__.py`.
4. Re-run `pulumi preview --diff` to confirm that specific drift is gone.

Repeat until preview reports `no changes required`.

For `+ create` operations: should be ZERO after Phase 1.1 removed the dormant resources. If any appear, stop and investigate — means we didn't import something correctly.

For `- delete` or `~ replace` operations: stop immediately. Never let `pulumi up` delete or replace a live resource without explicit user sign-off. Adjust the code to match reality.

- [ ] **Step 2.3.3: Commit the drift reconciliation**

After each discrete drift fix, commit:

```bash
git add infra/pulumi/__main__.py
git commit -m "chore(infra): reconcile pulumi program to match live <resource>"
```

Small commits make it easy to audit what was changed and why.

### Gate 2 — Preview is clean

- [ ] `(cd infra/pulumi && pulumi preview) | tail` reports `Resources: N unchanged` and `Duration: …`
- [ ] No `+ create`, `~ update`, `~ replace`, or `- delete` in any preview step
- [ ] `pulumi stack export | jq '.latest.resources | length'` >= 24
- [ ] Commits from Task 2.3 each describe one concrete reconciliation

---

## Phase 3 — Re-enable CI Pulumi job with narrowest necessary IAM

**Goal:** Turn the `pulumi` job of `release.yml` back on. Grant `bmt-runner-sa` the minimum roles Pulumi actually needs to produce a no-op `up` (drift-free). Keep the blast radius small.

### Task 3.1: Determine minimum required IAM

- [ ] **Step 3.1.1: Run `pulumi up --dry-run` as `bmt-runner-sa` locally**

Use impersonation to confirm the exact permissions needed:

```bash
gcloud auth application-default login --impersonate-service-account=bmt-runner-sa@train-kws-202311.iam.gserviceaccount.com
(cd infra/pulumi && pulumi up --yes --show-reads 2>&1 | tee /tmp/pulumi_up_as_sa.log)
```

Expected: Since preview is clean (Gate 2 passed), `up` should also be a no-op. If the SA lacks `get` or `list` permissions on any resource, we'll see `permission denied` errors. Record every missing permission.

Typical minimal read set for a no-op `up`:
- `resourcemanager.projects.get`
- `run.jobs.get`, `run.jobs.getIamPolicy`
- `artifactregistry.repositories.get`
- `iam.serviceAccounts.get`
- `secretmanager.secrets.get`, `secretmanager.secrets.getIamPolicy`
- `workflows.workflows.get`, `workflows.workflows.getIamPolicy`
- `storage.buckets.get`, `storage.buckets.getIamPolicy`

These are covered by a single role bundle: `roles/viewer` (project-wide read).

- [ ] **Step 3.1.2: Grant `roles/viewer` to `bmt-runner-sa`**

```bash
gcloud projects add-iam-policy-binding train-kws-202311 \
  --member="serviceAccount:bmt-runner-sa@train-kws-202311.iam.gserviceaccount.com" \
  --role="roles/viewer"
```

- [ ] **Step 3.1.3: Re-run as `bmt-runner-sa`**

Re-run `Step 3.1.1`. Expected: no permission errors, output ends with `Resources: N unchanged`.

### Task 3.2: Re-enable pulumi job in release.yml

**Files:**
- Modify: `.github/workflows/release.yml` (uncomment the `pulumi` job if it was descoped, or add it back if it was removed)

- [ ] **Step 3.2.1: Restore pulumi job block**

Ensure `release.yml` contains the `pulumi` job from Phase B.2 (see [`2026-04-18-ci-driven-release.md`](./2026-04-18-ci-driven-release.md) §Phase B.2 for the exact block). The job should:
- Conditional on `needs.detect-changes.outputs.infra == 'true'`
- Run `uv run python -m tools pulumi apply` (which calls `pulumi up --yes`)
- Emit `pulumi_stack_sha` output consumed by the `mark` job

- [ ] **Step 3.2.2: Commit and push**

```bash
git add .github/workflows/release.yml
git commit -m "$(cat <<'EOF'
feat(release): re-enable pulumi job in release.yml

State was reconciled via tools/pulumi/import_state.sh on 2026-04-20; `pulumi
up` is now a no-op on clean branches. bmt-runner-sa received roles/viewer
to satisfy the read permissions Pulumi needs to confirm state. Write
permissions for live-mutation operations are NOT granted here — actual
infra changes must come via a dedicated admin path (separate future work).

Resolves Phase B Pulumi descope from 2026-04-18-ci-driven-release.md.
EOF
)"
git push
```

### Gate 3 — CI pulumi job is green on a no-op branch

- [ ] Push the above commit. `release.yml` runs. `pulumi` job shows `Resources: N unchanged` in logs.
- [ ] The `mark` job's release marker now includes a non-null `pulumi_stack_sha`.
- [ ] No changes to live GCP resources occurred.

---

## Phase 4 — (Deferred) Write-path for future infra changes

**Out of scope.** When someone wants to modify `__main__.py` and have CI apply it, they will need a dedicated path. The current design grants CI only read access. Options for the future (each is its own plan):

| Option | Description | Downsides |
|---|---|---|
| Dedicated `bmt-deployer-sa` with admin bundle | Separate SA bound to same WIF provider, used only by `pulumi` job. Keeps `bmt-runner-sa` runtime-scoped. | Needs broad admin roles: `iam.serviceAccountAdmin`, `run.admin`, `workflows.admin`, `secretmanager.admin`, `artifactregistry.admin`, `resourcemanager.projectIamAdmin`, etc. |
| Manual apply path | CI stays read-only (preview). A human runs `just pulumi` from a workstation for actual mutations. | Breaks CI-only production model; creates drift opportunity between preview and apply. |
| Hybrid (preview in CI, apply via manual workflow_dispatch with elevated SA) | Most PRs get preview-only CI; actual applies are a deliberate manual workflow using the admin SA. | Extra UX complexity; surface for approval flow. |

Recommend: wait until there's an actual write demand, then pick an option tied to that first use case.

---

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| `pulumi import` succeeds but subsequent `up` tries to replace a resource because of computed-field drift | Phase 2.3 rule: update **code to match reality**, never the reverse. Cross-check every `replace` step before letting it apply. |
| Import script hits an unexpected ID format on one resource; imports partially succeed | Script is idempotent — re-run from top; already-imported resources are no-ops. Fix the failing line and continue. |
| KMS decrypt permission missing on admin account | Phase 2.2.2 documents the explicit grant; fall back to GCP IAM grant via owner. |
| bmt-runner-sa's `roles/viewer` grant is too broad | `roles/viewer` is project-wide read. For a bmt-gate project that's acceptable (nothing sensitive at the project level — secrets are IAM-gated separately). If concerned, replace with a custom role containing only the ~9 permissions listed in Phase 3.1.1. |
| Between running imports and CI re-enabling, someone mutates a resource out-of-band | Low probability (small team). Detect via `pulumi preview` at the start of every dev session; fix by re-reconciling the program. |
| We discover that the program's logic relies on resources we declared but didn't import (ghost declarations we missed) | Phase 1 removed the known ghost (`bmt-dataset-transfer`). Phase 2.3 preview will surface any remaining ghosts as `+ create`. If one appears: (a) delete the declaration if it's also dormant, or (b) import it manually if it exists but wasn't in our import list. |

---

## Open questions (resolve during implementation)

1. **IAM binding import IDs**: Pulumi-gcp docs for `storage.BucketIAMMember`, `projects.IAMMember`, `cloudrunv2.JobIamMember` specify the space-separated `{target} {role} {member}` format. If a concrete import fails with "invalid import ID", consult the provider source at `pulumi-gcp/sdk/python/pulumi_gcp/<pkg>/<resource>.py` for the `Import` docstring. The script has placeholder comments noting this.

2. **Computed fields** (`etag`, `uid`, `create_time`, `update_time`, `generation`): these will always diff on first preview. Pulumi handles these by default via `ignore_changes` on the provider level. If they surface as drift, add `opts=pulumi.ResourceOptions(ignore_changes=["etag", "uid", ...])` per-resource. Keep these additions minimal.

3. **Removed `bmt-dataset-transfer`**: if someone reviving the gdrive feature re-adds the declarations, they must **also run `pulumi import` for the real job** they create via `pulumi up` — otherwise they're creating state desync for that resource. Document this in the comment block added in Phase 1.1.2.

---

## Self-review

- **Spec coverage:** Every discovery from the investigation session is addressed: Phase 1 removes the ghost resource; Phase 2 imports the real 24; Phase 3 grants minimum IAM; Phase 4 defers the write-path.
- **Placeholders:** No TBDs, TODOs, "implement later" markers, or vague "handle edge cases". Each step has concrete commands or code.
- **Type consistency:** `bmt-runner-sa`, `bmt-job-runner`, and `bmt-workflow-sa` are used consistently throughout (note the distinction: `bmt-runner-sa` is the CI/WIF identity, `bmt-job-runner` is the Cloud Run Job executor SA, `bmt-workflow-sa` is the Workflow orchestrator SA — all three are real and all three are referenced correctly).
- **No speculative writes:** The plan is explicit that Phase 3 grants read-only `roles/viewer`. Write roles are deferred to Phase 4 which has no tasks — only option analysis.
