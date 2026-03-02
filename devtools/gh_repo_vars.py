#!/usr/bin/env python3
"""Check/apply declarative GitHub repository variables."""

from __future__ import annotations

import json
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path

import click
from click_exit import run_click_command
from repo_paths import DEFAULT_ENV_CONTRACT_PATH, DEFAULT_REPO_VARS_PATH


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=False, text=True, capture_output=True)


@dataclass(frozen=True)
class RepoVarBranchStatusContextCheck:
    repo_var: str
    branch: str
    context_substring: str | None = None


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


def _gh_repo_slug() -> str:
    result = _run(["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "gh repo view failed")
    slug = result.stdout.strip()
    if not slug or "/" not in slug:
        raise RuntimeError(f"failed to resolve repository slug via gh repo view: {slug!r}")
    return slug


def _required_status_contexts_for_branch(repo: str, branch: str) -> list[str]:
    result = _run(["gh", "api", f"repos/{repo}/rules/branches/{branch}"])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"failed to fetch effective rules for branch {branch}")
    try:
        rules = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"failed to parse branch rules payload for {branch}: {exc}") from exc
    if not isinstance(rules, list):
        raise RuntimeError(f"unexpected branch rules payload type for {branch}: expected list")
    contexts: list[str] = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        if str(rule.get("type", "")).strip() != "required_status_checks":
            continue
        parameters = rule.get("parameters", {})
        if not isinstance(parameters, dict):
            continue
        status_checks = parameters.get("required_status_checks", [])
        if not isinstance(status_checks, list):
            continue
        for item in status_checks:
            if not isinstance(item, dict):
                continue
            context = str(item.get("context", "")).strip()
            if context and context not in contexts:
                contexts.append(context)
    return contexts


def _select_branch_rule_context(
    *,
    contexts: list[str],
    check: RepoVarBranchStatusContextCheck,
    declared: dict[str, str],
    current: dict[str, str],
    defaults: dict[str, str],
) -> str:
    if not contexts:
        raise RuntimeError(
            f"Branch rule drift check for {check.repo_var} failed: "
            f"branch '{check.branch}' has no required_status_checks contexts."
        )

    candidates = contexts
    if check.context_substring:
        lowered = check.context_substring.lower()
        filtered = [context for context in contexts if lowered in context.lower()]
        if not filtered:
            raise RuntimeError(
                f"Branch rule drift check for {check.repo_var} failed: no required status context on "
                f"branch '{check.branch}' matches context_substring={check.context_substring!r}. "
                f"Available: {', '.join(contexts)}"
            )
        candidates = filtered

    if len(candidates) == 1:
        return candidates[0]

    preferred_values = (
        ("config", declared.get(check.repo_var)),
        ("current", current.get(check.repo_var)),
        ("default", defaults.get(check.repo_var)),
    )
    for _source, preferred in preferred_values:
        if preferred and preferred in candidates:
            return preferred

    if check.repo_var.startswith("BMT_"):
        bmt_contexts = [context for context in candidates if "bmt" in context.lower()]
        if len(bmt_contexts) == 1:
            return bmt_contexts[0]

    raise RuntimeError(
        f"Branch rule drift check for {check.repo_var} is ambiguous on branch '{check.branch}'. "
        f"Candidates: {', '.join(candidates)}. "
        f"Set context_substring in contract to disambiguate."
    )


def _resolve_branch_rule_repo_var_values(
    checks: list[RepoVarBranchStatusContextCheck],
    *,
    declared: dict[str, str],
    current: dict[str, str],
    defaults: dict[str, str],
) -> tuple[dict[str, str], dict[str, list[str]]]:
    if not checks:
        return {}, {}

    repo_slug = _gh_repo_slug()
    effective_values: dict[str, str] = {}
    available_by_var: dict[str, list[str]] = {}
    for check in checks:
        contexts = _required_status_contexts_for_branch(repo_slug, check.branch)
        selected = _select_branch_rule_context(
            contexts=contexts,
            check=check,
            declared=declared,
            current=current,
            defaults=defaults,
        )
        existing = effective_values.get(check.repo_var)
        if existing is not None and existing != selected:
            raise RuntimeError(
                f"Branch rule drift check conflict for {check.repo_var}: resolved both {existing!r} and {selected!r} "
                f"from different checks."
            )
        effective_values[check.repo_var] = selected
        available_by_var[check.repo_var] = contexts
    return effective_values, available_by_var


