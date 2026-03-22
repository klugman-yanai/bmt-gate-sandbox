# gcp/ Data Separation and Dev Workflow

**Status:** Proposed
**Urgency:** MOST URGENT + HIGH IMPACT
**Goal:** Establish a clean split between BMT code/config (fully local, editable) and BMT data (WAV audio corpora, potentially 30 GB per project) so that contributors can work against a real directory tree without storing large binary files locally. Fix 3 pre-existing bugs that block development.

---

## Reading Guide

This document is part of a 5-document roadmap series, split from the former holistic serverless migration plan. Documents are ordered by urgency and dependency.

| # | Document | Focus | Urgency |
|---|----------|-------|---------|
| **1** | **gcp-data-separation-and-dev-workflow.md** (this) | Bug fixes, manifest, FUSE, WorkspaceLayout | **MOST URGENT** |
| 2 | [gcp-image-refactor.md](gcp-image-refactor.md) | Constants, types, entrypoint, decoupling | HIGH |
| 3 | [contributor-api-and-manager-contract.md](contributor-api-and-manager-contract.md) | Protocol, BaseBmtManager, contributor workflow | HIGH |
| 4 | [cloud-run-containerization-and-infra.md](cloud-run-containerization-and-infra.md) | Dockerfile, Cloud Run, Pulumi, coordinator | MEDIUM |
| 5 | [ci-cutover-and-vm-decommission.md](ci-cutover-and-vm-decommission.md) | Direct API, shadow testing, cutover | LOWER |

**Dependency chain:** 1 → 2+3 → 4 → 5

**This document has no upstream dependencies.** It must be completed before documents 2 and 3 can begin.

---

## Pre-existing Bugs (Block Everything)

These bugs were discovered during design review and must be fixed before any FUSE or manifest tooling is layered on top.

1. **`FORBIDDEN_RUNTIME_SEED` pattern mismatch** — `tools/shared/layout_patterns.py` uses `r"(^|/)sk/inputs(/|$)"` (hard-coded old project prefix) but the current layout is `projects/sk/inputs/`. The exclusion never fires. `local_digest()` already silently walks `inputs/` if any files land there.

2. **`local_digest()` reads data paths** — `tools/shared/bucket_sync.py` performs a recursive filesystem walk + full file read of every file under `gcp/stage/` (currently `gcp/remote/`). If a FUSE mount is active (or real WAVs are present) at any `inputs/` path, it reads the entire corpus on every `just deploy` and on every pre-commit hook invocation that touches `gcp/`. This makes the dev workflow unusable unless `SKIP_SYNC_VERIFY=1` is permanently set.

3. **`resolve_local_path()` routing bug** — `tools/bmt/bmt_run_local.py` routes paths beginning with `sk/` to `runtime_root` but paths beginning with `projects/sk/` (the actual format in `bmt_jobs.json`) fall through to `Path.cwd() / raw`, resolving to `<repo_root>/projects/sk/…` rather than `<repo_root>/gcp/stage/projects/sk/…`. Without explicit `BMT_RUNNER` / `BMT_DATASET_ROOT` overrides the tool does not resolve paths correctly.

---

## Decision: Local Data Access Approach

The pre-existing `.gitignore` rule (`gcp/remote/**/inputs/**/*.wav`) already excludes real WAVs from git; the question is how to restore visibility.

| Approach | Complexity | Filename visibility (offline) | Tooling compat. | WSL2 safety | Verdict |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Manifest JSON** (tracked in git) | Low | Full (names + sizes in JSON) | Requires manifest-aware enumeration | Excellent | **Primary — recommended** |
| **gcsfuse `--only-dir` mount into `gcp/mnt/`** | Medium | Full (real filesystem tree) | Transparent — any tool works | Mostly fine (see pitfalls) | **Secondary — opt-in** |
| **rclone mount** | Medium | Full | Transparent | Same as gcsfuse | Alternative to gcsfuse |
| **Symlinks into a FUSE mount** | Medium | Full when mounted, dangling when not | Breaks on unmount (worse than empty dir) | Fragile | Not recommended |
| **Symlinks to GCS URIs (no FUSE)** | None | Symlinks exist but always ENOENT | Completely broken | N/A | Impossible |
| **0-byte stub files** | Low | Names visible, content absent | Breaks naive `open()` silently | Excellent | Not recommended |
| **DVC** | High | Opaque (`.dvc` dir file) | Requires DVC everywhere | Excellent | Too heavy for this use case |
| **`remote/src` + `remote/data` explicit split (Option B)** | Medium | Same as chosen + cleaner structure | ~7 file changes; sync remapping | Excellent | Deferred — achievable later |

