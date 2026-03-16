# Cloud Run Containerization — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create a Cloud Run Jobs-based BMT execution environment with Eventarc→Workflows→Job pipeline, GCS FUSE mounts, and Pulumi IaC — replacing the GCE VM executor.

**Architecture:** Eventarc Standard fires on GCS object finalize → Workflows filters by prefix, deduplicates, reads trigger, invokes Cloud Run Job with N tasks (one per leg) → each task runs `gcp/image/main.py` with `CLOUD_RUN_TASK_INDEX` → writes summary artifact → Workflow reads summaries and posts GitHub status.

**Tech Stack:** Docker, uv, Pulumi Python, Cloud Run Jobs Gen2, Eventarc Standard, Workflows, GCS FUSE, Artifact Registry.

**Design doc:** `docs/plans/2026-03-16-cloud-run-containerization-design.md`

---

## Batch 1: Phase 4 — Container Image (Tasks 1–3)

### Task 1: Create Dockerfile and .dockerignore

**Files:**
- Create: `gcp/image/Dockerfile`
- Create: `gcp/image/.dockerignore`

**Step 1: Create `.dockerignore`**

```dockerignore
# Build context is repo root; exclude everything not needed in the image
.git/
.github/
.venv/
__pycache__/
*.pyc
data/
docs/
infra/
tests/
tools/
local_batch/
sk_runtime/
bmt_workspace/
secrets/
*.md
!gcp/image/README.md
.env
.local/
gcp/stage/
gcp/mnt/
gcp/local/
```

**Step 2: Create `Dockerfile`**

The image mirrors the repo directory layout. `WORKDIR=/opt/bmt`, `PYTHONPATH=/opt/bmt`. Two-stage build: deps then app code.

```dockerfile
# Stage 1: system deps + Python deps (cached layer)
FROM python:3.12-slim-bookworm AS deps

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libsndfile1 ffmpeg curl gnupg && \
    rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.6 /uv /usr/local/bin/uv

WORKDIR /opt/bmt

# Copy only dependency metadata first (layer caching)
COPY gcp/image/pyproject.toml /opt/bmt/gcp/image/pyproject.toml
COPY gcp/__init__.py /opt/bmt/gcp/__init__.py
COPY gcp/image/__init__.py /opt/bmt/gcp/image/__init__.py

# Install deps into a project-local .venv
RUN cd /opt/bmt/gcp/image && uv sync --frozen --no-dev --no-editable

# Stage 2: application code
FROM deps AS app

# Copy the full gcp/image package (managers, contracts, schemas, scripts, etc.)
COPY gcp/__init__.py /opt/bmt/gcp/__init__.py
COPY gcp/image/ /opt/bmt/gcp/image/

ENV PYTHONPATH=/opt/bmt
ENV PATH="/opt/bmt/gcp/image/.venv/bin:$PATH"

# Config via BMT_CONFIG env var pointing to a JSON payload file,
# or mount at /etc/bmt/config.json (well-known path)
CMD ["python", "gcp/image/main.py"]
```

**Step 3: Verify Dockerfile syntax**