def _load_contract(
    path: Path,
) -> tuple[list[str], set[str], dict[str, str], list[RepoVarBranchStatusContextCheck]]:
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

    canonical = set(ordered)
    defaults_raw = payload.get("defaults", {})
    defaults: dict[str, str] = {}
    if isinstance(defaults_raw, dict):
        for key, value in defaults_raw.items():
            name = str(key).strip()
            if name:
                defaults[name] = str(value)

    checks: list[RepoVarBranchStatusContextCheck] = []
    consistency_raw = payload.get("consistency_checks", {})
    if consistency_raw and not isinstance(consistency_raw, dict):
        raise RuntimeError("'consistency_checks' must be an object")
    branch_checks_raw = (
        consistency_raw.get("repo_var_vs_branch_required_status_context", [])
        if isinstance(consistency_raw, dict)
        else []
    )
    if branch_checks_raw and not isinstance(branch_checks_raw, list):
        raise RuntimeError("'consistency_checks.repo_var_vs_branch_required_status_context' must be an array")
    for idx, entry in enumerate(branch_checks_raw):
        if not isinstance(entry, dict):
            raise RuntimeError(
                f"'consistency_checks.repo_var_vs_branch_required_status_context[{idx}]' must be an object"
            )
        repo_var = str(entry.get("repo_var", "")).strip()
        branch = str(entry.get("branch", "")).strip()
        context_substring_raw = entry.get("context_substring")
        context_substring = (
            str(context_substring_raw).strip()
            if isinstance(context_substring_raw, str) and context_substring_raw
            else None
        )
        if not repo_var or not branch:
            raise RuntimeError(
                f"'consistency_checks.repo_var_vs_branch_required_status_context[{idx}]' requires non-empty "
                "'repo_var' and 'branch'"
            )
        if repo_var not in canonical:
            raise RuntimeError(
                f"'consistency_checks.repo_var_vs_branch_required_status_context[{idx}]' repo_var={repo_var!r} "
                "is not declared in contexts.github_repo_vars required/optional"
            )
        checks.append(
            RepoVarBranchStatusContextCheck(
                repo_var=repo_var,
                branch=branch,
                context_substring=context_substring,
            )
        )

    return ordered, set(required), defaults, checks


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
@click.option("--config", default=DEFAULT_REPO_VARS_PATH, show_default=True, help="Declarative repo vars file")
@click.option("--contract", default=DEFAULT_ENV_CONTRACT_PATH, show_default=True, help="Env contract file")
@click.option("--apply", is_flag=True, help="Apply missing/drifted variables to GitHub")
@click.option("--prune-extra", is_flag=True, help="Delete repo vars not declared in config (only with --apply)")
@click.option(
    "--force",
    is_flag=True,
    help="With --apply: re-set all managed vars even if already in sync (default: skip when no changes).",
)
def main(
    config: str,
    contract: str,
    apply: bool,
    prune_extra: bool,
    force: bool,
) -> int:
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
        canonical_order, required_set, contract_defaults, branch_rule_checks = _load_contract(contract_path)
    except Exception as exc:
        click.echo(f"::error::Invalid config/contract: {exc}", err=True)
        return 2

    try:
        current = _gh_vars()
    except Exception as exc:
        click.echo(f"::error::{exc}", err=True)
        return 2

    try:
        branch_rule_values, branch_rule_available = _resolve_branch_rule_repo_var_values(
            branch_rule_checks,
            declared=declared,
            current=current,
            defaults=contract_defaults,
        )
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
        if name in branch_rule_values:
            desired[name] = branch_rule_values[name]
            desired_origin[name] = "branch_rule"
            continue
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
        name for name in ordered_names if name in current and desired[name] != "" and current[name] != desired[name]
    )
    should_delete = sorted(name for name in desired_absent if name in current)
    extra = sorted(name for name in current if name not in canonical)

    if config_path.is_file():
        click.echo(f"Config: {config_path}")
    else:
        click.echo(f"Config: (missing, using current+defaults only) [{config_path}]")
    click.echo(f"Contract: {contract_path}")
    click.echo("")
    if branch_rule_checks:
        click.echo("Branch-rule sourced vars:")
        for check in branch_rule_checks:
            available = ", ".join(branch_rule_available.get(check.repo_var, [])) or "<none>"
            resolved = branch_rule_values.get(check.repo_var, "<unresolved>")
            selector_suffix = (
                f", context_substring={check.context_substring!r}" if check.context_substring is not None else ""
            )
            click.echo(
                f"- {check.repo_var}: branch={check.branch}{selector_suffix} "
                f"resolved={_render(resolved)} from [{available}]"
            )
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
            if desired_origin.get(name) == "branch_rule":
                state = "OK (BRANCH_RULE)"
            elif desired_origin.get(name) == "current" and name not in declared:
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

    if not (missing or changed) and not force:
        click.echo("")
        click.echo("Repo vars already match; nothing to apply. Use --force to re-set all managed vars.")
        return 0

    if missing or changed or force:
        to_set = set(missing + changed) if not force else {n for n in ordered_names if desired.get(n) != ""}
        if to_set:
            click.echo("")
            click.echo("Applying managed repo vars...")
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
