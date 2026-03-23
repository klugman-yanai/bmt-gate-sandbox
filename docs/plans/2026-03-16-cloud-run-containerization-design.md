# Cloud Run Containerization and Infrastructure — Design

**Date:** 2026-03-16
**Status:** Approved
**Implements:** [docs/roadmap/cloud-run-containerization-and-infra.md](../roadmap/cloud-run-containerization-and-infra.md)

---

## Architecture Overview

```
CI writes triggers/runs/<id>.json (with if_generation_match=0)
  → GCS object.finalized event
  → Eventarc Standard
  → Workflows (24h dedup + prefix filter + job invocation)
  → Cloud Run Job (N tasks, one per leg)
  → Each task reads trigger, runs BMT via gcp/image/main.py
  → Each task writes summary to triggers/summaries/<id>/<leg>.json
  → Workflow waits for job completion
  → Workflow reads summaries, posts GitHub status/Check Run via HTTP
```

---

## Phase 4: Dockerfile & Container Image

### Image layout

Container mirrors the local repo structure. `WORKDIR=/opt/bmt`, `PYTHONPATH=/opt/bmt`.

```
/opt/bmt/
├── gcp/
│   ├── __init__.py
│   └── image/          # COPY gcp/image/ → /opt/bmt/gcp/image/
│       ├── main.py     # entrypoint
│       ├── models.py
│       ├── projects/
│       └── ...
├── pyproject.toml      # from gcp/image/pyproject.toml
└── .venv/              # uv-managed deps
```

### Dockerfile (gcp/image/Dockerfile)

- **Base:** `python:3.12-slim-bookworm`
- **System deps:** `libsndfile1`, `ffmpeg`, `curl`, `gnupg`
- **Python toolchain:** `uv` (pinned version from official image)
- **Entrypoint:** `python gcp/image/main.py`
- **Config:** JSON payload file via `BMT_CONFIG` env var or `/etc/bmt/config.json`

Multi-stage build:
1. **deps stage:** install system packages, copy pyproject.toml, `uv sync`
2. **app stage:** copy `gcp/` package, set PYTHONPATH and CMD

### What is NOT baked in

- `bmt_projects.json` registry — loaded from GCS FUSE mount at runtime
- Trigger payloads — read from GCS at runtime
- Datasets, runners — accessed via GCS FUSE mount

### What IS baked in

- All `gcp/image/` code including `projects/` managers
- Python dependencies

### .dockerignore

Excludes: `data/`, `.venv/`, `__pycache__/`, `tests/`, `tools/`, `infra/`, `.github/`, `docs/`, `*.md`, `.git/`

### Local validation

```bash
just docker-build      # docker build -t bmt-orchestrator:latest -f gcp/image/Dockerfile .
just docker-run-test   # docker run with bind mount simulating FUSE
```

---

## Phase 5: Cloud Run Gen 2 Infrastructure (Pulumi)

### Trigger pipeline: Eventarc Standard → Workflows → Cloud Run Job

**Why Workflows intermediary:**
- Eventarc Standard does NOT support Cloud Run Jobs as a direct destination
- Workflows provides built-in 24-hour event deduplication
- Workflow handles prefix filtering (direct GCS events only filter by bucket, not path)
- Workflow reads trigger to determine task count and resource tier

### Pulumi resources

| Resource | Name | Purpose |
|----------|------|---------|
| Artifact Registry | `bmt-images` | Docker image repository |
| Service Account | `bmt-job-runner` | Cloud Run Job runtime SA |
| Service Account | `bmt-workflow-sa` | Workflows SA |
| Cloud Run Job (standard) | `bmt-orchestrator-standard` | Default tier (4 CPU, 8Gi) |
| Cloud Run Job (heavy) | `bmt-orchestrator-heavy` | Large dataset tier (8 CPU, 16Gi) |
| Workflows | `bmt-trigger-workflow` | Event routing, dedup, job invocation |
| Eventarc trigger | `bmt-gcs-trigger` | GCS finalize → Workflow |
| IAM bindings | various | Least-privilege access |

### Config additions (bmt.tfvars.json)

```json
{
  "cloud_run_region": "europe-west4",
  "cloud_run_memory_standard": "8Gi",
  "cloud_run_cpu_standard": "4",
  "cloud_run_memory_heavy": "16Gi",
  "cloud_run_cpu_heavy": "8",
  "cloud_run_task_timeout_sec": 3600,
  "cloud_run_job_sa_name": "bmt-job-runner",
  "cloud_run_workflow_sa_name": "bmt-workflow-sa",
  "artifact_registry_repo": "bmt-images",
  "github_repo_owner": "klugman-yanai",
  "github_repo_name": "bmt-gcloud"
}
```

### IAM design

