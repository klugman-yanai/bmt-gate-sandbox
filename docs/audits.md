# Audits

Reference audits for Terraform outputs, BMT config fields, and results prefix layout.

---

## Terraform outputs

**Date:** 2025-03-11  
**Scope:** `infra/terraform/outputs.tf`, Terraform's role vs VM/Pub/Sub usage.

**Is Terraform still needed?**

**Yes.** Terraform provisions:

1. **Compute** — `google_compute_instance.bmt_vm`: VM name, zone, image, disk, network, service account, metadata (GCS_BUCKET, BMT_REPO_ROOT, GCP_PROJECT, BMT_PUBSUB_SUBSCRIPTION, startup-script, etc.), labels. The workflow starts this VM; it does not create it.

2. **Pub/Sub** — The VM relies on `google-cloud-pubsub`. Terraform creates:
   - `google_pubsub_topic.bmt_triggers` — CI publishes run triggers here (`BMT_PUBSUB_TOPIC`).
   - `google_pubsub_topic.bmt_triggers_dlq` — dead-letter topic.
   - `google_pubsub_subscription.bmt_vm` — VM subscribes here (`BMT_PUBSUB_SUBSCRIPTION`); when set, the watcher uses Pub/Sub instead of polling GCS.
   - IAM: VM SA as `roles/pubsub.subscriber`, CI SA as `roles/pubsub.publisher` on the topic, Pub/Sub SA as publisher on DLQ.

Without Terraform you would have no VM and no topic/subscription/IAM.

**outputs.tf audit**

Used by repo-vars export (`tools/terraform_repo_vars.py`). `TERRAFORM_OUTPUT_TO_VAR` in `tools/repo_vars_contract.py` maps these Terraform output names to GitHub vars:

| Output | GitHub variable |
| --- | --- |
| `gcs_bucket` | GCS_BUCKET |
| `gcp_project` | GCP_PROJECT |
| `gcp_zone` | GCP_ZONE |
| `bmt_vm_name` | BMT_LIVE_VM |
| `service_account` | GCP_SA_EMAIL |

**YAGNI:** Subscription, topic, repo root, and VM pool are **derived in code** (or constants); they are not exported as repo variables. Terraform still has outputs for VM metadata and internal use; only the five vars above are pushed to GitHub.

---

## BMT config fields

**Criterion:** Config = value can differ per repo/environment or must match an external system. Constant = fixed product behavior. Unnecessary = dead or redundant.

**Infra / runtime fields — necessary**

All used and deployment-specific: `gcs_bucket`, `gcp_project`, `gcp_zone`, `gcp_sa_email`, `bmt_vm_name`, `gcp_wif_provider`. Topic/subscription/repo_root are derived or constant in code (BmtConfig.effective_pubsub_subscription, constants.PUBSUB_TOPIC_NAME, effective_repo_root).

**Behavioral fields — audit**

- **bmt_status_context** — In code only (constants.STATUS_CONTEXT). Not in Terraform or env.
- **bmt_handshake_timeout_sec** — Default in BmtConfig only. Not in Terraform or env.
- **bmt_trigger_stale_sec** — In BmtConfig; could be constant (900) if desired.
- **bmt_vm_start_timeout_sec** — Dead (no code reads from config). Remove from BmtConfig or use constant in `vm.py`.
- **bmt_idle_timeout_sec** — Dead (vm_watcher uses `_env_int`, not config). Remove from BmtConfig or use constant.

**Summary**

| Field | Action |
| --- | --- |
| All infra/runtime | Keep. |
| **bmt_status_context** | Code only. |
| **bmt_handshake_timeout_sec** | BmtConfig only. |
| **bmt_trigger_stale_sec** | BmtConfig; optional constant. |
| **bmt_vm_start_timeout_sec** | Remove from BmtConfig or wire via `_RUNTIME_KEYS`. |
| **bmt_idle_timeout_sec** | Remove from BmtConfig or use constant in vm_watcher. |

---

## Results prefixes

**Layout**

- **Runtime root:** `gs://<bucket>/runtime`
- **Results for (project, bmt_id):** `gs://<bucket>/runtime/<results_prefix>/current.json` and `.../snapshots/<run_id>/...`
- **results_prefix** is the path segment *under* the runtime root (e.g. `sk/results/false_rejects`); it does *not* include `runtime/`.

**Source of truth**

- **Config:** `gcp/image/bmt_projects.json` → project's `jobs_config` (e.g. `projects/sk/bmt_jobs.json`) → `bmts.<bmt_id>.paths.results_prefix`
- **Resolver:** `tools/results_prefix.resolve_results_prefix(config_root, project, bmt_id)` reads config and returns the prefix, or falls back to `{project}/results/{bmt_id}` if missing.

**Current config**

- **sk (false_reject_namuh):** `paths.results_prefix` = `sk/results/false_rejects` in `gcp/image/projects/sk/bmt_jobs.json`. BMT id is the UUID `4a5b6e82-a048-5c96-8734-2f64d2288378` (see `tools/repo/sk_bmt_ids.py`); path segment is `false_rejects` by design.

**Verdict**

- **Prefix values are correct.** `tools/remote/bucket_validate_contract.py` derives the prefix via `resolve_results_prefix(config_root, "sk", SK_BMT_FALSE_REJECT_NAMUH)`.
