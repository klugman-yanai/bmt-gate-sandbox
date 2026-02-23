# Architecture

This document covers BMT CI and VM execution on GCP.

Current source-of-truth behavior is implemented in:

- `.github/workflows/ci.yml`
- `.github/workflows/bmt.yml`
- `.github/scripts/ci/`
- `remote/vm_watcher.py`
- `remote/root_orchestrator.py`
- `remote/sk/bmt_manager.py`

Some sections in this file describe planned refactors. When in doubt, trust the files above.

**Current overview (implemented):** `ci.yml` builds and dispatches `bmt.yml`; `bmt.yml` uploads runners, writes one run trigger to GCS, starts VM, waits for handshake ack, posts pending status, and exits. The VM watcher processes all legs, updates pointers, posts final GitHub status/check run, and deletes the trigger. For who posts which status when and how gaps (e.g. Trigger BMT failure, VM exception) are closed, see **docs/communication-flow.md**.

**Dummy CI and artifacts:** The repo’s `ci.yml` is a dummy that mirrors `resources/core-main-workflow.yml` (one job per project, filtered by `BMT_PROJECTS`; default `all release runners`). It uses the real `kardome_runner` from `build/` when present, or from `remote/sk/runners/sk_gcc_release/` otherwise, so the artifact layout and content match production. GitHub Actions artifacts are **per workflow run**; they do not carry to another run. The BMT workflow receives the CI run’s `run_id` and downloads those artifacts by `run-id` so it can upload the same runner bundles to GCS.

---

## Architecture Summary

### Execution Model: Fire-and-Forget

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ CI WORKFLOW (~15 seconds total)                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  1. upload-runners → Upload CI runner artifacts to GCS                      │
│  2. trigger        → Write one run trigger JSON to GCS                      │
│  3. sync-metadata  → Push bucket/prefix into VM metadata                     │
│  4. start-vm       → Start the BMT VM (gcloud compute instances start)      │
│  5. handshake      → Wait for VM ack + post pending status                  │
│  5. EXIT           → Workflow completes, VM continues independently         │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ VM EXECUTION (independent of CI)                                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  1. vm_watcher.py     → Poll GCS for run triggers                          │
│  2. root_orchestrator → Spawn project manager, collect verdicts            │
│  3. bmt_manager.py    → Execute runner pool, aggregate results              │
│  4. GitHub updates    → Commit Status + Check Run                           │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Mermaid Diagrams

For maintained Mermaid sources (including sequence + flowchart diagrams), see:

- `docs/diagrams.md`

### Key Principle: Trigger-And-Stop

GitHub Actions hands off quickly. Long-running BMT execution happens on VM, not on the runner.

### Key Principle: GCS Contract + Pointer Promotion

Managers write per-run snapshots under `snapshots/<run_id>/`. Watcher updates canonical `current.json` pointers (`latest`, `last_passing`) after leg completion and prunes stale snapshots.

### Key Principle: Strict retention (current + previous only)

There is no quarantine tier. Runtime cleanup is hard-delete:

- Snapshots not referenced by `current.json.latest` or `current.json.last_passing` are deleted.
- Workflow metadata families (`triggers/acks`, `triggers/status`) are trimmed to recent entries.
- VM local `run_*` directories are pruned to current + previous per project/BMT.

### Key Principle: Current Implementation Is CLI-First

Current code uses:

- `gcloud` subprocesses for GCS and VM operations.
- GitHub REST calls via `urllib` and `requests`.
- GitHub App JWT flow in `remote/lib/github_auth.py`, with PAT fallback.

Any SDK-first design notes in later sections are roadmap, not current runtime behavior.

---

## Client-side (workflow) scripts

These run on **GitHub Actions** during the workflow. Entrypoint: `ci_driver.py` (Click group) in `.github/scripts/`.

