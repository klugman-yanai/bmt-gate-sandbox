# BMT CLI (`bmt`)

Workflows run **`uv run bmt …`** from the repo root. This directory is the **Python package** wired in [`pyproject.toml`](pyproject.toml):

- **Installable / distribution name:** `bmt` (workspace member at the repo root; `uv sync` installs the `bmt` console script).
- **Import package name:** `ci` — use `from ci…` / `import ci…` in code (e.g. [`ci/handoff.py`](ci/handoff.py), [`ci/`](ci/)).

Keeping the distribution name `bmt` and the import path `ci` avoids colliding with other packages named `bmt` on `PYTHONPATH` while still matching the CLI name operators use in Actions.

## `bmt-gcloud` on the consumer repo (e.g. core-main)

This package declares a dependency on **`bmt-gcloud`** ([`pyproject.toml`](pyproject.toml)). In the **bmt-gcloud** monorepo, that resolves via the workspace root. On **core-main** you must supply **`bmt-gcloud` separately**:

1. **Git + tag/SHA (typical):** add `[tool.uv.sources]` at the **consumer** project that installs `.github/bmt` (often the repo root `pyproject.toml`):

   ```toml
   [tool.uv.sources]
   bmt-gcloud = { git = "https://github.com/<org>/bmt-gcloud.git", rev = "<tag-or-full-sha>", subdirectory = "." }
   ```

   Use the **repository root** as `subdirectory` if `[project]` for `bmt-gcloud` lives there (this repo). Pin **`rev`** to a tag or full commit SHA.

2. **Private index:** publish `bmt-gcloud` to Artifact Registry or an internal index and install with a pinned version; avoid mixing ambiguous `extra-index-url` with PyPI for internal package names.

After configuring sources, run **`uv lock`** / **`uv sync`** from the directory that contains that `pyproject.toml` (same as Actions `working-directory` for `uv run bmt`).
