# Env consolidation (typed resolution and handoff) — Implementation record

> **For agentic workers:** Original checklist lived in `.cursor/plans/env_consolidation_typed_settings_98876683.plan.md`; this file records what landed in-repo.

**Goal:** Reduce GitHub App alias sprawl, improve CLI discoverability for runner upload env, and type workflow context in handoff.

## Landed changes

| Area | Change |
| ---- | ------ |
| GitHub App env | [tools/shared/github_app_settings.py](../../tools/shared/github_app_settings.py) — explicit key tuples and `first_nonempty_env` (empty string falls through like legacy `or` chains; not pydantic `AliasChoices`, which would not match that behavior). [tools/repo/gh_app_perms.py](../../tools/repo/gh_app_perms.py) delegates to `app_id_for_profile` / `private_key_path_for_profile`. |
| Tests | [tests/tools/test_github_app_settings.py](../../tests/tools/test_github_app_settings.py) |
| Typer pilot | [tools/cli/bucket_cmd.py](../../tools/cli/bucket_cmd.py) `upload-runner`: `--source`, `--source-ref` with `envvar=` for `BMT_SOURCE`, `SOURCE_REF`; existing options gained `envvar` for runner path/URI. |
| CI handoff | [.github/bmt/ci/handoff.py](../../.github/bmt/ci/handoff.py) — `_handoff_env_from_workflow(WorkflowContext)`; duck-typed workflow objects still use `_w_attr` fallback. |
| Docs | [docs/configuration/env-reference.md](../../configuration/env-reference.md) — “Env usage to avoid or minimize”, GitHub App resolution pointer. |

## Optional follow-up (not done)

- `RuntimeEnv` `BaseSettings` in `gcp/image/runtime/facade.py` — only if the team wants one object for mode/paths/task index.
