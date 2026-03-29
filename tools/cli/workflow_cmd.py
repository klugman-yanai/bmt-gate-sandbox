"""Contributor workflow overview and repo status (Rich when TTY)."""

from __future__ import annotations

import sys

import typer
from rich import box
from rich.columns import Columns
from rich.console import Console, Group
from rich.padding import Padding
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from tools.repo.paths import repo_root
from tools.shared.contributor_docs import ContributorDocRefs
from tools.shared.rich_command_text import command_line_highlight
from tools.shared.rich_contributor_theme import contributor_console
from tools.shared.rich_minimal import use_rich
from tools.shared.rich_tty import detected_terminal_columns, rich_layout_profile
from tools.workflow.guide import RepoWorkflowHints, repo_workflow_hints, workflow_steps_ordered

app = typer.Typer(
    name="workflow",
    help="Ordered checklist for onboarding and adding projects/BMTs (see CONTRIBUTING.md).",
    no_args_is_help=True,
)


def _console() -> Console | None:
    if not use_rich(verbose=False) or not sys.stdout.isatty():
        return None
    return contributor_console(width=detected_terminal_columns(), strip_highlight=True)


def _overview_header(refs: ContributorDocRefs) -> Group:
    path = refs.contributing_rel()
    title = Text("Contributor workflow", style="contrib.title")
    sub = Text()
    sub.append("Full guide ", style="contrib.tagline")
    sub.append(path, style="contrib.link")
    return Group(title, sub)


def _print_overview_plain() -> None:
    refs = ContributorDocRefs.discover()
    print("Contributor workflow")
    print(f"Full guide: {refs.contributing_rel()}")
    print()
    print("—" * min(56, 72))
    for i, step in enumerate(workflow_steps_ordered(), start=1):
        cmd = step.primary_command or "—"
        print()
        print(f"{i}. {step.title}")
        print(f"   {step.summary}")
        print(f"   {cmd}")


def _print_overview_rich(console: Console) -> None:
    """Panel + themed text: one contained block, breathing room, no extra rules."""
    refs = ContributorDocRefs.discover()
    indent = 3
    blocks: list[Columns | Group | Padding | Text] = []

    for i, step in enumerate(workflow_steps_ordered(), start=1):
        if blocks:
            blocks.append(Text(""))
        head = Text()
        head.append(f"{i}. ", style="contrib.step_num")
        head.append(step.title, style="contrib.section")
        blocks.append(head)
        blocks.append(
            Padding(
                Text(step.summary, style="contrib.summary", overflow="fold", no_wrap=False),
                pad=(0, 0, 0, indent),
            )
        )
        cmd = (step.primary_command or "").strip()
        if cmd and cmd != "—":
            blocks.append(
                Padding(
                    Columns(
                        [Text("run  ", style="contrib.label"), command_line_highlight(cmd)],
                        padding=(0, 0),
                        expand=False,
                    ),
                    pad=(0, 0, 0, indent),
                )
            )
        else:
            blocks.append(Padding(Text("—", style="contrib.placeholder"), pad=(0, 0, 0, indent)))

    body = Group(*blocks)
    panel = Panel(
        body,
        title="[contrib.section]Steps[/]",
        title_align="left",
        border_style="contrib.panel_border",
        box=box.ROUNDED,
        padding=(0, 1),
        expand=False,
    )

    console.print(_overview_header(refs))
    console.print()
    console.print(panel)


@app.command("overview")
def workflow_overview() -> None:
    """Print the ordered checklist (CONTRIBUTING.md flow)."""
    c = _console()
    if c is None:
        _print_overview_plain()
    else:
        _print_overview_rich(c)
    raise typer.Exit(0)


def _print_status_plain(hints: RepoWorkflowHints) -> None:
    has_venv = hints.has_venv
    names = hints.stage_project_names
    print("Repo status")
    print()
    print(f".venv: {has_venv}")
    if names:
        print("benchmarks/projects: " + ", ".join(names))
    else:
        print("benchmarks/projects: (none)")


def _print_status_rich(console: Console, hints: RepoWorkflowHints) -> None:
    has_venv = hints.has_venv
    names = hints.stage_project_names
    profile = rich_layout_profile(columns=console.size.width)
    narrow = profile.narrow
    venv_cell = Text("yes", style="contrib.ok") if has_venv else Text("no", style="contrib.warn")
    table = Table(
        box=box.SIMPLE,
        show_header=True,
        header_style="contrib.table_head",
        border_style="contrib.panel_border",
        padding=(0, 0) if narrow else (0, 1),
        expand=False,
        width=None if narrow else min(profile.columns, 96),
    )
    table.add_column("Signal", style="contrib.muted", no_wrap=True, width=18 if narrow else None)
    table.add_column("Value", style="contrib.value", overflow="fold")
    table.add_row(".venv", venv_cell)
    if names:
        if narrow:
            shown = names[:20]
            proj_cell = Text()
            for j, n in enumerate(shown):
                if j:
                    proj_cell.append("\n")
                proj_cell.append(n, style="contrib.path")
            if len(names) > len(shown):
                proj_cell.append(f"\n(+{len(names) - len(shown)} more)", style="contrib.muted")
            table.add_row("benchmarks/projects", proj_cell)
        else:
            line = Text(", ".join(names[:12]), style="contrib.path")
            if len(names) > 12:
                line.append(" ")
                line.append(f"(+{len(names) - 12} more)", style="contrib.muted")
            table.add_row("benchmarks/projects", line)
    else:
        table.add_row("benchmarks/projects", Text("—", style="contrib.placeholder"))

    console.print(
        Panel(
            table,
            title="[contrib.section]Repo status[/]",
            title_align="left",
            border_style="contrib.panel_border",
            box=box.ROUNDED,
            padding=(0, 1),
            expand=False,
        )
    )


@app.command("status")
def workflow_status() -> None:
    """Show quick filesystem hints (.venv, benchmarks/projects/*)."""
    hints = repo_workflow_hints(repo_root=repo_root())
    c = _console()
    if c is None:
        _print_status_plain(hints)
    else:
        _print_status_rich(c, hints)
    raise typer.Exit(0)


def register_workflow(target: typer.Typer) -> None:
    target.add_typer(
        app,
        name="workflow",
        rich_help_panel="Contributor workflow",
    )
