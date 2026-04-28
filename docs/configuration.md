# Configuration

This repo now has one supported execution model: direct GitHub Actions handoff to Google Workflows, then Cloud Run Jobs.

**Environment variable inventory:** [below](#environment-variable-reference). Refresh commands: [Env inventory appendix](#env-inventory-appendix).

## Centralized config and repo variables

**Single config file:** `infra/pulumi/bmt.tfvars.json` is the source of truth for all non-secret infra and repo variables. You do not set `GCP_*` or `GCS_BUCKET` (or `GCP_WIF_PROVIDER`) in the GitHub UI for normal use.

**Apply infra and push repo vars:**

```bash
just pulumi
```

That command runs Pulumi and then syncs its outputs to GitHub repo variables. So:

- **User sets:** `bmt.tfvars.json` (copy from `bmt.tfvars.example.json`, set `gcp_project`, `gcp_zone`, `gcs_bucket`, `service_account`, and `gcp_wif_provider`).
- **Pulumi sets for you:** `GCS_BUCKET`, `GCP_PROJECT`, `GCP_ZONE`, `CLOUD_RUN_REGION`, `BMT_CONTROL_JOB`, `BMT_TASK_STANDARD_JOB`, `BMT_TASK_HEAVY_JOB`, `GCP_SA_EMAIL`, `GCP_WIF_PROVIDER` — all synced from config when you run `just pulumi`.

Defaults in the config file (e.g. `cloud_run_region`, job names) are used by Pulumi; you only override what you need.

## Required Manual GitHub Configuration (secrets and optional overrides)

- GitHub repo secret: `BMT_GITHUB_APP_ID`
- GitHub repo secret: `BMT_GITHUB_APP_INSTALLATION_ID`
- GitHub repo secret: `BMT_GITHUB_APP_PRIVATE_KEY`
- GitHub repo secret: `BMT_GITHUB_APP_DEV_ID`
- GitHub repo secret: `BMT_GITHUB_APP_DEV_INSTALLATION_ID`
- GitHub repo secret: `BMT_GITHUB_APP_DEV_PRIVATE_KEY`
- GCP Secret Manager secret: `GITHUB_APP_ID`
- GCP Secret Manager secret: `GITHUB_APP_INSTALLATION_ID`
- GCP Secret Manager secret: `GITHUB_APP_PRIVATE_KEY`
- GCP Secret Manager secret: `GITHUB_APP_DEV_ID`
- GCP Secret Manager secret: `GITHUB_APP_DEV_INSTALLATION_ID`
- GCP Secret Manager secret: `GITHUB_APP_DEV_PRIVATE_KEY`

`BMT_STATUS_CONTEXT` is optional. If unset, the default is `BMT Gate`.

GitHub reporting chooses the credential profile from the repository slug:

- `Kardome-org/*` uses `GITHUB_APP_*`
- all other repositories use `GITHUB_APP_DEV_*`

GitHub Actions reads the `BMT_GITHUB_APP_*` secrets from the repository. Cloud Run reads the `GITHUB_APP_*` names from GCP Secret Manager. While both the personal dev repo and the org repo are active, keep both profiles populated in Secret Manager so runtime reporting can finalize against either repository without any manual GCP secret swaps.

Use standard global Secret Manager secrets for the Cloud Run path. Regional secrets are not supported for Cloud Run secret injection.

## Local Tooling Environment

Typical local commands use:

- `GCS_BUCKET`
- `GCP_PROJECT`
- `CLOUD_RUN_REGION`

Optional local inspection helpers also use:

- `GCP_ZONE` for image-build and compute-image tooling

Print the current expected environment with:

```bash
just show-env
```

## Pulumi Config

`infra/pulumi/bmt.tfvars.json` must define:

- `gcp_project`
- `gcp_zone`
- `gcs_bucket`
- `service_account`
- `gcp_wif_provider` — Workload Identity Federation provider (GitHub Actions OIDC). Synced to `GCP_WIF_PROVIDER` by `just pulumi` like the other GCP_* vars.

Common optional fields:

- `cloud_run_region`
- `cloud_run_job_sa_name`
- `cloud_run_workflow_sa_name`
- `artifact_registry_repo`
- `github_repo_owner`
- `github_repo_name`

There is no VM name or startup-script setting in the active system.

## Config layers and consistency

Three places touch the same logical settings; they stay consistent as follows:

| Layer | Role | Source of values |
|-------|------|-------------------|
| **`infra/pulumi/config.py`** | Pulumi only. Loads `bmt.tfvars.json`, defines `InfraConfig` (gcp_project, gcs_bucket, service_account, cloud_run_region, gcp_wif_provider, etc.). | `infra/pulumi/bmt.tfvars.json` |
| **`ci/kardome_bmt/config.py`** | CI only. Builds `BmtConfig` from **env** (no file). Used when workflows run. | GitHub repo variables (and workflow env); values ultimately from Pulumi sync or manual. |
| **`runtime/config/constants.py`** | Code constants only (no loading). Defaults that must match across Pulumi and CI. | Hardcoded (e.g. `DEFAULT_CLOUD_RUN_REGION = "europe-west4"`). |

**Overlap:** The same settings (bucket, project, SA, WIF, region, job names) appear in Pulumi config (file) and CI config (env). The flow is: **bmt.tfvars.json → Pulumi → `just pulumi` syncs to GitHub vars → workflow env → CI config.** So the single source of truth for infra values is `bmt.tfvars.json`; CI reads what was synced.

**Pulumi consistency:** `infra/pulumi/config.py` uses defaults that match `runtime/config/constants.py` (e.g. `cloud_run_region = "europe-west4"` with a comment to keep it in sync). Required keys are enforced in Pulumi config; the repo-vars contract lists which vars the workflow requires (including `GCP_WIF_PROVIDER`).

**`GCP_WIF_PROVIDER`:** Required in `bmt.tfvars.json` as `gcp_wif_provider` and synced by Pulumi like the other GCP_* vars. The handoff workflow needs it for OIDC auth.

## Runtime Storage Contract

The active runtime writes:

- `triggers/plans/<workflow_run_id>.json`
- `triggers/summaries/<workflow_run_id>/<project>-<bmt_slug>.json`
- `projects/<project>/results/<bmt_slug>/snapshots/<run_id>/latest.json`
- `projects/<project>/results/<bmt_slug>/snapshots/<run_id>/ci_verdict.json`
- `projects/<project>/results/<bmt_slug>/current.json`

Published staged control-plane content lives under:

- `projects/<project>/project.json`
- `projects/<project>/bmts/<bmt_slug>/bmt.json`
- `projects/<project>/plugins/<plugin>/sha256-<digest>/...`
- `projects/<project>/inputs/<dataset>/...`

## Packages

The repo is a uv workspace with two active packages:

- `kardome-bmt` under [`ci/`](../ci) ([`ci/README.md`](../ci/README.md))
- `bmt-runtime` under [`runtime/`](../runtime)

Run a specific member with:

```bash
uv run --package kardome-bmt …
uv run --package bmt-runtime …
```

That command runs Pulumi and then syncs its outputs to GitHub repo variables. So:

## Environment variable reference

This document inventories **process environment** and closely related names used across GitHub Actions, the **`kardome-bmt`** package (`ci/kardome_bmt/`), Cloud Run runtime (`runtime/`), and local `tools/` scripts. It complements the high-level flow in [Centralized config and repo variables](#centralized-config-and-repo-variables) above.

**Secrets:** Never commit secrets. Repo **Variables** are not encrypted; use **Secrets** for tokens and keys.

**Large values:** Prefer files or step outputs (`GITHUB_OUTPUT`, `.bmt/context.json`) for big JSON blobs. Environment variables have size and escaping constraints in Actions.

## Env usage to avoid or minimize

New work should not add more of these patterns; refactors that touch them should prefer files, secrets stores, or typed resolution (see [tools/shared/github_app_settings.py](../tools/shared/github_app_settings.py) for GitHub App id/path precedence).

| Avoid or minimize | Why | Prefer instead |
| ----------------- | --- | -------------- |
| Large JSON or matrices in env | Size/escaping limits in Actions | `.bmt/context.json`, `GITHUB_OUTPUT`, artifacts |
| Secret bodies in env | Exposure in logs and dumps | GitHub Secrets, GCP Secret Manager; env holds paths/refs only |
| New parallel names for the same fact | Operator confusion | One name per layer; consolidate aliases in code (see GitHub App module) |
| New undocumented `BMT_*` for local tools | Hard to discover | Typer options with `envvar=` (e.g. `tools bucket upload-runner --help`) |
| Duplicating infra values already in `bmt.tfvars.json` | Drift vs Pulumi | `just pulumi` / repo variables |
| Constants as env | False configurability | [runtime/config/constants.py](../runtime/config/constants.py) |

## GitHub Actions precedence

When the same name appears at multiple levels:

1. Step `env` overrides job `env` overrides workflow `env`.
2. `secrets.*` injects masked values; `vars.*` is repository/org variables (non-secret); `env.*` is the computed env for the step.

Official behavior: [GitHub Docs — Workflow syntax](https://docs.github.com/en/actions/writing-workflows/workflow-syntax-for-github-actions#env).

## Where canonical names live

| Mechanism | Location |
| --------- | -------- |
| GitHub repo variables (Pulumi-synced) | [tools/repo/vars_contract.py](../tools/repo/vars_contract.py) |
| Aggregated contract (contexts) | [tools/shared/env_contract.py](../tools/shared/env_contract.py) |
| CI typed settings (`BmtConfig`) | [ci/kardome_bmt/config.py](../ci/kardome_bmt/config.py) |
| `ENV_*` string constants | [runtime/config/constants.py](../runtime/config/constants.py) |
| Infra file (not process env) | `infra/pulumi/bmt.tfvars.json` via [infra/pulumi/config.py](../infra/pulumi/config.py) |

## Infra and CI (`BmtConfig` / repo vars)

These names are synced from Pulumi to GitHub **Variables** for normal use. See [Centralized config and repo variables](#centralized-config-and-repo-variables).

| Name | Layer | Required | Notes |
| ---- | ----- | -------- | ----- |
| `GCS_BUCKET` | Repo var, CI, runtime | Yes | Bucket root mirror of `gcp/stage/` |
| `GCP_PROJECT` | Repo var, CI, runtime | Yes | |
| `GCP_ZONE` | Repo var, tooling | Yes | Image/compute helpers |
| `GCP_SA_EMAIL` | Repo var, CI | Yes | Service account email |
| `GCP_WIF_PROVIDER` | Repo var, CI | Yes | OIDC / WIF provider resource |
| `CLOUD_RUN_REGION` | Repo var, CI, runtime opt | Has default | Default `europe-west4` in code/docs |
| `BMT_CONTROL_JOB` | Repo var, local tools | Yes | Cloud Run job name |
| `BMT_TASK_STANDARD_JOB` | Repo var, local tools | Yes | |
| `BMT_TASK_HEAVY_JOB` | Repo var, local tools | Yes | |
| `BMT_STATUS_CONTEXT` | Repo var, CI, runtime (non-handoff) | Optional | Default status context (e.g. `BMT Gate`). **Reusable `bmt-handoff.yml` callers:** pass `bmt_status_context` via job `with:` (not a repo var). |
| `BMT_CLI` | Repo var, CI | Optional | `uv` (default) or `pex` — use release `bmt.pex` instead of `uv run kardome-bmt` when set to `pex` |
| `BMT_PEX_TAG` | Repo var, consumer CI | **Optional** for handoff | Prefer a **literal ref** on the reusable workflow: `uses: .../bmt-handoff.yml@bmt-handoff` (rolling) or `@bmt-v0.3.5` (pinned). Legacy: some repos still pin via `vars.BMT_PEX_TAG`; not required for new integrations. |

**Consumer `workflow_call`:** pin `uses: …/bmt-handoff.yml@bmt-handoff` (or `@bmt-v*`), set job `permissions:` as documented, and pass **`with:`** for `cloud_run_region`, `bmt_status_context`, `bmt_pex_repo`, and `force_pass` (declare values in the caller YAML — no repo vars for those). Omit other inputs when handoff runs in the same workflow as the `runner-*` upload; those resolve from the caller `github` context. **Repo vars** still required on the caller: `GCS_BUCKET`, `GCP_WIF_PROVIDER`, `GCP_SA_EMAIL`, `GCP_PROJECT`. **What `force_pass` does and does not do:** [bmt-pipeline-signal.md](bmt-pipeline-signal.md).

**Production consumer repos** typically download **`bmt.pex`** from that upstream release in a workflow step (see **`.github/actions/setup-bmt-pex`** in bmt-gcloud) instead of vendoring the full `ci/` tree for `uv run kardome-bmt`.

## Workflow handoff context (CI)

Read by `context_from_env` / `WorkflowContext` in [ci/kardome_bmt/config.py](../ci/kardome_bmt/config.py) (`_WORKFLOW_CONTEXT_ENV_KEYS`). Typical sources: workflow `env`, prior step outputs, and Actions built-ins.

| Name | Purpose (summary) |
| ---- | ------------------- |
| `ACCEPTED` | Accepted line / marker |
| `ACCEPTED_PROJECTS` | JSON array of projects |
| `AVAILABLE_ARTIFACTS` | Artifact listing |
| `BMT_RUNNERS_PRESEEDED_IN_GCS` | Runner seeding flag |
| `BMT_SKIP_PUBLISH_RUNNERS` | Skip publish |
| `DISPATCH_HEAD_SHA` | Dispatch SHA |
| `DISPATCH_PR_NUMBER` | Dispatch PR |
| `FAILURE_REASON` | Failure text |
| `FILTERED_MATRIX` | Matrix JSON |
| `GITHUB_REPOSITORY` | `owner/name` |
| `GITHUB_RUN_ID` | Workflow run id |
| `GITHUB_SERVER_URL` | Git host URL |
| `HANDSHAKE_OK` | Handshake |
| `HEAD_BRANCH` | Branch |
| `HEAD_SHA` | Commit |
| `MODE` | Mode string |
| `ORCH_HANDSHAKE_OK` | Orchestrator handshake |
| `ORCH_HAS_LEGS` | Has legs |
| `ORCH_TRIGGER_WRITTEN` | Trigger written |
| `PREPARE_HEAD_SHA` | Prepare SHA |
| `PREPARE_PR_NUMBER` | Prepare PR |
| `PREPARE_RESULT` | Prepare result |
| `PR_NUMBER` | Pull request number |
| `REPOSITORY` | Repo slug (alternate) |
| `RUNNER_MATRIX` | Runner matrix JSON |
| `TARGET_URL` | Target URL |
| `TRIGGER_WRITTEN` | Trigger written |

Additional names used by handoff / matrix code without being in `_WORKFLOW_CONTEXT_ENV_KEYS` include `GITHUB_OUTPUT`, `GITHUB_ENV`, `GITHUB_STEP_SUMMARY`, `GITHUB_TOKEN`, `FILTERED_MATRIX_JSON`, `GITHUB_SHA`, and orchestration flags such as `ORCH_*` read in [ci/kardome_bmt/handoff.py](../ci/kardome_bmt/handoff.py).

## Pipeline mapping: Actions → Cloud Run

Workflows pass run metadata into Google Workflows and then into Cloud Run. **Names differ** between the Actions step environment and the runtime container:

| Concept | Typical Actions / `bmt` env | Cloud Run runtime env |
| ------- | --------------------------- | ---------------------- |
| Commit SHA | `HEAD_SHA` | `BMT_HEAD_SHA` |
| Branch | `HEAD_BRANCH` | `BMT_HEAD_BRANCH` |
| Event | `HEAD_EVENT` | `BMT_HEAD_EVENT` |
| PR number | `PR_NUMBER` | `BMT_PR_NUMBER` |
| Run context | `RUN_CONTEXT` | `BMT_RUN_CONTEXT` |
| Accepted projects JSON | (in workflow argument) | `BMT_ACCEPTED_PROJECTS_JSON` |

`GITHUB_REPOSITORY` is shared. See [ci/kardome_bmt/workflow_dispatch.py](../ci/kardome_bmt/workflow_dispatch.py) and [runtime/entrypoint.py](../runtime/entrypoint.py).

## GitHub App and tooling aliases

Local and CI tools resolve credentials with several alternate variable names (first match wins):

| Role | Alternate names |
| ---- | ---------------- |
| Repository slug | `BMT_GITHUB_REPOSITORY`, `GITHUB_REPOSITORY` |
| App profile | `BMT_GITHUB_APP_PROFILE` |
| App id (dev) | `GITHUB_APP_DEV_ID`, `GH_APP_DEV_ID` |
| App id (primary) | `GITHUB_APP_ID`, `GH_APP_ID` |
| App id (override) | `BMT_APP_ID` |
| Private key path (dev) | `GITHUB_APP_DEV_PRIVATE_KEY_PATH`, `GH_APP_DEV_PRIVATE_KEY_PATH`, `BMT_APP_PRIVATE_KEY_PATH` |
| Private key path (primary) | `GITHUB_APP_PRIVATE_KEY_PATH`, `GH_APP_PRIVATE_KEY_PATH`, `BMT_APP_PRIVATE_KEY_PATH` |
| Utility | `BMT_JQ_PATH` |

**Resolution:** App id and PEM path precedence (per profile) are implemented in [tools/shared/github_app_settings.py](../tools/shared/github_app_settings.py) (`first_nonempty_env`, `app_id_for_profile`, `private_key_path_for_profile`). Empty string does not block a later alias in the chain (same as the former `a or b` behavior).

Secrets for production paths are listed in [Required Manual GitHub Configuration](#required-manual-github-configuration-secrets-and-optional-overrides).

## Local `tools/` and scripts (selected)

| Name | Purpose |
| ---- | ------- |
| `BMT_CONFIG` | Path for gh repo vars config |
| `BMT_CONTRACT` | Contract path override |
| `BMT_FORCE`, `BMT_PRUNE_EXTRA` | Tool flags |
| `BMT_PROJECT`, `BMT_DATASET`, `BMT_STAGE_ROOT`, `BMT_DRY_RUN` | Manifest / dataset helpers |
| `BMT_SRC_DIR`, `BMT_DELETE`, `BMT_ALLOW_GENERATED_ARTIFACTS` | Bucket sync / verify |
| `BMT_RUNNER_PATH`, `BMT_RUNNER_URI`, `BMT_SOURCE`, `SOURCE_REF` | Runner upload / CLI (`upload-runner` also exposes Typer options with these `envvar` names) |
| `BMT_ROOT` | Symlink helper |
| `BMT_BUILD_REPO` | Build command |
| `BMT_CONTEXT_FILE` | Override context file path (CI) |
| `MATRIX_CONFIGURE`, `BMT_OUTPUT_KEY`, `BMT_PRESETS_FILE`, `BMT_HAS_LEGS_KEY` | Matrix / presets |
| `BOOTSTRAP_NONINTERACTIVE`, `SKIP_UV_INSTALL` | Bootstrap script |

## Boolean env strings

Flags such as `BMT_SKIP_PUBLISH_RUNNERS` and `tools.shared.env.get_bool` treat these as true (case-insensitive, stripped): `1`, `true`, `yes`. Implementation: [runtime/config/env_parse.py](../runtime/config/env_parse.py) (`is_truthy_env_value`).

## Regenerating the machine-oriented inventory

See [Env inventory appendix](#env-inventory-appendix) for `rg` recipes and optional `vulture` / `pylint` duplicate-code scopes.

GitHub reporting chooses the credential profile from the repository slug:

## Env inventory appendix

First-party Python and automation live outside mirrored plugin trees under `gcp/stage/**`. Exclude that path when scanning for **new** env usage to avoid duplicated generated bundles.

## Discover `os.environ` / `getenv` keys (Python)

From the repo root (exclude mirrored stage plugins):

```bash
rg 'os\.environ\.get\(' -g '*.py' --glob '!gcp/stage/**'
rg 'os\.getenv\(' -g '*.py' --glob '!gcp/stage/**'
```

Narrow to string literals:

```bash
rg 'os\.environ\.get\("[A-Z0-9_]+"' -g '*.py' --glob '!gcp/stage/**'
rg "os\.environ\.get\\('[A-Z0-9_]+'" -g '*.py' --glob '!gcp/stage/**'
```

## Optional code health (env-related paths)

After `uv sync` (includes optional dev tools):

```bash
uv run vulture runtime/config tools/shared/env.py tools/shared/bucket_env.py --min-confidence 80
```

```bash
uv run pylint --disable=all --enable=duplicate-code --min-similarity-lines=6 \
  runtime/config/env_parse.py tools/shared/env.py tools/shared/bucket_env.py ci/kardome_bmt/workflow_dispatch.py
```

Or use `just doctor` from the repo root.

These checks are **optional** for contributors; the default gate remains `just test` (pytest, ruff, `ty`, etc.).

**GitHub App id / key path precedence** is implemented in [tools/shared/github_app_settings.py](../tools/shared/github_app_settings.py) (see [GitHub App and tooling aliases](#github-app-and-tooling-aliases)).
