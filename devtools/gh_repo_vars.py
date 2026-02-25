#!/usr/bin/env python3
"""Check/apply declarative GitHub repository variables."""

from __future__ import annotations

import json
import subprocess
import tomllib
from pathlib import Path

import click
from click_exit import run_click_command


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=False, text=True, capture_output=True)


def _gh_vars() -> dict[str, str]:
    result = _run(["gh", "variable", "list", "--json", "name,value"])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "gh variable list failed")
    try:
        rows = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"failed to parse gh variable list output: {exc}") from exc
    if not isinstance(rows, list):
        raise RuntimeError("gh variable list returned non-list payload")
    out: dict[str, str] = {}
    for row in rows:
        if isinstance(row, dict):
            name = str(row.get("name", "")).strip()
            value = str(row.get("value", ""))
            if name:
                out[name] = value
    return out


def _load_config(path: Path) -> dict[str, str]:
    raw = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix == ".toml":
        payload = tomllib.loads(raw)
    elif suffix == ".json":
        payload = json.loads(raw)
    else:
        # Try TOML first for human-edited configs, then JSON for compatibility.
        try:
            payload = tomllib.loads(raw)
        except tomllib.TOMLDecodeError:
            payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise RuntimeError("repo vars config must be a TOML/JSON object")
    out: dict[str, str] = {}
    for section_name in ("projects", "variables"):
        section = payload.get(section_name)
        if section is None:
            continue
        if not isinstance(section, dict):
            raise RuntimeError(f"'{section_name}' must be an object")
        for k, v in section.items():
            name = str(k).strip()
            if not name:
                continue
            if name in out:
                raise RuntimeError(f"duplicate variable '{name}' across sections")
            out[name] = str(v)
    return out