**Chosen direction:** Option C — `gcp/stage/` (1:1 GCS staging area, no data files); manifest JSON tracked at `inputs/<dataset>/dataset_manifest.json`; optional FUSE mounts at `gcp/mnt/<project>-inputs/` (gitignored, separate observation window).

---

### Q: Why not symlinks to each remote file?

Short answer: **symlinks to GCS objects are not possible without FUSE**, and even with FUSE, direct mounting is strictly better than symlinks into a mount.

- A Linux symlink stores a target *string*. The kernel has no GCS driver, so `ln -s gs://bucket/file.wav local/file.wav` creates a symlink that always returns `ENOENT` on any `open()`, `stat()`, or `os.path.exists()`. GCS URIs are not filesystem paths.
- If you create symlinks pointing *into* a FUSE mount (e.g. `local/inputs/file.wav → /mnt/gcs/projects/sk/inputs/file.wav`), they work when the mount is active but become **dangling** when it is not — `os.path.exists()` returns `False`, `open()` throws `FileNotFoundError`, and `git status` shows all files as deleted. This is a strictly worse failure mode than an empty directory (which is what you get when a FUSE mount is inactive over its mount point).
- **A direct FUSE mount gives you the same transparent filesystem access without the dangling-symlink failure mode.** When unmounted, the mount point is an empty directory (explicit and recoverable) rather than a directory of broken links.
- gcsfuse can store symlinks *inside* a mounted GCS bucket as objects with `symlink_target` metadata, but it cannot create symlinks *outside* its mount that point into it.

The only production-grade mechanism for "filesystem entries that proxy to remote content" on Linux is FUSE itself.

---

### Q: Should `gcp/stage/` be split into `stage/src` and `stage/data`?

The proposal is architecturally sound but adds meaningful complexity to the sync pipeline. Research shows:

- **Option A (GCS restructured too):** Migrates bucket objects to `src/` and `data/` prefixes. Breaks the 1:1 mirror, requires updating every `dataset_prefix` / `results_prefix` path in `bmt_jobs.json`, and forces a VM image update. Not recommended unless doing a deliberate full bucket layout migration.
- **Option B (local split with sync mapping):** `gcp/stage/src/` maps to certain GCS prefixes, `gcp/stage/data/` maps to `gs://bucket/projects/*/inputs/`. Adds path-remapping logic to `bucket_sync_runtime_seed.py` and an extra routing branch in `resolve_local_path()`. Touches ~7 files at low-to-medium effort. GCS stays flat.
- **Option C (GCS flat; mount tree outside the staging area — chosen):** `gcp/stage/` stays as the 1:1 GCS mirror for all non-audio content. Audio data gets its own mount tree at `gcp/mnt/` (gitignored), entirely outside the staging area. No sync changes, no path remapping, no `bmt_jobs.json` changes, no GCS restructuring.

```
gcp/
  image/        <- VM code baked into image (unchanged)
  stage/        <- local staging area, 1:1 GCS mirror (renamed from remote/ in 0.8)
    config/
    projects/sk/
      lib/
      kardome_runner
      inputs/false_rejects/.keep                    <- placeholder; no real WAVs
      inputs/false_rejects/dataset_manifest.json    <- tracked in git
  mnt/          <- FUSE observation window; gitignored entirely
    sk-inputs/  <- gcsfuse --only-dir=projects/sk/inputs ... -o ro
```

The explicit `stage/src` + `stage/data` split is achievable later (Option B) if the need arises. **This plan implements Option C; Option B is deferred.**

**Do not mount the code prefix (`gcp/stage/`) via FUSE for editing.** gcsfuse explicitly warns against VCS repos on FUSE mounts: `git` uses `flock`, hardlinks, and atomic renames that are unsupported or unreliable on gcsfuse. Edits to code via writable GCS FUSE push broken/partial code to the bucket immediately (no staging, no atomic commit), and code is baked into the VM image at build time anyway — a writable FUSE mount of the code tree has no deployment path and real downside risk.

