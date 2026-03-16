# Eventarc + Workflow + Cloud Run Job Pipeline — Remediation Plan

**Date:** 2026-03-16  
**Context:** GCS object finalize → Eventarc → Workflows → Cloud Run Job pipeline failing in two ways  
**Project:** train-kws-202311, region: europe-west4

---

## 1. Root-Cause Analysis (Ranked by Likelihood)

### Problem A: Eventarc Not Invoking Workflow on GCS Object Finalize

| Rank | Hypothesis | Evidence / Rationale |
|------|------------|------------------------|
| **1** | **Missing `roles/workflows.invoker` on trigger service account** | [Official Workflows roles-permissions](https://cloud.google.com/eventarc/standard/docs/workflows/roles-permissions) states: *"Grant the Workflows Invoker role on the project to the service account associated with your Eventarc trigger so that it can initiate your workflow execution."* Pulumi grants `eventarc.eventReceiver` but **not** `workflows.invoker`. The trigger SA (`bmt-workflow-sa`) is the identity Eventarc uses when invoking the workflow. Without it, Eventarc cannot create workflow executions. |
| **2** | **Missing `roles/pubsub.publisher` on Cloud Storage service agent** | GCS events flow via [Pub/Sub notifications](https://cloud.google.com/eventarc/standard/docs/workflows/route-trigger-cloud-storage). The GCS service agent must publish to the topic Eventarc creates. [Eventarc docs](https://cloud.google.com/eventarc/docs/roles-permissions): *"If you are creating a trigger for direct events from Cloud Storage, grant the Pub/Sub Publisher role on the project to the Cloud Storage service agent."* |
| **3** | **Bucket/trigger region mismatch** | Eventarc GCS triggers require the trigger location to match the bucket region. Bucket `train-kws-202311-bmt-gate` must be in `europe-west4` (or a compatible multi-region). |
| **4** | **Bucket notification limit exhausted** | GCS allows up to 10 notification configs per bucket. If other triggers/notifications exist, Eventarc may fail to register. |
| **5** | **Event payload > 512 KB** | Workflows reject events larger than 512 KB. Trigger JSON files are typically small; low likelihood. |

### Problem B: Workflow Cannot Run Cloud Run Job with Overrides (403)

| Rank | Hypothesis | Evidence / Rationale |
|------|------------|------------------------|
| **1** | **`roles/run.invoker` does NOT include `run.jobs.runWithOverrides`** | [IAM roles reference](https://cloud.google.com/iam/docs/roles-permissions/run): `run.invoker` grants `run.jobs.run` only. The Workflow calls `googleapis.run.v1.namespaces.jobs.run` with `body.overrides` (taskCount, containerOverrides), which requires `run.jobs.runWithOverrides`. |
| **2** | **Wrong role granted** | Pulumi grants `roles/run.invoker` on the job. Correct role for overrides is `roles/run.jobsExecutorWithOverrides` (least-privilege) or `roles/run.developer` (broader). |

---

## 2. Exact Least-Privilege IAM Roles

| Principal | Role | Resource Scope | Purpose |
|-----------|------|----------------|----------|
| **bmt-workflow-sa** | `roles/workflows.invoker` | Project | Eventarc trigger SA must create workflow executions |
| **bmt-workflow-sa** | `roles/eventarc.eventReceiver` | Project | Receive events from Eventarc (already present) |
| **bmt-workflow-sa** | `roles/run.jobsExecutorWithOverrides` | Job `bmt-orchestrator-standard` | Execute job with taskCount/containerOverrides |
| **bmt-workflow-sa** | `roles/run.jobsExecutorWithOverrides` | Job `bmt-orchestrator-heavy` | Same for heavy job |
| **bmt-workflow-sa** | `roles/storage.objectViewer` | Bucket | Read trigger and summaries (already present) |
| **bmt-workflow-sa** | `roles/logging.logWriter` | Project | Workflow logs (already present) |
| **GCS service agent** | `roles/pubsub.publisher` | Project | Publish GCS events to Pub/Sub topic |
| **Eventarc service agent** | `roles/workflows.invoker` | Project | (Optional) Some implementations use this; design doc recommends it |
| **Eventarc service agent** | `roles/pubsub.subscriber` | Project | (Optional) Internal Eventarc Pub/Sub usage |

**GCS service agent format:** `service-PROJECT_NUMBER@gs-project-accounts.iam.gserviceaccount.com`  
**Eventarc service agent:** `service-PROJECT_NUMBER@gcp-sa-eventarc.iam.gserviceaccount.com`

---

## 3. `googleapis.run.v1.namespaces.jobs.run` + `body.overrides`

**Yes, it requires a role beyond `run.invoker`.**

| Permission | `run.invoker` | `run.jobsExecutorWithOverrides` | `run.developer` |
|------------|---------------|--------------------------------|-----------------|
| `run.jobs.run` | ✅ | ✅ | ✅ |
| `run.jobs.runWithOverrides` | ❌ | ✅ | ✅ |

**Correct role:** `roles/run.jobsExecutorWithOverrides` on the job (least-privilege).

**Why:** The Workflow passes `body.overrides` (taskCount, containerOverrides with env vars). That path uses the Jobs Run API with overrides, which requires `run.jobs.runWithOverrides`. `run.invoker` only allows `run.jobs.run` (no overrides).

---

## 4. Eventarc Trigger Filtering Strategy

### Current Setup
- **Eventarc filters:** `type=google.cloud.storage.object.v1.finalized`, `bucket=train-kws-202311-bmt-gate`
- **Workflow guard:** Regex `^triggers/runs/.*\.json$` in `check_prefix` step

### Recommendation

| Aspect | Recommendation | Rationale |
|--------|----------------|-----------|
| **Bucket filter** | Keep | Required; Eventarc only supports `type` and `bucket` for GCS. |
| **Path filter in Eventarc** | Not available | Eventarc Standard for GCS does **not** support object path/prefix filters. |
| **Path filter location** | Workflow (`check_prefix`) | **Correct.** Filter in the workflow as you do. Fail fast: `skip_non_trigger` returns immediately. |
| **Tradeoff** | Event fires for every finalized object; workflow filters | Slightly more workflow executions (all skipped for non-triggers), but no wasted job runs. |

**Reliable behavior:** Keep bucket + type in Eventarc; path filter in workflow. This is the standard pattern per [Eventarc GCS docs](https://cloud.google.com/eventarc/standard/docs/workflows/route-trigger-cloud-storage).

---

## 5. Verification Playbook

### 5.1 IAM Checks

```bash
PROJECT="train-kws-202311"
REGION="europe-west4"
PROJECT_NUMBER=$(gcloud projects describe $PROJECT --format='value(projectNumber)')
WORKFLOW_SA="bmt-workflow-sa@${PROJECT}.iam.gserviceaccount.com"
GCS_SA="service-${PROJECT_NUMBER}@gs-project-accounts.iam.gserviceaccount.com"
EVENTARC_SA="service-${PROJECT_NUMBER}@gcp-sa-eventarc.iam.gserviceaccount.com"

# Workflow SA: workflows.invoker
gcloud projects get-iam-policy $PROJECT --flatten="bindings[].members" \
  --filter="bindings.members:serviceAccount:${WORKFLOW_SA}" --format="table(bindings.role)"

# Workflow SA: run.jobsExecutorWithOverrides on job
gcloud run jobs get-iam-policy bmt-orchestrator-standard --region=$REGION --project=$PROJECT \
  --flatten="bindings[].members" --filter="bindings.members:serviceAccount:${WORKFLOW_SA}" \
  --format="table(bindings.role)"

# GCS service agent: pubsub.publisher
gcloud projects get-iam-policy $PROJECT --flatten="bindings[].members" \
  --filter="bindings.members:serviceAccount:${GCS_SA}" --format="table(bindings.role)"

# Eventarc service agent (optional)
gcloud projects get-iam-policy $PROJECT --flatten="bindings[].members" \
  --filter="bindings.members:serviceAccount:${EVENTARC_SA}" --format="table(bindings.role)"
```

### 5.2 Eventarc Health Checks

```bash
# Describe trigger
gcloud eventarc triggers describe bmt-gcs-trigger --location=$REGION --project=$PROJECT

# Get trigger's Pub/Sub topic and subscription
gcloud eventarc triggers describe bmt-gcs-trigger --location=$REGION --project=$PROJECT \
  --format="table(transport.pubsub.topic, subscription)"
```

### 5.3 GCS Bucket Notifications

```bash
# List notifications (Eventarc creates one)
gcloud storage buckets notifications list gs://train-kws-202311-bmt-gate
```

### 5.4 Pub/Sub Delivery Diagnostics

```bash
# Get topic from trigger
TOPIC=$(gcloud eventarc triggers describe bmt-gcs-trigger --location=$REGION --project=$PROJECT \
  --format="value(transport.pubsub.topic)")

# List subscriptions on that topic
gcloud pubsub subscriptions list --filter="topic:${TOPIC}" --project=$PROJECT

# Check unacked messages (indicates delivery issues)
gcloud pubsub subscriptions get-iam-policy projects/${PROJECT}/subscriptions/$(gcloud pubsub subscriptions list --filter="topic:${TOPIC}" --project=$PROJECT --format="value(name)" | head -1)
```

### 5.5 Workflow Execution Diagnostics

```bash
# List recent executions
gcloud workflows executions list bmt-trigger-workflow --location=$REGION --project=$PROJECT --limit=10

# Describe a specific execution
gcloud workflows executions describe EXECUTION_ID --workflow=bmt-trigger-workflow --location=$REGION --project=$PROJECT --format=yaml
```

### 5.6 Cloud Run Job Execution Diagnostics

```bash
# List recent job executions
gcloud run jobs executions list --job=bmt-orchestrator-standard --region=$REGION --project=$PROJECT --limit=5

# Describe execution
gcloud run jobs executions describe EXECUTION_ID --job=bmt-orchestrator-standard --region=$REGION --project=$PROJECT
```

### 5.7 Logs (Eventarc + Workflows)

```bash
# Eventarc / Workflow invocation logs
gcloud logging read 'resource.type="cloud_workflows_workflow" resource.labels.workflow_id="bmt-trigger-workflow"' \
  --project=$PROJECT --limit=20 --format="table(timestamp,jsonPayload.message,jsonPayload.error)"

# Permission denied (workflows.executions.create)
gcloud logging read 'resource.type="cloud_workflows_workflow" "Permission.*workflows.executions.create.*denied"' \
  --project=$PROJECT --limit=10

# run.jobs.runWithOverrides denied
gcloud logging read '"run.jobs.runWithOverrides" "denied"' --project=$PROJECT --limit=10
```

### 5.8 End-to-End Canary Test

```bash
# 1. Write trigger
RUN_ID="canary-$(date +%s)"
echo '{"workflow_run_id":"'$RUN_ID'","legs":[{"project":"sk","bmt_id":"4a5b6e82-a048-5c96-8734-2f64d2288378"}]}' | \
  gcloud storage cp - gs://train-kws-202311-bmt-gate/triggers/runs/${RUN_ID}.json

# 2. Wait 30–60s
sleep 45

# 3. Check workflow executions
gcloud workflows executions list bmt-trigger-workflow --location=$REGION --project=$PROJECT --limit=5

# 4. If execution exists, check its result
EXEC_ID=$(gcloud workflows executions list bmt-trigger-workflow --location=$REGION --project=$PROJECT --limit=1 --format="value(name)")
gcloud workflows executions describe $EXEC_ID --workflow=bmt-trigger-workflow --location=$REGION --project=$PROJECT --format=yaml
```

---

## 6. Pulumi IaC Updates

Add the following to `infra/pulumi/__main__.py`:

### 6.1 Replace `run.invoker` with `run.jobsExecutorWithOverrides` on Jobs

```python
# Replace workflow-invokes-standard-job and workflow-invokes-heavy-job
# Change role from "roles/run.invoker" to "roles/run.jobsExecutorWithOverrides"
gcp.cloudrunv2.JobIamMember(
    "workflow-invokes-standard-job",
    name=cloud_run_job_standard.name,
    location=cfg.cloud_run_region,
    project=cfg.gcp_project,
    role="roles/run.jobsExecutorWithOverrides",  # was run.invoker
    member=pulumi.Output.concat("serviceAccount:", workflow_sa.email),
)

gcp.cloudrunv2.JobIamMember(
    "workflow-invokes-heavy-job",
    name=cloud_run_job_heavy.name,
    location=cfg.cloud_run_region,
    project=cfg.gcp_project,
    role="roles/run.jobsExecutorWithOverrides",  # was run.invoker
    member=pulumi.Output.concat("serviceAccount:", workflow_sa.email),
)
```

### 6.2 Add `workflows.invoker` for Trigger SA

```python
# Trigger SA must invoke workflows
gcp.projects.IAMMember(
    "workflow-sa-workflows-invoker",
    project=cfg.gcp_project,
    role="roles/workflows.invoker",
    member=pulumi.Output.concat("serviceAccount:", workflow_sa.email),
)
```

### 6.3 Add GCS Service Agent Pub/Sub Publisher

```python
# GCS service agent must publish events to Pub/Sub
gcp.projects.IAMMember(
    "gcs-sa-pubsub-publisher",
    project=cfg.gcp_project,
    role="roles/pubsub.publisher",
    member=f"serviceAccount:service-{project_info.number}@gs-project-accounts.iam.gserviceaccount.com",
)
```

### 6.4 (Optional) Eventarc Service Agent Roles

```python
# Eventarc service agent (optional; design doc recommends)
gcp.projects.IAMMember(
    "eventarc-sa-workflows-invoker",
    project=cfg.gcp_project,
    role="roles/workflows.invoker",
    member=f"serviceAccount:service-{project_info.number}@gcp-sa-eventarc.iam.gserviceaccount.com",
)

gcp.projects.IAMMember(
    "eventarc-sa-pubsub-subscriber",
    project=cfg.gcp_project,
    role="roles/pubsub.subscriber",
    member=f"serviceAccount:service-{project_info.number}@gcp-sa-eventarc.iam.gserviceaccount.com",
)
```

---

## 7. Rollback / Safety Plan

If permissions are too broad:

| Change | Rollback |
|--------|----------|
| **run.jobsExecutorWithOverrides** | Revert to `run.invoker` — jobs will run without overrides; workflow will fail. Remove overrides from workflow to use `run.invoker` only. |
| **workflows.invoker** | Remove — Eventarc will stop invoking workflows. No immediate security risk; pipeline simply stops. |
| **pubsub.publisher** (GCS SA) | Remove — GCS events will not reach Eventarc. No security risk; pipeline stops. |
| **Eventarc SA roles** | Remove — May break Eventarc if it relies on them; test with minimal bindings first. |

**Safest order:** Apply workflow SA permissions first (workflows.invoker, run.jobsExecutorWithOverrides), then GCS SA, then Eventarc SA if needed. Test after each step.

---

## Quick Reference: One-Off Remediation Commands

```bash
PROJECT="train-kws-202311"
REGION="europe-west4"
PROJECT_NUMBER=$(gcloud projects describe $PROJECT --format='value(projectNumber)')
WORKFLOW_SA="bmt-workflow-sa@${PROJECT}.iam.gserviceaccount.com"
GCS_SA="service-${PROJECT_NUMBER}@gs-project-accounts.iam.gserviceaccount.com"

# 1. Workflow SA: workflows.invoker
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:${WORKFLOW_SA}" --role="roles/workflows.invoker"

# 2. Workflow SA: run.jobsExecutorWithOverrides on jobs
gcloud run jobs add-iam-policy-binding bmt-orchestrator-standard --region=$REGION --project=$PROJECT \
  --member="serviceAccount:${WORKFLOW_SA}" --role="roles/run.jobsExecutorWithOverrides"

gcloud run jobs add-iam-policy-binding bmt-orchestrator-heavy --region=$REGION --project=$PROJECT \
  --member="serviceAccount:${WORKFLOW_SA}" --role="roles/run.jobsExecutorWithOverrides"

# 3. GCS service agent: pubsub.publisher
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:${GCS_SA}" --role="roles/pubsub.publisher"

# 4. (Optional) Eventarc service agent
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-eventarc.iam.gserviceaccount.com" \
  --role="roles/workflows.invoker"

gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-eventarc.iam.gserviceaccount.com" \
  --role="roles/pubsub.subscriber"
```
