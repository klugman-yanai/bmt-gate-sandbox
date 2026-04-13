# Design: bmt-gcloud Big-Bang Restructure

**Date:** 2026-04-13
**Status:** Approved

## Problem

The codebase has three compounding structural problems that make contributor onboarding needlessly hard:

1. **SDK coupling** — `BmtPlugin` (the interface contributors implement) lives inside the Cloud Run runtime package. Contributors cannot write or test a plugin without installing the entire runtime.
2. **Deep, confusing paths** — the plugin a contributor writes lives at `gcp/stage/projects/sk/plugin_workspaces/default/src/sk_plugin/plugin.py` (8 levels deep). Nothing in that path is self-explanatory.
3. **Misleading names** — `gcp/image/` is the Cloud Run runtime (not a GCP image); `gcp/stage/` is the GCS bucket mirror (not a staging environment); `.github/bmt/` is a full Python CLI package hidden inside GitHub tooling.

## Goal

A contributor with no prior knowledge of the repo should be able to:
1. Clone the repo
2. Run `just setup`
3. Navigate to `plugins/` and understand immediately where to add their plugin
4. Write `plugin.py` against a minimal installable SDK
5. Configure their BMTs in flat JSON files
6. Run `just deploy` and have it work

## Out of scope

- Changes to Cloud Run infrastructure topology
- Changes to GitHub Actions workflow YAML
- Changes to Pulumi/Terraform definitions
- GCS bucket naming or access policies

---

## Architecture

Five coordinated changes, delivered in five independent phases.

---

## Change 1: Extract `sdk/`

**Root issue fix.** The `BmtPlugin` interface and its supporting types are extracted from the runtime into a standalone installable package with no heavy dependencies.

### New package: `sdk/`

```
sdk/
  pyproject.toml        # name = "bmt-sdk"
  bmt_sdk/
    __init__.py         # exports: BmtPlugin, ExecutionContext, PreparedAssets,
                        #          ExecutionResult, ScoreResult, VerdictResult
    plugin.py           # BmtPlugin ABC (unchanged logic)
    context.py          # ExecutionContext (read-only view, no GCS calls)
    results.py          # PreparedAssets, ExecutionResult, ScoreResult, VerdictResult
```

No Pydantic, no GCS client, no GitHub client. Only stdlib + dataclasses.

### Import change

Before: `from gcp.image.runtime.sdk.plugin import BmtPlugin`  
After: `from bmt_sdk import BmtPlugin`

The `runtime/` package declares `bmt-sdk` as a dependency. Contributor plugins import only `bmt-sdk`. Neither depends on the other's internals.

### Contributor development loop

```bash
uv add bmt-sdk          # or pip install bmt-sdk
# write plugin.py locally, test against mock context
# drop into plugins/<project>/
just deploy
```

---

## Change 2: Rename top-level directories

### Before → After

| Before | After | Reason |
|---|---|---|
| `gcp/image/` | `runtime/` | It's the Cloud Run execution runtime, not a GCP image artifact |
| `gcp/stage/` | `plugins/` | It's the contributor plugin space (see Change 3) |
| `.github/bmt/` | `ci/` | Repo-root Python package; `.github/` becomes YAML-only |
| `gcp/__init__.py`, `gcp/README.md` | deleted | `gcp/` namespace removed |

### New top-level layout

```
bmt-gcloud/
  sdk/          ← BmtPlugin interface (installable, minimal deps)
  plugins/      ← Contributor space: one subdirectory per project
  runtime/      ← Cloud Run execution host (loads and runs plugins)
  ci/           ← GitHub Actions CI integration (moved from .github/bmt/)
  infra/        ← Pulumi / Terraform (unchanged)
  tools/        ← Maintainer tooling (unchanged)
  tests/        ← Updated imports
  docs/
  Justfile
  .github/      ← YAML only: workflows/, actions/
```

### `runtime/` internal changes

- `runtime/sdk/` is deleted — types now live in `sdk/`
- `runtime/projects/` is deleted — vestigial empty directory
- All `from gcp.image.runtime.sdk import ...` → `from bmt_sdk import ...`
- All `from gcp.image.config import ...` → `from runtime.config import ...`
- All `from gcp.image.github import ...` → `from runtime.github import ...`
- `runtime/pyproject.toml`: adds `bmt-sdk` as dependency

### `ci/` internal changes

- Directory moves from `.github/bmt/` to `ci/` at repo root
- Package name: `bmt` → `kardome-bmt`
- Module name: `ci` → `kardome_bmt`
- CLI entry point: `uv run bmt` → `uv run kardome-bmt`
- All `from ci import ...` in the package → `from kardome_bmt import ...`

