# GCP remote (read-only mount) and gcp/image (repo-only, not in GCS)

**Date:** 2026-03-12  
**Topic:** Single bucket layout (no code/ or runtime/ prefixes); gcp/remote = read-only gcsfuse mount; gcp/image = repo-only, baked into image only; publish code = image build from this repo.

---

## What we're building

- **Bucket has no `code/` or `runtime/` prefixes.** The bucket is a **1:1 copy of the layout under gcp/remote** — i.e. the bucket root directly contains what you see at gcp/remote (e.g. `sk/`, `triggers/`, `bmt_root_results.json`, runner metadata, inputs, results, etc.). **GCS is the source of truth** for that content.

- **gcp/remote** is a **read-only gcsfuse mount** of the whole bucket. You view and read bucket contents there; you do not write. Local dev uses it to inspect what’s in the bucket. **Only gcp/remote is a mount** — there is no other FUSE mount in this layout.

- **gcp/image** is **not a mount.** It is a normal directory in the repo. Its contents (code, config, VM scripts) live only in the repo and are **baked into the Packer image**. They are never uploaded to the bucket. The VM runs from code on disk (from the image), not from GCS.

- **Publish code** means building/publishing the **Packer image** from this repo (using gcp/image as the source). It is the only way “code” is published; it is done only from this repo. No separate “sync code to GCS” step.

- **Packer** builds the image by copying **gcp/image** into the VM (e.g. into `/opt/bmt`). It does not pull code from GCS. At runtime the VM **gcsfuse-mounts the bucket** to perform its task (read runners, datasets, triggers; write results, metadata).

---

## Why this approach

- **Single bucket namespace** — No split between “code” and “runtime” in the bucket; one layout under bucket root, 1:1 with gcp/remote. Simpler mental model and fewer path transformations.
- **Code stays out of GCS** — VM code and config are versioned in the repo and baked into the image. No risk of overwriting or drift between “code in bucket” and “code in repo.” Publish = image build.
- **Bucket = data and runtime artifacts only** — Runners, inputs, triggers, results, `bmt_root_results.json`, `runner_latest_meta.json`, etc. live at bucket root (and under logical paths like `sk/`). Visible locally only via the gcp/remote mount (read-only).
- **VM uses image + mount** — Image provides stable code and tooling; bucket mount provides data and runtime state. Clear separation of concerns.

---

## Key decisions

| Decision | Rationale |
|----------|-----------|
| **No `code/` or `runtime/` prefix in the bucket** | Bucket root = 1:1 with gcp/remote layout. All bucket paths are flat under root (e.g. `sk/runners/...`, `triggers/`, `bmt_root_results.json`). |
| **GCS bucket = source of truth for bucket content** | Runners, inputs, results, triggers, metadata are authored by CI/VM or upload tools; bucket is the only store. |
| **gcp/remote = read-only gcsfuse mount of the bucket** | Local view only; no writes. **Only gcp/remote is a mount.** gcp/image is a normal repo directory. |
| **gcp/image is not a mount; never in GCS** | gcp/image is a plain directory in the repo. Code/config/scripts live only in repo and in the Packer image. Not uploaded to the bucket. |
| **Packer builds image from gcp/image** | Provisioner copies gcp/image (from build context) into the VM at bmt_repo_root. No `gcloud storage rsync` of code from GCS. |
| **VM at runtime: code on disk + gcsfuse mount** | Code from image; bucket mounted read/write (or as needed) for data and runtime artifacts. |
| **Publish code = image build from this repo only** | “Publish code” is building and publishing the Packer image; the only source is gcp/image in this repo. |
| **runner_latest_meta.json, bmt_root_results.json in bucket only** | At bucket root or under logical paths (e.g. `sk/runners/.../runner_latest_meta.json`, `bmt_root_results.json`). Visible locally via gcp/remote mount. Not in the image. |

---

## Resolved / implied

- **Where do you edit code?** In **gcp/image** in the repo. You don’t upload it to GCS; you run a Packer build to publish (image contains gcp/image).
- **How does bucket content get there?** Via upload tools and CI (e.g. bucket_upload_wavs, bucket_upload_runner, VM/CI writing results and metadata). Those write to GCS; locally you only view via gcp/remote mount.
- **Mount:** Only **gcp/remote** is a read-only gcsfuse mount (bucket). **gcp/image** is a normal directory in the repo, not a mount.

---

## Open questions

1. **Bucket path compatibility:** Today many tools and the VM use `gs://<bucket>/code/...` and `gs://<bucket>/runtime/...`. Removing those prefixes means changing all URIs to bucket-root-relative (e.g. `gs://<bucket>/sk/...`, `gs://<bucket>/triggers/...`). Confirm that a single pass to update these references is acceptable and that no consumer expects a `code/` or `runtime/` prefix.

2. **Packer build context:** Packer must receive gcp/image from the machine running the build (e.g. copy from repo into the builder VM or rsync from host). Confirm that in your setup Packer runs in an environment where it can read the repo (e.g. CI or local) and that gcp/image is available as a normal directory (not a mount) at build time.

---

## Next steps

→ Resolve open questions if needed, then `/workflows:plan` for: bucket layout change (drop code/ and runtime/), gcp/remote mount script and docs, Packer change to use gcp/image as source (no GCS code pull), URI updates across codebase, and removal of sync-to-GCS for code.
