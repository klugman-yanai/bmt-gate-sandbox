# Env inventory appendix (refresh commands)

First-party Python and automation live outside mirrored plugin trees under `gcp/stage/**`. Exclude that path when scanning for **new** env usage to avoid duplicated generated bundles.

## Discover `os.environ` / `getenv` keys (Python)

From the repo root (exclude mirrored stage plugins):

```bash
rg 'os\.environ\.get\(' -g '*.py' --glob '!gcp/stage/**'
rg 'os\.getenv\(' -g '*.py' --glob '!gcp/stage/**'
```

Narrow to string literals:

```bash
rg 'os\.environ\.get\("[A-Z0-9_]+"' -g '*.py' --glob '!gcp/stage/**'
rg "os\.environ\.get\\('[A-Z0-9_]+'" -g '*.py' --glob '!gcp/stage/**'
```

## Optional code health (env-related paths)

After `uv sync` (includes optional dev tools):

```bash
uv run vulture gcp/image/config tools/shared/env.py tools/shared/bucket_env.py --min-confidence 80
```

```bash
uv run pylint --disable=all --enable=duplicate-code --min-similarity-lines=6 \
  gcp/image/config/env_parse.py tools/shared/env.py tools/shared/bucket_env.py .github/bmt/ci/workflow_dispatch.py
```

Or use `just doctor` from the repo root.

These checks are **optional** for contributors; the default gate remains `just test` (pytest, ruff, `ty`, etc.).

**GitHub App id / key path precedence** is implemented in [tools/shared/github_app_settings.py](../../tools/shared/github_app_settings.py) (see [env-reference.md](env-reference.md#github-app-and-tooling-aliases)).
