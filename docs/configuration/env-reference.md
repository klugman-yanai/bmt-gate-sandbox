# Environment variable reference

This document inventories **process environment** and closely related names used across GitHub Actions, the `bmt` CI package (`.github/bmt/ci`), Cloud Run runtime (`gcp/image`), and local `tools/` scripts. It complements the high-level flow in [configuration.md](configuration.md).

**Security:** Never commit secrets. Repo **Variables** are not encrypted; use **Secrets** for tokens and keys. See [SECURITY.md](../../SECURITY.md).

**Large values:** Prefer files or step outputs (`GITHUB_OUTPUT`, `.bmt/context.json`) for big JSON blobs. Environment variables have size and escaping constraints in Actions.

## Env usage to avoid or minimize

New work should not add more of these patterns; refactors that touch them should prefer files, secrets stores, or typed resolution (see [tools/shared/github_app_settings.py](../../tools/shared/github_app_settings.py) for GitHub App id/path precedence).

| Avoid or minimize | Why | Prefer instead |
| ----------------- | --- | -------------- |
| Large JSON or matrices in env | Size/escaping limits in Actions | `.bmt/context.json`, `GITHUB_OUTPUT`, artifacts |
| Secret bodies in env | Exposure in logs and dumps | GitHub Secrets, GCP Secret Manager; env holds paths/refs only |
| New parallel names for the same fact | Operator confusion | One name per layer; consolidate aliases in code (see GitHub App module) |
| New undocumented `BMT_*` for local tools | Hard to discover | Typer options with `envvar=` (e.g. `tools bucket upload-runner --help`) |
| Duplicating infra values already in `bmt.tfvars.json` | Drift vs Pulumi | `just pulumi` / repo variables |
| Constants as env | False configurability | [gcp/image/config/constants.py](../../gcp/image/config/constants.py) |

## GitHub Actions precedence

When the same name appears at multiple levels:

1. Step `env` overrides job `env` overrides workflow `env`.
2. `secrets.*` injects masked values; `vars.*` is repository/org variables (non-secret); `env.*` is the computed env for the step.

Official behavior: [GitHub Docs — Workflow syntax](https://docs.github.com/en/actions/writing-workflows/workflow-syntax-for-github-actions#env).

## Where canonical names live

| Mechanism | Location |
| --------- | -------- |
| GitHub repo variables (Pulumi-synced) | [tools/repo/vars_contract.py](../../tools/repo/vars_contract.py) |
| Aggregated contract (contexts) | [tools/shared/env_contract.py](../../tools/shared/env_contract.py) |
| CI typed settings (`BmtConfig`) | [.github/bmt/ci/config.py](../../.github/bmt/ci/config.py) |
| `ENV_*` string constants | [gcp/image/config/constants.py](../../gcp/image/config/constants.py) |
| Infra file (not process env) | `infra/pulumi/bmt.tfvars.json` via [infra/pulumi/config.py](../../infra/pulumi/config.py) |

## Infra and CI (`BmtConfig` / repo vars)

These names are synced from Pulumi to GitHub **Variables** for normal use. See [configuration.md](configuration.md#centralized-config-and-repo-variables).

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
| `BMT_STATUS_CONTEXT` | Repo var, CI, runtime | Optional | Default status context (e.g. `BMT Gate`) |

## Workflow handoff context (CI)

Read by `context_from_env` / `WorkflowContext` in [.github/bmt/ci/config.py](../../.github/bmt/ci/config.py) (`_WORKFLOW_CONTEXT_ENV_KEYS`). Typical sources: workflow `env`, prior step outputs, and Actions built-ins.

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

Additional names used by handoff / matrix code without being in `_WORKFLOW_CONTEXT_ENV_KEYS` include `GITHUB_OUTPUT`, `GITHUB_ENV`, `GITHUB_STEP_SUMMARY`, `GITHUB_TOKEN`, `FILTERED_MATRIX_JSON`, `GITHUB_SHA`, and orchestration flags such as `ORCH_*` read in [.github/bmt/ci/handoff.py](../../.github/bmt/ci/handoff.py).

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

`GITHUB_REPOSITORY` is shared. See [.github/bmt/ci/workflow_dispatch.py](../../.github/bmt/ci/workflow_dispatch.py) and [gcp/image/runtime/entrypoint.py](../../gcp/image/runtime/entrypoint.py).

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

**Resolution:** App id and PEM path precedence (per profile) are implemented in [tools/shared/github_app_settings.py](../../tools/shared/github_app_settings.py) (`first_nonempty_env`, `app_id_for_profile`, `private_key_path_for_profile`). Empty string does not block a later alias in the chain (same as the former `a or b` behavior).

Secrets for production paths are listed in [configuration.md](configuration.md#required-manual-github-configuration-secrets-and-optional-overrides).

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

Flags such as `BMT_USE_MOCK_RUNNER` and `tools.shared.env.get_bool` treat these as true (case-insensitive, stripped): `1`, `true`, `yes`. Implementation: [gcp/image/config/env_parse.py](../../gcp/image/config/env_parse.py) (`is_truthy_env_value`).

## Regenerating the machine-oriented inventory

See [env-inventory-appendix.md](env-inventory-appendix.md) for `rg` recipes and optional `vulture` / `pylint` duplicate-code scopes.
