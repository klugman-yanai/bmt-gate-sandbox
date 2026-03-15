# Pre-flight: Check bucket contents and ensure new gcp/remote is an improvement

Before wiping the GCS bucket and making **gcp/remote** a read-only gcsfuse mount, verify current bucket contents and confirm the new layout (bucket = runtime-only, code only in Packer image) is an improvement and loses no required data.

See also: [brainstorm](brainstorms/2026-03-12-gcp-remote-image-mounts-brainstorm.md).

---

## 1. Run bucket check and save output

From the repo root. If `GCS_BUCKET` is not set, it is taken from GitHub repo variables (`gh variable get GCS_BUCKET`); ensure you are in the repo and `gh` is authenticated.

```bash
just preflight
```

Or run the script directly (set the bucket or rely on `gh variable get GCS_BUCKET` in your shell):

```bash
GCS_BUCKET="${GCS_BUCKET:-$(gh variable get GCS_BUCKET)}" tools/scripts/preflight_bucket_vs_remote.sh
```

This runs:

- `gcloud storage ls gs://BUCKET/` (top-level prefixes)
- `gcloud storage ls -r gs://BUCKET/code/` (all objects under code/)
- `gcloud storage ls -r gs://BUCKET/runtime/` (all objects under runtime/)
- `gcloud storage du -s gs://BUCKET/code/` and `.../runtime/` (size/count)

---

## 2. Diff bucket code/ vs gcp/image

Ensure every object under `gs://BUCKET/code/` has a counterpart under **gcp/image/** so nothing required is lost when code leaves the bucket.

**Option A — use saved report:**

After running `preflight_bucket_vs_remote.sh` with a valid `GCS_BUCKET`, use the saved report path (printed at the end of the script):

```bash
uv run python tools/scripts/preflight_bucket_vs_remote.py --report .local/preflight-bucket-YYYYMMDD-HHMMSS.txt
```

If the report contains only errors (e.g. no bucket access), no code/ listing is found; use Option B with a valid bucket or Option C to get the gcp/image manifest for manual comparison.

**Option B — live (uses GCS_BUCKET from env or `gh variable get GCS_BUCKET`):**

```bash
GCS_BUCKET="${GCS_BUCKET:-$(gh variable get GCS_BUCKET)}" uv run python tools/scripts/preflight_bucket_vs_remote.py
```

Or after `just preflight`, the diff is already run; to run only the diff with current env: `uv run python tools/scripts/preflight_bucket_vs_remote.py` (requires GCS_BUCKET set).

**Option C — only list gcp/image (no bucket access):**

```bash
uv run python tools/scripts/preflight_bucket_vs_remote.py --local-only
```

The script reports:

- **In bucket code/ but NOT in gcp/image** — Would be dropped when code is removed from the bucket. Add to gcp/image or accept removal.
- **In gcp/image but NOT in bucket** — OK if never synced or excluded by sync rules.

---

## 3. Confirm new layout

- **New bucket = current `runtime/` only** — No `code/` or `runtime/` prefix; bucket root = 1:1 with current runtime content (triggers, sk/, bmt_root_results.json, runners, inputs, results).
- **gcp/image** — Not in GCS; source for Packer only. Code/config changes require a new image build.
- **gcp/remote** — Read-only gcsfuse mount of the bucket (view only).

---

## 4. Next steps (after verification)

When the pre-flight checks pass:

1. Unmount gcp/remote if it is already a mount: `fusermount -u gcp/remote` (or `umount gcp/remote`).
2. Wipe the bucket: `gcloud storage rm -r gs://BUCKET/`
3. Upload current runtime content to bucket root: `gcloud storage rsync gcp/remote gs://BUCKET/ --recursive` (or sync from current `gs://BUCKET/runtime/` to `gs://BUCKET/` if gcp/remote is already a mount).
4. Mount bucket at gcp/remote (read-only): `mkdir -p gcp/remote && gcsfuse -o ro --implicit-dirs BUCKET gcp/remote`

No code or bucket changes are made by the pre-flight scripts; they are verification and documentation only.
