#!/usr/bin/env python3
"""Report configuration surface size and reduction opportunities."""

from __future__ import annotations

import re
from pathlib import Path

import click
from click_exit import run_click_command
from shared_env_contract import default_contract_path, list_context_vars, load_env_contract


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _workflow_repo_vars() -> list[str]:
    workflows = sorted((_repo_root() / ".github" / "workflows").glob("*.yml"))
    pattern = re.compile(r"vars\.([A-Z0-9_]+)")
    names: set[str] = set()
    for path in workflows:
        text = path.read_text(encoding="utf-8")
        names.update(pattern.findall(text))
    return sorted(names)


def _count_alias_hits(alias: str) -> int:
    rg_paths = [
        _repo_root() / "Justfile",
        _repo_root() / "deploy" / "code" / "bootstrap",
        _repo_root() / "tools",
    ]
    pattern = re.compile(rf"\b{re.escape(alias)}\b")
    count = 0
    for root in rg_paths:
        if root.is_file():
            text = root.read_text(encoding="utf-8")
            count += len(pattern.findall(text))
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix not in {".py", ".sh", ".md", ""} and path.name != "Justfile":
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            count += len(pattern.findall(text))
    return count


def _string_map(raw: object) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in raw.items():
        if isinstance(k, str):
            out[k] = str(v)
    return out


@click.command()
def main() -> int:
    contract = load_env_contract()
    required = list_context_vars(contract, "github_repo_vars", "required")
    optional = list_context_vars(contract, "github_repo_vars", "optional")
    minimal = contract.get("recommended_minimal_input", [])
    minimal_list = [str(v) for v in minimal] if isinstance(minimal, list) else []
    aliases = _string_map(contract.get("aliases"))
    workflow_vars = _workflow_repo_vars()

    click.echo(f"Contract: {default_contract_path()}")
    click.echo("")
    click.echo("Variable surface summary:")
    click.echo(f"- workflow repo vars referenced: {len(workflow_vars)}")
    click.echo(f"- required repo vars: {len(required)}")
    click.echo(f"- optional repo vars: {len(optional)}")
    click.echo(f"- recommended minimal input vars: {len(minimal_list)}")
    click.echo(f"- alias vars: {len(aliases)}")

    click.echo("")
    click.echo("Workflow vars currently referenced:")
    click.echo(", ".join(workflow_vars))

    click.echo("")
    click.echo("Recommended minimal input:")
    click.echo(", ".join(minimal_list))

    if aliases:
        click.echo("")
        click.echo("Alias usage (replace with canonical names over time):")
        for alias, canonical in sorted(aliases.items()):
            hits = _count_alias_hits(alias)
            click.echo(f"- {alias} -> {canonical}: {hits} reference(s)")

    reduction_ratio = 0.0
    if workflow_vars:
        reduction_ratio = 1.0 - (len(minimal_list) / len(workflow_vars))
    click.echo("")
    click.echo(f"Potential reduction vs current workflow var surface: ~{reduction_ratio:.0%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_click_command(main))
