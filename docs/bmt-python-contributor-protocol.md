# BMT Python contributor protocol

**Contract** for Python benchmarks in this repo: what you ship under **`benchmarks/`**, how Cloud Run invokes your plugin, and how **`kardome_runner`** behaves today (stdout parsing) vs later (structured JSON).

**Prerequisites:** [adding-a-project.md](adding-a-project.md), [contributor-commands.md](contributor-commands.md). **Pipeline:** [architecture.md](architecture.md). **Happy path:** [bmt-first-benchmark.md](bmt-first-benchmark.md).

### SDK boundary (what ships where)

| Location | What it is |
| -------- | ---------- |
| **Cloud Run image** (`backend/`, especially `backend/runtime/sdk/`) | **Stable imports:** `from backend.runtime.sdk import BmtPlugin, …`. Changes need a **new image**. Re-exports: `backend/runtime/sdk/__init__.py`. |
| **`benchmarks/` → GCS** | Plugin package, `bmt.json`, datasets, `kardome_runner`. **Sync the bucket** without necessarily rebuilding the image ([ADR 0004](adr/0004-plugin-sdk-boundary.md)). |
| **`plugin.json` `api_version`** | Must match the plugin class and **`SUPPORTED_PLUGIN_API_VERSIONS`** in the running image, or load fails ([ADR 0006](adr/0006-runtime-plugin-api-version.md)). |

---

## 1. What you own vs what the platform owns

| Layer | Owner | Notes |
| ----- | ----- | ----- |
| **Plugin package** | **You** | `benchmarks/projects/<project>/plugin_workspaces/<plugin>/` → published under `plugins/…`. Exposes **`BmtPlugin`** and your **Pydantic manifest model**. |
| **Dataset** | **You** | Inputs under the benchmark’s inputs prefix. |
| **`bmt.json` on disk** | **Generated** | Must match **`BmtManifest`** wire schema; produce from **your** Pydantic model (§3). |
| **Benchmark folder** | **Layout** | `bmts/<folder>/`; **`bmt_slug`** must match the folder name. |
| **Runner binary** | **Project** | **`kardome_runner`** under stage tree; manifest URIs point at it. |

Runtime flow: build **`ExecutionContext`**, **`prepare`** → **`execute`** → **`score`** → **`evaluate`**. Types: **`backend.runtime.sdk`**.

---

## 2. Python plugin API (`BmtPlugin`)

Contract: **`backend/runtime/sdk/plugin.py`**. Subclass **`BmtPlugin`**, set **`plugin_name`** / **`api_version`** to match **`plugin.json`**, implement **`prepare`**, **`execute`**, **`score`**, **`evaluate`**.

After load: **`validate_against_loaded_manifest`**, then **`api_version`** vs **`SUPPORTED_PLUGIN_API_VERSIONS`**.

**Lifecycle:** after successful **`prepare`**, **`execute`** / **`score`** / **`evaluate`** run in `try`; **`teardown`** in `finally` when **`prepare`** succeeded. If **`prepare`** raises, no **`teardown`**.

**Baseline:** **`score`** / **`evaluate`** accept `baseline`, but the runner still passes **`None`** ([ADR 0005](adr/0005-baseline-scoring-not-loaded.md)).

**Helpers** on the base class: **`log`**, **`require_runner`**, **`prepared_assets_from_context`**, **`runner_env_with_deps`**, **`resolve_runner_template_path`**, **`parse_plugin_config`**, **`resolve_workspace_file`**, **`max_grace_case_failures`**, **`batch_command_timeout_seconds`**, **`execution_failure_result`**.

**Types:** **`ExecutionResult`** / **`CaseResult`** — `backend/runtime/sdk/results.py`. **`ExecutionContext`** — `backend/runtime/sdk/context.py`.

---

## 3. `bmt.json` from a plugin-owned Pydantic model

### 3.1 Wire shape

Parsed as **`BmtManifest`** in **`backend/runtime/models.py`** (`RunnerConfig`, `ExecutionConfig`, `results_prefix` alias, …).

### 3.2 Your model + defaults

**Factory:** `backend.runtime.sdk.manifest_build.build_default_bmt_manifest(…)`. **CLI:** `uv run python -m tools bmt stage manifest-template <project> <folder> [--stdout | --force]`.

Maintain a Pydantic model in the plugin; dump with e.g. `model_dump_json(by_alias=True, indent=2)` to **`benchmarks/projects/<project>/bmts/<folder>/bmt.json`**. Round-trip: `BmtManifest.model_validate_json(...)`.

### 3.3 Execution fields

- **`runner.uri`**, **`deps_prefix`**, **`template_path`**
- **`execution.policy`** — `adaptive_batch_then_legacy`, `batch_json_only`, `legacy_only`; **`AdaptiveKardomeExecutor`** in **`backend/runtime/sdk/kardome.py`**
- **`plugin_config`**

**`plugin_ref`** → published bundle after **`just publish`**.

---

## 4. Native runner: **`kardome_runner` + stdout** (today)

1. Non-zero exit ⇒ failure (subject to grace rules).
2. Log line: default `Hi NAMUH counter = <int>`; override via **`StdoutCounterParseConfig`** in **`backend/runtime/stdout_counter_parse.py`** (`keyword`, `counter_pattern`).
3. Per-case config from **`runner.template_path`**; **`LegacyKardomeStdoutExecutor`** in **`backend/runtime/legacy_kardome.py`**.

**Knobs:** **`BMT_KARDOME_CASE_TIMEOUT_SEC`** — **`backend/config/constants.py`**, **`legacy_kardome.py`**.

**Legacy marker:** **`execution_mode_used`** e.g. **`kardome_legacy_stdout`**.

---

## 5. Structured batch JSON (optional)

Batch command writes JSON → **`ExecutionResult`** when policy allows. See reference **`SkPlugin`**: `benchmarks/projects/sk/plugin_workspaces/default/src/sk_plugin/plugin.py`.

---

## 6. Future: native runner JSON

**Status:** not implemented. Hook: **`backend/runtime/sdk/kardome_runner_json.py`** (raises **`NotImplementedError`** until wired).

---

## 7. Checklist (new Python BMT)

1. Pydantic manifest model with safe defaults; **`bmt_slug`** matches folder.
2. Emit **`bmts/<folder>/bmt.json`** from the model; validate round-trip.
3. **`BmtPlugin`** with consistent **`ExecutionResult`**.
4. Runner meets §4 or §5.
5. **`just test-local`**, **`just publish`**, **`just sync-to-bucket`** — [adding-a-project.md](adding-a-project.md).

---

## See also (source files)

- `backend/runtime/sdk/__init__.py` — re-exports
- `backend/runtime/models.py` — **`BmtManifest`**, configs
- `backend/runtime/sdk/plugin.py`, `manifest_build.py`, `subprocess_batch.py`, `compatibility.py`, `kardome_runner_json.py`
- `backend/runtime/plugin_loader.py`, `plugin_errors.py`, `stdout_counter_parse.py`, `legacy_kardome.py`
- [ADR 0004](adr/0004-plugin-sdk-boundary.md), [ADR 0005](adr/0005-baseline-scoring-not-loaded.md), [ADR 0006](adr/0006-runtime-plugin-api-version.md)