| Script / module | Role |
| ----------------| ---- |
| **ci_driver.py** | Thin CLI; registers subcommands from the `ci` package. Invoked as `uv run python .github/scripts/ci_driver.py <command>`. |
| **ci/commands/job_matrix.py** | `matrix` — Reads `bmt_projects.json` and per-project jobs config, builds the list of (project, bmt_id) legs. Outputs JSON matrix for the trigger step. |
| **ci/commands/run_trigger.py** | `trigger` — Builds the run payload (workflow_run_id, repository, sha, legs with project, bmt_id, run_id, triggered_at), writes one JSON file to GCS `triggers/runs/<workflow_run_id>.json`. VM resolves results_prefix and verdict path from config and manager summary. |
| **ci/commands/sync_vm_metadata.py** | `sync-vm-metadata` — Updates VM metadata keys (`GCS_BUCKET`, `BMT_BUCKET_PREFIX`) from workflow env so bucket/prefix drift does not require manual VM bootstrap reruns. |
| **ci/commands/start_vm.py** | `start-vm` — Starts the GCP Compute Engine VM via `gcloud compute instances start`. Requires canonical env vars: `GCP_PROJECT`, `GCP_ZONE`, `BMT_VM_NAME`. |
| **ci/commands/wait_verdicts.py** | `wait` — Polls GCS for `current.json` pointer per leg; when pointer.latest matches run_id, downloads verdict from `snapshots/{run_id}/ci_verdict.json`. Aggregates outcomes. For manual/local use; not used by the workflow. |
| **ci/commands/verdict_gate.py** | `gate` — Enforces pass/fail from aggregated verdicts; for manual use. |
| **ci/config.py** | Loads project registry and jobs config; builds matrix; resolves `results_prefix` per project/bmt. |
| **ci/models.py** | Constants (status, reason codes), URI helpers (snapshot_verdict_uri, current_pointer_uri, run_trigger_uri), decision logic, data classes (CloudVerdict, LegOutcome, AggregateRow). |
| **ci/adapters/gcloud_cli.py** | All GCP interaction used by CI commands: GCS upload/download and VM start. Uses `gcloud` subprocess (SDK migration is future work). |

`bmt.yml` currently runs matrix + trigger + sync-vm-metadata + start-vm + handshake, then exits after posting pending status. It does not call `wait` or `gate`.

---

## VM-side scripts

These run **on the BMT VM** (started by the workflow). Code lives under `remote/` and is synced to the bucket; the VM downloads or uses a pre-staged copy.

| Script | Role |
| ------| ---- |
| **vm_watcher.py** | Main loop: polls GCS `triggers/runs/`. For each trigger: writes handshake ack, starts progress heartbeat file, downloads `root_orchestrator.py` from bucket, runs orchestrator **once per leg**, reads manager summaries, updates each leg `current.json` pointer and cleans stale snapshots, posts final commit status to GitHub, updates Check Run, and deletes trigger file. It also trims trigger metadata families and legacy history prefixes, and prunes local run directories to current + previous only. Optional `--exit-after-run` to exit after one run (VM then stops itself). Uses stdlib + `gcloud` CLI plus `requests` for Check Run API calls. |
| **root_orchestrator.py** | **Per leg:** Downloads `bmt_projects.json` and the project’s jobs config and manager script from the bucket. Validates project is enabled, invokes the **per-project manager** (e.g. `bmt_manager.py`) with bucket, project, bmt_id, run_id, run_context, Collects manager exit code and summary; writes root summary to GCS. Does not aggregate across legs (the watcher does that). |
| **Per-project BMT managers** (one **bmt_manager.py** per project, e.g. `sk/bmt_manager.py`) | **Per project:** Loads the BMT job config (runner URI, template, dataset, gate, etc.), caches runner bundle and template from GCS, syncs or uses cached dataset. For each WAV in the dataset: builds a runner config from the template, runs the **runner binary** (e.g. `kardome_runner`) in a thread pool, parses output (e.g. NAMUH counter), aggregates scores. Evaluates gate vs baseline from `current.json` pointer (last_passing snapshot). Writes all outputs under `{results_prefix}/snapshots/{run_id}/` (latest.json, ci_verdict.json, logs). Returns exit code and summary path to the orchestrator. |

Flow: **watcher** → for each leg → **orchestrator** → **manager** (one per project/bmt). The watcher is the only process that sees the full trigger and performs aggregation and promotion.

---

## Repo ↔ VM Path Mapping

The repo's `remote/` directory is the authoritative source for VM-side code. The sync script maps repo paths to VM paths:

| Repo path | VM path | Notes |
|-----------|---------|-------|
| `remote/vm_watcher.py` | `/opt/bmt/bin/vm_watcher.py` | systemd entry point |
| `remote/root_orchestrator.py` | `/opt/bmt/bin/root_orchestrator.py` | orchestrator |
| `remote/sk/bmt_manager.py` | `/opt/bmt/managers/sk/bmt_manager.py` | SK manager |
| `remote/lib/bmt_lib/` | `/opt/bmt/lib/bmt_lib/` | shared library (new) |
| `remote/lib/github_api.py` | `/opt/bmt/lib/github_api.py` | GitHub API (new) |
| `remote/sk/config/bmt_jobs.json` | `/opt/bmt/config/sk/bmt_jobs.json` | BMT definitions |
| `remote/bmt_projects.json` | `/opt/bmt/config/bmt_projects.json` | project registry |
| `remote/sk/config/input_template.json` | `/opt/bmt/templates/sk/input_template.json` | runner template |

New `lib/` directory will be created under `remote/lib/` in the repo (not at repo root).

