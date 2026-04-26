"""Post-bootstrap onboarding summary (Rich). Run after setup.sh."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

if TYPE_CHECKING:
    from rich.panel import Panel
    from rich.table import Table

import typer

from tools.shared.contributor_docs import SETUP_DOCS_ONE_LINE
from tools.shared.rich_minimal import use_rich

_PREK_STATES = frozenset({"hooks-path", "already-installed", "would-install", "no-git"})


def _panel_width(console) -> int:
    """Usable width for bordered panels (avoids mid-word fold in very narrow terminals)."""
    w = console.size.width
    return max(52, min(100, w - 4))


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _onboard_console():
    """Return a Rich Console with heuristic highlighting disabled (prose-friendly)."""
    from rich.console import Console
    from rich.highlighter import NullHighlighter

    if not use_rich(verbose=False):
        return None
    return Console(
        highlight=False,
        highlighter=NullHighlighter(),
        soft_wrap=True,
    )


def _dry_run_intro_markup(prek_state: str | None) -> str:
    """Body text for dry-run panel (bootstrap stderr is silent in preview mode)."""
    ps = (prek_state or "").strip()
    lines = [
        "[bold]Dry run[/]",
        "",
        "[dim]No writes:[/] skipped [cyan]uv sync[/][dim],[/] [cyan]prek install[/][dim], and hook commands.",
        "",
    ]
    if ps == "hooks-path":
        lines.extend(
            [
                "[dim]Prek install skipped:[/] [cyan]core.hooksPath[/][dim] is set (hooks are not under "
                "[cyan].git/hooks/[/]).[/]",
                "",
            ]
        )
    elif ps == "no-git":
        lines.extend(
            [
                "[dim]Not a git checkout — hook install does not apply.[/]",
                "",
            ]
        )
    lines.append(
        "[dim]Without[/] [cyan]--dry-run[/][dim], the bootstrap runs[/] [cyan]uv sync[/] [dim]then prek when applicable.[/]"
    )
    return "\n".join(lines)


def _hooks_table() -> Table:
    from rich import box
    from rich.table import Table

    table = Table(
        box=box.SIMPLE_HEAD,
        show_header=True,
        header_style="dim",
        border_style="dim",
        padding=(0, 1),
        title="Hook stages (.pre-commit-config.yaml)",
        title_style="dim",
    )
    table.add_column("Stage", style="dim", no_wrap=True, width=11)
    table.add_column("What runs", style="default")
    table.add_row(
        "pre-commit",
        "ruff check · ruff format · gcp/ sync check · image-build warning",
    )
    table.add_row(
        "pre-push",
        "ty check · pytest fast gate (unit or contract; not the full suite)",
    )
    return table


def _dry_run_prek_renderable(prek_state: str | None) -> Panel | None:
    from rich.panel import Panel
    from rich.text import Text

    state = (prek_state or "").strip()
    if state == "hooks-path":
        # Explained in dry-run intro (no second panel).
        return None
    if state == "already-installed":
        msg = (
            "[green]Prek[/] shims for [cyan]pre-commit[/] and [cyan]pre-push[/] look present.\n"
            "A real run would mostly refresh via [cyan]prek install -f[/]."
        )
        border = "green"
    elif state == "would-install":
        msg = "A real run would run [cyan]prek install[/] for [cyan]pre-commit[/] and [cyan]pre-push[/]."
        border = "blue"
    elif state == "no-git":
        msg = "[dim]Not a git working tree — hook install does not apply.[/]"
        border = "dim"
    else:
        msg = "Run [cyan]just setup[/] to complete bootstrap and install hooks. See [cyan]CONTRIBUTING.md[/]."
        border = "dim"

    return Panel(
        Text.from_markup(msg, overflow="fold"),
        border_style=border,
        padding=(0, 1),
        expand=False,
        highlight=False,
    )


def run_onboard_rich(*, dry_run: bool, prek_state: str | None) -> None:
    """Print Rich panels for post-bootstrap (or dry-run) summary."""
    if not dry_run:
        prek_state = None

    console = _onboard_console()
    root = _repo_root()
    contributing = root / "CONTRIBUTING.md"

    if dry_run:
        if console is None:
            ps = (prek_state or "").strip()
            if ps == "hooks-path":
                print(
                    "Dry run: no writes; core.hooksPath set (prek install skipped). " + SETUP_DOCS_ONE_LINE,
                    file=sys.stderr,
                )
            else:
                print("Dry run: no uv sync or prek writes. " + SETUP_DOCS_ONE_LINE, file=sys.stderr)
            return

        from rich.console import Group
        from rich.panel import Panel
        from rich.text import Text

        pw = _panel_width(console)
        intro = Text.from_markup(_dry_run_intro_markup(prek_state), overflow="fold")
        prek_panel = _dry_run_prek_renderable(prek_state)
        if prek_panel is not None:
            body = Group(intro, prek_panel, _hooks_table())
        else:
            body = Group(intro, _hooks_table())
        console.print(
            Panel.fit(
                body,
                width=pw,
                title="[bold]Onboarding preview[/]",
                subtitle="[dim]simulation only[/]",
                border_style="yellow",
                padding=(1, 2),
                highlight=False,
            ),
            highlight=False,
        )
        return

    cpath = str(contributing)
    if console is None:
        print(
            "Environment ready. See CONTRIBUTING.md for commit vs pre-push hooks. " + SETUP_DOCS_ONE_LINE,
            file=sys.stderr,
        )
        return

    from rich.console import Group
    from rich.panel import Panel
    from rich.text import Text

    pw = _panel_width(console)
    ready = Text.from_markup(
        "[bold]Environment ready[/]\n\n"
        "[dim]Local[/] [cyan].venv[/] [dim]matches the lockfile; prek shims are installed when onboarding\n"
        "completed successfully.[/]",
        overflow="fold",
    )
    summary = Text.from_markup(
        f"[bold]Next[/]\n\n"
        f"[dim]Docs:[/] [cyan]{cpath}[/]\n"
        "[dim]Shortcuts:[/] [cyan]just help[/] · [cyan]uv run ty check[/] · [cyan]just test[/]\n\n"
        "[dim]First[/] [cyan]git push[/] [dim]runs the[/] [cyan]pre-push[/] [dim]hooks (ty + fast pytest).[/]",
        overflow="fold",
    )
    body = Group(
        ready,
        _hooks_table(),
        summary,
    )
    console.print(
        Panel.fit(
            body,
            width=pw,
            title="[bold green]bmt-gcloud[/]",
            subtitle="[dim]hooks via prek[/]",
            border_style="green",
            padding=(1, 2),
            highlight=False,
        ),
        highlight=False,
    )


def register_onboard(app: typer.Typer) -> None:
    """Register [code]onboard[/] on the root tools CLI."""

    @app.command(
        "onboard",
        rich_help_panel="Development",
    )
    def onboard_command(
        dry_run: Annotated[
            bool,
            typer.Option("--dry-run", help="Show dry-run summary (after a dry-run bootstrap)."),
        ] = False,
        prek_state: Annotated[
            str | None,
            typer.Option(
                "--prek-state",
                help="Dry-run only: prek scenario from bootstrap (hooks-path, already-installed, would-install, no-git).",
            ),
        ] = None,
    ) -> None:
        """Post-bootstrap summary: git hooks (prek) and next steps."""
        if prek_state is not None and prek_state not in _PREK_STATES:
            raise typer.BadParameter(
                f"must be one of: {', '.join(sorted(_PREK_STATES))}",
                param_hint="--prek-state",
            )
        if prek_state is not None and not dry_run:
            raise typer.BadParameter("only valid with --dry-run", param_hint="--prek-state")
        run_onboard_rich(dry_run=dry_run, prek_state=prek_state)
