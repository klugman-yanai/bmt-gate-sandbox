# BMT runtime image (Packer)

Build the BMT VM image with Packer. CI uses [bmt-image-build.yml](../../.github/workflows/bmt-image-build.yml).

## Local init/build

To avoid GitHub API rate limits when downloading the `googlecompute` plugin, set a token before `packer init`:

```bash
# Use GitHub CLI token (or any PAT with public read)
export PACKER_GITHUB_API_TOKEN="$(gh auth token)"
packer init infra/packer/bmt-runtime.pkr.hcl
packer build -var-file=infra/packer/example.pkrvars.hcl infra/packer/bmt-runtime.pkr.hcl
```

Without `PACKER_GITHUB_API_TOKEN`, unauthenticated requests are limited to 60/hour; init may fail with 403 rate limit errors. CI sets `PACKER_GITHUB_API_TOKEN` from `github.token`.

## Variables

See [example.pkrvars.hcl](example.pkrvars.hcl). Copy to `local.pkrvars.hcl` and set `gcp_project`, `gcp_zone`, `gcs_bucket`, and optionally `service_account`.