---

## VM Filesystem Layout

```
/opt/bmt/
├── bin/
│   ├── vm_watcher.py              # systemd service, polls for triggers
│   └── root_orchestrator.py       # spawns project managers
│
├── lib/
│   ├── bmt_lib/                   # shared BMT utilities
│   │   ├── __init__.py
│   │   ├── models.py              # Pydantic models
│   │   ├── gcs.py                 # GCS operations + time helpers
│   │   ├── cache.py               # runner caching with digest invalidation
│   │   └── gate.py                # gate evaluation logic
│   │
│   └── github_api.py             # GitHub API (auth, status, check runs, comments)
│
├── managers/
│   └── sk/
│       └── bmt_manager.py      # SK project-specific manager
│
├── config/
│   ├── bmt_projects.json          # project registry
│   └── sk/
│       └── bmt_jobs.json          # SK BMT definitions
│
├── templates/
│   └── sk/
│       └── input_template.json    # runner JSON config template
│
├── data/
│   └── sk/
│       └── inputs/
│           └── false_rejects/     # WAV datasets (pre-staged)
│
├── cache/                         # runtime cache for runners
│   └── sk/
│       └── false_reject_namuh/
│           ├── runner_bundle/
│           └── meta/
│
└── runtime/                       # per-run workspaces (transient)
```

---

## GCS Bucket Structure

Only runners, triggers, and results live in GCS:

```
gs://bucket[/prefix]/
├── runners/                       # PUSHED by CI per build
│   └── sk_gcc_release/
│       ├── kardome_runner
│       └── runner_latest_meta.json
│
├── triggers/
│   ├── runs/{workflow_run_id}.json        # WRITTEN by CI; deleted after processing
│   ├── acks/{workflow_run_id}.json        # WRITTEN by VM; trimmed to recent
│   └── status/{workflow_run_id}.json      # WRITTEN by VM; trimmed to recent
│
└── sk/results/false_rejects/      # Per (project, bmt_id): pointer + snapshots
    ├── current.json               # Pointer (latest run_id, last_passing run_id)
    └── snapshots/
        └── {run_id}/              # One dir per run (cleaned up; at most 2 kept)
            ├── latest.json
            ├── ci_verdict.json
            └── logs/
```

### Pointer-based result layout

The manager writes **only** under `{results_prefix}/snapshots/{run_id}/`. The **canonical** state is a single file: `{results_prefix}/current.json`, which points to the latest and last-passing run_ids. The watcher updates this pointer after all legs complete and deletes any snapshot not referenced.

- **Goals:** No canonical writes during execution; atomic promotion (one file write); no promotion on cancel/supersede; trigger-agnostic (same flow for GCS or Pub/Sub).
- **Contract:** (1) Manager reads baseline by resolving `current.json` → last_passing → `snapshots/{run_id}/latest.json`. (2) Manager writes all outputs under `snapshots/{run_id}/`. (3) After all legs, watcher updates `current.json` and deletes stale snapshots. (4) Check Run / PR comment must run **after** the watcher updates `current.json`; they must read from pointer-resolved snapshot paths or in-memory aggregation.

### Retention contract

- Keep only snapshot directories referenced by `current.json.latest` and `current.json.last_passing`.
- Keep only recent workflow metadata in `triggers/acks` and `triggers/status`.
- Remove consumed run trigger objects in `triggers/runs`.
- Keep only two local `run_*` directories per project/BMT on the VM.

### Trigger sources: GCS and Pub/Sub

The run payload can be delivered by **GCS** (trigger file; VM polls) or **Pub/Sub** (message; VM puller). The payload shape and VM processing (staging, promotion, GitHub updates) are the same in both cases; the design is trigger-source agnostic.

---

## Run Trigger Schema

CI writes one trigger file per workflow run to `triggers/runs/{workflow_run_id}.json`. The VM watcher polls for these, processes all legs, then deletes the trigger. This is the contract between CI and the VM.

```json
{
  "workflow_run_id": "12345678",
  "repository": "owner/repo",
  "sha": "abc123def456...",
  "ref": "refs/heads/testing",
  "run_context": "pr",
  "triggered_at": "2026-02-19T12:00:00Z",
  "bucket": "my-bucket",
  "bucket_prefix": "",
  "legs": [
    {
      "project": "sk",
      "bmt_id": "false_reject_namuh",
      "run_id": "gh-12345678-1-sk-false_reject_namuh-abc123def456",
      "triggered_at": "2026-02-19T12:00:00Z"
    }
  ]
}
```

