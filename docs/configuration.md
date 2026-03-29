# Configuration

**Purpose:** **Reference** for environment variables and where they are defined. **Infra apply, secrets, Pulumi:** [infrastructure.md](infrastructure.md).

## Single source of truth

- **Non-secret infra + repo variables:** `infra/pulumi/bmt.config.json` → Pulumi → **`just workspace pulumi`** syncs GitHub repo variables.
- **Secrets:** GitHub repo secrets + GCP Secret Manager — lists in [infrastructure.md](infrastructure.md).

## Local tooling

Typical commands need:

- `GCS_BUCKET`, `GCP_PROJECT`, `CLOUD_RUN_REGION`

Optional:

- `GCP_ZONE` — image / compute tooling

Inspect what the repo expects:

```bash
just tools repo show-env
```

GitHub Actions runner labels and composite pins: [.github/README.md](../.github/README.md).

---

<a id="env-inventory-appendix"></a>

## Env inventory appendix

High-level map (not exhaustive — use `show-env`, Pulumi outputs, and code search when adding vars).

| Area | Examples | Where defined |
| --- | --- | --- |
| GCP project / bucket | `GCP_PROJECT`, `GCS_BUCKET`, `GCP_ZONE`, `CLOUD_RUN_REGION` | Pulumi / `bmt.config.json` → synced repo vars |
| Cloud Run job names | `BMT_CONTROL_JOB`, `BMT_TASK_*` | Pulumi outputs → synced |
| WIF | `GCP_WIF_PROVIDER` | `bmt.config.json` → synced |
| GitHub App (Actions) | `BMT_GITHUB_APP_*` | Repo secrets |
| GitHub App (runtime) | `GITHUB_APP_*` | Secret Manager |
| Handoff / CI | Workflow `env`, `GITHUB_ENV` from setup steps | `.github/workflows/` |

**Duplication / drift sweep (optional):** `just tools doctor` — see [CONTRIBUTING.md](../CONTRIBUTING.md).