### `.github/` after

Contains only YAML:
```
.github/
  workflows/
  actions/
  actionlint.yaml
  dependabot.yml
```

No `pyproject.toml`, no Python packages.

---

## GCS bucket path impact

`plugins/` replaces `gcp/stage/` as the local mirror. The bucket layout changes to match:

| Before (GCS) | After (GCS) |
|---|---|
| `projects/sk/bmts/false_alarms/bmt.json` | `plugins/sk/false_alarms.json` |
| `projects/sk/plugin_workspaces/default/...` | `plugins/sk/plugin.py` (and siblings) |
| `projects/sk/runner_bundle/kardome_runner` | `plugins/sk/runner` |
| `projects/sk/inputs/<slug>/...` | `plugins/sk/inputs/<slug>/...` |
| `projects/sk/results/<slug>/...` | `plugins/sk/results/<slug>/...` |
| `projects/sk/outputs/<slug>/...` | `plugins/sk/outputs/<slug>/...` |
| `projects/shared/dependencies/...` | `plugins/shared/dependencies/...` |

All `runtime/` code that references bucket paths (`projects/<project>/...`) is updated to `plugins/<project>/...` in Phase 4. Existing GCS bucket objects are migrated as part of Phase 4 deployment.

---

## Change 3: Flatten `plugins/` contributor structure

### Before

```
gcp/stage/projects/sk/
  plugin_workspaces/default/
    plugin.json
    src/sk_plugin/
      plugin.py           # 8 directory levels deep
      sk_scoring_policy.py
  plugins/default/
    sha256-3bb4.../       # published bundle (immutable)
  bmts/
    false_alarms/bmt.json
    false_rejects/bmt.json
  inputs/false_alarms/.keep
  inputs/false_rejects/.keep
  inputs/.keep
  outputs/.keep
  kardome_runner
  mock_kardome_runner
  runner_bundle/kardome_runner
  runner_latest_meta.json
  project.json
```

### After

```
plugins/
  sk/
    plugin.py             # REQUIRED: one BmtPlugin subclass
    false_alarms.json     # REQUIRED: one per BMT, slug = filename stem
    false_rejects.json
    runner                # runner binary (renamed from runner_bundle/kardome_runner)
    project.json          # optional: {description: "..."}
    sk_scoring_policy.py  # contributor adds whatever else they need
  shared/
    dependencies/         # shared .so files (unchanged content)
```

### Rules (enforced by convention + policy test)

| File | Rule |
|---|---|
| `plugin.py` | Must contain exactly one `BmtPlugin` subclass |
| `*.json` (not `project.json`) | Each is a BMT config; slug = filename stem |
| `runner` | Runner binary; located by convention, not config |

### Gone entirely

| Removed | Reason |
|---|---|
| `plugin_workspaces/` | Replaced by flat `plugin.py` at project root |
| `plugins/default/sha256-*/` | Replaced by direct loading (see Change 4) |
| `bmts/<slug>/` subdirectory | BMT configs are flat files at project root |
| `inputs/.keep`, `outputs/.keep` | Data is GCS-only; no repo placeholders needed |
| `kardome_runner`, `mock_kardome_runner` at project root | Duplicate of `runner`; mock is dev-only, handled separately |
| `runner_bundle/` | Renamed to just `runner` |
| `runner_latest_meta.json` | Operational noise; not contributor-relevant |
| `plugin.json` | Replaced by convention (BmtPlugin subclass discovery) |

---

## Change 4: Simplified BMT config + direct plugin loading

### BMT config before (15+ fields)

```json
{
  "schema_version": 1,
  "project": "sk",
  "bmt_slug": "false_rejects",
  "bmt_id": "4a5b6e82-...",
  "enabled": true,
  "plugin_ref": "published:default:sha256-3bb4b2f...",
  "inputs_prefix": "projects/sk/inputs/false_rejects",
  "results_prefix": "projects/sk/results/false_rejects",
  "outputs_prefix": "projects/sk/outputs/false_rejects",
  "runner": {
    "uri": "projects/sk/runner_bundle/kardome_runner",
    "deps_prefix": "projects/shared/dependencies",
    "template_path": "gcp/image/runtime/assets/kardome_input_template.json"
  },
  "execution": {"policy": "adaptive_batch_then_legacy"},
  "plugin_config": { ... }
}
```

### BMT config after (meaningful fields only)

```json
{
  "bmt_id": "4a5b6e82-...",
  "enabled": true,
  "plugin_config": { ... }
}
```

