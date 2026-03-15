# Terraform

Apply from repo root: **`just terraform`**. Runs preflight first (config, gcloud, bucket, image family, gh), then init+apply, then export vars to GitHub.

**Required in bmt.tfvars.json:** `gcp_project`, `gcp_zone`, `gcs_bucket`, `service_account`. **Optional:** `bmt_vm_name` (default `bmt-gate-blue`). Copy from `bmt.tfvars.example.json`.

Exported to GitHub: `GCS_BUCKET`, `GCP_PROJECT`, `GCP_SA_EMAIL`, `BMT_LIVE_VM`. Zone is not exported; fixed in code at runtime.