def _string_list(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        name = str(item).strip()
        if name and name not in out:
            out.append(name)
    return out


def _load_contract(path: Path) -> tuple[list[str], set[str], dict[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("env contract must be a JSON object")

    contexts = payload.get("contexts", {})
    if not isinstance(contexts, dict):
        raise RuntimeError("env contract missing 'contexts' object")

    gh_ctx = contexts.get("github_repo_vars", {})
    if not isinstance(gh_ctx, dict):
        raise RuntimeError("env contract missing 'contexts.github_repo_vars' object")

    required = _string_list(gh_ctx.get("required", []))
    optional = _string_list(gh_ctx.get("optional", []))
    ordered: list[str] = []
    for name in required + optional:
        if name not in ordered:
            ordered.append(name)
    if not ordered:
        raise RuntimeError("env contract has no github_repo_vars required/optional names")

    defaults_raw = payload.get("defaults", {})
    defaults: dict[str, str] = {}
    if isinstance(defaults_raw, dict):
        for key, value in defaults_raw.items():
            name = str(key).strip()
            if name:
                defaults[name] = str(value)

    return ordered, set(required), defaults


def _gh_set(name: str, value: str) -> None:
    result = _run(["gh", "variable", "set", name, "--body", value])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"failed to set {name}")


def _gh_delete(name: str) -> None:
    # gh variable delete is non-interactive for repo-level variables.
    result = _run(["gh", "variable", "delete", name])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"failed to delete {name}")


def _render(value: str) -> str:
    return value or "<empty>"


@click.command()
@click.option("--config", default="config/repo_vars.toml", show_default=True, help="Declarative repo vars file")
@click.option("--contract", default="config/env_contract.json", show_default=True, help="Env contract file")
@click.option("--apply", is_flag=True, help="Apply missing/drifted variables to GitHub")
@click.option("--prune-extra", is_flag=True, help="Delete repo vars not declared in config (only with --apply)")
def main(config: str, contract: str, apply: bool, prune_extra: bool) -> int:
    config_path = Path(config).expanduser().resolve()
    contract_path = Path(contract).expanduser().resolve()
    if not contract_path.is_file():
        click.echo(f"::error::Missing env contract file: {contract_path}", err=True)
        return 2

    try:
        if config_path.is_file():
            declared = _load_config(config_path)
        else:
            declared = {}
        canonical_order, required_set, contract_defaults = _load_contract(contract_path)
    except Exception as exc:
        click.echo(f"::error::Invalid config/contract: {exc}", err=True)
        return 2

    try:
        current = _gh_vars()
    except Exception as exc:
        click.echo(f"::error::{exc}", err=True)
        return 2

    canonical = set(canonical_order)
    undeclared_unknown = [name for name in declared if name not in canonical]
    if undeclared_unknown:
        click.echo("::error::Config contains names not in env contract github_repo_vars:", err=True)
        for name in undeclared_unknown:
            click.echo(f"::error::- {name}", err=True)
        return 2

    ordered_names = list(declared.keys()) + [name for name in canonical_order if name not in declared]
    desired: dict[str, str] = {}
    desired_origin: dict[str, str] = {}
    missing_required: list[str] = []
    for name in ordered_names:
        if name in declared:
            desired[name] = declared[name]
            desired_origin[name] = "config"
            continue
        if name in current:
            desired[name] = current[name]
            desired_origin[name] = "current"
            continue
        if name in contract_defaults:
            desired[name] = contract_defaults[name]
            desired_origin[name] = "default"
            continue
        if name in required_set:
            desired[name] = ""
            desired_origin[name] = "missing_required"
            missing_required.append(name)
            continue
        desired[name] = ""
        desired_origin[name] = "optional_absent"

    desired_absent = {name for name, value in desired.items() if value == ""}
    missing = sorted(
        name
        for name in ordered_names
        if name not in current
        and name not in desired_absent
        and name not in missing_required
        and (desired_origin.get(name) == "config" or (desired_origin.get(name) == "default" and name in required_set))
    )
    changed = sorted(
        name
        for name in ordered_names
        if name in current and desired[name] != "" and current[name] != desired[name]
    )
    should_delete = sorted(name for name in desired_absent if name in current)
    extra = sorted(name for name in current if name not in canonical)

    if config_path.is_file():
        click.echo(f"Config: {config_path}")
    else:
        click.echo(f"Config: (missing, using current+defaults only) [{config_path}]")
    click.echo(f"Contract: {contract_path}")
    click.echo("")
    click.echo("Repo vars status:")
    for name in ordered_names:
        if name in missing_required:
            state = "MISSING_REQUIRED"
            current_value = "<missing>"
        elif name in desired_absent and name not in current:
            state = "OK (ABSENT)"
            current_value = "<missing>"
        elif name in should_delete:
            state = "DRIFT (SHOULD_BE_ABSENT)"
            current_value = _render(current[name])
        elif name in missing:
            state = "MISSING"
            current_value = "<missing>"
        elif name in changed:
            state = "DRIFT"
            current_value = _render(current[name])
        elif desired_origin.get(name) == "default" and name not in current:
            state = "OK (DEFAULT)"
            current_value = "<missing>"
        else:
            state = "OK"
            current_value = _render(current[name])
            if desired_origin.get(name) == "current" and name not in declared:
                state = "OK (INHERITED_CURRENT)"
            elif desired_origin.get(name) == "default" and name not in declared:
                state = "OK (DEFAULT)"
        click.echo(f"- {name}: {state}")
        if not state.startswith("OK"):
            desired_value = "<required>" if name in missing_required else _render(desired[name])
            click.echo(f"  current: {current_value}")
            click.echo(f"  desired: {desired_value}")

    if extra:
        click.echo("")
        click.echo("Extra non-canonical repo vars:")
        for name in extra:
            click.echo(f"- {name}={_render(current[name])}")

    if missing_required:
        click.echo("")
        click.echo("::error::Missing required repo vars with no current value or contract default.", err=True)
        click.echo("::error::Set these in config/repo_vars.toml (or create them in GitHub vars).", err=True)
        for name in sorted(missing_required):
            click.echo(f"::error::- {name}", err=True)
        return 1

    if not apply:
        if missing or changed or should_delete or extra:
            click.echo("")
            click.echo("::error::Repo vars differ from contract/default-backed desired state.", err=True)
            click.echo("::error::Run: just repo-vars-apply --prune-extra", err=True)
            return 1
        click.echo("")
        click.echo("::notice::Repo vars match contract/default-backed desired state.")
        return 0

    if missing or changed:
        click.echo("")
        click.echo("Applying managed repo vars...")
        to_set = set(missing + changed)
        for name in [n for n in desired if n in to_set]:
            _gh_set(name, desired[name])
            click.echo(f"- set {name}={_render(desired[name])}")
    else:
        click.echo("")
        click.echo("No managed var updates needed.")

    if should_delete:
        click.echo("")
        click.echo("Deleting vars declared as absent (empty value in config)...")
        for name in should_delete:
            _gh_delete(name)
            click.echo(f"- deleted {name}")

    if prune_extra:
        if extra:
            click.echo("")
            click.echo("Pruning undeclared repo vars...")
            for name in extra:
                _gh_delete(name)
                click.echo(f"- deleted {name}")
        else:
            click.echo("")
            click.echo("No undeclared vars to prune.")
    elif extra:
        click.echo("")
        click.echo("Undeclared vars were not pruned (use --prune-extra).")

    click.echo("")
    if extra and not prune_extra:
        click.echo("::notice::Managed vars synced; undeclared vars still exist.")
    else:
        click.echo("::notice::Repo vars synced to contract/default-backed desired state.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_click_command(main))
