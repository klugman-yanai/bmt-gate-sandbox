"""Shared Rich theme + Console factory for contributor-facing CLIs (just list, workflow).

Rich does **not** ship a menu of named themes (unlike some editors). There is a single
large **default style set** (markdown, repr, logging, …). Custom :class:`~rich.theme.Theme`
instances **merge** with those defaults when ``inherit=True`` (the default): your styles
override or add names, everything else stays available.

To inspect defaults: ``python -m rich.theme`` or ``python -m rich.default_styles`` (see
`Rich style themes <https://rich.readthedocs.io/en/stable/style.html#style-themes>`_).

This module defines only ``contrib.*`` styles on top of Rich defaults. Doc paths use the
same spirit as Rich's built-in ``repr.url`` (underline + bright blue).

**Code blocks:** use ``contributor_syntax`` / ``contributor_markdown`` so fenced and inline
code use the Pygments style ``one-dark`` (``PYGMENTS_CODE_THEME``).
"""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.highlighter import NullHighlighter
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.theme import Theme

# Pygments style name for Rich Syntax / Markdown fenced and inline code (requires pygments).
PYGMENTS_CODE_THEME = "one-dark"

CONTRIBUTOR_THEME = Theme(
    {
        # Page / hero
        "contrib.title": "bold bright_white",
        "contrib.tagline": "grey62",
        # Section titles (panels, step titles, table section heads)
        "contrib.section": "bold steel_blue1",
        "contrib.step": "dim",
        "contrib.step_num": "bold steel_blue3",
        "contrib.arrow": "dim cyan",
        # Labels like “Docs:” / “Run:” — readable but quieter than titles
        "contrib.label": "bold grey74",
        # Secondary copy (separators, footnotes)
        "contrib.muted": "grey58",
        "contrib.hint": "grey63",
        # Doc paths: aligned with Rich default ``repr.url`` / ``markdown.link`` (bright blue)
        "contrib.link": "underline bright_blue",
        "contrib.bullet": "bright_magenta",
        # Shell snippets: ``just`` vs remainder (see ``command_line_text``)
        "contrib.cmd_word": "bold spring_green1",
        "contrib.cmd_args": "bright_white",
        "contrib.cmd": "bold spring_green1",
        "contrib.cmd_tail": "bright_white",
        "contrib.alias": "italic grey58",
        "contrib.summary": "grey82",
        "contrib.placeholder": "grey50",
        # Tables / chrome
        "contrib.value": "bright_white",
        "contrib.path": "cyan",
        "contrib.ok": "bold green",
        "contrib.warn": "bold yellow",
        "contrib.panel_border": "dim steel_blue3",
        "contrib.table_head": "bold slate_blue3",
        "contrib.rule": "dim steel_blue3",
    },
    inherit=True,
)


def contributor_console(*, width: int | None = None, strip_highlight: bool = True, **kwargs: Any) -> Console:
    """Console with contributor theme; optional NullHighlighter to avoid stray repr highlighting."""
    extra: dict[str, Any] = {
        "theme": CONTRIBUTOR_THEME,
        "soft_wrap": True,
        "width": width,
    }
    if strip_highlight:
        extra["highlight"] = False
        extra["highlighter"] = NullHighlighter()
    extra.update(kwargs)
    return Console(**extra)


def contributor_syntax(
    code: str,
    lexer: str,
    *,
    theme: str | None = None,
    **kwargs: Any,
) -> Syntax:
    """Build :class:`~rich.syntax.Syntax` using the contributor Pygments theme by default."""
    return Syntax(code, lexer, theme=theme or PYGMENTS_CODE_THEME, **kwargs)


def contributor_markdown(
    markup: str,
    *,
    code_theme: str | None = None,
    inline_code_theme: str | None = None,
    **kwargs: Any,
) -> Markdown:
    """Build :class:`~rich.markdown.Markdown` with One Dark (or override) for code."""
    ct = code_theme or PYGMENTS_CODE_THEME
    ict = inline_code_theme if inline_code_theme is not None else ct
    return Markdown(markup, code_theme=ct, inline_code_theme=ict, **kwargs)
