"""Contributor Rich helpers default to Pygments one-dark for code."""

from __future__ import annotations

from rich.markdown import Markdown
from rich.syntax import Syntax

from tools.shared.rich_contributor_theme import (
    PYGMENTS_CODE_THEME,
    contributor_markdown,
    contributor_syntax,
)


def test_pygments_code_theme_is_one_dark() -> None:
    assert PYGMENTS_CODE_THEME == "one-dark"


def test_contributor_syntax_uses_one_dark() -> None:
    syn = contributor_syntax("x = 1", "python")
    assert isinstance(syn, Syntax)


def test_contributor_markdown_uses_one_dark() -> None:
    md = contributor_markdown("```python\nx = 1\n```")
    assert isinstance(md, Markdown)