| Field | Source | Purpose |
|-------|--------|---------|
| `workflow_run_id` | `GITHUB_RUN_ID` | Unique per workflow invocation |
| `repository` | `GITHUB_REPOSITORY` | Used by VM to post commit status |
| `sha` | `GITHUB_SHA` | Commit to update status on |
| `run_context` | `"pr"` or `"dev"` | Controls gate behavior (e.g. bootstrap policy) |
| `legs[].run_id` | Generated | `gh-{RUN_ID}-{ATTEMPT}-{project}-{bmt_id}-{sha[:12]}` |

The VM resolves `results_prefix` from config and verdict location from manager summary (`ci_verdict_uri` under snapshots).

---

## Configuration Files

Environment variables are defined declaratively in `config/env_contract.json` (required/optional vars, defaults, and consistency checks). `config/repo_vars.toml` is optional and acts as an override file; omitted canonical vars inherit current GitHub repo values first, then contract defaults (`devtools/gh_repo_vars.py`). Canonical names are enforced (no alias vars such as `VM_NAME`/`BUCKET`, no derived `GCP_PROJECT`). Runtime values still come from environment variables, GitHub repo variables, and VM metadata; there is no separate `vm_config` runtime file. VM paths remain constants in code (`/opt/bmt/...`), and watcher settings are CLI args.

## Test vs Production Delta

Expected primary differences when moving this test setup to production:

- GitHub App credentials and repo mapping (`APP_*` secrets, `remote/config/github_repos.json`)
- Status context label used for branch protection (`BMT_STATUS_CONTEXT`)

### 1. `bmt_projects.json` (Project Registry, occasionally edited)

Keeps the current JSON format. No TOML migration — JSON works fine and the configs are rarely edited.

```json
{
  "projects": {
    "sk": {
      "enabled": true,
      "manager_script": "sk/bmt_manager.py",
      "jobs_config": "sk/config/bmt_jobs.json",
      "description": "Kardome (sk) BMTs"
    }
  }
}
```

### 2. `sk/config/bmt_jobs.json` (BMT Definitions, occasionally edited)

Keeps the current JSON format and key names. Loaded via Pydantic `BMTJobConfig` for validation.

---

## Shared Libraries

### `bmt_lib/` - BMT Utilities

| Module | Purpose |
|--------|---------|
| `gcs.py` | GCS operations via `google.cloud.storage.Client` — upload, download, list, delete. Also contains `now_iso()`, `now_stamp()` helpers. |
| `cache.py` | `CacheManager` for runner caching with digest invalidation |
| `gate.py` | `evaluate_gate()`, `resolve_status()` |
| `models.py` | Pydantic models (see below) |

#### `gcs.py` — SDK Usage

Wraps `google.cloud.storage.Client` for all GCS operations. No `gcloud` CLI subprocess calls.

```python
from google.cloud import storage

class GCSClient:
    def __init__(self, bucket_name: str, prefix: str = "") -> None:
        self._client = storage.Client()
        self._bucket = self._client.bucket(bucket_name)
        self._prefix = prefix.strip("/")

    def download_file(self, blob_path: str, local_path: Path) -> None: ...
    def upload_file(self, local_path: Path, blob_path: str) -> None: ...
    def list_blobs(self, prefix: str) -> list[storage.Blob]: ...
    def delete_blob(self, blob_path: str) -> None: ...
    def blob_exists(self, blob_path: str) -> bool: ...
    def download_json(self, blob_path: str) -> dict[str, Any]: ...
    def upload_json(self, payload: dict[str, Any], blob_path: str) -> None: ...
    def sync_prefix_to_local(self, prefix: str, local_dir: Path) -> None:
        """Download all blobs under prefix to local_dir."""
```

Authentication uses Application Default Credentials (ADC) — on the VM this is the attached service account; in CI it's the WIF-provided credential. No explicit key files needed.

#### `cache.py` — Digest Invalidation Detail

The runner cache uses a **manifest digest** to detect when the runner binary or its dependencies have changed. The mechanism (carried over from the current `bmt_manager.py`, now using the Python SDK):

1. `GCSClient.list_blobs()` on the runner bundle prefix and deps prefix
2. For each `storage.Blob`: extract `name`, `generation`, `size`
3. Sort rows, SHA-256 hash them → produces a single digest string
4. Compare against the stored digest in `cache/meta/runner_bundle_meta.json`
5. On mismatch → `GCSClient.sync_prefix_to_local()` the bundle; update the stored digest

This means any change to any file in the runner bundle (binary, shared libs, metadata) triggers a re-sync. Generation-based comparison catches in-place overwrites that don't change size.

### `github_api.py` - GitHub API Integration

A single module for all GitHub API calls via `PyGithub`. Replaces the raw `urllib.request` calls in `vm_watcher.py`.

Functions: `get_github_client()`, `get_github_client_from_pat()`, `post_commit_status()`, `create_check_run()`, `post_pr_comment()`, `render_results_table()`.

