#!/usr/bin/env python3
"""Show env vars used by CI, Cloud Run, and local tooling."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from backend.config.constants import (
    ENV_BMT_CONTROL_JOB,
    ENV_BMT_STATUS_CONTEXT,
    ENV_BMT_TASK_HEAVY_JOB,
    ENV_BMT_TASK_STANDARD_JOB,
    ENV_CLOUD_RUN_REGION,
    ENV_GCP_PROJECT,
    ENV_GCP_SA_EMAIL,
    ENV_GCP_WIF_PROVIDER,
    ENV_GCS_BUCKET,
)
from tools.shared.cli_availability import command_available
from tools.shared.env_contract import (
    default_contract_path,
    list_context_vars,
    list_repo_var_vs_branch_required_status_context_checks,
    load_env_contract,
)

console = Console()


@dataclass(frozen=True)
class SecretHint:
    name: str
    present_label: str
    absent_label: str = "(unset)"


APP_TRIGGER_VAR_NAMES: tuple[str, ...] = ()
APP_TRIGGER_SECRET_HINTS: tuple[SecretHint, ...] = (
    SecretHint("BMT_GITHUB_APP_ID", "(present)"),
    SecretHint("BMT_GITHUB_APP_INSTALLATION_ID", "(present)"),
    SecretHint("BMT_GITHUB_APP_PRIVATE_KEY", "(present)"),
    SecretHint("BMT_GITHUB_APP_DEV_ID", "(present)"),
    SecretHint("BMT_GITHUB_APP_DEV_INSTALLATION_ID", "(present)"),
    SecretHint("BMT_GITHUB_APP_DEV_PRIVATE_KEY", "(present)"),
)


def gh_var(name: str) -> str | None:
    if not command_available("gh"):
        return None
    result = subprocess.run(["gh", "variable", "get", name], capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def gh_secret_names() -> set[str] | None:
    if not command_available("gh"):
        return None
    result = subprocess.run(["gh", "secret", "list", "--json", "name"], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return None
    try:
        secrets = json.loads(result.stdout)
        return {str(s.get("name", "")).strip() for s in secrets if str(s.get("name", "")).strip()}
    except json.JSONDecodeError:
        return None


def gh_repo_slug() -> str | None:
    if not command_available("gh"):
        return None
    result = subprocess.run(
        ["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"],
        capture_output=True,
        text=True,
        check=False,
    )
    slug = result.stdout.strip()
    return slug if result.returncode == 0 and "/" in slug else None


def gh_required_status_contexts(repo_slug: str, branch: str) -> list[str] | None:
    result = subprocess.run(
        ["gh", "api", f"repos/{repo_slug}/rules/branches/{branch}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, list):
        return None

    contexts: list[str] = []
    for rule in payload:
        if not isinstance(rule, dict):
            continue
        if str(rule.get("type", "")).strip() != "required_status_checks":
            continue
        parameters = rule.get("parameters", {})
        if not isinstance(parameters, dict):
            continue
        checks = parameters.get("required_status_checks", [])
        if not isinstance(checks, list):
            continue
        for check in checks:
            if not isinstance(check, dict):
                continue
            context = str(check.get("context", "")).strip()
            if context and context not in contexts:
                contexts.append(context)
    return contexts


def gcloud_config(name: str) -> str | None:
    if not command_available("gcloud"):
        return None
    result = subprocess.run(["gcloud", "config", "get-value", name], capture_output=True, text=True, check=False)
    val = result.stdout.strip()
    return val if val and not val.startswith("(unset)") else None


def _contract_defaults(contract: dict[str, object]) -> dict[str, str]:
    defaults_raw = contract.get("defaults", {})
    if not isinstance(defaults_raw, dict):
        return {}
    return {str(k): str(v) for k, v in defaults_raw.items()}


def _var_value_cell(val: str | None, default: str | None = None) -> Text:
    if val:
        return Text(val, style="green")
    if default is not None:
        if default == "":
            return Text('"" (default)', style="dim cyan")
        return Text(f"{default} (default)", style="dim cyan")
    return Text("(unset)", style="dim red")


def _vars_table(rows: list[tuple[str, Text]]) -> Table:
    t = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    t.add_column("Variable", style="bold")
    t.add_column("Value")
    for name, value in rows:
        t.add_row(name, value)
    return t


def print_github_section(contract: dict[str, object]) -> None:
    description = "Used by: build-and-test.yml, bmt-handoff.yml, direct Workflow dispatch, and Cloud Run jobs."
    content_parts: list = []

    contract_path = default_contract_path()
    content_parts.append(Text(f"Contract: {contract_path}", style="dim"))
    content_parts.append(Text())

    if not command_available("gh"):
        content_parts.append(Text("(gh not available; run 'gh auth login' in repo to list GitHub vars)", style="dim"))
        console.print(Panel(Text.assemble(*content_parts), title="[bold]GitHub (gh)[/]", subtitle=description))
        return

    required_vars = list_context_vars(contract, "github_repo_vars", "required")
    if not required_vars:
        required_vars = [
            ENV_GCS_BUCKET,
            ENV_GCP_PROJECT,
            ENV_CLOUD_RUN_REGION,
            ENV_BMT_CONTROL_JOB,
            ENV_BMT_TASK_STANDARD_JOB,
            ENV_BMT_TASK_HEAVY_JOB,
            ENV_GCP_SA_EMAIL,
        ]

    defaults = _contract_defaults(contract)
    optional_vars = list_context_vars(contract, "github_repo_vars", "optional")
    if not optional_vars:
        optional_vars = [ENV_BMT_STATUS_CONTEXT, ENV_GCP_WIF_PROVIDER]
    rows: list[tuple[str, Text]] = []
    for name in required_vars:
        rows.append((name, _var_value_cell(gh_var(name))))
    for name in optional_vars:
        rows.append((name, _var_value_cell(gh_var(name), default=defaults.get(name))))

    content_parts.append(_vars_table(rows))
    content_parts.append(Text())

    # Branch-rule consistency checks
    repo_slug = gh_repo_slug()
    branch_checks = list_repo_var_vs_branch_required_status_context_checks(contract)
    if repo_slug and branch_checks:
        tree = Tree(Text("Branch-rule consistency", style="bold"))
        for check in branch_checks:
            repo_var = check["repo_var"]
            branch = check["branch"]
            required = gh_required_status_contexts(repo_slug, branch)
            if required is None:
                tree.add(Text(f"{repo_var} @ {branch}: unable to read branch rules", style="dim"))
                continue
            current = gh_var(repo_var) or ""
            listed = ", ".join(required) if required else "<none>"
            if current and current in required:
                tree.add(
                    Text(f"{repo_var} @ {branch}: ", style="dim")
                    + Text("OK", style="green")
                    + Text(f" ({current}) from [{listed}]", style="dim")
                )
            elif current:
                tree.add(
                    Text(f"{repo_var} @ {branch}: ", style="dim")
                    + Text("DRIFT", style="yellow")
                    + Text(f" current={current} required=[{listed}]", style="dim")
                )
            else:
                tree.add(Text(f"{repo_var} @ {branch}: repo var unset required=[{listed}]", style="dim"))
        content_parts.append(tree)
        content_parts.append(Text())

    # App-trigger auth config (var + secret)
    secret_names = gh_secret_names() or set()
    secret_rows: list[tuple[str, Text]] = []
    for name in APP_TRIGGER_VAR_NAMES:
        secret_rows.append((name, _var_value_cell(gh_var(name))))
    for h in APP_TRIGGER_SECRET_HINTS:
        val = Text(h.present_label, style="green") if h.name in secret_names else Text(h.absent_label, style="dim red")
        secret_rows.append((h.name, val))
    content_parts.append(Text("GitHub App secrets:", style="bold"))
    content_parts.append(_vars_table(secret_rows))

    # Build panel content
    console.print(Panel(Group(*content_parts), title="[bold]GitHub (gh)[/]", subtitle=description))


def print_gcloud_section() -> None:
    description = "Used by: local uploads, Pulumi apply, and ad-hoc Cloud Run / Storage diagnostics."
    if not command_available("gcloud"):
        console.print(Panel(Text("(gcloud not available)", style="dim"), title="[bold]gcloud[/]", subtitle=description))
        return

    rows: list[tuple[str, Text]] = [
        ("project", _var_value_cell(gcloud_config("project"))),
        ("account", _var_value_cell(gcloud_config("account"))),
        ("run/region", _var_value_cell(gcloud_config("run/region"))),
    ]
    console.print(Panel(_vars_table(rows), title="[bold]gcloud[/]", subtitle=description))


class GhShowEnv:
    """Show env vars used by CI, Cloud Run, and local tooling."""

    def run(self) -> int:
        try:
            contract = load_env_contract()
        except (OSError, ValueError, json.JSONDecodeError):
            contract = {}
        print_github_section(contract)
        console.print()
        print_gcloud_section()
        return 0


if __name__ == "__main__":
    raise SystemExit(GhShowEnv().run())
