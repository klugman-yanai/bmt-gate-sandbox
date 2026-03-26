---
name: Repo layout v2
overview: >
  Onboarding-first repo restructure: rename gcp/stage → benchmarks/, gcp/image → backend/;
  flatten per-project layout; decouple CI from runtime imports; reduce root directory count.
  Worktree: refactor/repo-layout.
todos:
  - id: phase-1-portable-ci
    content: "Phase 1: Move .github/bmt → ci/ (src layout, bmt_gate package); decouple gcp.image imports; parameterize paths; drift guard"
    status: pending
  - id: phase-2-paths-single-source
    content: "Phase 2: Update tools/repo/paths.py constants to new roots, update repo_root() heuristic"
    status: pending
  - id: phase-3-rename-roots
    content: "Phase 3: git mv gcp/stage → benchmarks/, gcp/image → backend/; fold schemas/ and cache/ into new roots; update Dockerfile, imports, workspace config"
    status: pending
  - id: phase-4-dual-read
    content: "Phase 4: New discovery logic in stage_paths.py — benchmark.spec.json, flat src/ + plugin.json, releases/, legacy fallbacks"
    status: pending
  - id: phase-5-scaffold-doctor
    content: "Phase 5: Align scaffold + doctor with new layout; reserved slug enforcement"
    status: pending
  - id: phase-6-migrate-sk
    content: "Phase 6: Migrate benchmarks/sk to new per-project layout; update manifests; run full test suite"
    status: pending
  - id: phase-7-bucket-migration
    content: "Phase 7: Rename GCS bucket prefix projects/ → benchmarks/; update all manifest path fields"
    status: pending
  - id: phase-8-docs
    content: "Phase 8: Onboarding one-pager, update CLAUDE.md/CONTRIBUTING.md/README.md, remove stale docs"
    status: pending
  - id: phase-9-cleanup
    content: "Phase 9: Remove dual-read legacy fallbacks after migration window; delete dead code"
    status: pending
isProject: false
---

# Repo layout v2

**Supersedes:**
- `stage_and_repo_redesign_dbb76a70.plan.md` (on `ci/check-bmt-gate`) — layout redesign; fully absorbed here.
- `portable_.github_bmt_refactor_1ddf72bb.plan.md` (on `ci/check-bmt-gate`) — CI decoupling; absorbed as Phases 1–2 here.

Both predecessor plans should be deleted or marked `status: superseded` when this plan merges.

**Worktree:** `refactor/repo-layout` (via `wt switch refactor/repo-layout`)

---

## 1. Goals

1. A new contributor can find **where Python lives** and **where specs live** from the repo root in under 2 minutes — without reading architecture docs.
2. **Scaffold + doctor** teach layout; docs are backup, not prerequisite.
3. Repo root has **≤ 7 visible directories** (down from 9 today).
4. `ci/` package (`bmt-gate`) has **zero imports from the runtime** (`backend.*`), making it portable to consumer repos via git dep.
5. Bucket mirror paths in manifests **match repo-local paths** (1:1 mirror).

## 2. Principles

1. **Names are the curriculum** — `benchmarks/sk/src/` answers "where's my code?" without a README.
2. **Progressive disclosure** — One short onboarding page; architecture is linked, not required.
3. **Convention over configuration** — One blessed layout per project; multi-plugin is an escape hatch.
4. **Tools are documentation** — `doctor` and scaffold print what's wrong, the expected path, and the next command.
5. **Single source of truth** — `tools/repo/paths.py` owns all root constants; nothing else hardcodes them.
6. **Time-bounded compatibility** — Dual-read for legacy paths during migration only; then delete.

## 3. Repo root: before → after

### Before (9 visible dirs + legacy files)

```
bmt-gcloud/
├── cache/                 # Local runner cache (sk runner bundle)
├── docs/
├── gcp/                   # image/ + stage/ — two concerns in one dir
│   ├── image/             # Cloud Run code + SDK
│   └── stage/             # Bucket mirror
├── infra/                 # Pulumi
├── schemas/               # 1 file (bmt_jobs.schema.json)
├── tests/
├── tools/
├── .github/
├── .github-release/
├── CMakeLists.txt         # Legacy
├── CMakePresets.json      # Legacy
├── legacy-workflow.yml    # Legacy
└── ...
```