---

## Checklist

- [ ] **0.1 Fix `FORBIDDEN_RUNTIME_SEED` pattern (pre-existing bug)**
  - **File:** `tools/shared/layout_patterns.py`
  - **Task:** Change the hard-coded `r"(^|/)sk/inputs(/|$)"` pattern in `DEFAULT_CODE_EXCLUDES`, `FORBIDDEN_RUNTIME_SEED`, and `CODE_CLEAN_PATTERNS` to the project-agnostic `r"(^|/)projects/[^/]+/inputs(/|$)"` (matching the actual `projects/<name>/inputs/` layout). Verify by running `just test` and `just validate-layout`.
  - **Why:** The current pattern is keyed to the `sk` project name and does not match the actual path layout `projects/sk/inputs/`, so no inputs exclusion fires today. This means `local_digest()` and the runtime seed sync are silently including any files present under `inputs/`.

- [ ] **0.2 Protect `local_digest()` from data paths**
  - **File:** `tools/shared/bucket_sync.py`
  - **Task:** Verify that the fix to 0.1 causes the `exclude_patterns` path to correctly skip `inputs/` subtrees. Add a unit test that passes a synthetic `inputs/` directory containing a `.wav` file and asserts it is excluded from the digest. Add an explicit guard: any path under `projects/*/inputs/` that is not a `.keep` or `dataset_manifest.json` is skipped.
  - **Why:** `local_digest()` opens and SHA256-hashes every file. If a FUSE mount is active at `gcp/mnt/` or real WAVs land in `gcp/stage/`, this function reads gigabytes of audio on every `git commit` that touches `gcp/`.

- [ ] **0.2b Fix `resolve_local_path()` routing (pre-existing bug)**
  - **File:** `tools/bmt/bmt_run_local.py`
  - **Task:** The current routing for `projects/sk/…` paths (from `bmt_jobs.json`) falls through to `Path.cwd() / raw`, resolving to `<repo_root>/projects/sk/…` instead of `<repo_root>/gcp/stage/projects/sk/…`. Add an explicit `projects/` prefix branch that routes to `runtime_root`. Example: `if raw.startswith("projects/"): return (runtime_root / raw).resolve()`. Add a unit test covering a `projects/sk/kardome_runner` path with an explicit `runtime_root`.
  - **Why:** Without this fix, `bmt_run_local.py` only works correctly when `BMT_RUNNER` and `BMT_DATASET_ROOT` env overrides are provided explicitly. The path resolution contract should work from `bmt_jobs.json` alone.

- [ ] **0.3 Add `DatasetManifest` model and generation tool**
  - **Files:** `tools/shared/dataset_manifest.py` (new), `tools/remote/gen_input_manifest.py` (new)
  - **Task:** Define a `DatasetEntry` (path relative to dataset root, size_bytes, sha256, updated) and `DatasetManifest` (schema_version, dataset, project, bucket, prefix, generated_at, entries) as frozen dataclasses (or Pydantic models matching the project style). Emit `dataset_manifest.json` at the dataset root (e.g. `gcp/stage/projects/sk/inputs/false_rejects/dataset_manifest.json`). The generation tool calls `gcloud storage ls --json gs://$GCS_BUCKET/<prefix>/` to enumerate, normalises paths, and writes the manifest. Manifest files are tracked in git (they are tiny; the existing `.gitignore` excludes only `*.wav` under inputs, not JSON).
  - **Manifest shape:**

    ```json
    {
      "schema_version": 1,
      "project": "sk",
      "dataset": "false_rejects",
      "bucket": "my-bmt-bucket",
      "prefix": "projects/sk/inputs/false_rejects",
      "generated_at": "2026-03-15T12:00:00Z",
      "files": [
        {"name": "ambient/cafe_001.wav", "size_bytes": 4812800, "sha256": "abc123...", "updated": "2026-02-01T10:00:00Z"}
      ]
    }
    ```