```python
from github import Github, GithubIntegration
from google.cloud import secretmanager
from tabulate import tabulate

def get_github_client_from_app(app_id_secret: str, key_secret: str, install_secret: str) -> Github:
    """Create authenticated GitHub client via GitHub App installation token."""
    sm = secretmanager.SecretManagerServiceClient()
    app_id = _access_secret(sm, app_id_secret)
    private_key = _access_secret(sm, key_secret)
    installation_id = int(_access_secret(sm, install_secret))
    integration = GithubIntegration(int(app_id), private_key)
    token = integration.get_access_token(installation_id).token
    return Github(token)

def get_github_client_from_pat(token: str) -> Github:
    """Fallback: create GitHub client from PAT."""
    return Github(token)

def post_commit_status(gh: Github, repo: str, sha: str, state: str, description: str) -> bool: ...
def create_check_run(gh: Github, repo: str, sha: str, name: str, summary: str) -> bool: ...
def post_pr_comment(gh: Github, repo: str, pr_number: int, body: str, marker: str) -> bool: ...

def render_results_table(legs: list[dict]) -> str:
    """Render BMT results as a GitHub-flavored markdown table."""
    rows = [[l["bmt"], l["status"], f"{l['score']:.2f}", l["reason"]] for l in legs]
    return tabulate(rows, headers=["BMT", "Status", "Score", "Reason"], tablefmt="github")
```

#### Dependencies

All Python SDK dependencies are managed via `uv` in [pyproject.toml](pyproject.toml):

| Package | Purpose | Used by |
|---------|---------|---------|
| `google-cloud-storage` | GCS blob operations | `bmt_lib/gcs.py`, CI scripts |
| `google-cloud-secret-manager` | Fetch GitHub App secrets | `github/auth.py` (VM only) |
| `google-cloud-compute` | Start/stop VM | CI `start-vm` command |
| `PyGithub` | GitHub API (statuses, check runs, comments) | `github/`, CI scripts |
| `PyJWT` | GitHub App JWT generation | `github/auth.py` |
| `pydantic` | Data models, config validation, JSON schema | All modules (see below) |
| `tabulate` | Markdown table generation (escaping, alignment) | `github_api.py` |

---

## Pydantic Models and Structured Data

### Why Pydantic

The current code uses `dict[str, Any]` for everything — configs, results, verdicts, triggers. This is fragile: misspelled keys silently produce `None`, there's no validation on load, and every consumer has to defensively cast types. Pydantic gives us typed models, validation on construction, and automatic JSON serialization.

### Models to Define

All models live in `remote/lib/bmt_lib/models.py`:

```python
from pydantic import BaseModel, Field

# --- Config models (loaded from TOML/JSON) ---

class RunnerConfig(BaseModel):
    uri: str
    deps_prefix: str = ""

class PathsConfig(BaseModel):
    template: str
    dataset: str
    results_prefix: str
    logs_prefix: str

class RuntimeConfig(BaseModel):
    runner_timeout_sec: int = 120
    max_workers: int = 4
    num_source_test: int = 0
    enable_overrides: dict[str, bool] = Field(default_factory=dict)

class GateConfig(BaseModel):
    comparison: str = "gte"  # "gte" | "lte"

class ParsingConfig(BaseModel):
    keyword: str = "NAMUH"
    counter_pattern: str = r"Hi NAMUH counter = (\d+)"

class BMTJobConfig(BaseModel):
    enabled: bool = True
    description: str = ""
    runner: RunnerConfig
    paths: PathsConfig
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    gate: GateConfig = Field(default_factory=GateConfig)
    warning_policy: dict[str, bool] = Field(default_factory=dict)
    demo: dict[str, bool] = Field(default_factory=dict)
    parsing: ParsingConfig = Field(default_factory=ParsingConfig)

class ProjectConfig(BaseModel):
    enabled: bool = True
    manager_script: str
    jobs_config: str
    description: str = ""

# --- Runtime data models ---

class FileResult(BaseModel):
    file: str
    exit_code: int
    namuh_count: int
    status: str  # "ok" | "failed"
    log: str
    output: str
    error: str = ""

class GateResult(BaseModel):
    comparison: str
    last_score: float | None
    current_score: float
    passed: bool
    reason: str

class CIVerdict(BaseModel):
    run_id: str
    project_id: str
    bmt_id: str
    status: str  # "pass" | "fail" | "warning"
    reason_code: str
    aggregate_score: float
    runner: dict[str, str]
    gate: GateResult
    timestamps: dict[str, str]
    artifacts: dict[str, str]

class RunTrigger(BaseModel):
    """Schema for triggers/runs/{workflow_run_id}.json — contract between CI and VM."""
    workflow_run_id: str
    repository: str
    sha: str
    ref: str
    run_context: str
    triggered_at: str
    bucket: str
    bucket_prefix: str = ""
    legs: list[TriggerLeg]

class TriggerLeg(BaseModel):
    project: str
    bmt_id: str
    run_id: str
    results_prefix: str
    verdict_uri: str
    triggered_at: str
```