Run: `docker build --check -f gcp/image/Dockerfile .` (Docker 27+ with BuildKit)
If `--check` is unsupported: `docker build -f gcp/image/Dockerfile --target deps .`
Expected: Build completes for deps stage (app stage may fail if uv.lock missing — that's fine for syntax check).

---

### Task 2: Add Justfile recipes for Docker build/run

**Files:**
- Modify: `Justfile` (append at end)

**Step 1: Add docker recipes**

Append to `Justfile`:

```just
# -- Docker (Cloud Run image) --------------------------------------------------

# Build the BMT orchestrator container image
[group('docker')]
docker-build:
    docker build -t bmt-orchestrator:latest -f gcp/image/Dockerfile .

# Run the container locally with gcp/stage bind-mounted as /mnt/runtime (FUSE simulation)
[group('docker')]
docker-run-test *args:
    docker run --rm \
        -v "$(pwd)/gcp/stage:/mnt/runtime:ro" \
        -e BMT_CONFIG=/etc/bmt/config.json \
        {{ args }} \
        bmt-orchestrator:latest

# Tag and push the image to Artifact Registry (requires gcloud auth configure-docker)
[group('docker')]
docker-push:
    #!/usr/bin/env bash
    set -euo pipefail
    PROJECT=$(cd infra/pulumi && pulumi stack output gcp_project 2>/dev/null || echo "${GCP_PROJECT:-train-kws-202311}")
    REGION="${CLOUD_RUN_REGION:-europe-west4}"
    REPO="${ARTIFACT_REGISTRY_REPO:-bmt-images}"
    IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/bmt-orchestrator:latest"
    docker tag bmt-orchestrator:latest "${IMAGE}"
    docker push "${IMAGE}"
    echo "Pushed: ${IMAGE}"
```

**Step 2: Verify recipe listing**

Run: `just --list | grep docker`
Expected: Shows `docker-build`, `docker-run-test`, `docker-push` under `docker` group.

---

### Task 3: Add constants for Cloud Run / FUSE / summary paths

**Files:**
- Modify: `gcp/image/config/constants.py` (append to end)

**Step 1: Add Cloud Run and FUSE constants**

Append to `gcp/image/config/constants.py` after the `ARTIFACT_SCHEMA_VERSION` line:

```python
# ---------------------------------------------------------------------------
# Cloud Run / FUSE constants
# ---------------------------------------------------------------------------
FUSE_MOUNT_ROOT = "/mnt/runtime"

# Summary artifacts written by each Cloud Run task for the coordinator
TRIGGER_SUMMARIES_PREFIX = "triggers/summaries"

# Partial failure reason (coordinator could not collect all leg summaries)
REASON_PARTIAL_MISSING = "partial_missing"

# Cloud Run task index env var (set automatically by Cloud Run)
CLOUD_RUN_TASK_INDEX_ENV = "CLOUD_RUN_TASK_INDEX"
CLOUD_RUN_TASK_COUNT_ENV = "CLOUD_RUN_TASK_COUNT"

# Env vars set by the Workflow when invoking the Cloud Run Job
BMT_TRIGGER_OBJECT_ENV = "BMT_TRIGGER_OBJECT"
BMT_WORKFLOW_RUN_ID_ENV = "BMT_WORKFLOW_RUN_ID"
```

**Step 2: Verify imports**

Run: `uv run python -c "from gcp.image.config.constants import FUSE_MOUNT_ROOT, TRIGGER_SUMMARIES_PREFIX, REASON_PARTIAL_MISSING; print('OK')"`
Expected: `OK`

**Step 3: Run lint**

Run: `ruff check gcp/image/config/constants.py`
Expected: Clean.

---

## Batch 2: Phase 5 — Pulumi IaC (Tasks 4–6)

### Task 4: Extend Pulumi config with Cloud Run fields

**Files:**
- Modify: `infra/pulumi/config.py:14-48` (add fields to `InfraConfig`)
- Modify: `infra/pulumi/bmt.tfvars.example.json` (add example values)

**Step 1: Add Cloud Run fields to InfraConfig**

In `infra/pulumi/config.py`, add these fields to the `InfraConfig` dataclass after the existing fields (after `startup_wrapper_script_path`):

```python
    # Cloud Run
    cloud_run_region: str = "europe-west4"
    cloud_run_memory_standard: str = "8Gi"
    cloud_run_cpu_standard: str = "4"
    cloud_run_memory_heavy: str = "16Gi"
    cloud_run_cpu_heavy: str = "8"
    cloud_run_task_timeout_sec: int = 3600
    cloud_run_job_sa_name: str = "bmt-job-runner"
    cloud_run_workflow_sa_name: str = "bmt-workflow-sa"
    artifact_registry_repo: str = "bmt-images"
    github_repo_owner: str = ""
    github_repo_name: str = ""
```

Also add a computed property for the image URI:

```python
    @property
    def cloud_run_image_uri(self) -> str:
        """Derive image URI from Artifact Registry config."""
        return (
            f"{self.cloud_run_region}-docker.pkg.dev/"
            f"{self.gcp_project}/{self.artifact_registry_repo}/bmt-orchestrator"
        )
```

**Step 2: Update example config**

Update `infra/pulumi/bmt.tfvars.example.json` to include the new fields:

```json
{
  "gcp_project": "my-gcp-project",
  "gcp_zone": "europe-west4-a",
  "gcs_bucket": "my-bmt-bucket",
  "service_account": "bmt-vm@my-gcp-project.iam.gserviceaccount.com",
  "bmt_vm_name": "bmt-gate-blue",
  "startup_wrapper_script_path": "../../.github/bmt/ci/resources/startup_entrypoint.sh",
  "github_vars": {
    "GCP_WIF_PROVIDER": "projects/123456/locations/global/workloadIdentityPools/...",
    "BMT_DISPATCH_APP_ID": "12345"
  },
  "cloud_run_region": "europe-west4",
  "cloud_run_job_sa_name": "bmt-job-runner",
  "cloud_run_workflow_sa_name": "bmt-workflow-sa",
  "artifact_registry_repo": "bmt-images",
  "github_repo_owner": "klugman-yanai",
  "github_repo_name": "bmt-gcloud"
}
```

**Step 3: Verify config loads**

Run: `cd infra/pulumi && uv run python -c "from config import load_config; c = load_config(); print(c.cloud_run_image_uri)"`
Expected: Prints `europe-west4-docker.pkg.dev/train-kws-202311/bmt-images/bmt-orchestrator`

---

### Task 5: Create Workflow YAML definition

**Files:**
- Create: `infra/pulumi/workflow.yaml`

**Step 1: Write the Workflow definition**

```yaml
main:
  params: [event]
  steps:
    - init:
        assign:
          - project_number: ${sys.get_env("GOOGLE_CLOUD_PROJECT_NUMBER")}
          - location: ${sys.get_env("GOOGLE_CLOUD_LOCATION")}

    - extract_event:
        assign:
          - object_name: ${event.data.name}
          - bucket: ${event.data.bucket}

    - check_prefix:
        switch:
          - condition: ${not(text.match_regex(object_name, "^triggers/runs/.*\\.json$"))}
            next: skip_non_trigger

    - read_trigger:
        call: http.get
        args:
          url: ${"https://storage.googleapis.com/download/storage/v1/b/" + bucket + "/o/" + text.url_encode(object_name) + "?alt=media"}
          auth:
            type: OAuth2
        result: trigger_response

    - parse_trigger:
        assign:
          - trigger: ${trigger_response.body}
          - task_count: ${len(trigger.legs)}
          - workflow_run_id: ${trigger.workflow_run_id}

    - execute_job:
        call: googleapis.run.v1.namespaces.jobs.run
        args:
          name: ${"namespaces/" + project_number + "/jobs/bmt-orchestrator-standard"}
          location: ${location}
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

    - wait_completion:
        assign:
          - execution_status: ${job_execution.status}

    - run_coordinator:
        call: googleapis.run.v1.namespaces.jobs.run
        args:
          name: ${"namespaces/" + project_number + "/jobs/bmt-orchestrator-standard"}
          location: ${location}
          body:
            overrides:
              taskCount: 1
              containerOverrides:
                - env:
                    - name: BMT_MODE
                      value: "coordinator"
                    - name: BMT_WORKFLOW_RUN_ID
                      value: ${workflow_run_id}
                    - name: BMT_TRIGGER_OBJECT
                      value: ${object_name}
        result: coordinator_result

    - done:
        return:
          workflow_run_id: ${workflow_run_id}
          task_count: ${task_count}
          status: "completed"

    - skip_non_trigger:
        return:
          status: "skipped"
          reason: "not a trigger file"
          object: ${object_name}
```

**Step 2: Validate YAML syntax**

Run: `uv run python -c "import yaml; yaml.safe_load(open('infra/pulumi/workflow.yaml')); print('Valid YAML')"`
Expected: `Valid YAML` (requires PyYAML — if not available, `python -c "import json, yaml" ...` may fail; just visually verify).

---

### Task 6: Add Pulumi resources (Artifact Registry, SAs, Cloud Run, Workflows, Eventarc, IAM)

**Files:**
- Modify: `infra/pulumi/__main__.py` (append after existing resources, before exports)

**Step 1: Add all Cloud Run infrastructure resources**

After the existing IAM bindings (line ~135) and before the exports section (line ~137), add:

```python
# ===================================================================
# Cloud Run Infrastructure
# ===================================================================

# --- Artifact Registry ---

artifact_registry = gcp.artifactregistry.Repository(
    "bmt-images",
    repository_id=cfg.artifact_registry_repo,
    location=cfg.cloud_run_region,
    project=cfg.gcp_project,
    format="DOCKER",
    description="BMT orchestrator container images",
)

# --- Service Accounts ---

job_runner_sa = gcp.serviceaccount.Account(
    "bmt-job-runner-sa",
    account_id=cfg.cloud_run_job_sa_name,
    display_name="BMT Cloud Run Job Runner",
    project=cfg.gcp_project,
)

workflow_sa = gcp.serviceaccount.Account(
    "bmt-workflow-sa",
    account_id=cfg.cloud_run_workflow_sa_name,
    display_name="BMT Trigger Workflow",
    project=cfg.gcp_project,
)

# --- Cloud Run Jobs ---

cloud_run_job_standard = gcp.cloudrunv2.Job(
    "bmt-orchestrator-standard",
    name="bmt-orchestrator-standard",
    location=cfg.cloud_run_region,
    project=cfg.gcp_project,
    launch_stage="GA",
    template=gcp.cloudrunv2.JobTemplateArgs(
        task_count=1,  # overridden per-execution by Workflow
        template=gcp.cloudrunv2.JobTemplateTemplateArgs(
            service_account=job_runner_sa.email,
            timeout=f"{cfg.cloud_run_task_timeout_sec}s",
            max_retries=1,
            containers=[
                gcp.cloudrunv2.JobTemplateTemplateContainerArgs(
                    image=f"{cfg.cloud_run_image_uri}:latest",
                    resources=gcp.cloudrunv2.JobTemplateTemplateContainerResourcesArgs(
                        limits={
                            "cpu": cfg.cloud_run_cpu_standard,
                            "memory": cfg.cloud_run_memory_standard,
                        },
                    ),
                ),
            ],
            volumes=[
                gcp.cloudrunv2.JobTemplateTemplateVolumeArgs(
                    name="runtime-data",
                    gcs=gcp.cloudrunv2.JobTemplateTemplateVolumeGcsArgs(
                        bucket=cfg.gcs_bucket,
                        read_only=False,
                    ),
                ),
            ],
            volume_mounts=[],  # set on containers — see note below
        ),
    ),
)

cloud_run_job_heavy = gcp.cloudrunv2.Job(
    "bmt-orchestrator-heavy",
    name="bmt-orchestrator-heavy",
    location=cfg.cloud_run_region,
    project=cfg.gcp_project,
    launch_stage="GA",
    template=gcp.cloudrunv2.JobTemplateArgs(
        task_count=1,
        template=gcp.cloudrunv2.JobTemplateTemplateArgs(
            service_account=job_runner_sa.email,
            timeout=f"{cfg.cloud_run_task_timeout_sec}s",
            max_retries=1,
            containers=[
                gcp.cloudrunv2.JobTemplateTemplateContainerArgs(
                    image=f"{cfg.cloud_run_image_uri}:latest",
                    resources=gcp.cloudrunv2.JobTemplateTemplateContainerResourcesArgs(
                        limits={
                            "cpu": cfg.cloud_run_cpu_heavy,
                            "memory": cfg.cloud_run_memory_heavy,
                        },
                    ),
                ),
            ],
            volumes=[
                gcp.cloudrunv2.JobTemplateTemplateVolumeArgs(
                    name="runtime-data",
                    gcs=gcp.cloudrunv2.JobTemplateTemplateVolumeGcsArgs(
                        bucket=cfg.gcs_bucket,
                        read_only=False,
                    ),
                ),
            ],
        ),
    ),
)

# --- Workflows ---

workflow_source = (Path(__file__).parent / "workflow.yaml").read_text(encoding="utf-8")

bmt_workflow = gcp.workflows.Workflow(
    "bmt-trigger-workflow",
    name="bmt-trigger-workflow",
    region=cfg.cloud_run_region,
    project=cfg.gcp_project,
    description="Routes GCS trigger events to BMT Cloud Run Jobs",
    service_account=workflow_sa.id,
    source_contents=workflow_source,
)

# --- Eventarc ---

eventarc_trigger = gcp.eventarc.Trigger(
    "bmt-gcs-trigger",
    name="bmt-gcs-trigger",
    location=cfg.cloud_run_region,
    project=cfg.gcp_project,
    matching_criterias=[
        gcp.eventarc.TriggerMatchingCriteriaArgs(
            attribute="type",
            value="google.cloud.storage.object.v1.finalized",
        ),
        gcp.eventarc.TriggerMatchingCriteriaArgs(
            attribute="bucket",
            value=cfg.gcs_bucket,
        ),
    ],
    destination=gcp.eventarc.TriggerDestinationArgs(
        workflow=bmt_workflow.id,
    ),
    service_account=workflow_sa.email,
)

# --- IAM: Job Runner SA ---

# Read access to bucket (config, triggers, datasets)
gcp.storage.BucketIAMMember(
    "job-runner-bucket-reader",
    bucket=cfg.gcs_bucket,
    role="roles/storage.objectViewer",
    member=pulumi.Output.concat("serviceAccount:", job_runner_sa.email),
)

# Write access to bucket (summaries, results, acks)
gcp.storage.BucketIAMMember(
    "job-runner-bucket-writer",
    bucket=cfg.gcs_bucket,
    role="roles/storage.objectCreator",
    member=pulumi.Output.concat("serviceAccount:", job_runner_sa.email),
)

# --- IAM: Workflow SA ---

# Invoke Cloud Run Jobs
gcp.cloudrunv2.JobIamMember(
    "workflow-invokes-standard-job",
    name=cloud_run_job_standard.name,
    location=cfg.cloud_run_region,
    project=cfg.gcp_project,
    role="roles/run.invoker",
    member=pulumi.Output.concat("serviceAccount:", workflow_sa.email),
)

gcp.cloudrunv2.JobIamMember(
    "workflow-invokes-heavy-job",
    name=cloud_run_job_heavy.name,
    location=cfg.cloud_run_region,
    project=cfg.gcp_project,
    role="roles/run.invoker",
    member=pulumi.Output.concat("serviceAccount:", workflow_sa.email),
)

# Read trigger files from bucket
gcp.storage.BucketIAMMember(
    "workflow-sa-bucket-reader",
    bucket=cfg.gcs_bucket,
    role="roles/storage.objectViewer",
    member=pulumi.Output.concat("serviceAccount:", workflow_sa.email),
)

# Receive Eventarc events
gcp.projects.IAMMember(
    "workflow-sa-eventarc-receiver",
    project=cfg.gcp_project,
    role="roles/eventarc.eventReceiver",
    member=pulumi.Output.concat("serviceAccount:", workflow_sa.email),
)

# Workflow logging
gcp.projects.IAMMember(
    "workflow-sa-log-writer",
    project=cfg.gcp_project,
    role="roles/logging.logWriter",
    member=pulumi.Output.concat("serviceAccount:", workflow_sa.email),
)
```

**Step 2: Add new Pulumi exports**

Append to the existing exports section at the end of `__main__.py`:

```python
# Cloud Run exports
pulumi.export("artifact_registry_repo", artifact_registry.name)
pulumi.export("cloud_run_job_standard", cloud_run_job_standard.name)
pulumi.export("cloud_run_job_heavy", cloud_run_job_heavy.name)
pulumi.export("cloud_run_image_uri", cfg.cloud_run_image_uri)
pulumi.export("workflow_name", bmt_workflow.name)
pulumi.export("eventarc_trigger", eventarc_trigger.name)
pulumi.export("job_runner_sa", job_runner_sa.email)
pulumi.export("workflow_sa", workflow_sa.email)
```

**Step 3: Verify Pulumi preview**

Run: `cd infra/pulumi && pulumi preview --diff 2>&1 | head -50`
Expected: Shows new resources to create (no errors). May fail if APIs not enabled — that's expected (manual step).

---

## Batch 3: Phase 6 — Task Dispatch & FUSE Detection (Tasks 7–9)

### Task 7: Add Cloud Run task-index dispatch to main.py and entrypoint_config.py

**Files:**
- Modify: `gcp/image/entrypoint_config.py:57-64` (add `coordinator` mode + `task` mode)
- Modify: `gcp/image/main.py:17-35` (add `task` and `coordinator` dispatch)
- Test: `tests/test_entrypoint_config.py` (add test for new modes)

**Step 1: Write tests for new modes**

Create or extend `tests/test_entrypoint_config.py`:

```python
"""Tests for Cloud Run task-index dispatch and coordinator mode."""

import json
from pathlib import Path

import pytest

from gcp.image.entrypoint_config import load_entrypoint_config


def test_task_mode_loads_trigger_and_index(tmp_path: Path) -> None:
    """Task mode reads trigger object path and task index."""
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({
        "mode": "task",
        "bucket": "test-bucket",
        "trigger_object": "triggers/runs/12345.json",
        "workspace_root": str(tmp_path),
    }))
    config = load_entrypoint_config(str(config_file))
    assert config.mode == "task"
    assert config.task is not None
    assert config.task.bucket == "test-bucket"
    assert config.task.trigger_object == "triggers/runs/12345.json"
    assert config.task.task_index == 0  # default


def test_task_mode_reads_task_index_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Task mode picks up CLOUD_RUN_TASK_INDEX from env."""
    monkeypatch.setenv("CLOUD_RUN_TASK_INDEX", "3")
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({
        "mode": "task",
        "bucket": "test-bucket",
        "trigger_object": "triggers/runs/12345.json",
        "workspace_root": str(tmp_path),
    }))
    config = load_entrypoint_config(str(config_file))
    assert config.task is not None
    assert config.task.task_index == 3


def test_coordinator_mode_loads(tmp_path: Path) -> None:
    """Coordinator mode reads workflow run ID and trigger object."""
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({
        "mode": "coordinator",
        "bucket": "test-bucket",
        "workflow_run_id": "run-12345",
        "trigger_object": "triggers/runs/12345.json",
        "workspace_root": str(tmp_path),
    }))
    config = load_entrypoint_config(str(config_file))
    assert config.mode == "coordinator"
    assert config.coordinator_cfg is not None
    assert config.coordinator_cfg.workflow_run_id == "run-12345"
```

**Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/test_entrypoint_config.py -v -k "task_mode or coordinator_mode" 2>&1 | tail -5`
Expected: FAIL (AttributeError — `task` and `coordinator_cfg` don't exist yet).

**Step 3: Add TaskConfig and CoordinatorEntrypointConfig to entrypoint_config.py**

After `OrchestratorConfig` (line 54), add:

```python
@dataclass(frozen=True, slots=True)
class TaskConfig:
    """Config for Cloud Run task mode (one leg, selected by CLOUD_RUN_TASK_INDEX)."""

    bucket: str
    trigger_object: str
    workspace_root: Path
    repo_root: Path = Path(_DEFAULT_REPO_ROOT)
    task_index: int = 0
    run_context: str = "ci"
    summary_out: Path = Path("manager_summary.json")


@dataclass(frozen=True, slots=True)
class CoordinatorEntrypointConfig:
    """Config for coordinator mode (post-execution aggregation)."""

    bucket: str
    workflow_run_id: str
    trigger_object: str
    workspace_root: Path
    repo_root: Path = Path(_DEFAULT_REPO_ROOT)
```

Update `EntrypointConfig` to add the new optional fields:

```python
@dataclass(frozen=True, slots=True)
class EntrypointConfig:
    mode: str  # "watcher" | "orchestrator" | "task" | "coordinator"
    watcher: WatcherConfig | None = None
    orchestrator: OrchestratorConfig | None = None
    task: TaskConfig | None = None
    coordinator_cfg: CoordinatorEntrypointConfig | None = None
    raw: dict[str, Any] = field(default_factory=dict)
```

Add builders in `load_entrypoint_config`:

```python
    elif mode == "task":
        task = _build_task_config(raw, path)
        return EntrypointConfig(mode=mode, task=task, raw=raw)
    elif mode == "coordinator":
        coord = _build_coordinator_entrypoint_config(raw, path)
        return EntrypointConfig(mode=mode, coordinator_cfg=coord, raw=raw)
```

Add builder functions:

```python
def _build_task_config(raw: dict[str, Any], source: Path) -> TaskConfig:
    task_index_str = os.environ.get("CLOUD_RUN_TASK_INDEX", str(raw.get("task_index", 0)))
    return TaskConfig(
        bucket=_str_required(raw, "bucket", source),
        trigger_object=_str_required(raw, "trigger_object", source),
        workspace_root=Path(raw.get("workspace_root", ".")).expanduser().resolve(),
        repo_root=Path(raw.get("repo_root") or os.environ.get("BMT_REPO_ROOT", _DEFAULT_REPO_ROOT)),
        task_index=int(task_index_str),
        run_context=str(raw.get("run_context", "ci")),
        summary_out=Path(raw.get("summary_out", "manager_summary.json")),
    )


def _build_coordinator_entrypoint_config(raw: dict[str, Any], source: Path) -> CoordinatorEntrypointConfig:
    return CoordinatorEntrypointConfig(
        bucket=_str_required(raw, "bucket", source),
        workflow_run_id=_str_required(raw, "workflow_run_id", source),
        trigger_object=_str_required(raw, "trigger_object", source),
        workspace_root=Path(raw.get("workspace_root", ".")).expanduser().resolve(),
        repo_root=Path(raw.get("repo_root") or os.environ.get("BMT_REPO_ROOT", _DEFAULT_REPO_ROOT)),
    )
```

**Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/test_entrypoint_config.py -v -k "task_mode or coordinator_mode"`
Expected: 3 PASS.

**Step 5: Update main.py for new modes**

In `gcp/image/main.py`, add dispatch for `task` and `coordinator` after the orchestrator block:

```python
    if config.mode == "task":
        from gcp.image.run import run_task

        assert config.task is not None
        return run_task(config.task)

    if config.mode == "coordinator":
        from gcp.image.run import run_coordinator_entrypoint

        assert config.coordinator_cfg is not None
        return run_coordinator_entrypoint(config.coordinator_cfg)
```

**Step 6: Verify lint**

Run: `ruff check gcp/image/main.py gcp/image/entrypoint_config.py`
Expected: Clean.

---

### Task 8: Add FUSE detection to bmt_manager_base.py

**Files:**
- Modify: `gcp/image/projects/shared/bmt_manager_base.py` (add FUSE mount detection)
- Test: `tests/test_fuse_detection.py`

**Step 1: Write tests**

```python
"""Tests for FUSE mount detection in BmtManagerBase."""

from pathlib import Path
from unittest.mock import patch

from gcp.image.projects.shared.bmt_manager_base import BmtManagerBase


def test_fuse_not_mounted_when_dir_missing() -> None:
    """fuse_mounted is False when /mnt/runtime does not exist."""
    with patch.object(Path, "is_dir", return_value=False):
        assert BmtManagerBase.is_fuse_available() is False


def test_fuse_mounted_when_dir_exists() -> None:
    """fuse_mounted is True when /mnt/runtime exists."""
    with patch.object(Path, "is_dir", return_value=True):
        assert BmtManagerBase.is_fuse_available() is True


def test_fuse_inputs_root_resolves_to_mount(tmp_path: Path) -> None:
    """When FUSE is available, inputs resolve relative to mount root."""
    from gcp.image.projects.shared.bmt_manager_base import _fuse_inputs_root

    result = _fuse_inputs_root("projects/sk/inputs/false_rejects")
    assert result == Path("/mnt/runtime/projects/sk/inputs/false_rejects")
```

**Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/test_fuse_detection.py -v 2>&1 | tail -5`
Expected: FAIL (no `is_fuse_available` or `_fuse_inputs_root`).

**Step 3: Add FUSE detection to bmt_manager_base.py**

Near the top of the file (after imports, before `_gcs_client_holder`), add:

```python
from gcp.image.config.constants import FUSE_MOUNT_ROOT as _FUSE_MOUNT_ROOT_STR

_FUSE_MOUNT_ROOT = Path(_FUSE_MOUNT_ROOT_STR)


def _fuse_inputs_root(inputs_prefix: str) -> Path:
    """Resolve an inputs prefix to a path under the FUSE mount."""
    return _FUSE_MOUNT_ROOT / inputs_prefix.strip("/")
```

Add a static method to `BmtManagerBase`:

```python
    @staticmethod
    def is_fuse_available() -> bool:
        """True if GCS FUSE mount is present (Cloud Run with volume mount)."""
        return _FUSE_MOUNT_ROOT.is_dir()
```

**Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/test_fuse_detection.py -v`
Expected: 3 PASS.

---

### Task 9: Add summary artifact write function to coordinator.py

**Files:**
- Modify: `gcp/image/coordinator.py` (add `write_leg_summary` and `read_leg_summaries`)
- Modify: `gcp/image/config/constants.py` (already done in Task 3)
- Test: `tests/test_coordinator_summaries.py`

**Step 1: Write tests**

```python
"""Tests for coordinator summary artifact read/write."""

import json
from pathlib import Path

from gcp.image.coordinator import summary_artifact_path


def test_summary_artifact_path_format() -> None:
    """Summary path follows triggers/summaries/<wf_id>/<project>-<bmt_id>.json convention."""
    result = summary_artifact_path("wf-123", "sk", "4a5b6e82")
    assert result == "triggers/summaries/wf-123/sk-4a5b6e82.json"


def test_summary_artifact_path_strips_whitespace() -> None:
    result = summary_artifact_path(" wf-123 ", " sk ", " abc ")
    assert result == "triggers/summaries/wf-123/sk-abc.json"
```

**Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/test_coordinator_summaries.py -v 2>&1 | tail -5`
Expected: FAIL (no `summary_artifact_path`).

**Step 3: Add summary artifact functions to coordinator.py**

Add at the end of `coordinator.py`:

```python
# ---------------------------------------------------------------------------
# Summary artifact contract (Cloud Run task → coordinator)
# ---------------------------------------------------------------------------


def summary_artifact_path(workflow_run_id: str, project: str, bmt_id: str) -> str:
    """Build the GCS object path for a leg's summary artifact.

    Convention: triggers/summaries/<workflow_run_id>/<project>-<bmt_id>.json
    """
    from gcp.image.config.constants import TRIGGER_SUMMARIES_PREFIX

    wf = workflow_run_id.strip()
    proj = project.strip()
    bid = bmt_id.strip()
    return f"{TRIGGER_SUMMARIES_PREFIX}/{wf}/{proj}-{bid}.json"
```

**Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/test_coordinator_summaries.py -v`
Expected: 2 PASS.

**Step 5: Run full test suite**

Run: `uv run python -m pytest tests/ -v -k "not bootstrap and not handshake and not wait" --timeout=60 2>&1 | tail -20`
Expected: All existing tests plus new tests pass.

**Step 6: Run lint and type check**

Run: `ruff check . && basedpyright 2>&1 | grep -E "error|0 errors"`
Expected: Clean (0 errors from basedpyright; ruff clean).

---

## Batch 4: Verification & Manual Operations Guide (Task 10)

### Task 10: Update bmt.tfvars.json and verify end-to-end

**Files:**
- Modify: `infra/pulumi/bmt.tfvars.json` (add Cloud Run config for real project)

**Step 1: Add Cloud Run fields to real config**

Add to `infra/pulumi/bmt.tfvars.json`:

```json
{
  "gcp_project": "train-kws-202311",
  "gcp_zone": "europe-west4-a",
  "gcs_bucket": "train-kws-202311-bmt-gate",
  "service_account": "bmt-runner-sa@train-kws-202311.iam.gserviceaccount.com",
  "startup_wrapper_script_path": "../../.github/bmt/ci/resources/startup_entrypoint.sh",
  "cloud_run_region": "europe-west4",
  "cloud_run_job_sa_name": "bmt-job-runner",
  "cloud_run_workflow_sa_name": "bmt-workflow-sa",
  "artifact_registry_repo": "bmt-images",
  "github_repo_owner": "klugman-yanai",
  "github_repo_name": "bmt-gcloud"
}
```

**Step 2: Build Docker image locally**

Run: `just docker-build 2>&1 | tail -5`
Expected: `Successfully tagged bmt-orchestrator:latest` (or equivalent).

**Step 3: Verify image layout matches repo**

Run: `docker run --rm --entrypoint ls bmt-orchestrator:latest -la /opt/bmt/gcp/image/main.py`
Expected: Shows the file exists.

Run: `docker run --rm --entrypoint python bmt-orchestrator:latest -c "from gcp.image.config.constants import FUSE_MOUNT_ROOT; print(FUSE_MOUNT_ROOT)"`
Expected: `/mnt/runtime`

**Step 4: Run all tests**

Run: `uv run python -m pytest tests/ -v -k "not bootstrap and not handshake and not wait" --timeout=60`
Expected: All pass.

**Step 5: Run lint + typecheck**

Run: `ruff check . && ruff format --check . && basedpyright`
Expected: Clean.

---

## Manual GCP Operations (for the user)

After all code tasks are complete, these operations must be done via `gcloud` CLI before `pulumi up` can succeed:

### Pre-requisite: Enable APIs

```bash
gcloud services enable \
  run.googleapis.com \
  workflows.googleapis.com \
  eventarc.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  --project=train-kws-202311
```

### Pre-requisite: Authenticate Docker

```bash
gcloud auth configure-docker europe-west4-docker.pkg.dev
```

### Pre-requisite: Push initial image

Cloud Run Job definition requires an image reference. Push before `pulumi up`:

```bash
just docker-build
just docker-push
```

### Pre-requisite: Eventarc service agent permissions

```bash
PROJECT_NUMBER=$(gcloud projects describe train-kws-202311 --format="value(projectNumber)")

gcloud projects add-iam-policy-binding train-kws-202311 \
  --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-eventarc.iam.gserviceaccount.com" \
  --role="roles/workflows.invoker"

gcloud projects add-iam-policy-binding train-kws-202311 \
  --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-eventarc.iam.gserviceaccount.com" \
  --role="roles/pubsub.subscriber"
```

### Optional: Create GitHub App secrets in Secret Manager

Only needed if not already using VM metadata for these:

```bash
echo -n "YOUR_APP_ID" | gcloud secrets create bmt-github-app-id \
  --data-file=- --project=train-kws-202311

echo -n "YOUR_PRIVATE_KEY" | gcloud secrets create bmt-github-app-private-key \
  --data-file=- --project=train-kws-202311

echo -n "YOUR_INSTALLATION_ID" | gcloud secrets create bmt-github-app-installation-id \
  --data-file=- --project=train-kws-202311
```

### Deploy: Pulumi up

```bash
cd infra/pulumi && pulumi up
```

### Post-deploy verification

```bash
# Verify resources
gcloud artifacts repositories describe bmt-images --location=europe-west4 --project=train-kws-202311
gcloud run jobs describe bmt-orchestrator-standard --region=europe-west4 --project=train-kws-202311
gcloud run jobs describe bmt-orchestrator-heavy --region=europe-west4 --project=train-kws-202311
gcloud workflows describe bmt-trigger-workflow --location=europe-west4 --project=train-kws-202311
gcloud eventarc triggers describe bmt-gcs-trigger --location=europe-west4 --project=train-kws-202311

# Smoke test: write a dummy trigger (Workflow should start and skip — no valid legs)
echo '{"workflow_run_id":"test-1","legs":[]}' | \
  gcloud storage cp - gs://train-kws-202311-bmt-gate/triggers/runs/test-smoke.json

# Check Workflow execution
gcloud workflows executions list bmt-trigger-workflow --location=europe-west4 --limit=5
```
