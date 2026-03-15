# Path usages: where pathlib.Path ought to be used

Ripgrep-based audit of path-related parameters and literals. Run from repo root.

## Ripgrep commands

```bash
# Params typed as str that are filesystem paths (candidates for Path | str or Path)
rg -n 'config_root|runtime_root|src_dir|code_root|jobs_config|runner_path|workspace_root|lib_dir' --type py -g '!__pycache__' | rg ': str'

# Places that wrap a path arg in Path() immediately (accept Path to avoid double wrap)
rg -n 'Path\([a-z_]+\)\.(resolve|expanduser|open|read_text|is_file|is_dir)' --type py

# Remaining os.path usage (prefer Path when possible)
rg -n 'os\.path\.' --type py

# String literals that are repo-relative paths (could use paths.py constants)
rg -n '"gcp/|'"'"'gcp/' --type py
```

## Findings (pathlib.Path ought to be used)

### 1. Parameters typed `str` that are paths

**Updated to `Path | str`:** All of the following now accept `Path | str`; defaults from `paths.py` are `Path`, and callers can pass env-derived strings.

| File | Parameter(s) | Status |
|------|--------------|--------|
| `tools/bmt/bmt_run_local.py` | `code_root`, `runtime_root`, `jobs_config` | ✅ `Path \| str` |
| `tools/remote/bucket_verify_runtime_seed_sync.py` | `src_dir` | ✅ `Path \| str` |
| `tools/remote/bucket_sync_runtime_seed.py` | `src_dir` | ✅ `Path \| str` |
| `tools/remote/bucket_verify_gcp_sync.py` | `src_dir` | ✅ `Path \| str` |
| `tools/remote/bucket_sync_gcp.py` | `src_dir` | ✅ `Path \| str` |
| `tools/bmt/bmt_monitor.py` | `config_root` | ✅ `Path \| str` |
| `tools/remote/bucket_upload_runner.py` | `runner_path` | ✅ `Path \| str` |
| `tools/remote/bucket_validate_contract.py` | `runtime_root` | GCS URI — kept as `str` |

### 2. Single `os.path` usage

| File | Line | Current | Path alternative |
|------|------|---------|-------------------|
| `tools/scripts/symlink_bmt_deps.py` | 117 | `os.path.relpath(target, link_path.parent)` | `target.relative_to(link_path.parent)` only works when `target` is under `link_path.parent`; for cross-directory symlinks `relpath` is correct. Keep as-is or use a try/except with `Path.relative_to`. |

### 3. Already using Path correctly

- `tools/repo/paths.py` — all constants are `Path`
- `tools/repo/results_prefix.py` — `config_root: str | Path`
- `gcp/image/config/bmt_config.py` — `path: Path | str` for context file
- `gcp/image/github/github_auth.py` — `config_path: str | Path`, `_resolve_config_path` returns `Path`
- `gcp/image/vm_watcher.py`, `gcp/image/root_orchestrator.py` — `workspace_root: Path`, `Path(raw).expanduser().resolve()`
- `bmt_manager_base.py` (in `gcp/image/projects/shared/`) — `workspace_root: Path`, `Path(args.workspace_root).expanduser().resolve()`

### 4. GCS / bucket URIs (keep as str)

- `runtime_root` in `bucket_validate_contract.py` — GCS prefix `gs://...`, not a filesystem path
- `bucket_root`, `runtime_bucket_root`, `results_prefix` in verdict/orchestrator code — URIs or prefixes

## Optional: fzf to search interactively

```bash
# List all .py files that mention path-like params, then fuzzy search
rg -l 'config_root|src_dir|runtime_root|code_root|Path\(' --type py | fzf

# Or: show lines and open in editor on selection
rg -n 'config_root|src_dir|runtime_root|code_root' --type py | fzf --preview 'bat --style=numbers --color=always {1}' | cut -d: -f1-2
```
