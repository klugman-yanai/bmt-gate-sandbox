"""Minimal Rich output for quiet/non-verbose CLI: step lines and success panels.

Use when stdout is a TTY for Rich formatting; otherwise plain one-line output
so CI and pipes stay parseable. Pattern: step(console, label, ok) per phase,
success_panel(console, title, message) at end.
"""

from __future__ import annotations

import contextlib
import sys
from collections.abc import Generator
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rich.console import Console


def use_rich(verbose: bool) -> bool:
    """True if we should use Rich (TTY and not verbose)."""
    return not verbose and sys.stdout.isatty()


def step_console(verbose: bool = False) -> Console | None:
    """Return a Rich Console when use_rich(verbose), else None. Use with step() and success_panel()."""
    if use_rich(verbose):
        from rich.console import Console

        return Console()
    return None


def step(console: Console | None, label: str, ok: bool) -> None:
    """Print a minimal step line (Rich if console, else plain)."""
    if console is not None:
        status = "[green]✓[/]" if ok else "[red]✗[/]"
        console.print(f"  [dim]{label}…[/] {status}")
    else:
        status = "OK" if ok else "FAILED"
        print(f"  {label}… {status}")


def success_panel(console: Console | None, title: str, message: str, *, style: str = "green") -> None:
    """Print final success (Rich panel if console, else plain line)."""
    if console is not None:
        from rich.panel import Panel

        console.print(Panel(message, title=f"[{style}]{title}[/]", border_style=style))
    else:
        print(f"{title}: {message}")


@contextlib.contextmanager
def spinner_status(console: Console | None, label: str) -> Generator[None, None, None]:
    """Context manager: Rich spinner on TTY, plain label on non-TTY."""
    if console is not None:
        with console.status(label):
            yield
    else:
        print(label)
        yield
