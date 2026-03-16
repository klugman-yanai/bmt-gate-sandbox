# Infrastructure

Pulumi is source of truth for non-secret config. GitHub repo vars come from **`infra/pulumi/bmt.tfvars.json`** via `just pulumi`. Packer builds the VM image; Pulumi creates the VM from that image.

## Order

1. **Config** — Copy `infra/pulumi/bmt.tfvars.example.json` → `bmt.tfvars.json`, set `gcp_project`, `gcp_zone`, `gcs_bucket`, `service_account`. Optional: add a `github_vars` block with `GCP_WIF_PROVIDER` and `BMT_DISPATCH_APP_ID` so `just pulumi` syncs them to GitHub; otherwise set those two in GitHub Variables by hand. See [pulumi/README.md](pulumi/README.md) if present.
2. **Image** — Build first (Packer or `just build`). See [packer/README.md](packer/README.md).
3. **Apply** — `just pulumi` (login, stack select, up, export vars to GitHub).
4. **Secrets** — Set `GCP_WIF_PROVIDER`, `BMT_DISPATCH_APP_ID`, `BMT_DISPATCH_APP_PRIVATE_KEY` in GitHub. VM-side App credentials in GCP Secret Manager.

## Secrets (GitHub)

| Name | Type | Purpose |
|------|------|---------|
| `GCP_WIF_PROVIDER` | Variable | WIF for CI |
| `BMT_DISPATCH_APP_ID` | Variable | App ID for workflow_dispatch |
| `BMT_DISPATCH_APP_PRIVATE_KEY` | Secret | App private key (PEM) |

## Safeguards

- `just pulumi` runs preflight then up; no drift. Boot image updates replace the VM by design.

## Bootstrap (new repo)

Copy `bmt.tfvars.example.json` → `bmt.tfvars.json`, set the four required keys, run `just pulumi`, set secrets.

## Troubleshooting

- **409 (topic exists):** Topics exist in GCP but not in Pulumi state. Use Pulumi import, e.g. `pulumi import 'gcp:pubsub/topic:Topic' bmt-triggers projects/<project>/topics/bmt-triggers` from `infra/pulumi`, then `just pulumi` again.
- **State lock:** If Pulumi reports a state lock (e.g. after an interrupted run), ensure no other Pulumi run is active. For GCS backend, locks are managed by Pulumi; retry after the lock TTL or clear the lock in the bucket if safe.
- **No Pulumi.yaml found:** Run Pulumi commands from repo root with `--cwd infra/pulumi` or from the `infra/pulumi` directory (e.g. in CI, `working-directory: infra/pulumi`).
