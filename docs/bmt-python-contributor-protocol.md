# BMT Python contributor protocol

This document is the **contract** for implementing benchmarks in Python inside this repo: what you ship in `gcp/stage/`, how the Cloud Run runtime calls your code, and how the native **`kardome_runner`** binary is expected to behave **today** (log parsing) versus **later** (structured JSON).

**Prerequisites:** scaffold and file layout — [adding-a-project.md](adding-a-project.md), [contributor-commands.md](contributor-commands.md). **Pipeline context:** [architecture.md](architecture.md).

**Short happy path (clone → first benchmark):** [bmt-first-benchmark.md](bmt-first-benchmark.md).

### SDK boundary (what ships where)

| Location | What it is |
| -------- | ---------- |
| **Cloud Run image** (`gcp/image/`, especially `gcp/image/runtime/sdk/`) | **Stable imports** for plugins: `from gcp.image.runtime.sdk import BmtPlugin, …`. Changing this code requires **deploying a new image**. Re-exported names live in `gcp/image/runtime/sdk/__init__.py`. |
| **`gcp/stage/` → GCS** | **Your** plugin package, `bmt.json`, datasets, `kardome_runner`. Sync the bucket to update remote runs **without** an image rebuild (see [ADR 0004](adr/0004-plugin-sdk-boundary.md)). |
| **`plugin.json` `api_version`** | Must match your plugin class **and** be listed in **`SUPPORTED_PLUGIN_API_VERSIONS`** for the running image, or load fails with `PluginLoadError` ([ADR 0006](adr/0006-runtime-plugin-api-version.md)). |

---

## 1. What you own vs what the platform owns

| Layer | Owner | Notes |
| ----- | ----- | ----- |
| **Plugin package** | **You** | Under `gcp/stage/projects/<project>/plugin_workspaces/<plugin>/`; published to `plugins/…`. Exposes **`BmtPlugin`** and (per below) the **Pydantic model** that defines each benchmark’s manifest. |
| **Dataset** | **You** | Inputs (e.g. WAVs) under the benchmark’s inputs prefix; quality and layout are your responsibility. |
| **`bmt.json` on disk** | **Generated artifact** | Not treated as hand-maintained source of truth. It must match the **wire schema** the runtime loads (`BmtManifest`), but **you produce it from a Pydantic model you own** in the plugin (§3). |
| **Benchmark folder** | **Platform / layout** | `bmts/<folder>/` exists in the stage tree so planners and uploads have a stable path; you **materialize** `bmt.json` there from your model (CLI, script, or `model_dump_json`). The JSON field `bmt_slug` must match that folder name. |
| **Runner binary** | **Project / release** | **`kardome_runner`** (and deps) live under the stage tree; URIs in the manifest point at them. Defaults on your Pydantic model should make the common preset **safe without editing every benchmark by hand**. |

The runtime loads your plugin, builds an **`ExecutionContext`**, calls **`prepare`** then **`execute`**, then **`score`** and **`evaluate`**. Those types live under `gcp/image/runtime/sdk/`.

---

## 2. Python plugin API (`BmtPlugin`)

The stable abstract contract lives in **`gcp/image/runtime/sdk/plugin.py`**. You subclass **`BmtPlugin`**, set **`plugin_name`** and **`api_version`** to match **`plugin.json`**, and implement **`prepare`**, **`execute`**, **`score`**, and **`evaluate`**.

After load, the runtime calls **`validate_against_loaded_manifest`** so class attributes and **`plugin.json`** cannot drift silently, then checks **`api_version`** against **`SUPPORTED_PLUGIN_API_VERSIONS`**.

**Lifecycle:** after a successful **`prepare`**, the runtime runs **`execute`**, **`score`**, and **`evaluate`** inside a `try`, and always calls **`teardown`** in `finally` if `prepare` returned—even when **`execute`** (or later steps) raise. If **`prepare`** raises, **`teardown`** is not called. Override **`teardown`** to release temp resources.

**Baseline:** **`score`** / **`evaluate`** still accept a `baseline` argument, but the benchmark runner **does not load a baseline yet**—it always passes `None` ([ADR 0005](adr/0005-baseline-scoring-not-loaded.md)).

**Framework helpers** (concrete methods on the base class—reuse instead of re-implementing):

- **`log`** — logger for the plugin module.
- **`require_runner`**, **`prepared_assets_from_context`**, **`runner_env_with_deps`**, **`resolve_runner_template_path`** — runner and path conventions shared with the Kardome legacy executor.
- **`parse_plugin_config(context, PydanticModel)`** — validate **`plugin_config`** with a small Pydantic type (`extra="ignore"` on the model is typical).
- **`resolve_workspace_file`**, **`max_grace_case_failures`**, **`batch_command_timeout_seconds`** — safe workspace-relative paths, grace parsing, and batch subprocess TTL from **`BATCH_COMMAND_TIMEOUT_SEC`**.
- **`execution_failure_result`** — turn an unexpected exception in **`execute`** into a single failed **`CaseResult`** and a standard **`raw_summary`** flag (**`plugin_execute_exception`**); use it in a top-level **`try`/`except`** so **`score`** / **`evaluate`** can branch consistently.