### After (7 visible dirs)

```
bmt-gcloud/
├── benchmarks/            # 1:1 mirror of gs://<bucket>/benchmarks/
│   ├── sk/                #   contributor workspace (see §4)
│   └── shared/            #   shared native deps + runner templates
├── backend/               # Cloud Run image (was gcp/image/)
│   ├── main.py
│   ├── Dockerfile
│   ├── runtime/           #   execution engine + SDK
│   │   └── sdk/           #   stable plugin surface
│   ├── config/            #   env parsing, constants
│   ├── schemas/           #   ← absorbed from root schemas/
│   └── ...
├── ci/                    # BMT CI package (portable, distributable)
│   ├── pyproject.toml     #   name = "bmt-gate"
│   ├── src/bmt_gate/        #   src layout; import as bmt_gate
│   └── README.md
├── docs/
├── infra/                 # Pulumi IaC
├── tests/
├── tools/                 # Developer CLI, sync, shared libs
├── .github/               # (hidden) workflows + actions only (no Python package)
├── .github-release/       # (hidden) release assembler
└── (config files: pyproject.toml, Justfile, ...)
```

**What moved:**
| Old | New | Reason |
|---|---|---|
| `gcp/image/` | `backend/` | One word, clear boundary: "the service that runs your benchmarks" |
| `gcp/stage/` | `benchmarks/` | Matches bucket prefix; name says what's inside |
| `gcp/__init__.py` | *(deleted)* | No more `gcp` namespace package |
| `schemas/` | `backend/schemas/` | One file; reduce root clutter |
| `cache/sk/` | `benchmarks/sk/runner/` | Runner artifacts belong with the project |
| `gcp/image/runtime/assets/` | *(deleted)* | Only file (`kardome_input_template.json`) moves to `benchmarks/shared/templates/` |
| `gcp/image/bmt_runtime/` | *(deleted)* | Empty dir; build artifact of pip package name. Not real code. |
| `gcp/image/bmt_runtime.egg-info/` | *(deleted / .gitignore)* | Build artifact |
| `CMakeLists.txt`, `CMakePresets.json` | *(deleted or .github-release/)* | Legacy; not used by Python toolchain |
| `legacy-workflow.yml` | *(deleted)* | Legacy |

## 4. Per-project layout: `benchmarks/<project_id>/`

### Single-plugin project (default — what scaffold generates)

```
benchmarks/sk/
├── project.json                       # Identity + metadata (optional)
├── README.md                          # Scaffold-generated, project-specific
│
├── src/                               # Default plugin Python source
│   └── sk_plugin/
│       ├── __init__.py
│       ├── plugin.py                  #   class SkPlugin(BmtPlugin)
│       └── sk_scoring_policy.py
│
├── plugin.json                        # Plugin manifest (at project root)
│
├── releases/                          # Published (immutable) plugin bundles
│   └── sha256-<hex>/
│       ├── plugin.json
│       └── src/sk_plugin/…
│
├── false_alarms/                      # Benchmark slug = folder name
│   └── benchmark.spec.json            #   (same BmtManifest model)
│
├── false_rejects/
│   └── benchmark.spec.json
│
├── inputs/                            # Datasets (bucket-synced, not in git)
│   ├── false_alarms/*.wav
│   └── false_rejects/*.wav
│
├── outputs/                           # CI-written
├── results/                           # CI-written
│
├── runner/                            # Native runner + libs (flat, same dir)
│   ├── kardome_runner
│   └── libKardome.so
│
└── ci/                                # CI metadata
    ├── runner_meta.json
    └── runner.slsa.json
```

### Multi-plugin project (escape hatch — not default)

```
benchmarks/<id>/
├── plugins/
│   ├── scoring/
│   │   ├── plugin.json
│   │   ├── src/<pkg>/…
│   │   └── releases/sha256-<hex>/…
│   └── analysis/
│       └── ...
├── <slug>/benchmark.spec.json
└── ...
```

When `plugins/` exists, runtime reads from `plugins/<name>/plugin.json` instead of root `plugin.json`. Root-level `src/` is absent.

