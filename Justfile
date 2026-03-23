# default/list → tools/scripts/just_list_recipes.py (Rich). Repo: bmt-gcloud.

alias help := default

[doc('Typical contributor workflow; `just list` for all recipes.')]
[group('help')]
default *args:
    @uv run python tools/scripts/just_list_recipes.py --intro {{ args }} "{{ justfile() }}"

[doc('Command table (task + run); `just list --verbose` for Justfile docs. No intro.')]
[group('help')]
list *args:
    @uv run python tools/scripts/just_list_recipes.py {{ args }} "{{ justfile() }}"

[doc('Full Typer CLI (bucket, repo, build, bmt, …); see --help.')]
[group('cli')]
tools *args:
    @uv run python -m tools {{ args }}

[doc('Pre-push: pytest, ruff, ty, actionlint, shellcheck, layout.')]
[group('pre-push')]
test:
    @bash tools/scripts/verify_repo.sh

[doc('Quick pytest + ruff before publish. See docs/local-bmt-testing.md.')]
[group('pre-push')]
test-local:
    @uv run python -m tools repo test-local

[group('pre-push')]
[private]
ship *args:
    @uv run python -m tools ship {{ args }}

[group('validate')]
[private]
show-env:
    @uv run python -m tools repo show-env

[doc('tools workspace <cmd>: deploy syncs gcp/stage→GCS; also pulumi, validate, preflight, e2e. See docs/contributor-commands.md.')]
[group('workspace')]
workspace *args:
    @uv run python -m tools workspace {{ args }}

[doc('Upload local gcp/ config to your GCS bucket so CI matches the repo (same as `just workspace deploy`). Needs GCS_BUCKET. See docs/contributor-commands.md.')]
[group('workspace')]
sync-to-bucket *args:
    @uv run python -m tools workspace deploy {{ args }}

alias sync-stage := sync-to-bucket

[doc('project=gcp/stage/projects/<name>; source=local .zip or WAV folder. See docs/contributor-commands.md.')]
[group('bucket')]
upload-wav project source *args:
    @uv run python -m tools bucket upload-wav "{{ project }}" "{{ source }}" {{ args }}

[doc('FUSE mount project inputs (list: `just tools bucket --help`).')]
[group('bucket')]
[private]
mount project:
    @uv run python -m tools bucket mount-project "{{ project }}"

[doc('Unmount FUSE mount (see `just tools bucket umount-project --help`).')]
[group('bucket')]
[private]
unmount project:
    @uv run python -m tools bucket umount-project "{{ project }}"

[doc('Project and/or BMT scaffold and/or WAV upload. See `just tools add --help`.')]
[group('dev')]
add *argv:
    @uv run python -m tools add {{ argv }}

[doc('bmt stage: project|bmt|publish — lower-level; prefer `just add` / `just publish`.')]
[group('dev')]
stage *argv:
    @uv run python -m tools bmt stage {{ argv }}

[doc('New project scaffold (same as `just add <name>`).')]
[group('dev')]
[private]
add-project *argv:
    @uv run python -m tools bmt stage project {{ argv }}

[doc('New BMT (same as `just add <proj> --bmt=<name>`).')]
[group('dev')]
[private]
add-bmt *argv:
    @uv run python -m tools bmt stage bmt {{ argv }}

[doc('Publish plugin; enables BMT by default. See `just tools publish --help`.')]
[group('dev')]
publish *argv:
    @uv run python -m tools publish {{ argv }}

[doc('Two-arg publish (same as `just publish PROJ BMT`).')]
[group('dev')]
[private]
publish-bmt project benchmark *args:
    @uv run python -m tools publish "{{ project }}" "{{ benchmark }}" {{ args }}

[doc('Contributor checklist (same as `just tools workflow overview`).')]
[group('help')]
workflow:
    @uv run python -m tools workflow overview

[doc('Repo status: .venv, gcp/stage/projects (same as `just tools workflow status`).')]
[group('help')]
status:
    @uv run python -m tools workflow status

alias workflow-status := status

[doc('Bootstrap script; *args forwarded (e.g. --dry-run). vs tools onboard: see docs/contributor-commands.md.')]
[group('dev')]
onboard *args:
    @bash tools/scripts/bootstrap_dev_env.sh {{ args }}

[group('bucket')]
[private]
project-sync project:
    @uv run python -m tools bucket project-sync "{{ project }}"

[group('bucket')]
[private]
clean-bloat *args:
    @uv run python -m tools bucket clean-bloat {{ args }}

[group('bucket')]
[private]
fetch-inputs project dataset:
    @gcloud storage cp -r "gs://$GCS_BUCKET/projects/{{ project }}/inputs/{{ dataset }}/" \
        "gcp/stage/projects/{{ project }}/inputs/{{ dataset }}/"

[group('bucket')]
[private]
fetch-wav path:
    @gcloud storage cp "gs://$GCS_BUCKET/{{ path }}" "gcp/stage/{{ path }}"

[group('bucket')]
[private]
gen-manifest project dataset:
    @BMT_PROJECT={{ project }} BMT_DATASET={{ dataset }} uv run python -m tools.remote.gen_input_manifest

[group('bucket')]
[private]
mount-data project:
    @bash tools/scripts/mount_project_inputs_fuse.sh "{{ project }}"

[group('bucket')]
[private]
umount-data project:
    @fusermount -u gcp/mnt/{{ project }}-inputs

[group('bucket')]
[private]
set-bucket-var:
    @gh variable set GCS_BUCKET --body "$(cd infra/pulumi && pulumi stack output gcs_bucket)"

[group('validate')]
[private]
repo-vars-apply:
    @uv run python -m tools.repo.gh_repo_vars --apply

[group('infra')]
[private]
build *args:
    @uv run python -m tools build image --branch "`git rev-parse --abbrev-ref HEAD`" {{ args }}

[group('infra')]
[private]
packer-validate:
    @uv run python -m tools build packer-validate
