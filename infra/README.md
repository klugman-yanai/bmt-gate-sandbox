# Infrastructure (Terraform)

Terraform is the **source of truth** for all non-secret configuration. Repo variables used by CI and the BMT CLI are populated from Terraform outputs.

## Flow

1. **Define infra** in `terraform/*.tf` and variables (e.g. `terraform.tfvars` or env).
2. **Apply:** `cd infra/terraform && terraform init && terraform apply`
3. **Export repo vars:** From repo root run `just terraform-export-vars` (or `uv run python tools/terraform_repo_vars.py --apply`) to set GitHub repo variables from Terraform outputs.
4. **Set secrets manually** (see below). They are never in Terraform or the export script.

## Secrets (not in Terraform)

Set these in **GitHub repository or organization** (Settings → Secrets and variables → Actions):

| Variable / Secret       | Where to set | Purpose |
|-------------------------|--------------|---------|
| `GCP_WIF_PROVIDER`      | Variables    | Workload Identity Federation provider for CI |
| `BMT_DISPATCH_APP_ID`   | Secrets      | GitHub App ID for workflow_dispatch token |
| `BMT_DISPATCH_APP_PRIVATE_KEY` | Secrets | GitHub App private key (PEM) |

VM-side GitHub App credentials (e.g. `*_ID`, `*_INSTALLATION_ID`, `*_PRIVATE_KEY` per repo in `gcp/code/config/github_repos.json`) are also not in Terraform; configure them on the VM or via your secrets store.

## Repo vars and contract

**Contract and behavioral defaults:** [tools/repo_vars_contract.py](../tools/repo_vars_contract.py) defines required/optional/secrets and default values for non-infra vars. **Infra-derived vars:** Terraform outputs (see outputs.tf) supply GCS_BUCKET, GCP_PROJECT, GCP_ZONE, BMT_VM_NAME, BMT_REPO_ROOT, GCP_SA_EMAIL, BMT_PUBSUB_SUBSCRIPTION, BMT_PUBSUB_TOPIC. The export script (`just terraform-export-vars-apply`) reads those from Terraform and uses contract defaults for the rest. Secrets are set manually (see table above).

## Branch status context

`infra/branch-status-context.json` defines the check that ensures `BMT_STATUS_CONTEXT` matches the branch protection required status context (e.g. branch `dev` must require a context containing `bmt`). Used by `just repo-vars-check`.

## Bootstrap (new repo or new env)

1. Apply Terraform.
2. Run `just terraform-export-vars` (or `uv run python tools/terraform_repo_vars.py --apply`).
3. Set secrets (see table above).
4. Configure VM-side GitHub App credentials if the VM posts status or Check Runs.