### Reserved slugs (cannot be benchmark folder names)

`src`, `plugins`, `releases`, `inputs`, `outputs`, `results`, `runner`, `ci`,
`plugin_workspaces`, `bmts`, `benchmarks`, `packages`, `shared`

Enforced at scaffold time (reject) and doctor time (error).

### Manifest path fields (updated)

```jsonc
{
  "schema_version": 1,
  "project": "sk",
  "bmt_slug": "false_alarms",
  "plugin_ref": "published:default:sha256-e250…",
  "inputs_prefix": "benchmarks/sk/inputs/false_alarms",
  "results_prefix": "benchmarks/sk/results/false_alarms",
  "outputs_prefix": "benchmarks/sk/outputs/false_alarms",
  "runner": {
    "uri": "benchmarks/sk/runner/kardome_runner",
    "deps_prefix": "benchmarks/shared/dependencies",
    "template_path": "benchmarks/shared/templates/kardome_input_template.json"
  }
}
```

### File rename summary

| Old | New |
|---|---|
| `projects/<id>/bmts/<slug>/bmt.json` | `<slug>/benchmark.spec.json` |
| `projects/<id>/plugin_workspaces/default/` | root `plugin.json` + `src/` |
| `projects/<id>/plugins/default/sha256-…/` | `releases/sha256-…/` |
| `projects/<id>/runner_bundle/{binary,lib/…}` | `runner/{binary,lib.so}` (flat) |
| `projects/<id>/runner_meta.json` | `ci/runner_meta.json` |
| `projects/<id>/runner.slsa.json` | `ci/runner.slsa.json` |

## 5. Python module namespace

| Old import | New import |
|---|---|
| `from gcp.image.runtime.sdk import BmtPlugin` | `from backend.runtime.sdk import BmtPlugin` |
| `from gcp.image.runtime.models import BmtManifest` | `from backend.runtime.models import BmtManifest` |
| `from gcp.image.config.constants import STATUS_CONTEXT` | `from backend.config.constants import STATUS_CONTEXT` |
| `python -m gcp.image.main` | `python -m backend.main` |

CI package (`.github/bmt/ci/`) imports **none** of these — it uses its own contract modules (Phase 1).

## 6. `tools/repo/paths.py` (target state)

```python
DEFAULT_STAGE_ROOT  = Path("benchmarks")    # 1:1 mirror of gs://<bucket>/benchmarks/
DEFAULT_CONFIG_ROOT = Path("backend")       # Cloud Run image
DEFAULT_BMT_ROOT    = Path("local")         # Optional local native deps (if needed)

GITHUB_BMT_ROOT = Path(".github/bmt")       # unchanged
INFRA_PULUMI    = Path("infra/pulumi")      # unchanged
```

`repo_root()` heuristic: walk up to find `pyproject.toml` + `backend/` + `infra/`.

## 7. Discovery order (dual-read migration window)

**Benchmark specs** (checked in order, first match wins):
1. `benchmarks/<id>/<slug>/benchmark.spec.json` ← new canonical
2. `benchmarks/<id>/benchmarks/<slug>/bmt.json` ← v2 legacy
3. `benchmarks/<id>/bmts/<slug>/bmt.json` ← v1 legacy

**Plugin source:**
1. `benchmarks/<id>/plugin.json` + `benchmarks/<id>/src/` ← new flat
2. `benchmarks/<id>/plugin_workspaces/<name>/plugin.json` ← v1 legacy

**Published bundles:**
1. `benchmarks/<id>/releases/sha256-…/` ← new
2. `benchmarks/<id>/plugins/<name>/sha256-…/` ← v1 legacy

After migration window closes, only #1 in each group remains.

---

## 8. Implementation phases

### Phase 1: `portable-ci-package`

**Goal:** Move `.github/bmt/` → `ci/` at repo root with src layout (`ci/src/bmt_gate/`). Decouple all `gcp.image` imports. Replace hardcoded `gcp/stage`/`gcp/image` paths with env-driven defaults. This MUST complete before the root rename (Phase 4) so CI doesn't break during the `git mv`.

