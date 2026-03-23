# BMT CLI (`bmt`)

Workflows run **`uv run bmt …`** from the repo root. This directory is the **Python package** wired in [`pyproject.toml`](pyproject.toml):

- **Installable / distribution name:** `bmt` (workspace member at the repo root; `uv sync` installs the `bmt` console script).
- **Import package name:** `ci` — use `from ci…` / `import ci…` in code (e.g. [`ci/handoff.py`](ci/handoff.py), [`ci/`](ci/)).

Keeping the distribution name `bmt` and the import path `ci` avoids colliding with other packages named `bmt` on `PYTHONPATH` while still matching the CLI name operators use in Actions.
