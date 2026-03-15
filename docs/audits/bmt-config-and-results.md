# BMT config and results prefix audit

Reference: infra outputs (now Pulumi; historically Terraform), BMT config fields, results prefix layout.

---

## Infra outputs → repo vars

Repo variables are set from **Pulumi** via `just pulumi` (see [infra/README.md](../../infra/README.md)). Exported vars include: `GCS_BUCKET`, `GCP_PROJECT`, `GCP_ZONE`, `BMT_VM_NAME` (or `BMT_LIVE_VM`), `GCP_SA_EMAIL`. Subscription, topic, repo root are derived in code; only the canonical set is pushed to GitHub.

---

## BMT config fields

**Criterion:** Config = value can differ per repo/environment. Constant = fixed product behavior.

**Infra / runtime — necessary:** `gcs_bucket`, `gcp_project`, `gcp_zone`, `gcp_sa_email`, `bmt_vm_name`, `gcp_wif_provider`. Topic/subscription/repo_root are derived or constant in code.

**Behavioral:** `bmt_status_context`, `bmt_handshake_timeout_sec` — in code or BmtConfig. `bmt_trigger_stale_sec` — BmtConfig. `bmt_vm_start_timeout_sec`, `bmt_idle_timeout_sec` — remove from BmtConfig or wire via constants.

---

## Results prefixes

- **Runtime root:** `gs://<bucket>/runtime`
- **Results:** `gs://<bucket>/runtime/<results_prefix>/current.json` and `.../snapshots/<run_id>/...`
- **results_prefix** is under runtime root (e.g. `sk/results/false_rejects`). Source: project's jobs config → `bmts.<bmt_id>.paths.results_prefix`. Resolver: `tools.repo.results_prefix.resolve_results_prefix(config_root, project, bmt_id)`.