**Step 1 — Move and restructure:**
- `git mv .github/bmt/ ci/`
- Restructure to src layout: `ci/src/bmt_gate/` (rename Python package `ci` → `bmt_gate`)
- Update `ci/pyproject.toml`: `name = "bmt-gate"`, `[project.scripts] bmt = "bmt_gate.driver:main"`, remove `bmt-gcloud` dep
- Update root `pyproject.toml` workspace members: `.github/bmt` → `ci`
- Update all workflow `uv run` invocations that referenced the old package location

**Step 2 — Add CI-owned contract modules (replace `gcp.image` imports):**
- `ci/src/bmt_gate/env_contract.py` — all `ENV_*`, `STATUS_CONTEXT`, `DEFAULT_CLOUD_RUN_REGION` (from `gcp.image.config.constants`)
- `ci/src/bmt_gate/gate.py` — `GateDecision` StrEnum + `DECISION_*` (from `gcp.image.config.decisions`)
- `ci/src/bmt_gate/gcp_links.py` — `workflow_execution_console_url` (from `gcp.image.github.reporting`)
- `ci/src/bmt_gate/env_parse.py` — `is_truthy_env_value`, `sanitize_run_id` (from `gcp.image.config.{env_parse,value_types}`)

**Step 3 — Rewrite imports in existing modules:**
- `ci/src/bmt_gate/config.py` — 12 imports → `bmt_gate.env_contract`
- `ci/src/bmt_gate/core.py` — imports → `bmt_gate.{gate,env_parse,env_contract}`
- `ci/src/bmt_gate/runner.py` — `is_truthy_env_value` → `bmt_gate.env_parse`
- `ci/src/bmt_gate/workflow_dispatch.py` — all `gcp.image` imports → `bmt_gate.*`

**Step 4 — Parameterize hardcoded paths:**
- `ci/src/bmt_gate/runner.py` — `BMT_STAGE_ROOT` env (default: `"benchmarks"`)
- `ci/src/bmt_gate/preset.py` — parameterize SK runner path via stage root
- `ci/src/bmt_gate/handoff_dataset.py` — `BMT_STAGE_ROOT`
- `ci/src/bmt_gate/core.py` — `DEFAULT_CONFIG_ROOT` from env or `"backend"`

**Step 5 — Fix workflows and actions:**
- `.github/workflows/bmt-handoff.yml` — replace inline `from gcp.image.config.constants import STATUS_CONTEXT` with `uv run bmt` or workflow var; update message strings and sparse-checkout patterns
- `.github/workflows/internal/bmt-image-build.yml` — path trigger `gcp/image/**` → `backend/**`
- `.github/actions/check-image-up-to-date/action.yml` — `AFFECTED_PATHS` array

**Step 6 — Drift guard + tests:**
- `tests/ci/test_ci_contract_parity.py` — assert CI contract values match `backend.*` values
- Update existing `tests/ci/` imports from `ci.*` → `bmt_gate.*`

**Distribution:** This repo uses `ci/` as a uv workspace member. Prod repo consumes via git dep:
```toml
[tool.uv.sources]
bmt-gate = { git = "https://github.com/klugman-yanai/bmt-gcloud", subdirectory = "ci", tag = "ci/v0.1.0" }
```

**Run:**
```bash
rg 'gcp\.image|from gcp' ci/             # expect: 0 matches
rg 'gcp/stage|gcp/image' ci/ .github/    # expect: 0 matches (except comments/docs)
uv sync && uv run bmt --help
uv run pytest tests/ci/ -v
```

---

### Phase 2: `paths-single-source`

**Goal:** `tools/repo/paths.py` is the single source of truth for new root names.

**Files modified:**
- `tools/repo/paths.py`:
  - `DEFAULT_STAGE_ROOT = Path("benchmarks")`
  - `DEFAULT_CONFIG_ROOT = Path("backend")`
  - `DEFAULT_BMT_ROOT = Path("local")`
  - `repo_root()` → detect `backend/` instead of `gcp/`
  - `WorkspaceLayout.default()` updated
- Any tool that imports `DEFAULT_STAGE_ROOT` / `DEFAULT_CONFIG_ROOT` directly (grep and verify)

**Run:**
```bash
uv run python -c "from tools.repo.paths import WorkspaceLayout; print(WorkspaceLayout.default())"
```

---

