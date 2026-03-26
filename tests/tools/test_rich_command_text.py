"""command_line_text styling (no Pygments)."""

from __future__ import annotations

from rich.syntax import Syntax

from tools.shared.rich_command_text import command_line_highlight, command_line_text


def test_command_line_empty() -> None:
    t = command_line_text("—")
    assert t.plain == "—"


def test_command_line_just_prefix() -> None:
    t = command_line_text("just stage project foo")
    assert "just" in t.plain
    assert "stage project foo" in t.plain


def test_command_line_highlight_uses_syntax() -> None:
    h = command_line_highlight("just onboard")
    assert isinstance(h, Syntax)
    assert "just onboard" in h.code
