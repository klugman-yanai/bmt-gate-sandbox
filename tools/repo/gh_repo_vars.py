#!/usr/bin/env python3
"""Check/apply declarative GitHub repository variables.

Pulumi is the source of truth. Expected values come from Pulumi stack output;
optional config file can override. Secrets are not set by this tool.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from runtime.config.constants import ENV_GCP_PROJECT, ENV_GCP_WIF_PROVIDER
from tools.pulumi.pulumi_repo_vars import get_expected_repo_vars_from_pulumi
from tools.shared.bucket_env import truthy
from tools.shared.cli_availability import command_available
from tools.shared.contributor_docs import ContributorDocRefs
from tools.shared.env_contract import default_contract_path, load_env_contract


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


def _get_expected_from_pulumi() -> tuple[dict[str, str], str | None]:
    """Return (Pulumi-sourced desired repo vars, error message if Pulumi failed)."""
    try:
        return get_expected_repo_vars_from_pulumi(), None
    except Exception as e:
        return {}, str(e)


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
        # Branch has no required status checks (e.g. protection not configured, or test repo).
        # Fall back to declared → current → default so repo-vars-check can still run.
        fallback = declared.get(check.repo_var) or current.get(check.repo_var) or defaults.get(check.repo_var)
        if fallback:
            return fallback
        raise RuntimeError(
            f"Branch rule drift check for {check.repo_var} failed: "
            f"branch '{check.branch}' has no required_status_checks contexts and no fallback (declared/current/default) for {check.repo_var}."
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
    payload = load_env_contract(str(path))
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


def _validate_wif_provider_consistency(desired: dict[str, str]) -> list[str]:
    """Validate GCP_WIF_PROVIDER format and project-number alignment when possible."""
    warnings: list[str] = []
    provider = desired.get(ENV_GCP_WIF_PROVIDER, "").strip()
    project_id = desired.get(ENV_GCP_PROJECT, "").strip()
    if not provider or not project_id:
        return warnings

    pattern = r"^projects/([0-9]+)/locations/global/workloadIdentityPools/([^/]+)/providers/([^/]+)$"
    match = re.match(pattern, provider)
    if not match:
        raise RuntimeError(
            f"Invalid {ENV_GCP_WIF_PROVIDER} format. Expected "
            "projects/<number>/locations/global/workloadIdentityPools/<pool>/providers/<provider> "
            f"but got: {provider!r}"
        )

    provider_project_number = match.group(1)
    if not command_available("gcloud"):
        refs = ContributorDocRefs.discover()
        warnings.append(
            "gcloud not found; skipped WIF/provider project-number alignment check. "
            f"Install the Google Cloud SDK or see {refs.configuration_rel()}."
        )
        return warnings

    result = _run(["gcloud", "projects", "describe", project_id, "--format=value(projectNumber)"])
    if result.returncode != 0:
        warnings.append(
            f"could not resolve project number via gcloud for "
            f"{ENV_GCP_PROJECT}={project_id!r}; skipped strict WIF alignment check."
        )
        return warnings

    actual_project_number = result.stdout.strip()
    if not actual_project_number:
        warnings.append(
            f"gcloud returned empty project number for {ENV_GCP_PROJECT}={project_id!r}; skipped strict WIF alignment check."
        )
        return warnings

    if provider_project_number != actual_project_number:
        raise RuntimeError(
            f"{ENV_GCP_WIF_PROVIDER} project number mismatch: "
            f"provider={provider_project_number} project={actual_project_number} ({ENV_GCP_PROJECT}={project_id})"
        )
    return warnings


def _render(value: str) -> str:
    if not value:
        return "<empty>"
    # Avoid showing Pulumi errors or ANSI garbage as "desired"
    if "\n" in value or "No outputs found" in value or "Warning:" in value or "\x1b[" in value:
        return "<run just pulumi first>"
    return value


def _print_success(msg: str, *, use_rich: bool) -> None:
    if use_rich:
        try:
            from rich.console import Console

            Console().print(f"  [green]{msg}[/]")
            return
        except ImportError:
            pass
    print(f"  {msg}")


def _print_branch_rule_plain(
    branch_rule_checks: list,
    branch_rule_available: dict,
    branch_rule_values: dict,
) -> None:
    print("Branch-rule sourced vars:")
    for check in branch_rule_checks:
        available = ", ".join(branch_rule_available.get(check.repo_var, [])) or "<none>"
        resolved = branch_rule_values.get(check.repo_var, "<unresolved>")
        selector_suffix = (
            f", context_substring={check.context_substring!r}" if check.context_substring is not None else ""
        )
        print(
            f"- {check.repo_var}: branch={check.branch}{selector_suffix} "
            f"resolved={_render(resolved)} from [{available}]"
        )


def _print_repo_vars_status_plain(diff: _VarsDiff) -> None:
    print("Repo vars status:")
    for name in diff.ordered_names:
        state, current_display, desired_display = _var_row_data(name, diff)
        print(f"- {name}: {state}")
        if not state.startswith("OK"):
            print(f"  current: {current_display}")
            print(f"  desired: {desired_display}")


@dataclass(frozen=True)
class _VarsDiff:
    """All computed state for a repo-vars check/apply run."""

    ordered_names: list[str]
    required_set: set[str]
    declared: dict[str, str]
    current: dict[str, str]
    desired: dict[str, str]
    desired_origin: dict[str, str]
    desired_absent: set[str]
    missing_required: list[str]
    missing: list[str]
    changed: list[str]
    should_delete: list[str]
    extra: list[str]
    branch_rule_checks: list[RepoVarBranchStatusContextCheck]
    branch_rule_available: dict[str, list[str]]
    branch_rule_values: dict[str, str]
    wif_warnings: list[str]
    pulumi_error: str | None
    contract_path: Path
    config_path: Path


def _var_row_data(
    name: str,
    diff: _VarsDiff,
) -> tuple[str, str, str]:
    """Return (state_label, current_display, desired_display) for a single var row.

    Used by both the Rich and plaintext renderers so state-labeling logic lives once.
    """
    desired = diff.desired
    current = diff.current
    if name in diff.missing_required:
        return "MISSING_REQUIRED", "<missing>", "<required>"
    if name in diff.desired_absent and name not in current:
        return "OK (ABSENT)", "<missing>", "-"
    if name in diff.should_delete:
        return "DRIFT (SHOULD_BE_ABSENT)", _render(current[name]), "<absent>"
    if name in diff.missing:
        return "MISSING", "<missing>", _render(desired[name])
    if name in diff.changed:
        return "DRIFT", _render(current[name]), _render(desired[name])
    if diff.desired_origin.get(name) == "default" and name not in current:
        return "OK (DEFAULT)", "<missing>", "-"
    # OK variants
    current_display = _render(current.get(name, ""))
    origin = diff.desired_origin.get(name, "")
    if origin == "branch_rule":
        state = "OK (BRANCH_RULE)"
    elif origin == "current" and name not in diff.declared:
        state = "OK (INHERITED_CURRENT)"
    elif origin == "default" and name not in diff.declared:
        state = "OK (DEFAULT)"
    else:
        state = "OK"
    desired_display = _render(desired[name]) if desired.get(name) else "-"
    return state, current_display, desired_display


class GhRepoVars:
    """Check/apply declarative GitHub repository variables."""

    def run(
        self,
        *,
        config: str = "",
        contract_path: Path | None = None,
        apply: bool = False,
        prune_extra: bool = False,
        force: bool = False,
    ) -> int:
        diff = self._build_diff(config=config, contract_path=contract_path)
        if isinstance(diff, int):
            return diff
        self._render(diff)
        if diff.missing_required:
            print(file=sys.stderr)
            print("::error::Missing required repo vars with no current value or contract default.", file=sys.stderr)
            print("::error::Run: just pulumi (or set in GitHub vars / infra).", file=sys.stderr)
            for name in sorted(diff.missing_required):
                print(f"::error::- {name}", file=sys.stderr)
            return 1
        if not apply:
            return self._check_result(diff)
        return self._apply(diff, prune_extra=prune_extra, force=force)

    def _build_diff(self, *, config: str, contract_path: Path | None) -> _VarsDiff | int:
        """Load all state and compute the diff. Returns an int exit code on error."""
        resolved_contract = contract_path if contract_path is not None else default_contract_path()
        config_path = Path(config).expanduser().resolve() if config else Path("/nonexistent/repo_vars.toml")
        if not Path(resolved_contract).resolve().is_file():
            print(f"::error::Missing env contract file: {resolved_contract}", file=sys.stderr)
            return 2

        try:
            declared, pulumi_error = _get_expected_from_pulumi()
            if config_path.is_file():
                for k, v in _load_config(config_path).items():
                    declared[k] = v
            canonical_order, required_set, contract_defaults, branch_rule_checks = _load_contract(resolved_contract)
        except Exception as exc:
            print(f"::error::Invalid config/contract: {exc}", file=sys.stderr)
            return 2

        try:
            current = _gh_vars()
        except Exception as exc:
            print(f"::error::{exc}", file=sys.stderr)
            return 2

        try:
            branch_rule_values, branch_rule_available = _resolve_branch_rule_repo_var_values(
                branch_rule_checks,
                declared=declared,
                current=current,
                defaults=contract_defaults,
            )
        except Exception as exc:
            print(f"::error::{exc}", file=sys.stderr)
            return 2

        canonical = set(canonical_order)
        undeclared_unknown = [name for name in declared if name not in canonical]
        if undeclared_unknown:
            print("::error::Config contains names not in env contract github_repo_vars:", file=sys.stderr)
            for name in undeclared_unknown:
                print(f"::error::- {name}", file=sys.stderr)
            return 2

        ordered_names = list(declared.keys()) + [name for name in canonical_order if name not in declared]
        desired: dict[str, str] = {}
        desired_origin: dict[str, str] = {}
        missing_required: list[str] = []
        for name in ordered_names:
            if name in branch_rule_values:
                desired[name] = branch_rule_values[name]
                desired_origin[name] = "branch_rule"
            elif name in declared:
                desired[name] = declared[name]
                desired_origin[name] = "config"
            elif name in current:
                desired[name] = current[name]
                desired_origin[name] = "current"
            elif name in contract_defaults:
                desired[name] = contract_defaults[name]
                desired_origin[name] = "default"
            elif name in required_set:
                desired[name] = ""
                desired_origin[name] = "missing_required"
                missing_required.append(name)
            else:
                desired[name] = ""
                desired_origin[name] = "optional_absent"

        desired_absent = {name for name, value in desired.items() if value == ""}
        missing = sorted(
            name
            for name in ordered_names
            if name not in current
            and name not in desired_absent
            and name not in missing_required
            and (
                desired_origin.get(name) == "config" or (desired_origin.get(name) == "default" and name in required_set)
            )
        )
        changed = sorted(
            name for name in ordered_names if name in current and desired[name] != "" and current[name] != desired[name]
        )
        should_delete = sorted(name for name in desired_absent if name in current)
        extra = sorted(name for name in current if name not in canonical)

        try:
            wif_warnings = _validate_wif_provider_consistency(desired)
        except Exception as exc:
            print(f"::error::{exc}", file=sys.stderr)
            return 2

        return _VarsDiff(
            ordered_names=ordered_names,
            required_set=required_set,
            declared=declared,
            current=current,
            desired=desired,
            desired_origin=desired_origin,
            desired_absent=desired_absent,
            missing_required=missing_required,
            missing=missing,
            changed=changed,
            should_delete=should_delete,
            extra=extra,
            branch_rule_checks=branch_rule_checks,
            branch_rule_available=branch_rule_available,
            branch_rule_values=branch_rule_values,
            wif_warnings=wif_warnings,
            pulumi_error=pulumi_error,
            contract_path=Path(resolved_contract),
            config_path=config_path,
        )

    def _render(self, diff: _VarsDiff) -> None:
        """Print header, branch-rule table, and repo-vars status table."""
        use_rich = sys.stdout.isatty() and not os.environ.get("GITHUB_ACTIONS")

        if diff.config_path.is_file():
            print(f"Config: {diff.config_path}")
        else:
            print("Config: (Pulumi + optional overrides; no override file)")
        print(f"Contract: {diff.contract_path}")
        if diff.pulumi_error:
            print()
            print(f"::warning::Pulumi state unavailable: {diff.pulumi_error}")
            print(
                "::warning::Desired values for infra-derived vars come from current/default only. Run `just pulumi` to populate from Pulumi."
            )
        print()

        if diff.branch_rule_checks:
            if use_rich:
                try:
                    from rich.console import Console
                    from rich.table import Table

                    t = Table(title="Branch-rule sourced vars")
                    t.add_column("Var", style="cyan")
                    t.add_column("Branch", style="dim")
                    t.add_column("Resolved", style="green")
                    t.add_column("Available", style="dim")
                    for check in diff.branch_rule_checks:
                        available = ", ".join(diff.branch_rule_available.get(check.repo_var, [])) or "<none>"
                        resolved = diff.branch_rule_values.get(check.repo_var, "<unresolved>")
                        selector = f"{check.branch}" + (
                            f" {check.context_substring!r}" if check.context_substring else ""
                        )
                        t.add_row(check.repo_var, selector, _render(resolved), available)
                    Console().print(t)
                except ImportError:
                    _print_branch_rule_plain(
                        diff.branch_rule_checks, diff.branch_rule_available, diff.branch_rule_values
                    )
            else:
                _print_branch_rule_plain(diff.branch_rule_checks, diff.branch_rule_available, diff.branch_rule_values)
            print()

        for warning in diff.wif_warnings:
            print(f"::warning::{warning}")
        if diff.wif_warnings:
            print()

        if use_rich:
            try:
                from rich.console import Console
                from rich.table import Table

                t = Table(title="Repo vars status")
                t.add_column("Var", style="cyan")
                t.add_column("State", style="bold")
                t.add_column("Current", style="dim")
                t.add_column("Desired", style="dim")
                for name in diff.ordered_names:
                    state, current_display, desired_display = _var_row_data(name, diff)
                    style = "red" if state.startswith(("MISSING", "DRIFT")) else "green"
                    t.add_row(name, state, current_display, desired_display, style=style)
                Console().print(t)
            except ImportError:
                _print_repo_vars_status_plain(diff)
        else:
            _print_repo_vars_status_plain(diff)

        if diff.extra:
            print()
            print("Extra non-canonical repo vars:")
            for name in diff.extra:
                print(f"- {name}={_render(diff.current[name])}")

    def _check_result(self, diff: _VarsDiff) -> int:
        """Return exit code for a check (non-apply) run."""
        use_rich = sys.stdout.isatty() and not os.environ.get("GITHUB_ACTIONS")
        if diff.missing or diff.changed or diff.should_delete or diff.extra:
            print(file=sys.stderr)
            print("::error::Repo vars differ from contract/default-backed desired state.", file=sys.stderr)
            print("::error::Run: just repo-vars-apply (with BMT_PRUNE_EXTRA=1 to prune)", file=sys.stderr)
            return 1
        print()
        _print_success("Repo vars match contract/default-backed desired state.", use_rich=use_rich)
        return 0

    def _apply(self, diff: _VarsDiff, *, prune_extra: bool, force: bool) -> int:
        """Apply the diff: set missing/changed vars, delete absent vars, optionally prune extras."""
        use_rich = sys.stdout.isatty() and not os.environ.get("GITHUB_ACTIONS")

        if not (diff.missing or diff.changed) and not force:
            print()
            print("Repo vars already match; nothing to apply. Use BMT_FORCE=1 to re-set all managed vars.")
            return 0

        if diff.missing or diff.changed or force:
            to_set = (
                set(diff.missing + diff.changed)
                if not force
                else {n for n in diff.ordered_names if diff.desired.get(n) != ""}
            )
            if to_set:
                print()
                print("Applying managed repo vars...")
                for name in [n for n in diff.desired if n in to_set]:
                    _gh_set(name, diff.desired[name])
                    print(f"- set {name}={_render(diff.desired[name])}")
        else:
            print()
            print("No managed var updates needed.")

        if diff.should_delete:
            print()
            print("Deleting vars declared as absent (empty value in config)...")
            for name in diff.should_delete:
                _gh_delete(name)
                print(f"- deleted {name}")

        if prune_extra:
            if diff.extra:
                print()
                print("Pruning undeclared repo vars...")
                for name in diff.extra:
                    _gh_delete(name)
                    print(f"- deleted {name}")
            else:
                print()
                print("No undeclared vars to prune.")
        elif diff.extra:
            print()
            print("Undeclared vars were not pruned (set BMT_PRUNE_EXTRA=1).")

        print()
        msg = (
            "Managed vars synced; undeclared vars still exist."
            if diff.extra and not prune_extra
            else "Repo vars synced to contract/default-backed desired state."
        )
        _print_success(msg, use_rich=use_rich)
        return 0


if __name__ == "__main__":
    config = (os.environ.get("BMT_CONFIG") or "").strip()
    contract_raw = (os.environ.get("BMT_CONTRACT") or "").strip()
    contract_path = Path(contract_raw).resolve() if contract_raw else None
    apply = "--apply" in sys.argv
    prune_extra = truthy(os.environ.get("BMT_PRUNE_EXTRA"))
    force = truthy(os.environ.get("BMT_FORCE"))
    raise SystemExit(
        GhRepoVars().run(
            config=config,
            contract_path=contract_path,
            apply=apply,
            prune_extra=prune_extra,
            force=force,
        )
    )