- [ ] **0.4 Add `InputFileRegistry` and manifest-aware enumeration to shared tooling**
  - **File:** `tools/shared/dataset_manifest.py`
  - **Task:** Add an `InputFileRegistry` class with a `list_wavs(require_materialized: bool = False) -> list[Path]` method. When local `*.wav` files exist under `dataset_root`, return them. Otherwise, read `dataset_manifest.json` and return virtual `Path` objects (correct names, may not exist on disk). When `require_materialized=True` and files are absent, raise with a clear message pointing to `just fetch-inputs`. **No tool should call `rglob("*.wav")` directly on a dataset root; they must go through `InputFileRegistry`.**
  - **Update `tools/bmt/bmt_run_local.py`:** Replace the `dataset_root.rglob("*.wav")` walk with `InputFileRegistry(dataset_root).list_wavs(require_materialized=True)`.

- [ ] **0.5 Hook manifest regeneration into the upload tool**
  - **File:** `tools/remote/bucket_upload_wavs.py` (or `bucket_upload_dataset.py`)
  - **Task:** After a successful upload, call the manifest generation tool for the affected dataset. Commit the updated `dataset_manifest.json` as part of the deploy workflow (or instruct the developer to do so via a `just` recipe).

- [ ] **0.6 Add `just` recipes for on-demand materialization and FUSE mounts**
  - **File:** `Justfile`
  - **Task:** Add the following recipes:
    - `just fetch-inputs <project> <dataset>` — `gcloud storage cp -r gs://$GCS_BUCKET/projects/<project>/inputs/<dataset>/ gcp/stage/projects/<project>/inputs/<dataset>/`
    - `just fetch-wav <path>` — fetch a single file: `gcloud storage cp gs://$GCS_BUCKET/<path> gcp/stage/<path>`
    - `just gen-manifest <project> <dataset>` — run the generation tool for one dataset
    - `just mount-data <project>` (optional, documented as dev QoL) — mounts `gs://$GCS_BUCKET/projects/<project>/inputs` read-only into `gcp/mnt/<project>-inputs/` via `gcsfuse --only-dir`. **Does not mount into `gcp/stage/`** — the staging area stays clean.
    - `just umount-data <project>` — `fusermount -u gcp/mnt/<project>-inputs`
  - **Task:** Add `gcp/mnt/` to `.gitignore` so mount points are never tracked.

- [ ] **0.7 Update `gcp/README.md` and `docs/development.md`**
  - **Task:** Document the manifest contract (what `dataset_manifest.json` contains, where it lives, when to regenerate it). Document the three tiers of local data access: (1) manifest-only (offline, zero deps — see WAV names without content); (2) on-demand fetch via `just fetch-inputs`; (3) FUSE mount at `gcp/mnt/<project>-inputs/` via `just mount-data` for full fidelity. Document that `gcp/stage/` is never directly mounted via FUSE. Document WSL2 FUSE pitfalls.

- [ ] **0.8 Rename `gcp/remote/` → `gcp/stage/`**
  - **Why:** `gcp/remote/` is a misnomer — it is the local staging area you edit and deploy *from* to GCS, not the remote side. `gcp/stage/` names what it actually is: a staging area under local control. `gcp/mnt/` remains correct (FUSE mount points).
  - **Scope — 14 files that reference `gcp/remote` or `DEFAULT_RUNTIME_ROOT`:**
    - `tools/repo/paths.py` — rename `DEFAULT_RUNTIME_ROOT` to `DEFAULT_STAGE_ROOT = Path("gcp/stage")`
    - `tools/shared/layout_patterns.py` — update any hardcoded `gcp/remote` strings
    - `tools/shared/bucket_env.py` — update path references
    - `tools/remote/bucket_sync_runtime_seed.py` — update default root
    - `tools/remote/bucket_verify_runtime_seed_sync.py` — update default root
    - `tools/remote/bucket_upload_dataset.py` — update `local_mirror` default
    - `tools/bmt/bmt_run_local.py` — update `runtime_root` default
    - `tools/cli/bucket_cmd.py` — update docstrings and defaults
    - `tools/repo/gcp_layout_policy.py` — update layout root
    - `tools/repo/repo_layout_policy.py` — update any path refs
    - `CLAUDE.md` — update all references
    - `gcp/README.md` — update all references
    - `Justfile` — update all recipes
    - `.gitignore` / `.cursorignore` — update path patterns
  - **Note:** This rename exposes the deeper issue that path roots are scattered across 14 files rather than flowing from a single config object. Do 0.8 as a pure rename first; fix the architecture in 0.9.

