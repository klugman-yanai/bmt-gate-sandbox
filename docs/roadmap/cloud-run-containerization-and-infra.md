# Cloud Run Containerization and Infrastructure

**Status:** Proposed
**Urgency:** MEDIUM
**Goal:** Create a "Zero-Download" execution environment using Cloud Run Gen 2 with mandatory GCS Fuse mounts, replacing the GCE VM-based executor. Solve the 40GB+ "startup wall" and support 20+ parallel projects.

> **Supersedes:** `2026-03-15-migration-to-cloud-run-jobs.md`. This document is strictly more detailed, covering coordinator ownership, partial failure semantics, log collection for Check Run, and security hardening.

---

## Reading Guide

This document is part of a 5-document roadmap series, split from the former holistic serverless migration plan.

| # | Document | Focus | Urgency |
|---|----------|-------|---------|
| 1 | [gcp-data-separation-and-dev-workflow.md](gcp-data-separation-and-dev-workflow.md) | Bug fixes, manifest, FUSE, WorkspaceLayout | MOST URGENT |
| 2 | [gcp-image-refactor.md](gcp-image-refactor.md) | Constants, types, entrypoint, decoupling | HIGH |
| 3 | [contributor-api-and-manager-contract.md](contributor-api-and-manager-contract.md) | Protocol, BaseBmtManager, contributor workflow | HIGH |
| **4** | **cloud-run-containerization-and-infra.md** (this) | Dockerfile, Cloud Run, Pulumi, coordinator | **MEDIUM** |
| 5 | [ci-cutover-and-vm-decommission.md](ci-cutover-and-vm-decommission.md) | Direct API, shadow testing, cutover | LOWER |

**Dependency chain:** 1 → 2+3 → 4 → 5

**Depends on:** Documents 2 (gcp/image refactor) and 3 (contributor API) — the container image uses the same entrypoint and config model established there.

---

## Phase 4: High-Performance Containerization

**Goal:** Create a "Zero-Download" execution environment.

- [ ] **4.1 Create `gcp/image/Dockerfile`**
  - **Base:** `python:3.12-slim-bookworm`.
  - **Deps:** `libsndfile1`, `ffmpeg`, `curl`, `gnupg`, `uv`.
  - **Image layout:** One entrypoint at image root: `main.py` (e.g. `/app/main.py`). Copy the rest of the code into submodules under `/app` (e.g. `/app/config/`, `/app/contracts/`, `/app/projects/`, or `/app/gcp/image/` as a package). Set `PYTHONPATH` so `main.py` can import the package. `CMD`/`ENTRYPOINT` invoke only `python main.py` (config via env and optional payload).
  - **Code:** Copy `gcp/image` (required) and optionally `tools` (e.g. for local dev); image root has exactly `main.py` and one top-level package; no other scripts at root. For minimal job image, `gcp/image` alone may suffice.

- [ ] **4.2 Project code: image vs GCS (decoupled)**
  - **Task:** Do **not** bake the project registry (`bmt_projects.json`) into the image. The registry lives in GCS and is loaded at runtime so new BMTs can be added without image rebuild.
  - **Task:** Bake project manager code in the image (per `gcp/README.md`: gcp/image is not uploaded to the bucket; publish = image build). The orchestrator resolves which projects exist from the GCS registry. New projects are added by adding code to the repo and rebuilding the image, and updating the registry in GCS.
  - **Impact:** Same image can run any BMT listed in the GCS registry; adding a BMT = image rebuild (to include new project code) + update registry in GCS.

- [ ] **4.3 Local validation**
  - **Task:** Build `bmt-orchestrator:latest`.
  - **Task:** Run config-driven invocation to verify local FUSE simulation, e.g. `docker run -v $(pwd)/gcp/remote:/mnt/runtime -e GCS_BUCKET=... -e BMT_MODE=orchestrator -e BMT_PAYLOAD_PATH=/config/payload.json bmt-orchestrator` (or `python main.py` with the same env). No `--leg-json` or subcommands; entrypoint reads config from env and optional payload path.

### Research Insights (Phase 4)

**Best Practices:**
- Keep runtime image lean and deterministic; pin toolchain versions and avoid dynamic installs at runtime.
- Treat project managers as baked plugins (`gcp/image/projects/**`) to remove startup download dependencies.

**Performance Considerations:**
- Cold start and mount readiness are major contributors; target smaller image layers and minimal import-time work.
- Build and push by digest, and execute by digest in CI to eliminate image drift during rollout.

**Implementation Details:**
- Add an image freshness gate equivalent to current VM image checks for `gcp/image/**` and Docker-affecting paths.

**Edge Cases:**
- Local bind mount and GCS Fuse behavior are not identical; keep local test as functional validation, not full perf proxy.

