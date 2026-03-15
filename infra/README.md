# Infrastructure

Terraform is source of truth for non-secret config. GitHub repo vars come from **`infra/terraform/bmt.tfvars.json`** via `just terraform`. Packer builds the VM image; Terraform creates the VM from that image.

## Order

1. **Config** — Copy `infra/terraform/bmt.tfvars.example.json` → `bmt.tfvars.json`, set `gcp_project`, `gcp_zone`, `gcs_bucket`, `service_account`. See [terraform/README.md](terraform/README.md).
2. **Image** — Build first (Packer or `just build`). See [packer/README.md](packer/README.md).
3. **Apply** — `just terraform` (init, plan, apply, export vars to GitHub).
4. **Secrets** — Set `GCP_WIF_PROVIDER`, `BMT_DISPATCH_APP_ID`, `BMT_DISPATCH_APP_PRIVATE_KEY` in GitHub. VM-side App credentials in GCP Secret Manager.

## Secrets (GitHub)

| Name | Type | Purpose |
|------|------|---------|
| `GCP_WIF_PROVIDER` | Variable | WIF for CI |
| `BMT_DISPATCH_APP_ID` | Variable | App ID for workflow_dispatch |
| `BMT_DISPATCH_APP_PRIVATE_KEY` | Secret | App private key (PEM) |

## Safeguards

- `just terraform` runs plan then apply; no drift. If plan would destroy/replace the VM, it exits unless `BMT_TERRAFORM_ALLOW_DESTROY=1`.
- VM has `prevent_destroy = true`.

## Bootstrap (new repo)

Copy `bmt.tfvars.example.json` → `bmt.tfvars.json`, set the four required keys, run `just terraform`, set secrets.

## Troubleshooting

- **409 (topic exists):** Topics exist in GCP but not in Terraform state. Run **`just terraform import-topics`**, then **`just terraform`**.
- **State lock:** If Terraform says "Error acquiring the state lock" (e.g. after an interrupted run), ensure no other Terraform run is active, then run `terraform force-unlock <LOCK_ID>` from `infra/terraform` using the ID from the error. Optionally back up state first: `terraform state pull > backup.json`.