- [ ] **0.9 Introduce `WorkspaceLayout` — a single typed path config for all dev tools**
  - **File:** `tools/repo/paths.py`
  - **Why:** The fact that renaming one directory requires 14 file edits is a design smell. Path roots are scattered as constants across multiple tools rather than flowing from a single injected config object. This makes renames expensive, makes testing with alternative roots fragile, and means every new tool must independently discover and import the right constant.
  - **Task:** Define a `WorkspaceLayout` frozen dataclass in `tools/repo/paths.py` that owns **all** local path roots:

    ```python
    @dataclass(frozen=True)
    class WorkspaceLayout:
        stage_root: Path   # gcp/stage/ — local staging mirror of GCS (renamed from gcp/remote/)
        image_root: Path   # gcp/image/ — VM code baked into image (read-only locally)
        mnt_root: Path     # gcp/mnt/   — FUSE mount points (gitignored, opt-in)
        data_root: Path    # data/      — local WAV corpora for bmt_run_local

        @classmethod
        def from_env(cls) -> "WorkspaceLayout":
            """Construct from environment variables with defaults."""
            ...

        @classmethod
        def default(cls) -> "WorkspaceLayout":
            return cls(
                stage_root=Path("gcp/stage"),
                image_root=Path("gcp/image"),
                mnt_root=Path("gcp/mnt"),
                data_root=Path("data"),
            )
    ```

  - **Note:** `bmt_workspace` is NOT part of `WorkspaceLayout`. It is the VM-side runtime scratch directory (`~/bmt_workspace/` on the running VM), used by `vm_watcher.py` and `bmt_manager_base.py` for caching runner binaries and staging run outputs. It has no presence in dev tooling. Local dev equivalent is `local_batch/` (used by `bmt_run_local.py`), which is also not part of `WorkspaceLayout` — it is configured separately via `BMT_LOCAL_BATCH_DIR` or the `--workspace` flag.
  - **Task:** Refactor all tools that currently import `DEFAULT_RUNTIME_ROOT`, `DEFAULT_STAGE_ROOT`, etc. to instead receive a `WorkspaceLayout` instance as a constructor parameter (or accept it via `from_env()`). No tool should import a bare path constant; they should all accept a `WorkspaceLayout`.
  - **Task:** Add `WorkspaceLayout.from_env()` that reads `BMT_STAGE_ROOT`, `BMT_MNT_ROOT`, etc. overrides so integration tests can point tools at a temp directory without any monkey-patching.
  - **Outcome:** After this task, changing any root directory is a one-line change to `WorkspaceLayout.default()`. Future renames cost zero files.

---

## Research Insights

### Why manifest JSON is the right primary mechanism

- Zero runtime dependencies; works completely offline for structure visibility.
- Stored in git alongside the code mirror so any `git clone` gives the full directory tree shape without any files.
- Naturally composable with the existing `gcloud storage cp` materialisation pattern used by `bmt_manager.py`.
- Manifest generation is a one-liner on top of `gcloud storage ls --json`; no new infra required.
- Manifests are small: ~10 KB for 1 000 WAV files; negligible storage.

### gcsfuse opt-in (full fidelity for editors and shell tools)

When a contributor wants to see real filenames in their editor's file tree or wants shell autocomplete on WAV paths, they mount the inputs prefix into the **`gcp/mnt/` tree** (gitignored; separate from the mirror):

```bash
# just mount-data sk
mkdir -p gcp/mnt/sk-inputs
gcsfuse \
  --only-dir=projects/sk/inputs \
  --file-mode=444 \
  --dir-mode=555 \
  --implicit-dirs \
  --stat-cache-ttl=300s \
  --type-cache-ttl=300s \
  --kernel-list-cache-ttl-secs=60 \
  $GCS_BUCKET \
  gcp/mnt/sk-inputs
```

Unmount: `fusermount -u gcp/mnt/sk-inputs` (Linux/WSL2).