### Derivation rules (applied by `BmtManifest` loader)

| Field | Derived from |
|---|---|
| `project` | Parent directory name (`plugins/sk/` → `sk`) |
| `bmt_slug` | Filename stem (`false_rejects.json` → `false_rejects`) |
| `inputs_prefix` | `plugins/<project>/inputs/<slug>` |
| `results_prefix` | `plugins/<project>/results/<slug>` |
| `outputs_prefix` | `plugins/<project>/outputs/<slug>` |
| `runner.uri` | `plugins/<project>/runner` (convention) |
| `runner.deps_prefix` | `plugins/shared/dependencies` (convention) |
| `runner.template_path` | `runtime/assets/kardome_input_template.json` (constant) |
| `execution.policy` | Default: `adaptive_batch_then_legacy` |
| `plugin_ref` | Removed — runtime loads `plugin.py` directly |

### Direct plugin loading

`runtime/plugin_loader.py` loads `plugin.py` from the project directory:

```python
spec = importlib.util.spec_from_file_location(
    f"bmt_plugin_{project}",       # unique module name per project, no collision
    project_dir / "plugin.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
candidates = [
    cls for cls in vars(module).values()
    if isinstance(cls, type)
    and issubclass(cls, BmtPlugin)
    and cls is not BmtPlugin
]
if len(candidates) != 1:
    raise RuntimeError(
        f"plugins/{project}/plugin.py must define exactly one BmtPlugin subclass, "
        f"found {len(candidates)}: {[c.__name__ for c in candidates]}"
    )
plugin_class = candidates[0]
```

Any sibling `.py` files in the project directory are importable because `project_dir` is added to `sys.path` before exec.

### Audit digest (replaces `plugin_ref` pinning)

`just deploy` computes `sha256` of all `.py` files in `plugins/<project>/`, records it in `project.json` under `plugin_digest`. This provides auditability without requiring contributors to run a separate publish step.

### Migration compat

`plugin_ref: "published:..."` is supported as a fallback in Phase 3 (runtime reads bundle if present). Removed in Phase 5 after all projects are migrated.

---

## Change 5: Naming convention — "Kardome BMT" throughout

| Before | After |
|---|---|
| package `bmt` | `kardome-bmt` |
| `uv run bmt <cmd>` | `uv run kardome-bmt <cmd>` |
| PEX `bmt.pex` | `kardome-bmt.pex` |
| module `ci` (import) | `kardome_bmt` |
| `tests/support/fixtures/paths.py` `github_bmt_root` | `kardome_bmt_root` → `ci/` |

Consistent with existing: `kardome_runner`, `AdaptiveKardomeExecutor`, `mock_kardome_runner`, `legacy_kardome.py`.

---

## Additional cleanup (no new behavior)

| Item | Action |
|---|---|
| `tests/vm/` | Delete — tests dead VM-era stubs |
| `gcp/image/projects/` | Delete — vestigial, only `__pycache__` |
| `gcp/__init__.py` | Delete — `gcp` namespace removed |
| Layout policy tests | Update path assertions to new structure |
| `CLAUDE.md` | Update all path references |
| `docs/architecture.md` | Update diagrams and path references |

---

## Migration phases

Each phase is independently mergeable, green CI before proceeding.

| Phase | Changes | Gate |
|---|---|---|
| 1 | Extract `sdk/`; update `runtime/` imports from `gcp.image.runtime.sdk` → `bmt_sdk` | All tests pass |
| 2 | Rename `gcp/image/` → `runtime/`, `gcp/stage/` → `plugins/`; move `.github/bmt/` → `ci/`; rename package `bmt` → `kardome-bmt` | Layout policy + all tests pass |
| 3 | Rewrite `plugin_loader.py` for direct loading; keep `published:` fallback; simplify `BmtManifest` with derivation | Existing SK BMT loads correctly via both paths |
| 4 | Flatten `plugins/sk/`; simplify SK manifests; add `plugin_digest` to `project.json`; `just deploy` computes digest | SK BMT works end-to-end with new loader |
| 5 | Drop `published:` fallback; delete `plugin_workspaces/`, `sha256-*/`, `runner_bundle/`; delete `tests/vm/` | All tests pass, CI green |

---

## Success criteria

- A new contributor can run `just setup`, read `plugins/`, and write a working `plugin.py` without reading any other source file
- `from bmt_sdk import BmtPlugin` works with no runtime installed
- SK BMT passes end-to-end after Phase 4
- `git ls-files plugins/sk/` shows ≤ 6 files for a fully configured project
- No `gcp/` directory exists after Phase 5