### Phase 3: `rename-roots`

**Goal:** The big `git mv`. Safe now because CI (Phase 1) and path constants (Phase 2) are already updated.

**Steps:**
```bash
# Directory moves
git mv gcp/image backend
git mv gcp/stage benchmarks
git mv schemas/bmt_jobs.schema.json backend/schemas/bmt_jobs.schema.json
rm -rf gcp/             # __init__.py, README.md
rm -rf schemas/         # now empty
# Migrate cache/sk/ runner artifacts → benchmarks/sk/runner/ (manual)
# Delete legacy root files if confirmed dead: CMakeLists.txt, CMakePresets.json, legacy-workflow.yml
```

**Files modified (mechanical find-replace):**
- All `from gcp.image` → `from backend` (across `backend/`, `tools/`, `tests/`)
- `backend/Dockerfile` — `COPY backend/...`, entrypoint `python -m backend.main`
- Root `pyproject.toml` — workspace member `backend/` instead of `gcp/image/`
- `pyrightconfig.json`, `ruff.toml` — path excludes
- `tools/repo/gcp_layout_policy.py` — expect `backend/` and `benchmarks/` (rename file to `layout_policy.py`)
- `tools/repo/just_image_gate.py` — `IMAGE_GIT_PATHSPECS = ("backend", ...)`
- `tools/cli/maintainer_cmd.py` — type-check path references
- `Justfile` — any `gcp/` references
- `CLAUDE.md` — path table

**Run:**
```bash
rg 'gcp/image|gcp/stage|gcp\.image|gcp\.stage' --type py  # expect: 0
rg 'gcp/' . --glob '!.git' --glob '!docs/plans/*'         # audit remaining
uv sync && ruff check . && ruff format --check .
uv run pytest tests/ -v
```

---

### Phase 4: `dual-read`

**Goal:** `backend/runtime/stage_paths.py` discovers both new and legacy project layouts.

**Files modified:**
- `backend/runtime/stage_paths.py`:
  - `iter_bmt_manifest_paths()` — check `<slug>/benchmark.spec.json` first, fall back to `bmts/<slug>/bmt.json`
  - `resolve_plugin_workspace_dir()` — check root `plugin.json` + `src/` first, fall back to `plugin_workspaces/<name>/`
  - `resolve_published_plugin_dir()` — check `releases/sha256-…/` first, fall back to `plugins/<name>/sha256-…/`
- `backend/runtime/project_manifest.py` — adapt to new paths
- Reserved slug validation function (used by scaffold + doctor)

**Run:**
```bash
uv run pytest tests/bmt/ -v -k "stage_path or manifest"
```

---

### Phase 5: `scaffold-doctor`

**Goal:** `tools bmt stage` commands generate and validate the new layout.

**Files modified:**
- `tools/bmt/scaffold.py`:
  - `add_project()` generates: `src/<pkg>/`, root `plugin.json`, `<slug>/benchmark.spec.json`, `runner/`, `ci/`
  - Reject reserved slugs at creation time
- `tools/bmt/stage_doctor.py`:
  - Validate new layout (root `plugin.json`, `<slug>/benchmark.spec.json`, `releases/`)
  - Warn on legacy paths with actionable migration commands: `"Found bmts/foo/bmt.json → run: tools bmt migrate <project>"`
- `tools/bmt/publisher.py` — publish to `releases/sha256-…/` instead of `plugins/<name>/sha256-…/`
- CLI help text in `tools/cli/bmt_cmd.py`, `tools/cli/add_cmd.py`, `tools/cli/publish_cmd.py`

**Run:**
```bash
uv run python -m tools bmt stage project test-scaffold --dry-run
uv run python -m tools bmt stage doctor sk
uv run pytest tests/bmt/ -v
```

---

### Phase 6: `migrate-sk`

**Goal:** Real project validates everything end-to-end.

