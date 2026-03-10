# BMT CLI

Python CLI for BMT (Benchmark/Milestone Testing) CI. Entrypoint: `driver.py`. Commands are in `commands/` and read inputs from environment variables.

## Package layout

- **`shared`** — Canonical shared module: config loading (`get_config`, `BmtConfig`), gcloud helpers (`run_capture`, `GcloudError`, VM/GCS operations), URI helpers (`code_bucket_root_uri`, `run_trigger_uri`, etc.), and matrix/build helpers (`build_matrix`, `sanitize_run_id`). Command modules should use `from cli import shared` and call `shared.*`; there are no aliases (`gcloud`, `models`, `config`).
- **`gcs`** — GCS path/upload helpers used by workflow steps.
- **`github_api`** — GitHub API (status, checks) used by workflow steps.
- **`gh_output`** — GitHub Actions output and grouping (`gh_group`, `gh_warning`, etc.).
- **`commands/`** — One module per command (or group); each exposes a `run_*` function registered in `driver.py`.

## Imports

Use the real modules only:

```python
from cli import shared
from cli import gcs, github_api  # when needed
# Use shared.get_config(), shared.run_capture(), shared.GcloudError, etc.
```

Do not rely on or add aliases in `cli/__init__.py`; they blur module boundaries and push attribute errors to runtime.
