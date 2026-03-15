# Migration to Google Cloud Run Jobs: Detailed Implementation Plan

**Status:** Proposed / Detailed Strategy
**Date:** 2026-03-15
**Goal:** Replace the GCE VM-based BMT executor with a serverless, parallelized Cloud Run Jobs architecture. **Mandatory adoption of Cloud Run Gen 2 GCS Fuse mounts** as the primary dataset interface to solve the 40GB+ scalability "startup wall."

---

## Executive Summary: Solving the 40GB Scalability Wall
The current VM architecture relies on `gcloud rsync` to download datasets into a local cache. For 40GB datasets, this creates a significant "startup wall" and expensive disk requirements. 

**This migration mandates a "Zero-Download" architecture:** 
By using native **Cloud Run Gen 2 GCS Fuse mounts**, every container (regardless of dataset size) starts in seconds. Files are streamed on-demand as they are read by the Python code, enabling simultaneous, parallel execution for 20+ projects with zero local disk overhead.

---

## Phase 1: Containerization & Local Validation
**Goal:** Create a reproducible execution environment that matches the current VM.

*   [ ] **1.1 Create `gcp/image/Dockerfile`**
    *   Base: `python:3.12-slim-bookworm`.
    *   Install system dependencies: `libsndfile1`, `ffmpeg`, `curl`, `gnupg`.
    *   Install `uv` binary (pinned version matching `code/_tools/uv/`).
*   [ ] **1.2 Package Code & Config**
    *   Copy `gcp/image` to `/app/gcp/image`.
    *   Copy `tools` to `/app/tools`.
    *   Set `PYTHONPATH=/app`.
*   [ ] **1.3 Local Execution Test**
    *   Build: `docker build -t bmt-orchestrator:latest gcp/image/`.
    *   Run: `docker run -v $(pwd)/gcp/remote:/mnt/runtime -e GCS_BUCKET=... bmt-orchestrator --leg-json='{...}'` (Simulate FUSE mount locally).

---

## Phase 2: Infrastructure Setup (Pulumi)
**Goal:** Provision the GCP resources and IAM permissions for the Job.

*   [ ] **2.1 Define Cloud Run Job (Gen 2 - MANDATORY)**
    *   Resource: `gcp.cloudrunv2.Job`.
    *   Config: 1-4 vCPU, 2-8GiB RAM (scalable per BMT requirements).
    *   **Mandatory GCS Fuse Mount:** Configure a volume mount to map `gs://{GCS_BUCKET}/runtime` to `/mnt/runtime`. 
    *   **Performance Tuning:** Set `file-cache`, `stat-cache-capacity`, and `type: "gcs"` in the Pulumi volume definition to optimize for read-heavy WAV streaming.
*   [ ] **2.2 IAM & Service Account**
    *   Create `bmt-job-runner` Service Account.
    *   Grant `roles/storage.objectAdmin` (for results) and `roles/storage.objectViewer` (for Fuse mount).
    *   Grant `roles/secretmanager.secretAccessor` for GitHub App keys.
*   [ ] **2.3 Artifact Registry**
    *   Provision a Docker repository in Artifact Registry.

---

## Phase 3: Entrypoint & Orchestrator Refactor
**Goal:** Adapt the Python logic for single-shot, parallelized execution using the FUSE backbone.

*   [ ] **3.1 Single-Shot `job_entrypoint.py`**
    *   Handle **Task Indexing**: Use `CLOUD_RUN_TASK_INDEX` to pick the specific leg (Project + BMT ID) from the trigger payload.
    *   **Path Mapping (MANDATORY):** Refactor `path_utils` and `bmt_manager_base.py` to check for `/mnt/runtime`. If present, all input paths MUST be resolved relative to this mount, **bypassing all `rsync` or download logic**.
*   [ ] **3.2 Scalable Project Loading**
    *   The container will include the full `gcp/image/projects/` tree. The orchestrator dynamically imports the correct `bmt_manager.py` based on the leg identity. This scales to 20+ projects without changing the container entrypoint.

---

## Phase 4: Triggering Integration (API & Eventarc)
**Goal:** Enable multiple ways to start the job.

*   [ ] **4.1 Direct API (GitHub Actions)**
    *   Update `bmt-handoff.yml` to use `google-github-actions/deploy-cloudrun` or a raw `gcloud run jobs execute` command.
    *   Pass the trigger JSON as an environment variable override or CLI arg.
*   [ ] **4.2 Eventarc (GCS Trigger Fallback)**
    *   Provision `gcp.eventarc.Trigger`.
    *   Filter: `type=google.cloud.storage.object.v1.finalized`, `attribute.name=runtime/triggers/runs/**.json`.
    *   Target: Start the Cloud Run Job.

---

## Phase 5: CI Workflow Migration
**Goal:** Cut over from VM to Job.

*   [ ] **5.1 Parallel Testing**
    *   Update `bmt-handoff.yml` to trigger BOTH the VM and the Cloud Run Job (using a `--dry-run` or test prefix).
    *   Verify that Cloud Run results match VM results exactly.
*   [ ] **5.2 Cutover**
    *   Disable the `start-vm` and `wait-handshake` steps in CI.
    *   Set `IDLE_TIMEOUT_SEC=0` on the VM and eventually decommission the instance.

---

## Phase 6: Scalability & Large Datasets (40GB+)
**Goal:** Ensure the system handles 20+ projects and large WAV corpora efficiently.

*   [ ] **6.1 Zero-Download Parallelism**
    *   Map the GitHub Action handoff so that a single `execute` call spawns `N` tasks (one per project/BMT leg). Cloud Run Jobs will automatically distribute these across the serverless fleet.
    *   **Impact:** A 40GB SK run and a 5GB Woven run will execute simultaneously in separate containers, both starting in seconds because no files are pre-downloaded.
*   [ ] **6.2 Resource Overrides per Project**
    *   Implement logic in the CI to request higher memory (e.g., 8GiB) for the 40GB dataset BMTs and lower memory (2GiB) for lightweight BMTs to optimize cost.
*   [ ] **6.3 Project Scaffolding Scalability**
    *   Ensure the `just add-project` tool generates `bmt_manager.py` code that is compatible with the `/mnt/runtime` pathing required for the Cloud Run GCS Fuse mount.

---

## Technical Requirements & Constraints
*   **Networking:** Cloud Run Jobs must have Egress access to GCS and GitHub APIs.
*   **Artifacts:** Container images should be tagged with the `GITHUB_SHA` for traceability.
*   **Observability:** All container logs must be directed to `stdout/stderr` for Cloud Logging integration.