**Normalized execution output** is an **`ExecutionResult`**: `execution_mode_used`, `case_results` (`CaseResult` per input: `exit_code`, `status`, `metrics`, `error`, …), optional `raw_summary`. See `gcp/image/runtime/sdk/results.py`.

**Context** (`ExecutionContext`) carries `bmt_manifest` (including **`plugin_config`**), paths for workspace, dataset, outputs, logs, runner, and deps. See `gcp/image/runtime/sdk/context.py`.

You usually implement **`BmtPlugin` once per project plugin**; differences between benchmarks are expressed as **data** on the Pydantic manifest model (defaults + overrides), not as ad hoc JSON edits.

---

## 3. `bmt.json` from a **plugin-owned Pydantic model**

### 3.1 Canonical wire shape (platform)

On Cloud Run, the benchmark manifest (`bmt.json`) is parsed as **`BmtManifest`** in `gcp/image/runtime/models.py` (with `RunnerConfig`, `ExecutionConfig`, `results_prefix` alias, etc.). That type is the **contract with the executor**—field names and types must stay compatible.

### 3.2 Your responsibility: model + safe defaults

**Reference factory (optional):** `gcp.image.runtime.sdk.manifest_build.build_default_bmt_manifest(project, benchmark_folder_name, …)` returns a validated `BmtManifest` with the same defaults as scaffolding. **CLI:** `uv run python -m tools bmt stage manifest-template <project> <folder> [--stdout | --force]` writes or prints that JSON.

**You maintain a Pydantic model in your plugin package** (e.g. `sk_plugin/bmt_manifest_spec.py`) that **creates** valid `BmtManifest` data:

- Prefer **subclassing** `BmtManifest` and overriding only what you need, **or** a thin wrapper whose `.build(...)` returns `BmtManifest` after `model_validate`.
- Put **safe defaults** on the model: `runner=RunnerConfig(...)`, `execution=ExecutionConfig(...)`, sensible `plugin_config`, and stable prefix patterns so a **new benchmark folder** does not require copying JSON by hand.
- Serialize the file with Pydantic v2, respecting the **`results_prefix`** alias, for example:

  `manifest.model_dump_json(by_alias=True, indent=2)`  

  (or build a `BmtManifest` instance and dump that), then write to `gcp/stage/projects/<project>/bmts/<folder>/bmt.json`.

- **Round-trip check** in CI or locally: `BmtManifest.model_validate_json(path.read_text())` so drift from the wire schema fails fast.

Scaffold commands (e.g. **`just add`**, **`tools bmt stage bmt`**) may still drop an initial **`bmt.json`**; treat that as a **template** and **replace or regenerate** from your plugin model before you rely on the benchmark in production.

### 3.3 Fields that drive execution (reference)

These are the same `BmtManifest` fields the runtime reads; they should come from your model’s defaults or per-benchmark fields:

- **`runner.uri`**, **`runner.deps_prefix`**, **`runner.template_path`**
- **`execution.policy`** — `adaptive_batch_then_legacy`, `batch_json_only`, `legacy_only`; see `AdaptiveKardomeExecutor` in `gcp/image/runtime/sdk/kardome.py`
- **`plugin_config`** — used by your plugin and shared helpers (stdout parsing, batch command, grace limits)

**`plugin_ref`** must point at a published plugin bundle after **`just publish`** (your publisher step can set this field from the model when you cut a release).

---

## 4. Current native runner contract: **`kardome_runner` + stdout logs**

**Today**, the reference path (e.g. SK’s plugin) runs the **`kardome_runner`** process **per case**, captures **combined stdout/stderr to a log file**, checks **process exit code**, and extracts a **numeric counter** from the log text using a regex (fragile by design until JSON lands).

### 4.1 What the runner must satisfy

1. **Exit code** — non-zero ⇒ case failure (subject to plugin grace rules).
2. **Log line for scoring** — by default the runtime looks for a line matching  
   `Hi <keyword> counter = <integer>`  
   with default **keyword `NAMUH`**. The keyword and regex are configurable via **`plugin_config`** using **`StdoutCounterParseConfig`** (`gcp/image/runtime/stdout_counter_parse.py`): fields **`keyword`**, optional **`counter_pattern`** (full regex; last capture group is the integer).