### Benefits

| Before (dict) | After (Pydantic) |
|----------------|-----------------|
| `bmt_cfg.get("runner", {}).get("uri", "")` | `bmt_cfg.runner.uri` |
| Silent `None` on typo | `ValidationError` on load |
| Manual `json.dumps(result, indent=2)` | `result.model_dump_json(indent=2)` |
| No schema docs | Auto-generated JSON Schema via `Model.model_json_schema()` |
| Defensive `isinstance` checks everywhere | Guaranteed types after construction |

### Where Models Are Used

| Producer | Model | Consumer |
|----------|-------|----------|
| CI `run_trigger.py` | `RunTrigger` | VM `vm_watcher.py` |
| VM `bmt_manager.py` | `CIVerdict` | CI `wait_verdicts.py` / `verdict_gate.py` |
| VM `bmt_manager.py` | `FileResult` | `latest.json` |
| Config loader | `BMTJobConfig` | Manager, CI matrix |
| Config loader | `ProjectConfig` | Orchestrator, CI matrix |

---

## Markdown Reports (tabulate)

Check run summaries and PR comments use `tabulate` for reliable GitHub-flavored markdown tables. The document structure around the table is simple enough to build with f-strings — no template engine needed.

```python
def render_check_run_summary(legs: list[dict], run_id: str, timestamp: str) -> str:
    table = render_results_table(legs)
    return f"## BMT Results\n\n{table}\n\n> Run `{run_id}` · {timestamp}"

def render_pr_comment(legs: list[dict]) -> str:
    table = render_results_table(legs)
    return f"<!-- bmt-results -->\n## BMT Results\n\n{table}"
```

---

## Logging

Keep it simple: `print()` with a consistent prefix format. systemd captures stdout to the journal, and the GCE Ops Agent (if installed) ships journal entries to Cloud Logging automatically — no Python logging library needed.

Convention for all VM scripts:

```python
# Informational
print(f"[{_now_iso()}] Processing run {run_id} with {len(legs)} leg(s)")

# Gate results (parseable by grep/jq)
print(f"BMT_GATE={state} PROJECT={project} BMT={bmt_id} SCORE={score:.3f}")

# Errors
print(f"  ERROR: Failed to download {uri}: {exc}", file=sys.stderr)
```

This is the existing pattern in the codebase. No migration needed.

### Runner Process Management

On timeout, use `os.killpg()` to kill the runner and any child processes it spawned:

```python
import os, signal, subprocess

proc = subprocess.Popen(runner_cmd, preexec_fn=os.setsid)
try:
    proc.wait(timeout=timeout_sec)
except subprocess.TimeoutExpired:
    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    proc.wait()
```

No extra dependencies needed — stdlib `os` and `signal` handle process group cleanup.

---

### GitHub Auth Migration: PAT → GitHub App

The current `vm_watcher.py` uses a PAT (`GITHUB_STATUS_TOKEN` env var) and only posts commit statuses. The refactored architecture introduces GitHub App auth for richer API access (check runs, PR comments).

**Prerequisites**:
1. Create a GitHub App with permissions: `statuses:write`, `checks:write`, `pull_requests:write`
2. Install the App on the repository
3. Store three secrets in GCP Secret Manager: `github-app-id`, `github-installation-id`, `github-private-key`
4. The `auth.py` module fetches these via `google.cloud.secretmanager` Python SDK, generates a JWT with PyJWT, exchanges it for an installation token via `PyGithub`'s `GithubIntegration`

**Fallback**: If GitHub App secrets are not configured, `vm_watcher.py` falls back to the `GITHUB_STATUS_TOKEN` PAT for commit status only (no check runs or PR comments). This allows incremental migration.

---

## Error Handling and Retry Strategy

### Runner Failures

Carried over from the current `bmt_manager.py`:
- Each runner invocation has a configurable timeout (`runner_timeout_sec`). On timeout, exit code 124 is recorded.
- Failed runs (non-zero exit) are counted. If `failed_count > 0`, the gate fails with reason `runner_failures`.
- Individual file results are always recorded, so partial failures are diagnosable from `latest.json`.

### GCS Failures

