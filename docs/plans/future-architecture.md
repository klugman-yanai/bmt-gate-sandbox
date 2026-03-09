# Future Architecture (Planned)

This document describes **planned** changes, not current behavior. The current implementation is CLI-first (gcloud subprocess, no Google Cloud SDK), uses dataclasses in CI and dict/JSON elsewhere, and uses GitHub App auth with Check Runs but **not** PR comments. See [../architecture.md](../architecture.md) and [../implementation.md](../implementation.md) for what is implemented today.

## Current vs planned

| Area | Current | Planned |
|------|---------|---------|
| GCP | `gcloud` CLI subprocess | Google Cloud SDK (`google.cloud.storage`, `google.cloud.compute`, `google.cloud.secretmanager`) |
| Data models | CI: dataclasses; VM/config: dict/JSON | Pydantic models for configs, verdicts, triggers (e.g. `BMTJobConfig`, `CIVerdict`, `RunTrigger`) |
| VM shared libs | `deploy/code/lib/`: `github_auth.py`, `github_checks.py`, `status_file.py` | Add `deploy/code/lib/bmt_lib/` (gcs, cache, gate, models) and `deploy/code/lib/github_api.py` (PyGithub, tabulate) |
| GitHub | Commit status + Check Run (implemented); PR comment not implemented | PR comments with markdown table; optional PyGithub everywhere |

---

## Planned: Shared libraries

### `bmt_lib/` — BMT utilities

- **gcs.py** — Wrap `google.cloud.storage.Client` for all GCS operations (no `gcloud` subprocess). Helpers: `now_iso()`, `now_stamp()`.
- **cache.py** — `CacheManager` for runner caching with digest invalidation (manifest digest from blob list).
- **gate.py** — `evaluate_gate()`, `resolve_status()`.
- **models.py** — Pydantic models for job config, runtime results, verdicts, triggers (see below).

### `github_api.py` — GitHub API

- Single module for all GitHub API calls via **PyGithub** (replacing raw `urllib.request`/`requests` in watcher).
- Functions: `get_github_client_from_app()`, `get_github_client_from_pat()`, `post_commit_status()`, `create_check_run()`, `post_pr_comment()`, `render_results_table()`.
- GitHub App: fetch secrets via `google.cloud.secretmanager`, JWT with PyJWT, installation token via `GithubIntegration`.

---

## Planned: Pydantic models

Config and runtime data would move from `dict[str, Any]` to Pydantic models in `deploy/code/lib/bmt_lib/models.py` (and CI could use matching models):

- **Config:** `RunnerConfig`, `PathsConfig`, `RuntimeConfig`, `GateConfig`, `ParsingConfig`, `BMTJobConfig`, `ProjectConfig`.
- **Runtime:** `FileResult`, `GateResult`, `CIVerdict`, `RunTrigger`, `TriggerLeg`.

Benefits: validation on load, typed access, JSON schema generation. Current code uses dataclasses in CI (`ci/models.py`) and dict/JSON elsewhere.

---

## Planned: Check run and PR comment (full)

- **Check run:** Already implemented via `deploy/code/lib/github_checks.py` and watcher. Planned: optional migration to `github_api.py` + PyGithub.
- **PR comment:** Not implemented. Planned: post a markdown table to the PR (e.g. `<!-- bmt-results -->` marker) using `tabulate` for GitHub-flavored tables, after watcher updates `current.json`.

---

## Planned: Error handling (SDK-based)

- **GCS:** Use `google.cloud.storage`; handle `GoogleAPICallError`; retry loop for transient errors (`ServiceUnavailable`, `TooManyRequests`); SDK transport retries for HTTP.
- **Runner / watcher:** Same as current (timeout, per-leg failure, graceful shutdown). See [../architecture.md](../architecture.md) for current behavior.

---

## Planned: Deployment and VM layout

- **Repo ↔ VM path:** Add mapping for `deploy/code/lib/bmt_lib/` → `/opt/bmt/lib/bmt_lib/` and `deploy/code/lib/github_api.py` → `/opt/bmt/lib/github_api.py`.
- **Sync script:** e.g. `tools/sync_to_vm.sh` using `gcloud compute scp --recurse` and remote script to arrange files under `/opt/bmt/` (bin, lib, managers, config, templates, data, cache, runtime).
- **systemd:** `PYTHONPATH=/opt/bmt/lib`; env for bucket, prefix, GitHub token/App secrets.
- **Dependencies (VM):** e.g. `google-cloud-storage`, `google-cloud-secret-manager`, `PyGithub`, `PyJWT`, `pydantic`, `tabulate`.

---

## Planned: Migration phases (summary)

1. **Shared libs and Pydantic** — Add `bmt_lib` and `github_api`; define models; refactor watcher, orchestrator, manager to use them; remove `gcloud` subprocess from VM code (keep for runner binary execution only).
2. **CI scripts** — Replace `ci/adapters/gcloud_cli.py` subprocess calls with Google Cloud SDK; use Pydantic (or aligned) models in trigger/wait/gate.
3. **GitHub App auth** — Harden App-only auth; wire PR comment in watcher post-run.
4. **Deployment** — Sync script, systemd, end-to-end test (status + check run + PR comment).

---

## Open questions (planned work)

- GCP Secret Manager secret names for GitHub App.
- VM instance name/zone for sync script.
- Dataset WAV locations for initial sync.
- Keep `bmt_projects.json` on bucket (orchestrator downloads at runtime) vs pre-stage on VM.