3. **Input** — a per-case JSON config derived from **`runner.template_path`**; path placeholders are rewritten for each WAV/input (see `LegacyKardomeStdoutExecutor` in `gcp/image/runtime/legacy_kardome.py`).

### 4.2 Operational knobs

- Per-case timeout: environment **`BMT_KARDOME_CASE_TIMEOUT_SEC`** (see `gcp/image/config/constants.py` and `legacy_kardome.py`).
- **`plugin_config`** may include **`max_grace_case_failures`** and other plugin-specific keys documented in your project’s plugin module.

### 4.3 Why this is “legacy”

Parsing human-oriented logs breaks when wording, locale, or logging format changes. **`execution_mode_used`** values such as **`kardome_legacy_stdout`** mark this path in **`ExecutionResult`**.

---

## 5. Structured batch JSON (optional, today)

Some plugins can run a **batch command** that writes a **JSON file** listing per-case outcomes; the runtime parses that into **`ExecutionResult`** (e.g. `kardome_batch_json`) when **`execution.policy`** allows and the file is present. This reduces reliance on per-file log regex for those benchmarks but is still a separate mechanism from **native runner JSON on stdout**.

Concrete keys (e.g. **`batch_command`**, **`batch_results_relpath`**) are defined by the project plugin; see the reference **`SkPlugin`** in `gcp/stage/projects/sk/plugin_workspaces/default/src/sk_plugin/plugin.py`.

---

## 6. Future: native **`kardome_runner` JSON result**

**Goal:** `kardome_runner` (or a wrapper) emits a **single, versioned JSON document** per invocation (or a documented stream contract) so the runtime can build **`CaseResult`** / **`ExecutionResult`** without regex over logs.

**Status:** **Not implemented.** The adapter hook is reserved in code: `gcp/image/runtime/sdk/kardome_runner_json.py`. Calling it raises **`NotImplementedError`** until the schema and runtime wiring are agreed and implemented.

**Design direction (for when implemented):**

- Define a small **JSON schema version** field and stable field names for `exit_code`, `case_id`, `metrics`, `status`, `error`, etc.
- Map JSON → existing **`ExecutionResult`** / **`CaseResult`** types so **`score`** / **`evaluate`** stay unchanged.
- Keep **exit code** as a secondary signal (process vs payload) until the binary is trusted to always emit valid JSON.
- **`execution.policy`** (or a successor) would gain a mode such as **`native_json`** that prefers this path over log parsing.

---

## 7. Checklist for a new Python BMT

1. Add or extend a **Pydantic manifest model** in the **plugin package** with **safe defaults** for `runner`, `execution`, `plugin_config`, and path prefixes; include the **benchmark folder name** (or args) that builds a full **`BmtManifest`**-compatible payload (wire field `bmt_slug` must match that folder).
2. **Emit `bmts/<folder>/bmt.json`** from that model (`model_dump_json` / validate round-trip); do not rely on hand-edited JSON as the source of truth.
3. Implement or extend **`BmtPlugin`**; ensure **`execute`** returns **`ExecutionResult`** consistent with your scoring.
4. Confirm **`kardome_runner`** meets §4 (or batch JSON §5) for this benchmark.
5. **`just test-local`**, **`just publish`**, **`just sync-to-bucket`** — see [adding-a-project.md](adding-a-project.md).

---

## See also

- `gcp/image/runtime/sdk/__init__.py` — **blessed re-exports** for plugin code
- `gcp/image/runtime/models.py` — **`BmtManifest`**, **`RunnerConfig`**, **`ExecutionConfig`** (wire schema for `bmt.json`)
- `gcp/image/runtime/sdk/plugin.py` — **`BmtPlugin`** (abstract API + concrete framework helpers)
- `gcp/image/runtime/sdk/manifest_build.py` — **`build_default_bmt_manifest`**
- `gcp/image/runtime/sdk/subprocess_batch.py` — **`run_subprocess_in_workspace`** (batch commands)
- `gcp/image/runtime/sdk/compatibility.py` — **`SUPPORTED_PLUGIN_API_VERSIONS`**
- [ADR 0004](adr/0004-plugin-sdk-boundary.md), [ADR 0005](adr/0005-baseline-scoring-not-loaded.md), [ADR 0006](adr/0006-runtime-plugin-api-version.md)
- `gcp/image/runtime/plugin_loader.py` / `plugin_errors.py` — load path and **`PluginLoadError`** (e.g. identity mismatch)
- `gcp/image/runtime/stdout_counter_parse.py` — stdout counter **`keyword`** / **`counter_pattern`**
- `gcp/image/runtime/legacy_kardome.py` — per-case subprocess + log parsing
- `gcp/image/runtime/sdk/kardome_runner_json.py` — **future** JSON adapter (**`NotImplementedError`**)