- `google.cloud.storage` raises `google.api_core.exceptions.GoogleAPICallError` on failures. A failed download/upload aborts the current leg.
- The watcher catches orchestrator failures per-leg and continues to the next leg. A leg that fails to produce a verdict is counted as a failure in the aggregate.
- GCS operations use a simple retry loop (3 attempts, exponential backoff) for transient errors (`ServiceUnavailable`, `TooManyRequests`). Permanent errors (404, 403) fail immediately. The SDK's built-in transport retries handle lower-level HTTP errors transparently.

### GitHub API Failures

- GitHub calls retry (3 attempts) for transient 5xx errors. On permanent failure (403, 422), log a warning and continue — GitHub status is best-effort.

### Watcher-Level Failures

- If the orchestrator crashes (non-zero exit), the watcher still posts an aggregate commit status (counting that leg as failed).
- If the trigger file is unparseable, it is deleted (to avoid infinite retries) with a warning.
- SIGTERM/SIGINT trigger graceful shutdown: finish current leg, skip remaining, post partial status.

---

## GitHub Visibility

### 1. Commit Status (Gate)

Blocks PR merge via branch protection:

```
PR #123 Checks
└── BMT Gate ✓ Pass — BMT: 2/2 passed
```

### 2. Check Run (Details)

```
PR #123 Checks
└── BMT Matrix ✓ Completed
    ┌──────────────────────────────────────────────┐
    │ ## BMT Results                               │
    │                                              │
    │ | Project | BMT | Status | Score | Reason | │
    │ |---------|-----|--------|-------|--------| │
    │ | sk | false_reject | ✓ pass | 42.50 | ... | │
    └──────────────────────────────────────────────┘
```

### 3. PR Comment (Summary)

```
PR #123 Conversation
└── <!-- bmt-results -->
    ## 🔬 BMT Results

    | BMT | Status | Score | Delta |
    |-----|--------|-------|-------|
    | sk.false_reject_namuh | ✅ pass | 42.50 | +0.30 |
```

---

## Deployment

### Sync Script: `devtools/sync_to_vm.sh`

Uses `gcloud compute scp --recurse` on the entire `remote/` tree rather than individual file copies, then rearranges into the VM layout. This is simpler and more robust than per-file scp.

```bash
#!/bin/bash
set -euo pipefail

BMT_VM_NAME=${1:-bmt-vm}
ZONE=${2:-europe-west4-a}
BMT_ROOT="/opt/bmt"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "Syncing BMT to VM: $BMT_VM_NAME (zone: $ZONE)"

# Upload the entire remote/ tree to a staging area on the VM
gcloud compute scp --recurse --zone="$ZONE" \
  "$REPO_ROOT/remote/" "$BMT_VM_NAME:/tmp/bmt_staging/"

# Run a remote script to arrange files into /opt/bmt/ layout
gcloud compute ssh "$BMT_VM_NAME" --zone="$ZONE" -- bash -s <<'REMOTE'
set -euo pipefail
BMT_ROOT="/opt/bmt"
STAGING="/tmp/bmt_staging"

sudo mkdir -p "$BMT_ROOT"/{bin,lib/bmt_lib,managers/sk,config/sk,templates/sk,data/sk/inputs/false_rejects,cache,runtime}

# Binaries
sudo cp "$STAGING/vm_watcher.py"        "$BMT_ROOT/bin/"
sudo cp "$STAGING/root_orchestrator.py"  "$BMT_ROOT/bin/"

# Libraries
sudo cp "$STAGING/lib/bmt_lib/"*.py      "$BMT_ROOT/lib/bmt_lib/"
sudo cp "$STAGING/lib/github_api.py"     "$BMT_ROOT/lib/"

# Managers
sudo cp "$STAGING/sk/bmt_manager.py"  "$BMT_ROOT/managers/sk/"

# Configs
sudo cp "$STAGING/bmt_projects.json"     "$BMT_ROOT/config/"
sudo cp "$STAGING/sk/config/"*           "$BMT_ROOT/config/sk/"

# Templates
sudo cp "$STAGING/sk/config/input_template.json" "$BMT_ROOT/templates/sk/"

# Permissions
sudo chmod -R 755 "$BMT_ROOT"

rm -rf "$STAGING"
echo "VM layout synced to $BMT_ROOT"
REMOTE

# Install Python deps on VM
gcloud compute ssh "$BMT_VM_NAME" --zone="$ZONE" -- \
  "uv pip install google-cloud-storage google-cloud-secret-manager PyGithub PyJWT pydantic tabulate"

echo "Sync complete."
```

### systemd Service: `/etc/systemd/system/bmt-watcher.service`

