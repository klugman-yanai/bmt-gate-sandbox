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
| `bmt_repo_root` | BMT_REPO_ROOT |
| `service_account` | GCP_SA_EMAIL |
| `pubsub_subscription` | BMT_PUBSUB_SUBSCRIPTION |
| `pubsub_topic` | BMT_PUBSUB_TOPIC |

`BMT_STATUS_CONTEXT` and `BMT_HANDSHAKE_TIMEOUT_SEC` are required repo vars but **not** read from Terraform; they come from contract defaults.

**Outputs not used by export:** `vm_name` (redundant with `bmt_vm_name`), `bmt_status_context`, `bmt_handshake_timeout_sec`, `bmt_trigger_stale_sec`, `vm_self_link`, `resolved_image`, `image_family`. Optional cleanups: remove `vm_name`; consider removing or documenting the three behavioral outputs so it's clear export uses contract defaults, not Terraform.

---

## BMT config fields

**Criterion:** Config = value can differ per repo/environment or must match an external system. Constant = fixed product behavior. Unnecessary = dead or redundant.

**Infra / runtime fields — necessary**

All used and deployment-specific: `gcs_bucket`, `gcp_project`, `gcp_zone`, `gcp_sa_email`, `bmt_vm_name`, `bmt_repo_root`, `gcp_wif_provider`, `bmt_pubsub_topic`, `bmt_pubsub_subscription`.

**Behavioral fields — audit**

- **bmt_status_context** — Necessary. Must match GitHub branch protection status check name. Add `BMT_STATUS_CONTEXT` to `_RUNTIME_KEYS` in `gcp/image/lib/bmt_config.py` so repo/Terraform value is used.
- **bmt_handshake_timeout_sec** — Necessary. Add `BMT_HANDSHAKE_TIMEOUT_SEC` to `_RUNTIME_KEYS` so it is configurable.
- **bmt_trigger_stale_sec** — Could be constant (single use, 900). Optional: move to constant `TRIGGER_STALE_SEC = 900` and remove from BmtConfig.
- **bmt_vm_start_timeout_sec** — Dead (no code reads from config). Remove from BmtConfig or use constant in `vm.py`.
- **bmt_idle_timeout_sec** — Dead (vm_watcher uses `_env_int`, not config). Remove from BmtConfig or use constant.

**Summary**

| Field | Action |
| --- | --- |
| All infra/runtime | Keep. |
| **bmt_status_context** | Keep; add to `_RUNTIME_KEYS`. |
| **bmt_handshake_timeout_sec** | Keep; add to `_RUNTIME_KEYS`. |
| **bmt_trigger_stale_sec** | Optional: constant and remove from config. |
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
