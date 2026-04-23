# `kardome-bmt` (CI / handoff CLI)

This directory is the **`kardome-bmt`** workspace member ([`pyproject.toml`](pyproject.toml)).

- **Console:** `uv run kardome-bmt …` from the repo root (after `uv sync`). A legacy alias **`bmt`** points at the same entrypoint.
- **Import package:** `kardome_bmt` — e.g. [`kardome_bmt/handoff.py`](kardome_bmt/handoff.py).

Production GitHub workflows typically use the release **`bmt.pex`** via [`.github/actions/setup-bmt-pex`](../.github/actions/setup-bmt-pex/action.yml) instead of vendoring this tree.

## Consumer repos (e.g. core-main)

Cross-repo callers depend on **`bmt-gcloud`** as a **git** or **index** source (see root [`pyproject.toml`](../pyproject.toml) `[tool.uv.sources]`). They do **not** install from `.github/bmt`; pin **`rev`** to a tag or full SHA when using git sources.

After configuring sources, run **`uv lock`** / **`uv sync`**, then **`uv run kardome-bmt …`** (or invoke the PEX in CI).