**Steps:**
- Flatten `benchmarks/sk/plugin_workspaces/default/` → `benchmarks/sk/src/` + `benchmarks/sk/plugin.json`
- Move `benchmarks/sk/bmts/false_alarms/bmt.json` → `benchmarks/sk/false_alarms/benchmark.spec.json` (repeat for each benchmark)
- Move `benchmarks/sk/plugins/default/sha256-…/` → `benchmarks/sk/releases/sha256-…/`
- Flatten `benchmarks/sk/runner_bundle/{kardome_runner,lib/libKardome.so}` → `benchmarks/sk/runner/{kardome_runner,libKardome.so}`
- Move `benchmarks/sk/runner_meta.json` → `benchmarks/sk/ci/runner_meta.json`
- Move `benchmarks/sk/runner.slsa.json` → `benchmarks/sk/ci/runner.slsa.json`
- Update `plugin_ref` digest references in benchmark.spec.json files
- Delete empty legacy dirs (`bmts/`, `plugin_workspaces/`, `plugins/`, `runner_bundle/`)

**Run:**
```bash
uv run python -m tools bmt stage doctor sk
uv run pytest tests/ -v
just test
```

---

### Phase 7: `bucket-migration`

**Goal:** GCS bucket matches new layout. Coordinate with any running CI.

**Steps:**
1. Pause CI (no active bmt-handoff runs)
2. `gsutil -m cp -r gs://<bucket>/projects/ gs://<bucket>/benchmarks/` (copy first, not move)
3. Verify `benchmarks/` prefix works with a test handoff
4. `gsutil -m rm -r gs://<bucket>/projects/` (remove old prefix)
5. Update any Pulumi/workflow references to the bucket prefix

**Note:** `triggers/` and `bmt_root_results.json` stay at bucket root — they're not under `projects/` today and remain unchanged.

---

### Phase 8: `docs`

**Goal:** Documentation reflects reality (written AFTER migration, not before).

**Files created:**
- `docs/bmt-onboarding.md` — single-screen Layer 1 doc:
  1. Change behavior → edit `benchmarks/<project>/src/…`
  2. Add a benchmark → `uv run python -m tools bmt stage bmt <project> <slug>`
  3. Check your tree → `uv run python -m tools bmt stage doctor <project>`
  4. Test locally → `just test-local <project> <benchmark>`
  5. Sync → `just sync-to-bucket`

**Files modified:**
- `README.md` — one paragraph: "`benchmarks/` = your work, `backend/` = the service"
- `CONTRIBUTING.md` — setup + daily commands updated
- `CLAUDE.md` — path table, code layout, recipes
- `.github/README.md` — consumer story: no `gcp/image` required
- Remove or archive stale docs that reference old layout

---

### Phase 9: `cleanup`

**Goal:** Remove dual-read fallbacks after migration window (suggest: 2 weeks after Phase 6 merges).

**Files modified:**
- `backend/runtime/stage_paths.py` — remove legacy fallback paths (#2 and #3 from §7)
- `tools/bmt/stage_doctor.py` — remove legacy warnings (hard error only)
- `tools/bmt/scaffold.py` — remove any legacy compatibility
- Delete stale tests that exercised legacy paths
- Remove `DEFAULT_RUNTIME_ROOT` alias from `tools/repo/paths.py`

---

## 9. Optional future phases (not part of this plan)

- **`bmt-runtime-pkg`** — Rename Python package from `backend.*` → `bmt_runtime.*` for cleaner plugin imports. High churn; defer unless the import path is a real contributor pain point.

## 10. What this plan does NOT change

- `infra/` location (operators expect it at root)
- `.github/bmt/` location (GitHub convention)
- Bucket-internal structure under `triggers/`, `bmt_root_results.json` (not project data)
- Google Workflow job names (`bmt-control`, `bmt-task-*`)
- Plugin SDK API surface (classes, methods, signatures — only the import path changes)

## 11. Risk log

| Risk | Mitigation |
|---|---|
| CI breaks during rename | Phases 1–2 decouple CI first; rename is safe |
| Bucket migration data loss | Copy-then-delete (Phase 8); pause CI during cutover |
| Stale imports missed | `rg 'gcp\.image\|gcp/stage\|gcp/image' --type py` after Phase 4 |
| Consumer repos (core-main) break | `.github/bmt/` is portable after Phase 1; no `gcp.image` dependency |
| Legacy layout lingers forever | Phase 10 removes fallbacks on a fixed date |
| Contributors confused by two layouts during migration | Doctor prints migration commands; scaffold only generates new layout |
