# `gcp/` layout

- [`/home/yanai/sandbox/bmt-gcloud/gcp/image`](/home/yanai/sandbox/bmt-gcloud/gcp/image): image-baked framework/runtime code. This is deployed as the Cloud Run image, not synced to GCS.
- [`/home/yanai/sandbox/bmt-gcloud/gcp/stage`](/home/yanai/sandbox/bmt-gcloud/gcp/stage): editable staged mirror of bucket-managed content.
- [`/home/yanai/sandbox/bmt-gcloud/gcp/mnt`](/home/yanai/sandbox/bmt-gcloud/gcp/mnt): read-only bucket mounts for inspection.

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

1. edit staged manifests/plugin workspaces in `gcp/stage`
2. publish immutable plugin bundles
3. sync the staged project subtree
4. mount `gcp/mnt` only when you need to inspect the live bucket state

Do not treat `gcp/mnt` as an authoring surface. It is observational only.
