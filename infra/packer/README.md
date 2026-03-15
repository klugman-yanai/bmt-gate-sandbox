# Packer (BMT runtime image)

CI: [bmt-vm-image-build.yml](../../.github/workflows/ops/bmt-vm-image-build.yml). Local: copy [example.pkrvars.hcl](example.pkrvars.hcl) → `local.pkrvars.hcl`, set `gcp_project`, `gcp_zone`, `gcs_bucket`, then:

```bash
export PACKER_GITHUB_API_TOKEN="$(gh auth token)"
packer init infra/packer/bmt-runtime.pkr.hcl
packer build -var-file=infra/packer/local.pkrvars.hcl infra/packer/bmt-runtime.pkr.hcl
```

Validate only (no GCP): `just packer-validate` or `packer validate -var 'gcp_project=dry-run' -var 'gcp_zone=europe-west4-a' -var 'gcs_bucket=dry-run' infra/packer/bmt-runtime.pkr.hcl`.
