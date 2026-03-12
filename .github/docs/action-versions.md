# Action version pins

Single source of truth for third-party action refs used in `.github/`. When adding new workflows or actions, use these pins. When upgrading, update this file and all references.

| Action | Pin (SHA) | Tag / note |
|--------|-----------|-------------|
| `actions/checkout` | `de0fac2e4500dabe0009e67214ff5f5447ce83dd` | v6 |
| `actions/upload-artifact` | `bbbca2ddaa5d8feaa63e36b76fdaad77386f024f` | v7 |
| `actions/download-artifact` | `70fc10c6e5e1ce46ad2ea6f2b72d43f7d47b13c3` | v8 |
| `actions/cache` | `cdf6c1fa76f9f475f3d7449005a359c84ca0f306` | v5 |
| `google-github-actions/auth` | `7c6bc770dae815cd3e89ee6cdf493a5fab2cc093` | v3 |
| `google-github-actions/setup-gcloud` | `aa5489c8933f4cc7a4f7d45035b3b1440c9c10db` | v3.0.1 |
| `astral-sh/setup-uv` | `65ef90775fa85bf7130e46f3f22dc79a206581c8` | v7 |
| `hashicorp/setup-packer` | `54678572a9eae3130016b4548482317e9f83f9f3` | main |
| `hashicorp/setup-terraform` | `b9cd54a3c349d3f38e8881555d616ced269862dd` | v3 |
| `sigstore/cosign-installer` | `d58896d6a1865668819e1d91763c7751a165e159` | v3.9.2 |

## Where GCP + uv are centralized

GCP auth and gcloud (and optionally uv) are centralized in **`.github/actions/setup-gcp-uv`**. Workflows that need GCP should use that action instead of pinning `google-github-actions/auth` and `google-github-actions/setup-gcloud` directly. That keeps auth/setup-uv upgrades in one place.

## Pinning format in YAML

Use the full SHA with an optional comment for the tag:

```yaml
uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd # v6
```
