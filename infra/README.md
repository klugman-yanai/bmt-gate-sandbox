# Infrastructure (Terraform)

Terraform is the **source of truth** for all non-secret configuration. Repo variables used by CI and the BMT CLI are populated from Terraform outputs.

## Proper order: Packer → Terraform

Terraform **does not build** the VM image. It creates the VM from an **existing** image (family `bmt-runtime`). Build the image first, then apply Terraform.

| Step | What to do |
|------|------------|
| **1. GitHub variables** | Set `GCP_PROJECT`, `GCP_ZONE`, `GCS_BUCKET`, `GCP_SA_EMAIL` (Settings → Variables or `infra/bootstrap/bootstrap_gh_vars.sh`). |
| **2. Packer image** | **Option A (CI):** `just build` — dispatches the image-build workflow from your branch and waits. **Option B (local):** `packer init` then `packer build -var-file=infra/packer/local.pkrvars.hcl infra/packer/bmt-runtime.pkr.hcl` (copy `example.pkrvars.hcl` → `local.pkrvars.hcl`, set `gcp_project`, `gcp_zone`, `gcs_bucket`, `service_account`; use `PACKER_GITHUB_API_TOKEN="$(gh auth token)"` before init to avoid rate limits). See [infra/packer/README.md](packer/README.md). |
| **3. Terraform** | From repo root: **`just terraform`**. Init (backend from `GCS_BUCKET`), plan, apply (vars from `gh variable get`), then export outputs to GitHub. No prompts. |
| **4. Secrets** | Set `GCP_WIF_PROVIDER`, `BMT_DISPATCH_APP_ID`, `BMT_DISPATCH_APP_PRIVATE_KEY` and any VM-side GitHub App credentials (see table below). |

One-liner after the image exists: **`just terraform`**. To rebuild the image and then apply Terraform: **`just build-terraform`** (or `BMT_SKIP_IMAGE_BUILD=1 just build-terraform` if the image-build workflow is not on the default branch).

## Flow

Configuration is **fully declarative**: all values come from the repo (GitHub variables + in-repo defaults). No Terraform prompts.

1. **Set GitHub repo variables** (once per repo): `GCP_PROJECT`, `GCP_ZONE`, `GCS_BUCKET`, `GCP_SA_EMAIL`. Use GitHub Settings → Variables or `infra/bootstrap/bootstrap_gh_vars.sh` with an env file.
2. **Build the Packer image** (see table above).
3. **Apply and export:** From repo root run **`just terraform`**. This runs Terraform init (using `GCS_BUCKET` for state backend), **plan** then **apply** the plan (vars from gh), then pushes Terraform outputs to GitHub repo variables. No user input.
4. **Set secrets manually** (see below). They are never in Terraform or the export script.

## Safeguards

- **Plan before apply:** `just terraform` runs `terraform plan -out=tfplan` then `terraform apply tfplan`, so apply always matches the plan (no drift between plan and apply).
- **No accidental VM destroy:** If the plan would destroy or replace the BMT VM (`google_compute_instance.bmt_vm`), the script exits with an error unless `BMT_TERRAFORM_ALLOW_DESTROY=1` is set.
- **Terraform lifecycle:** The VM resource has `prevent_destroy = true`, so `terraform destroy` will fail unless that is removed first.

## VM lifecycle

Terraform **does not build** the Packer image. It creates the VM from an **existing** image in the project (family `bmt-runtime` or explicit `image_name`). Build the image separately via Packer or the `bmt-vm-image-build` workflow, then run `just terraform`. Blue/green is done via `create_bmt_green_vm.py` plus `cutover_bmt_vm.py` / `rollback_bmt_vm.py` (see [gcp/image/scripts/README.md](gcp/image/scripts/README.md)).

## Secrets (not in Terraform)

Set these in **GitHub repository or organization** (Settings → Secrets and variables → Actions):

| Variable / Secret       | Where to set | Purpose |
| --- | --- | --- |
| `GCP_WIF_PROVIDER`      | Variables    | Workload Identity Federation provider for CI |
| `BMT_DISPATCH_APP_ID`   | Secrets      | GitHub App ID for workflow_dispatch token |
| `BMT_DISPATCH_APP_PRIVATE_KEY` | Secrets | GitHub App private key (PEM) |

VM-side GitHub App credentials (e.g. `*_ID`, `*_INSTALLATION_ID`, `*_PRIVATE_KEY` per repo in `gcp/image/config/github_repos.json`) are also not in Terraform; configure them on the VM or via your secrets store.

## Repo vars and contract

**Contract and behavioral defaults:** [tools/repo_vars_contract.py](../tools/repo_vars_contract.py) defines required/optional/secrets and default values for non-infra vars. **Infra-derived vars:** Terraform outputs (see outputs.tf) supply GCS_BUCKET, GCP_PROJECT, GCP_ZONE, BMT_LIVE_VM, BMT_REPO_ROOT, GCP_SA_EMAIL, BMT_PUBSUB_SUBSCRIPTION, BMT_PUBSUB_TOPIC. The export script (`just terraform-export-vars-apply`) reads those from Terraform and uses contract defaults for the rest. Secrets are set manually (see table above).

## Branch status context

`infra/branch-status-context.json` defines the check that ensures `BMT_STATUS_CONTEXT` matches the branch protection required status context (e.g. branch `dev` must require a context containing `bmt`). Used by `just repo-vars-check`.

## Troubleshooting

- **Packer image:** Terraform uses whatever image exists in the project (e.g. `bmt-runtime` family). Build the image first (Packer or `bmt-vm-image-build` workflow).
- **Error 409 (Pub/Sub topic already exists):** The topics `bmt-triggers` / `bmt-triggers-dlq` exist in GCP but not in Terraform state. Import them, then run `just terraform` again (it will create the subscription and IAM):

  ```bash
  cd infra/terraform
  # Use your GCP project ID
  terraform import 'google_pubsub_topic.bmt_triggers' 'projects/YOUR_PROJECT_ID/topics/bmt-triggers'
  terraform import 'google_pubsub_topic.bmt_triggers_dlq' 'projects/YOUR_PROJECT_ID/topics/bmt-triggers-dlq'
  cd ../..
  just terraform
  ```

## Bootstrap (new repo or new env)

1. Set GitHub repo variables: `GCP_PROJECT`, `GCP_ZONE`, `GCS_BUCKET`, `GCP_SA_EMAIL` (e.g. via `infra/bootstrap/bootstrap_gh_vars.sh`).
2. Run **`just terraform`** (init + apply from gh vars, then export outputs to GitHub). No prompts.
3. Set secrets (see table above).
4. Configure VM-side GitHub App credentials if the VM posts status or Check Runs.