**References:**
- [Cloud Run container runtime contract](https://cloud.google.com/run/docs/container-contract)

---

## Phase 5: Cloud Run Gen 2 Infrastructure (Pulumi)

**Goal:** Provision the serverless backbone with mandatory GCS Fuse mounting.

- [ ] **5.1 Define Cloud Run Job (Gen 2)**
  - **Resource:** `gcp.cloudrunv2.Job`.
  - **Volume:** **Mandatory GCS Fuse Mount.** If the bucket uses a `runtime/` prefix (current layout: gcp/remote synced to `runtime/`), map `gs://{BUCKET}/runtime` to `/mnt/runtime`. If the bucket root is the gcp/remote mirror (target layout; see `tools/shared/bucket_env.py`), map `gs://{BUCKET}` to `/mnt/runtime`. The mounted root must be the 1:1 gcp/remote layout (config/, triggers/, projects/, etc.).
  - **FUSE Tuning:** Set `file-cache`, `stat-cache-capacity`, and `type: "gcs"` for optimal read-heavy WAV streaming.

- [ ] **5.2 IAM & Secret Access**
  - **Task:** Create `bmt-job-runner` Service Account.
  - **Task:** Grant least-privilege, resource-scoped access. **Bucket layout:** The bucket (or the mounted prefix) is a **1:1 mirror of `gcp/remote`** (see `gcp/README.md`, `tools/shared/bucket_env.py`). Paths below are relative to that root.
    - **Read:** `config/` (registry, etc.), `triggers/`, `projects/` (runners, inputs/datasets).
    - **Write:** `triggers/` (acks, status, summaries), `<results_prefix>/snapshots/`, `<results_prefix>/current.json`.
    - **Secrets:** Secret Manager access limited to required GitHub App secrets only; list exact secret names in config/docs.

- [ ] **5.3 Artifact Registry**
  - **Task:** Provision Docker repository and set CI push permissions.

- [ ] **5.4 Trigger-Source Policy (Direct API vs Eventarc)**
  - **Task:** Choose and document one primary trigger path for CI (`direct-api` or `eventarc`) and enforce mutual exclusion. Implement a single source of truth for execution path (e.g. `BMT_EXECUTOR=job` vs Eventarc-only for internal triggers); ensure CI never enables both for the same workflow run.
  - **Requirement:** No configuration should allow duplicate execution for a single workflow run.

- [ ] **5.5 Security Hardening Prerequisites**
  - **Task:** Require WIF attribute conditions (`attribute.repository`, `attribute.repository_owner`, optional `attribute.ref`) for CI identity bindings.
  - **Task:** Scope secret access to specific GitHub App secrets; avoid broad project-level secret accessor grants.
  - **Task:** Define image digest enforcement policy for execution-time pinning.

### Research Insights (Phase 5)

**Best Practices:**
- Use Gen2 Cloud Run Jobs with explicit GCS volume mount options tuned for read-heavy workloads.
- Scope IAM to required resources and actions; prefer `run.invoker` where execute-only is sufficient.

**Performance Considerations:**
- Prefer mount options such as `metadata-cache-ttl-secs`, `stat-cache-max-size-mb`, and `type-cache-max-size-mb`. Use `only-dir=runtime` only when the bucket has a `runtime/` prefix (current layout); when bucket root = gcp/remote (target), the mount is the whole bucket.
- Size container memory with Fuse cache + worker concurrency overhead in mind.

**Security Considerations:**
- Bind WIF with repository/branch conditions (`attribute.repository`, `attribute.repository_owner`, optional `attribute.ref`).
- Scope `iam.serviceAccountUser` to the job runtime SA only.
- Prefer secret-specific access and version pinning strategy for sensitive GitHub app credentials.

**Implementation Details:**
- Clarify trigger-source policy: direct API primary vs Eventarc fallback, and prevent dual active triggers.
- Prefer `roles/run.invoker` where execution-only is needed; use `roles/run.developer` only when deployment mutation is required.

**Edge Cases:**
- Fuse mount has startup timeout behavior; include retry/failure handling and clear status path when mount fails.
- Explicitly define Artifact Registry push identity and minimum permissions to avoid over-privileged build principals.

**References:**
- [Cloud Storage volume mounts for Cloud Run jobs](https://cloud.google.com/run/docs/configuring/jobs/cloud-storage-volume-mounts)
- [Cloud Run parallelism](https://cloud.google.com/run/docs/configuring/parallelism)
- [Workload Identity Federation with deployment pipelines](https://cloud.google.com/iam/docs/workload-identity-federation-with-deployment-pipelines)
- [Cloud Run IAM roles](https://cloud.google.com/run/docs/reference/iam/roles)

---

## Phase 6: Scalability & Performance Tuning

**Goal:** Enable native parallelism and handle 40GB datasets efficiently.

- [ ] **6.1 Native Task Parallelism**
  - **Task:** Map the GitHub Action handoff so one `execute` call spawns `N` tasks.
  - **Entrypoint:** Use `CLOUD_RUN_TASK_INDEX` to pick the leg from the trigger payload.

- [ ] **6.2 Dynamic Resource Overrides**
  - **Task:** Validate Cloud Run Job resource override capabilities; if per-task overrides are unavailable, implement **tiered jobs** (`bmt-heavy`, `bmt-light`) selected by leg profile.
  - **Task:** Define profile mapping rules (dataset size, workers, memory, cpu) in config.

- [ ] **6.3 Zero-Download Refactor (BMT Base)**
  - **File:** `gcp/image/projects/shared/bmt_manager_base.py` (in-image path consistent with Phase 4.1 layout).
  - **Task:** Detect `/mnt/runtime`. If present, bypass ALL `rsync` or download logic.
  - **Task:** Ensure `path_utils` resolves relative to the mount.

- [ ] **6.4 Post-Execution Coordinator**
  - **Task:** Define concrete coordinator runtime model: Option A (dedicated Cloud Run coordinator job) vs Option B (CI post-step coordinator command). Choose and document the default (e.g. CI post-step for Phase 7; optional Cloud Run coordinator job for later).
  - **Task:** Coordinator obtains registry and per-leg `results_prefix` from GCS (registry + jobs config) or from aggregated leg summaries; document how the coordinator gets registry/jobs.
  - **Task:** Define summary artifact contract path (e.g. `triggers/summaries/<workflow_run_id>/<leg>.json` under the mount root) and optional JSONL telemetry path with aggregation trigger condition.
  - **Task:** Coordinator must own final pointer updates, check/status publication, and cleanup. Define and document **who runs the coordinator** when CI uses `gcloud run jobs execute --wait`: e.g. last task in the same job, or a CI step after `--wait` that reads summary artifacts; ensure pointer/status/cleanup run exactly once.
  - **Task (log collection for Check Run in Cloud Run model):** In the Cloud Run Jobs model there is no persistent watcher process — log collection for the Check Run failure summary changes fundamentally. Define the log collection mechanism before Phase 7 cutover. Options: (A) **GCS-based**: each task writes its own log artifact to `{results_prefix}/snapshots/{run_id}/logs/` (already the per-leg manager pattern); the coordinator downloads and concatenates them after `--wait` completes, uploads the dump, and generates a signed URL — same path as the VM model; (B) **Cloud Logging**: coordinator reads Cloud Run task logs from Cloud Logging API scoped to the job execution ID. Option A is preferred because it reuses the existing `log_config` machinery and requires no new IAM. **Requirement:** the coordinator must generate a signed URL and include it in the Check Run `output.summary` as "Log dump (link expires in 3 days): `<url>`" for every `failure` conclusion.

- [ ] **6.5 Partial Failure and Retry Semantics**
  - **Task:** Specify behavior for missing leg summaries, retry exhaustion, partial success/failure outcomes, and final gate decision mapping. **Explicit rules:** If any leg has no summary by timeout → aggregate = failure, reason = partial_missing. If all legs have summaries → aggregate = failure if any leg failed; success only if all passed. Retry exhaustion for one leg → that leg = failure; others unchanged.
  - **Task:** Ensure coordinator logic is idempotent for safe retries (e.g. write pointer/status keyed by workflow_run_id; overwrite or skip-if-already-final so retries do not duplicate status or corrupt pointer).

### Research Insights (Phase 6)

**Best Practices:**
- Keep one execution contract: one task = one leg, resolved by `CLOUD_RUN_TASK_INDEX` from the trigger payload.
- Add explicit worker/resource tiering rules in config so runtime behavior is predictable and reviewable.

**Performance Considerations:**
- For one-pass WAV reads, prioritize metadata cache tuning over aggressive file caching.
- Define resource tiers by dataset class (light/medium/heavy) with explicit CPU/RAM profiles.

**Implementation Details:**
- Add a coordinator requirement: after all tasks complete, aggregate outcomes, update pointer(s), prune stale snapshots, and persist run summary.
- Treat per-leg summary artifacts as the source of truth for aggregation, not task logs.
- Treat JSONL telemetry as observability input only; final decisions come from canonical summary/verdict JSON artifacts.

**Edge Cases:**
- Partial task failures must produce deterministic aggregate verdicts and non-ambiguous final status.
- Quota-driven parallelism limits should degrade gracefully (reduced parallelism or explicit failure reason).
- Log collection must not block the Check Run update: if the log dump upload or signed URL generation fails, the coordinator must still finalize the Check Run (with a degraded note: "Log dump unavailable") rather than leaving it in `in_progress`.
- Signed URLs expire in 3 days; the Check Run text must state the expiry so developers know to act promptly.

**References:**
- [Cloud Run jobs retries](https://cloud.google.com/run/docs/jobs-retries)
- [Cloud Run task timeout](https://cloud.google.com/run/docs/configuring/task-timeout)

---

## Done When

Docker image builds and runs with config-driven invocation; Cloud Run Job is provisioned with GCS Fuse; task parallelism and coordinator ownership (aggregation, pointer update, status/check, cleanup) are defined and validated (e.g. tested with a multi-leg run and documented).

[Document 5 (ci-cutover-and-vm-decommission.md)](ci-cutover-and-vm-decommission.md) depends on completion of this document.

---

## Verification

| Phase | Method |
| :--- | :--- |
| **4** | `docker run` — local FUSE simulation |
| **5-6** | `just workspace deploy` + Manual Job Execution in GCP Console |
| **5.5** | IAM/WIF policy validation (resource-scoped secrets/storage, attribute conditions, digest policy checks) |
| **6** | Run matrix of >=20 legs and single leg with 40GB dataset; document resource tier and success criteria |