`gcp/stage/` is **never directly mounted** — the staging area stays a clean, fully-local, git-trackable directory. The FUSE mount lives entirely outside it in `gcp/mnt/`.

### Future optional: `stage/src` + `stage/data` explicit split (Option B)

If you later want the data subtree to be structurally separated from the staging area (e.g. for a cleaner per-project FUSE boundary, or for independent sync), the tooling changes are bounded thanks to `WorkspaceLayout` (0.9):

- Add `data_root: Path = Path("gcp/stage/data")` to `WorkspaceLayout`
- Update `bucket_sync_runtime_seed.py` + verify tool to accept two source dirs with path remapping (`gcp/stage/data/sk/` → `gs://bucket/projects/sk/inputs/sk/`)
- Update `resolve_local_path()` routing to route `projects/*/inputs/` paths to `data_root`
- Update `bucket_upload_dataset.py` `local_mirror` path
- Touches ~7 files, all small-to-medium changes; GCS layout stays flat (no `bmt_jobs.json` changes)

This is explicitly deferred. This plan does not require it.

### WSL2 FUSE pitfalls (kernel 6.6, Microsoft standard)

- WSL2 kernel 6.6 includes FUSE 3.x — gcsfuse works. However:
  - `chmod`/`chown` silently fail; gcsfuse pins all file ownership to the mounting user's UID. Any tool that calls `os.chmod()` on a mounted path gets `Operation not permitted`.
  - The FUSE mount is torn down when the WSL session exits. Manage with `just mount-data` / `just umount-data`; document that contributors need to re-mount on each session. Optionally use systemd (available with `systemd=true` in `.wslconfig`).
  - Heavy traversal (e.g. `rg`, `find`, basedpyright scanning) without `--stat-cache-ttl` floods the GCS List API. Use `--stat-cache-ttl=300s` to mitigate.
  - `--implicit-dirs` is required; GCS does not store directory marker objects.
  - **Add the inputs mount point to `.cursorignore`** (and IDE ignore lists) so the IDE does not index WAV files or traverse 30 GB of audio.
- FUSE should be **opt-in and undocumented as a requirement**. The manifest path must work without it.

### What would break if FUSE were active and 0.1/0.2 were not fixed first

- `local_digest()` reads the entire FUSE mount on every `just deploy` and every pre-commit hook invocation that touches `gcp/` — effectively reading 30 GB on every commit.
- `BucketVerifyRuntimeSeedSync` calls `local_digest()` — CI verify step reads FUSE.
- `bucket_upload_wavs.py` pre-flight stats all local WAVs — floods GCS metadata API.

This is why 0.1 and 0.2 are the mandatory first steps.

### Python `NewType` for path semantics (optional but recommended)

The existing tooling passes `Path` for runner binaries, config files, and 30 GB WAV corpus roots with no semantic distinction. Adding `NewType` aliases signals intent and enables grep-based auditing:

```python
from typing import NewType
from pathlib import Path

CodePath = NewType("CodePath", Path)   # always fully local; safe to hash/read
DataPath = NewType("DataPath", Path)   # may be FUSE/manifest; never hash contents
GcsUri  = NewType("GcsUri", str)       # gs://bucket/...
```

Key enforcement rule: **`local_digest()` and `BucketVerifyRuntimeSeedSync` must never receive a `DataPath`**. Document this in the function signatures. In `bmt_run_local.py` `ResolvedConfig`, separate `runner_path: CodePath` from `dataset_root: DataPath`.

### References

- [gcsfuse `--only-dir` docs](https://cloud.google.com/storage/docs/cloud-storage-fuse/cli-options)
- [gcsfuse implicit-dirs](https://cloud.google.com/storage/docs/cloud-storage-fuse/implicit-directories)
- [rclone mount](https://rclone.org/commands/rclone_mount/)

---

## Verification

| Check | Method |
| :--- | :--- |
| Bug fixes | `pytest tests/` passes with fixed pattern; `just validate-layout` passes |
| Digest safety | Unit test for `local_digest()` asserts `inputs/` WAVs are excluded |
| Manifest | Manifest JSON generated and round-trips through `InputFileRegistry` |
| Path routing | Unit test for `resolve_local_path()` with `projects/sk/...` paths |
