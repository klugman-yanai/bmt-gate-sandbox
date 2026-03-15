# CLI: Typer and Rich

How the unified `tools` CLI uses Typer and where Rich improves human-facing output (not CI automation).

## Typer usage

- **Entry:** `uv run python -m tools` → [tools/**main**.py](../tools/__main__.py) mounts sub-apps (bucket, pulumi, repo, build, bmt).
- **Rich help:** Root app uses `rich_markup_mode="rich"` so help strings support [bold], [green], etc. Sub-apps use `rich_help_panel` to group commands (e.g. "Storage & deploy", "Infrastructure", "BMT").
- **Consistent pattern:** Typer commands parse options/args and call tool classes (`.run()`) or scripts; exit via `typer.Exit(rc)`.

## Minimal output standard (Just commands)

**Quiet/minimal** runs (no `--verbose`) use [tools/shared/rich_minimal.py](../tools/shared/rich_minimal.py): step lines (`Label… ✓`) and a final success panel/line. **TTY:** Rich formatting (green panels, dim step labels). **Non-TTY/CI:** Plain one-line-per-step and `Title: message` so logs stay parseable.

| Just / command | Minimal output |
|----------------|----------------|
| **just deploy** | `tools bucket deploy` — Header "Deploy", steps Sync / Verify code / Verify runtime seed, green "Deploy" panel. |
| **just preflight** | `tools bucket preflight` — Step "Preflight", green "Preflight" panel (or script output then step + panel). |
| **just clean-bloat** | `tools bucket clean-bloat` — "Clean bloat" step + blue "Clean bloat" panel. |
| **just pulumi** | `tools pulumi apply` — Preflight panel; steps Login, Stack select, Config set, Install, Up, Repo vars; green "Apply" panel. |
| **just packer-validate** | `tools build packer-validate` — Green "Packer" panel on success. |
| **just build** | `tools build image` — Panels for dispatch/wait; green "Build" panel on success. |
| **just test** (layout) | `tools repo validate-layout` — "Validate layout" header, steps GCP layout / Repo layout, green panel. |

## Rich output (TTY only)

Rich is used only when **stdout is a TTY** (`sys.stdout.isatty()`), so CI and pipes keep plain text.

| Command / flow | Rich when TTY |
|----------------|----------------|
| **tools repo show-env** | Rich (tables, panels, tree) in `gh_show_env.py`. |
| **tools repo validate-layout** | Bold header, step lines, green "Validate layout" panel. |
| **tools bmt add-project** | Next steps as a Panel after scaffolding. |
| **tools bmt wait** | Verdict summary as a Table (decision + pass/warning/fail/timeout counts). |
| **tools bmt monitor** | Full Rich TUI (Live, Layout, panels). |
| **tools bucket deploy** | Bold "Deploy", step lines, green "Deploy" panel. |
| **tools bucket preflight** | With `--report`/`--local-only`: Rich tables; default: step + green panel. |
| **tools bucket clean-bloat** | Bold "Clean bloat", step, blue "Clean bloat" panel. |
| **tools build image** | Panels for dispatch and wait; green "Build" panel on success. |
| **tools build packer-validate** | Green "Packer" panel on success. |
| **tools repo validate** | When not CI: Rich tables and green Panel for success. |
| **tools pulumi apply** | Step lines (Login ✓, …) and green "Apply" panel. |
| **tools pulumi preflight** | Green "Preflight" panel with checks list. |

Commands that stay plain when not TTY: all of the above use `rich_minimal.step` / `success_panel` for plain one-line equivalents in CI.

## Possible future improvements

- **Global options:** Add a root callback with `--no-color` / `--verbose` in `ctx.obj` so commands can respect them (e.g. disable Rich when `--no-color`).
- **Progress:** For long operations (e.g. pulumi up, wait polling), optional `rich.progress` when TTY and `--verbose` (or a `--progress` flag).
- **rich-click:** Optional theme override via [rich-click](https://github.com/ewels/rich-click) (themes, env) if you want to customize Typer/Click help appearance beyond built-in Rich.

## Dependencies

- **typer[all]** and **rich** are main-deps in [pyproject.toml](../pyproject.toml). Rich is used by `gh_show_env`, `bmt_monitor`, and the CLI success/summary outputs above.
