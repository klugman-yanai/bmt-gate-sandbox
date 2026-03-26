"""Shell-ish lines for contributor CLIs.

* :func:`command_line_text` — compact ``contrib.*`` colors (no Pygments).
* :func:`command_line_highlight` — Pygments **one-dark** via :class:`rich.syntax.Syntax`
  (use in TTY Rich output so the theme is visible).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text

if TYPE_CHECKING:
    from rich.syntax import Syntax

_EMPTY = "—"


def command_line_text(line: str) -> Text:
    """Render a shell-style line: ``just`` token vs args (theme: ``contrib.cmd_*``)."""
    stripped = line.strip()
    if not stripped or stripped == _EMPTY:
        return Text(_EMPTY, style="contrib.placeholder")
    if stripped == "just":
        return Text("just", style="contrib.cmd_word")
    if stripped.startswith("just "):
        rest = stripped[5:]
        return Text.assemble(
            ("just", "contrib.cmd_word"),
            (" ", ""),
            (rest, "contrib.cmd_args"),
        )
    return Text(stripped, style="contrib.cmd_args")


def command_line_highlight(line: str) -> Text | Syntax:
    """Highlight a shell line with Pygments (default theme: **one-dark**)."""
    stripped = line.strip()
    if not stripped or stripped == _EMPTY:
        return Text(_EMPTY, style="contrib.placeholder")
    from rich.syntax import Syntax

    from tools.shared.rich_contributor_theme import PYGMENTS_CODE_THEME

    return Syntax(
        stripped,
        "bash",
        theme=PYGMENTS_CODE_THEME,
        word_wrap=True,
        tab_size=4,
        padding=(0, 0, 0, 0),
    )
