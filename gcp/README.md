# `gcp/` layout

- [`gcp/image`](image): image-baked framework/runtime code. Deployed as the **Cloud Run** image; not synced to GCS.
- [`gcp/stage`](stage): editable staged mirror of bucket-managed content.
- [`gcp/mnt`](mnt): read-only bucket mounts for inspection.

## Bucket contract

Bucket root mirrors `gcp/stage` directly.

Supported published paths:

- `projects/<project>/project.json`
- `projects/<project>/bmts/<bmt_slug>/bmt.json`
- `projects/<project>/plugins/<plugin>/sha256-<digest>/...`
- `projects/<project>/inputs/<dataset>/...`
- `projects/<project>/results/<bmt_slug>/...`
- `triggers/plans/...`
- `triggers/summaries/...`

## Local workflow

1. Edit staged manifests/plugin workspaces in `gcp/stage`.
2. Publish immutable plugin bundles.
3. Sync the staged project subtree (`just deploy` when using a real bucket).
4. Mount `gcp/mnt` only when you need to inspect live bucket state.

Do not treat `gcp/mnt` as an authoring surface. It is observational only.