**bmt-job-runner SA:**
- `roles/storage.objectViewer` on bucket (read config, triggers, datasets)
- `roles/storage.objectCreator` on bucket (write summaries, results, acks)
- Secret Manager `secretAccessor` scoped to specific GitHub App secrets

**bmt-workflow-sa:**
- `roles/run.invoker` on Cloud Run Jobs (execute jobs)
- `roles/storage.objectViewer` on bucket (read trigger and summaries)
- `roles/eventarc.eventReceiver` (receive events)
- `roles/logging.logWriter` (Workflow logs)

**CI SA (existing):**
- `roles/storage.objectCreator` on bucket `triggers/runs/` (write triggers)
- No `run.invoker` needed (CI doesn't invoke jobs directly)

### Workflow definition

```yaml
main:
  params: [event]
  steps:
    - extract:
        assign:
          - object_name: ${event.data.name}
          - bucket: ${event.data.bucket}
    - check_prefix:
        switch:
          - condition: ${not(text.match_regex(object_name, "^triggers/runs/.*\\.json$"))}
            next: end
    - read_trigger:
        call: http.get
        args:
          url: ${"https://storage.googleapis.com/storage/v1/b/" + bucket + "/o/" + text.url_encode(object_name) + "?alt=media"}
          auth:
            type: OAuth2
        result: trigger_response
    - parse_trigger:
        assign:
          - trigger: ${trigger_response.body}
          - task_count: ${len(trigger.legs)}
          - workflow_run_id: ${trigger.workflow_run_id}
    - run_job:
        call: googleapis.run.v1.namespaces.jobs.run
        args:
          name: ${"namespaces/" + sys.get_env("GOOGLE_CLOUD_PROJECT_NUMBER") + "/jobs/bmt-orchestrator-standard"}
          location: ${sys.get_env("GOOGLE_CLOUD_LOCATION")}
          body:
            overrides:
              taskCount: ${task_count}
              containerOverrides:
                - env:
                    - name: BMT_TRIGGER_OBJECT
                      value: ${object_name}
                    - name: BMT_WORKFLOW_RUN_ID
                      value: ${workflow_run_id}
        result: job_execution
    - read_summaries:
        call: http.get
        args:
          url: ${"https://storage.googleapis.com/storage/v1/b/" + bucket + "/o?prefix=triggers/summaries/" + workflow_run_id + "/"}
          auth:
            type: OAuth2
        result: summaries_list
    - post_status:
        # Coordinator step: read summaries, aggregate, post GitHub status
        # Implemented as HTTP calls to GitHub API from Workflow
        # or as a final coordinator Cloud Run Service call
        next: end
    - end:
        return: "done"
```

### Trigger-source policy

- **Primary:** Eventarc (GCS finalize → Workflows → Cloud Run Job)
- **No direct API invocation from CI** (CI only writes trigger to GCS)
- **Mutual exclusion:** Single trigger path; no dual-execution possible
- CI's `if_generation_match=0` on trigger write prevents duplicate triggers
- Workflows' 24h dedup prevents duplicate job executions from duplicate events

### Security hardening

- WIF attribute conditions: `attribute.repository == "klugman-yanai/bmt-gcloud"` and `attribute.repository_owner == "klugman-yanai"`
- Secret access scoped to specific secret names (not project-level)
- Image executed by digest (CI updates job image reference after push)

---

## Phase 6: Scalability & Performance

### 6.1 Task parallelism

- One job execution per trigger, N tasks (one per leg)
- `CLOUD_RUN_TASK_INDEX` selects the leg from the trigger payload
- `main.py` reads index and dispatches to the correct leg

### 6.2 Resource tiers

- Two job definitions: `bmt-orchestrator-standard` and `bmt-orchestrator-heavy`
- Workflow reads trigger, determines tier per leg, routes accordingly
- If all legs fit one tier → single execution
- If mixed → separate executions per tier

### 6.3 Zero-download (FUSE detection)

In `bmt_manager_base.py`: detect `/mnt/runtime`. If present, skip all download/rsync logic and resolve paths relative to the mount.

```python
FUSE_MOUNT_ROOT = Path("/mnt/runtime")

@property
def fuse_mounted(self) -> bool:
    return self.FUSE_MOUNT_ROOT.is_dir()
```

### 6.4 Coordinator

The Workflow acts as coordinator after job completion:
1. Reads summary artifacts from `triggers/summaries/<workflow_run_id>/`
2. Aggregates verdicts (reuses logic from `coordinator.py`)
3. Posts GitHub commit status and finalizes Check Run
4. Updates `current.json` pointers
5. Cleans stale snapshots

For GitHub API calls that need complex logic (Check Run rendering, pointer updates), the Workflow invokes a lightweight coordinator Cloud Run Service endpoint (or the same job image with `BMT_MODE=coordinator`).

### 6.5 Partial failure rules

- Missing leg summary by timeout → `failure`, reason `partial_missing`
- All summaries present, any leg failed → `failure`
- All summaries present, all passed → `success`
- Retry exhaustion for one leg → that leg = `failure`
- Idempotent: pointer/status keyed by `workflow_run_id`

### Summary artifact contract

- Path: `triggers/summaries/<workflow_run_id>/<project>-<bmt_id>.json`
- Written by each Cloud Run task on completion
- Read by Workflow coordinator step after job ends
- Schema: same as existing `ManagerSummary` TypedDict

---

## Manual GCP Operations

These must be done via `gcloud` CLI or GCP Console before `pulumi up`:

### 1. Enable required APIs

```bash
gcloud services enable \
  run.googleapis.com \
  workflows.googleapis.com \
  eventarc.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  --project=train-kws-202311
```

### 2. Create Artifact Registry repository

Pulumi will handle this, but if you prefer to pre-create:

```bash
gcloud artifacts repositories create bmt-images \
  --repository-format=docker \
  --location=europe-west4 \
  --description="BMT orchestrator container images" \
  --project=train-kws-202311
```

### 3. Push initial container image

After `just docker-build`, before `pulumi up` (Cloud Run Job needs an image to reference):

```bash
# Tag and push
docker tag bmt-orchestrator:latest europe-west4-docker.pkg.dev/train-kws-202311/bmt-images/bmt-orchestrator:latest
docker push europe-west4-docker.pkg.dev/train-kws-202311/bmt-images/bmt-orchestrator:latest
```

### 4. Grant Eventarc service agent permissions

The Eventarc service agent needs permission to invoke Workflows:

```bash
PROJECT_NUMBER=$(gcloud projects describe train-kws-202311 --format="value(projectNumber)")

# Eventarc service agent needs Workflows invoker
gcloud projects add-iam-policy-binding train-kws-202311 \
  --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-eventarc.iam.gserviceaccount.com" \
  --role="roles/workflows.invoker"

# Eventarc service agent needs to read from Pub/Sub (used internally by Eventarc)
gcloud projects add-iam-policy-binding train-kws-202311 \
  --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-eventarc.iam.gserviceaccount.com" \
  --role="roles/pubsub.subscriber"
```

### 5. Create GitHub App secrets in Secret Manager

If not already created (for the Cloud Run Job to post GitHub status):

```bash
# Create secrets (values from your GitHub App)
echo -n "YOUR_APP_ID" | gcloud secrets create bmt-github-app-id \
  --data-file=- --project=train-kws-202311

echo -n "YOUR_PRIVATE_KEY" | gcloud secrets create bmt-github-app-private-key \
  --data-file=- --project=train-kws-202311

echo -n "YOUR_INSTALLATION_ID" | gcloud secrets create bmt-github-app-installation-id \
  --data-file=- --project=train-kws-202311
```

### 6. Authenticate Docker to Artifact Registry

One-time setup on your dev machine:

```bash
gcloud auth configure-docker europe-west4-docker.pkg.dev
```

### Post-Pulumi verification

After `pulumi up`:

```bash
# Verify Artifact Registry
gcloud artifacts repositories describe bmt-images --location=europe-west4

# Verify Cloud Run Jobs
gcloud run jobs describe bmt-orchestrator-standard --region=europe-west4
gcloud run jobs describe bmt-orchestrator-heavy --region=europe-west4

# Verify Workflow
gcloud workflows describe bmt-trigger-workflow --location=europe-west4

# Verify Eventarc trigger
gcloud eventarc triggers describe bmt-gcs-trigger --location=europe-west4

# Test: write a dummy trigger and watch the pipeline
echo '{"test": true}' | gcloud storage cp - gs://YOUR_BUCKET/triggers/runs/test-dummy.json
# Then check Workflow execution logs
gcloud workflows executions list bmt-trigger-workflow --location=europe-west4
```

---

## Files to create/modify

| File | Action | Purpose |
|------|--------|---------|
| `gcp/image/Dockerfile` | Create | Container image definition |
| `gcp/image/.dockerignore` | Create | Build context exclusions |
| `infra/pulumi/__main__.py` | Modify | Add Cloud Run, Workflows, Eventarc, AR, IAM |
| `infra/pulumi/config.py` | Modify | Add Cloud Run config fields |
| `infra/pulumi/bmt.tfvars.example.json` | Modify | Add example Cloud Run config |
| `infra/pulumi/workflow.yaml` | Create | Workflow definition |
| `gcp/image/main.py` | Modify | Add CLOUD_RUN_TASK_INDEX dispatch |
| `gcp/image/entrypoint_config.py` | Modify | Add task-index-aware config loading |
| `gcp/image/projects/shared/bmt_manager_base.py` | Modify | FUSE detection, zero-download |
| `gcp/image/coordinator.py` | Modify | Add summary artifact write path |
| `Justfile` | Modify | Add docker-build, docker-run-test recipes |
