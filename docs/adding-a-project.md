# Adding a project or BMT

The supported path is the staged Cloud Run plugin workflow.

## New project

1. Run `just add-project <project>`.
2. Edit the staged files under [`/home/yanai/sandbox/bmt-gcloud/gcp/stage/projects/<project>`](/home/yanai/sandbox/bmt-gcloud/gcp/stage).
3. Upload any dataset with `just upload-data <project> <zip-or-folder> [--dataset <name>]`.
4. Publish the default plugin with `just publish-bmt <project> example`.
5. Enable the BMT manifest.
6. The next CI invocation discovers the enabled BMT automatically.

## New BMT

1. Run `just add-bmt <project> <bmt_slug>`.
2. Edit [`/home/yanai/sandbox/bmt-gcloud/gcp/stage/projects/<project>/bmts/<bmt_slug>/bmt.json`](/home/yanai/sandbox/bmt-gcloud/gcp/stage).
3. Point `inputs_prefix`, `results_prefix`, and `outputs_prefix` at the canonical bucket paths.
4. Keep `plugin_ref` as a workspace ref while editing, then publish it with `just publish-bmt <project> <bmt_slug>`.
5. Upload the dataset with `just upload-data <project> <source> [--dataset <name>]`.
6. Set `"enabled": true`.

## Plugin code

- Editable plugin code lives under [`/home/yanai/sandbox/bmt-gcloud/gcp/stage/projects/<project>/plugin_workspaces/<plugin>`](/home/yanai/sandbox/bmt-gcloud/gcp/stage).
- Production manifests must reference immutable bundles under `projects/<project>/plugins/<plugin>/sha256-<digest>/...`.
- Contributors normally customize parsing, scoring, and evaluation logic only. The framework owns planning, task orchestration, summaries, pointers, and GitHub reporting.

## Dataset upload

- Archives are the preferred local artifact.
- `just upload-data` uploads archives with `gcloud storage cp`, then the Cloud Run importer extracts them into `projects/<project>/inputs/<dataset>/`.
- `just upload-data` uses `gcloud storage rsync` when the source is already a WAV directory.
- `just mount-project <project>` gives a read-only bucket view under [`/home/yanai/sandbox/bmt-gcloud/gcp/mnt/projects/<project>`](/home/yanai/sandbox/bmt-gcloud/gcp/mnt).

## What not to use

- Do not add new `gcp/image/projects/<project>/bmt_manager.py` managers.
- Do not reintroduce the deleted `bmt_jobs.json` contributor flow.
- Do not rely on any trigger-file or VM-era workflow patterns for new work.
