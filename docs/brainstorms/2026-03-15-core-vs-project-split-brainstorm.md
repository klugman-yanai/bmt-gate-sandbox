# Brainstorm: Core vs project split

**Date:** 2026-03-15  
**Driver:** Both (1) a clear core boundary — watcher, orchestrator, lib as one deployable artifact — and (2) a simpler way to add new BMT projects without rebuilding the core image.

---

## What we're building

A split between **core** (VM runtime that polls triggers, runs legs, posts status) and **projects** (per-project manager scripts + jobs config). Goals:

- **Core** is a single, versioned artifact (e.g. wheel) on the image: watcher, root_orchestrator, trigger_resolution, verdict_aggregation, github_status, config, lib, scripts entrypoints. No loose source for core on the VM.
- **Projects** are the unit of “add a new BMT”: one or more projects (sk, skyworth, …) with `bmt_manager.py` and `bmt_jobs.json`. Adding a project should not require rebuilding the core image.
- Discovery: the trigger (from CI) already lists legs (project, bmt_id). Core resolves each leg by loading that project’s jobs (and optionally checking that a manager exists). Today that’s from GCS `code/projects/<project>/`; the split keeps that discovery contract and decides only where project content lives.

---

## Why this approach

- **Single deployable core** reduces drift and makes “what runs on the VM” explicit (one wheel + deps). Image build = install core wheel; no editable source tree for core.
- **Projects as a separate layer** supports “add a project” without an image rebuild: add project files to a store (GCS or a dedicated path) and have core load them at runtime. CI/repo remains the source of truth; publish project = sync/upload to that store.
- Aligns with the existing trigger-and-leg model: CI sends legs; VM only needs to resolve and run them. The split clarifies what “core” owns vs what “projects” provide.

---

## Approaches

### Approach A: Core wheel on image + projects from GCS (recommended)

**Idea:** Core is built as a wheel (e.g. `bmt-vm-runtime`) and installed on the image. No core code in GCS. Projects remain in GCS at `code/projects/<project>/bmt_manager.py` and `bmt_jobs.json`. Orchestrator continues to download manager + jobs from GCS per leg. Adding a project = add to repo, sync to bucket (existing `just deploy` or upload step); no image rebuild.

**Pros:** Clear core boundary; add project without image rebuild; reuses current “projects in GCS” flow; minimal change to orchestrator (still downloads from code bucket root).  
**Cons:** Two sources for “code” (core on image, projects in GCS); bucket must stay in sync for project content.  
**Best for:** Teams that want a clean core artifact and the simplest “add project” path (sync to GCS).

---

### Approach B: Core wheel + projects baked on image

**Idea:** Core as wheel on image. Projects directory on image at e.g. `/opt/bmt/projects/` with manager + jobs per project; orchestrator reads from disk (no GCS download for project code). Adding a project = add to repo and rebuild image (or a separate “project pack” step that updates a mounted volume or image layer).

**Pros:** No code in GCS; single image contains everything; simpler runtime (no project download).  
**Cons:** Adding a project requires image rebuild unless you introduce a separate project-pack or writable project store.  
**Best for:** When GCS is not the desired source for project code and image rebuilds per project are acceptable.

---

### Approach C: Core wheel + projects from GCS with optional image cache

**Idea:** Same as A, but the image can optionally pre-bake a default set of projects so cold start doesn’t need GCS for known projects. New or updated projects still come from GCS; core always prefers GCS when present or falls back to baked project dir.

**Pros:** Add project without image rebuild; core is one artifact; can optimize cold path for known projects.  
**Cons:** More complexity (two project sources; cache invalidation or precedence rules).  
**Best for:** When you want A’s “add project via GCS” but also want faster cold start for a fixed set of projects. YAGNI until cold start is a real problem.

---

## Key decisions

| Decision | Recommendation |
|----------|----------------|
| **Core artifact** | Build `gcp/image` as a wheel; image installs only that wheel (plus any non-packaged scripts/config agreed separately). |
| **Project source** | Projects live in GCS at `code/projects/<project>/`; orchestrator downloads manager + jobs per leg (current behavior). Add project = add to repo + sync to bucket. |
| **Discovery** | No change: trigger supplies legs (project, bmt_id); core loads jobs from GCS and runs manager (downloaded to run_root). No central “project registry” file required. |
| **Config / data** | Core wheel includes code and in-package config (e.g. constants, schema paths). Per-project config (`bmt_jobs.json`, `input_template.json`) stays with projects in GCS (or in project dir if ever on disk). |

---

## Open questions

1. **Bucket layout:** If we later move to “no code/ in GCS” (per 2026-03-12 brainstorm), project content would need a dedicated namespace (e.g. `projects/` at bucket root) or stay on image. For Approach A we keep current `code/projects/` until that layout change.
2. **Entrypoints:** Should `vm_watcher`, `root_orchestrator`, and scripts like `run_watcher` be console_scripts from the wheel, or stay as script paths that invoke `python -m gcp.image...`? Console_scripts simplify PATH and avoid repo-root assumptions.
3. **Packer build:** Image build today copies `gcp/image` and runs `install_deps`. With a wheel, build would: build wheel from `gcp/image`, copy wheel into builder, install wheel into image venv. Confirm Packer can receive the wheel (e.g. from repo build step or artifact).

---

## Resolved / implied

- **Core** = watcher, orchestrator, trigger_resolution, verdict_aggregation, pointer_update, trigger_cleanup, github_status, github (lib), config, path_utils, utils, log_config, gcs_helpers. All of this ships in the wheel.
- **Projects** = everything under `gcp/image/projects/<name>/` (bmt_manager.py, bmt_jobs.json, shared/). These are not part of the core wheel when using Approach A; they are synced to GCS and loaded at runtime.
- **Adding a project** (Approach A): Add `projects/<name>/bmt_manager.py` and `bmt_jobs.json` in repo, extend CI matrix/preset if needed, run sync to bucket. No image rebuild.