```ini
[Unit]
Description=BMT Trigger Watcher
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=bmt
WorkingDirectory=/opt/bmt
Environment="PYTHONPATH=/opt/bmt/lib"
Environment="GCS_BUCKET=my-bucket"
Environment="BMT_BUCKET_PREFIX="
Environment="GITHUB_STATUS_TOKEN=..."
ExecStart=/usr/bin/python3 /opt/bmt/bin/vm_watcher.py --bucket ${GCS_BUCKET} --bucket-prefix ${BMT_BUCKET_PREFIX} --exit-after-run
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

---

## Files to Create

| Repo path | VM path | Lines (est.) | Purpose |
|-----------|---------|--------------|---------|
| `remote/lib/bmt_lib/__init__.py` | `lib/bmt_lib/__init__.py` | 5 | Package init |
| `remote/lib/bmt_lib/models.py` | `lib/bmt_lib/models.py` | 100 | Pydantic models |
| `remote/lib/bmt_lib/gcs.py` | `lib/bmt_lib/gcs.py` | 150 | GCS operations + time helpers |
| `remote/lib/bmt_lib/cache.py` | `lib/bmt_lib/cache.py` | 100 | Runner caching |
| `remote/lib/bmt_lib/gate.py` | `lib/bmt_lib/gate.py` | 60 | Gate evaluation |
| `remote/lib/github_api.py` | `lib/github_api.py` | 180 | GitHub auth, status, check runs, comments, markdown |
| `remote/vm_watcher.py` | `bin/vm_watcher.py` | 200 | Refactored watcher |
| `remote/root_orchestrator.py` | `bin/root_orchestrator.py` | 80 | Refactored orchestrator |
| `remote/sk/bmt_manager.py` | `managers/sk/bmt_manager.py` | 250 | Refactored SK manager |
| `devtools/sync_to_vm.sh` | (not deployed) | 50 | Deployment script |
| **Total** | | **~1,175** | |

---

## Scalability Benefits

| Scenario | Before | After |
|----------|--------|-------|
| Add new project | Copy-paste 856-line manager | ~100 lines, use `bmt_lib` |
| Change GCS bucket | Edit 3+ files | Change env var |
| Add new BMT type | Modify monolithic `main()` | Edit `bmt_jobs.toml` |
| Bug fix in GCS logic | Update 4 files | Update `gcs.py` |
| GitHub auth change | Edit `vm_watcher.py` | Edit `github_api.py` |
| Testing | Mock entire manager | Unit test `bmt_lib` modules |

---

## Migration Steps

### Phase 1: Shared libraries and Pydantic models

1. Define Pydantic models in `remote/lib/bmt_lib/models.py` — `RunTrigger`, `CIVerdict`, `BMTJobConfig`, `ProjectConfig`, `FileResult`, `GateResult`.
2. Create `remote/lib/bmt_lib/gcs.py` — `GCSClient` wrapping `google-cloud-storage`. Replace all `gcloud` CLI subprocess calls.
3. Create `remote/lib/bmt_lib/cache.py` and `gate.py`. Extract from existing `bmt_manager.py`.
4. Create `remote/lib/github_api.py` — replace `urllib.request` in `vm_watcher.py` with `PyGithub`. Include `tabulate`-based markdown report rendering.
5. Update `remote/vm_watcher.py`, `remote/root_orchestrator.py`, `remote/sk/bmt_manager.py` to import from `bmt_lib` and `github_api`, use Pydantic models. **No subprocess calls remain except for `kardome_runner` execution.**

### Phase 2: CI scripts migration

1. Refactor `ci/adapters/gcloud_cli.py` → `ci/adapters/gcp.py` — replace `gcloud storage` subprocess calls with `google-cloud-storage` SDK; replace `gcloud compute instances start` with `google-cloud-compute` SDK.
2. Update `ci/commands/run_trigger.py` to emit `RunTrigger` model (validated before upload).
3. Update `ci/commands/wait_verdicts.py` and `ci/commands/verdict_gate.py` to parse `CIVerdict` model.

### Phase 3: GitHub App auth

1. Set up GitHub App, install on repo, store secrets in GCP Secret Manager.
2. Implement GitHub App auth in `github_api.py` with PAT fallback.
3. Wire check run + PR comment into watcher's post-run flow.

### Phase 4: Deployment

1. Create `devtools/sync_to_vm.sh`.
2. Update systemd unit to set `PYTHONPATH=/opt/bmt/lib`.
3. Test end-to-end: trigger CI, verify GitHub status + check run + PR comment.
4. Validate end-to-end with a real PR.

---

## Open Questions

- [ ] Confirm GCP Secret Manager secret names for GitHub App
- [ ] Confirm VM instance name and zone for sync script
- [ ] Confirm dataset WAV file locations for initial sync
- [ ] Keep `bmt_projects.json` on bucket (current: orchestrator downloads at runtime) or pre-stage on VM? Pre-staging is simpler but means adding a project requires a VM redeploy.
