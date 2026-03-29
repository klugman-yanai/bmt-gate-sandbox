#!/usr/bin/env python3
"""Print Just recipes with Rich (TTY) or plain text (pipes / CI).

``--intro``: tight quick path + doc links, then a minimal reference table
(Task / Run). ``--verbose`` swaps in full Justfile ``[doc(...)]`` text.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from tools.shared.rich_command_text import command_line_highlight, command_line_text
from tools.shared.rich_contributor_theme import contributor_console
from tools.shared.rich_tty import RichLayoutProfile, rich_layout_profile

_DEFAULT_DOC_MAX_LEN = 52
_ELLIPSIS = "…"

# Typical-path panel: (step_no, command, short gloss). Gloss stays off the command line on narrow/tight.
_INTRO_QUICK_STEPS: tuple[tuple[str, str, str], ...] = (
    ("1", "just onboard", ""),
    ("2", "just add <project>", "optional --bmt and --data"),
    ("3", "just test-local", "before publish"),
    ("4", "just publish", "enables BMT; add project + folder if several staged"),
    ("5", "just sync-to-bucket", "whole benchmarks/ stage mirror → bucket"),
    ("6", "just test", "full verify (lint, pytest, …)"),
)


def _compact_just(name: str, _sig: str) -> str:
    """Short Run column / cheat-sheet line; full dump signature only in --verbose."""
    if name == "onboard":
        return "just onboard"
    if name == "add":
        return "just add PROJ [--bmt=…] [--data=…]"
    if name == "add-project":
        return "just add-project NAME"
    if name == "add-bmt":
        return "just add-bmt PROJ BMT"
    if name == "stage":
        return "just stage …"
    if name == "upload-wav":
        return "just upload-wav PROJ PATH"
    if name == "publish":
        return "just publish [PROJ [BMT]]"
    if name == "publish-bmt":
        return "just publish-bmt PROJ BMT"
    if name == "test-local":
        return "just test-local"
    if name == "sync-to-bucket":
        return "just sync-to-bucket"
    if name == "workspace":
        return "just workspace …"
    if name == "test":
        return "just test"
    if name == "tools":
        return "just tools …"
    if name == "workflow":
        return "just workflow"
    if name == "status":
        return "just status"
    if name == "workflow-status":
        return "just status"
    if name == "list":
        return "just list"
    if name == "default":
        return "just default"
    return f"just {name}".strip()


# Ultra-short task labels for the reference table (default mode).
_RECIPE_TASK: dict[str, str] = {
    "onboard": "Dev setup",
    "add": "Project / BMT / dataset",
    "add-project": "New project",
    "add-bmt": "New BMT",
    "stage": "Other stage subcommands",
    "upload-wav": "WAV inputs → bucket",
    "publish": "Publish plugin (+ enable)",
    "publish-bmt": "Publish (two-arg)",
    "test-local": "Quick checks pre-publish",
    "sync-to-bucket": "Upload benchmarks/ stage mirror → bucket",
    "workspace": "Other workspace cmds",
    "test": "Checks before push",
    "tools": "Rest of the CLI",
    "workflow": "Workflow checklist",
    "status": "Repo status (.venv, projects)",
    "workflow-status": "Repo status (.venv, projects)",
    "list": "List only (no intro)",
    "default": "This help",
}


def _doc_for_display(doc: str, *, verbose: bool, max_len: int = _DEFAULT_DOC_MAX_LEN) -> str:
    stripped = doc.strip()
    if not stripped:
        return ""
    if verbose or len(stripped) <= max_len:
        return stripped
    budget = max_len - len(_ELLIPSIS)
    if budget < 12:
        return stripped[:max_len]
    head = stripped[:budget]
    last_space = head.rfind(" ")
    if last_space > int(budget * 0.45):
        head = head[:last_space]
    return head.rstrip() + _ELLIPSIS


def _goal_line_for_recipe(name: str, raw_doc: str) -> str:
    if name in _RECIPE_TASK:
        return _RECIPE_TASK[name]
    return _doc_for_display(raw_doc, verbose=False)


def _summary_for_recipe(name: str, raw_doc: str, *, verbose: bool) -> str:
    if verbose:
        return _doc_for_display(raw_doc, verbose=True)
    return _goal_line_for_recipe(name, raw_doc)


_WORKFLOW_RECIPE_ORDER: tuple[str, ...] = (
    "onboard",
    "add",
    "test-local",
    "publish",
    "sync-to-bucket",
    "upload-wav",
    "add-project",
    "add-bmt",
    "publish-bmt",
    "stage",
    "workspace",
    "test",
    "tools",
    "workflow",
    "status",
    "list",
    "default",
)


def _ordered_recipe_rows(
    by_group: dict[str, list[tuple[str, str, str]]],
) -> list[tuple[str, str, str]]:
    by_name: dict[str, tuple[str, str, str]] = {}
    for rows in by_group.values():
        for row in rows:
            by_name[row[0]] = row
    out: list[tuple[str, str, str]] = []
    for name in _WORKFLOW_RECIPE_ORDER:
        if name in by_name:
            out.append(by_name.pop(name))
    for name in sorted(by_name):
        out.append(by_name[name])
    return out


def _run_just_dump(justfile: Path) -> dict[str, Any]:
    cmd = [
        "just",
        "--dump",
        "--dump-format",
        "json",
        "--justfile",
        str(justfile.resolve()),
    ]
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr or proc.stdout or "just --dump failed\n")
        raise SystemExit(proc.returncode)
    return json.loads(proc.stdout)


def _attr_group(attributes: Sequence[Any]) -> str:
    for item in attributes:
        if isinstance(item, dict) and "group" in item:
            g = item["group"]
            if isinstance(g, str):
                return g
    return ""


def _format_signature(parameters: Sequence[Mapping[str, Any]] | None) -> str:
    if not parameters:
        return ""
    parts: list[str] = []
    for p in parameters:
        kind = p.get("kind")
        name = p.get("name")
        if not isinstance(name, str):
            continue
        if kind == "star":
            parts.append(f"*{name}")
        else:
            parts.append(name)
    return " ".join(parts)


def _aliases_for_target(aliases: Mapping[str, Any], target: str) -> list[str]:
    out: list[str] = []
    for alias_name, info in aliases.items():
        if isinstance(alias_name, str) and isinstance(info, dict) and info.get("target") == target:
            out.append(alias_name)
    return sorted(out)


def _gather_public_recipes(data: dict[str, Any]) -> tuple[dict[str, list[tuple[str, str, str]]], dict[str, list[str]]]:
    recipes_raw = data.get("recipes")
    if not isinstance(recipes_raw, dict):
        return {}, {}
    aliases_raw = data.get("aliases")
    if not isinstance(aliases_raw, dict):
        aliases_raw = {}

    by_group: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for name, recipe in recipes_raw.items():
        if not isinstance(recipe, dict) or not isinstance(name, str):
            continue
        if recipe.get("private"):
            continue
        sig = _format_signature(recipe.get("parameters") if isinstance(recipe.get("parameters"), list) else [])
        doc = recipe.get("doc")
        doc_s = doc.strip() if isinstance(doc, str) else ""
        group = _attr_group(recipe.get("attributes") if isinstance(recipe.get("attributes"), list) else [])
        by_group[group].append((name, sig, doc_s))

    alias_map: dict[str, list[str]] = {}
    for rows in by_group.values():
        for name, _, _ in rows:
            alias_map[name] = _aliases_for_target(aliases_raw, name)
    return dict(by_group), alias_map


def _intro_goal_plain(*, profile: RichLayoutProfile) -> list[str]:
    lines: list[str] = ["Typical path"]
    stack_hints = profile.narrow
    for num, cmd, gloss in _INTRO_QUICK_STEPS:
        if gloss and stack_hints:
            lines.append(f"  {num}  {cmd}")
            lines.append(f"      {gloss}")
        elif gloss:
            lines.append(f"  {num}  {cmd}   — {gloss}")
        else:
            lines.append(f"  {num}  {cmd}")
    lines.append("")
    if profile.xs:
        lines.extend(
            [
                "Docs:",
                "  CONTRIBUTING.md",
                "  docs/configuration.md",
                "  docs/contributors.md (plugin SDK)",
                "",
                "Run:",
                "  just workflow   (checklist)",
                "  just status     (repo hints)",
            ]
        )
    else:
        lines.extend(
            [
                "Docs: CONTRIBUTING.md · docs/configuration.md · docs/contributors.md (SDK)",
                "Run:  just workflow · just status   (checklist · repo hints)",
            ]
        )
    return lines


def _more_recipes_hint_plain(*, profile: RichLayoutProfile) -> list[str]:
    if profile.tight:
        return ["All recipes: just list", "Full CLI:     just tools --help"]
    return ["All recipes: just list  ·  full CLI: just tools --help"]


def _print_plain(
    by_group: dict[str, list[tuple[str, str, str]]],
    alias_map: dict[str, list[str]],
    *,
    intro: bool,
    verbose: bool,
) -> None:
    if intro:
        plain_profile = rich_layout_profile()
        for line in _intro_goal_plain(profile=plain_profile):
            print(line)
        print()
        if not verbose:
            for line in _more_recipes_hint_plain(profile=plain_profile):
                print(line)
            return
    rows = _ordered_recipe_rows(by_group)
    if not rows:
        return
    if verbose:
        for i, (name, sig, doc) in enumerate(rows, start=1):
            aliases = alias_map.get(name, [])
            left = f"{name} {sig}".rstrip()
            if aliases:
                left = f"{left}  [alias: {', '.join(aliases)}]"
            shown = _summary_for_recipe(name, doc, verbose=True)
            if shown:
                print(f"{i:>2}  {left}  # {shown}")
            else:
                print(f"{i:>2}  {left}")
    else:
        print("Commands")
        for i, (name, sig, doc) in enumerate(rows, start=1):
            aliases = alias_map.get(name, [])
            cmd = _compact_just(name, sig)
            if aliases:
                cmd = f"{cmd}  [alias: {', '.join(aliases)}]"
            task = _goal_line_for_recipe(name, doc)
            print(f"{i:>2}  {task}  {cmd}")


def _rich_quick_path_panel(*, profile: RichLayoutProfile):
    from rich import box
    from rich.columns import Columns
    from rich.console import Group
    from rich.padding import Padding
    from rich.panel import Panel
    from rich.text import Text

    num_w = 2 if profile.xs else 3
    sub_indent = "   " if profile.xs else "      "

    def step(num: str, cmd: str, hint: str) -> Columns | Group:
        num_cell = Text(f"{num:>{num_w}}  ", style="contrib.step_num")
        cmd_h = command_line_highlight(cmd)
        top = Columns([num_cell, cmd_h], padding=(0, 0), expand=False)
        if not hint:
            return top
        if profile.narrow:
            sub = Text(f"{sub_indent}{hint}", style="contrib.hint", overflow="fold", no_wrap=False)
            return Group(top, sub)
        return Columns(
            [
                num_cell,
                cmd_h,
                Text("  —  ", style="contrib.muted"),
                Text(hint, style="contrib.hint"),
            ],
            padding=(0, 0),
            expand=False,
        )

    inner = Group(*[step(n, c, h) for n, c, h in _INTRO_QUICK_STEPS])
    inner_pad = (0, 0) if profile.xs else (0, 1)
    return Panel(
        Padding(inner, inner_pad),
        title=Text("Typical path", style="contrib.section"),
        title_align="left",
        border_style="contrib.panel_border",
        box=box.ROUNDED,
        padding=(0, 1),
        expand=False,
    )


def _rich_more_recipes_hint(*, profile: RichLayoutProfile):
    from rich.columns import Columns
    from rich.console import Group
    from rich.text import Text

    if profile.tight:
        return Group(
            Columns(
                [Text("All recipes  ", style="contrib.muted"), command_line_highlight("just list")],
                padding=(0, 0),
                expand=False,
            ),
            Columns(
                [Text("Full CLI     ", style="contrib.muted"), command_line_highlight("just tools --help")],
                padding=(0, 0),
                expand=False,
            ),
        )
    return Columns(
        [
            Text("All recipes  ", style="contrib.muted"),
            command_line_highlight("just list"),
            Text("   ·   ", style="contrib.muted"),
            Text("Full CLI  ", style="contrib.muted"),
            command_line_highlight("just tools --help"),
        ],
        padding=(0, 0),
        expand=False,
    )


def _rich_doc_footer_links():
    """Paths with muted separators (no ``Docs:`` prefix)."""
    from rich.text import Text

    t = Text()
    t.append("CONTRIBUTING.md", style="contrib.link")
    t.append("  ·  ", style="contrib.muted")
    t.append("docs/configuration.md", style="contrib.link")
    t.append("  ·  ", style="contrib.muted")
    t.append("docs/contributors.md", style="contrib.link")
    return t


def _rich_doc_footer_docs_line():
    """One line: ``Docs:`` + links (matches plain ``just`` / intro text)."""
    from rich.text import Text

    line = Text()
    line.append("Docs: ", style="contrib.label")
    line.append_text(_rich_doc_footer_links())
    return line


def _rich_doc_footer_links_vertical():
    """One path per line (≤60 col terminals)."""
    from rich.console import Group
    from rich.text import Text

    return Group(
        Text("CONTRIBUTING.md", style="contrib.link"),
        Text("docs/configuration.md", style="contrib.link"),
        Text("docs/contributors.md", style="contrib.link"),
    )


def _rich_doc_footer_run_stacked():
    """Two-line run hints when a single row would wrap awkwardly."""
    from rich.columns import Columns
    from rich.console import Group
    from rich.padding import Padding
    from rich.text import Text

    w = Columns(
        [
            command_line_highlight("just workflow"),
            Text(" (checklist)", style="contrib.hint"),
        ],
        padding=(0, 0),
        expand=False,
    )
    s = Columns(
        [
            command_line_highlight("just status"),
            Text(" (repo hints)", style="contrib.hint"),
        ],
        padding=(0, 0),
        expand=False,
    )
    return Group(
        Padding(w, (0, 0, 0, 2)),
        Padding(s, (0, 0, 0, 2)),
    )


def _rich_doc_footer_run_line():
    from rich.columns import Columns
    from rich.text import Text

    return Columns(
        [
            Text("Run:  ", style="contrib.label"),
            command_line_highlight("just workflow"),
            Text("  ·  ", style="contrib.muted"),
            command_line_highlight("just status"),
            Text(" ", style=""),
            Text("(checklist · repo hints)", style="contrib.hint"),
        ],
        padding=(0, 0),
        expand=False,
    )


def _rich_doc_footer(*, profile: RichLayoutProfile):
    from rich.console import Group
    from rich.padding import Padding
    from rich.text import Text

    if profile.xs:
        return Group(
            Text("Docs:", style="contrib.label"),
            Padding(_rich_doc_footer_links_vertical(), (0, 0, 0, 2)),
            Text("Run:", style="contrib.label"),
            _rich_doc_footer_run_stacked(),
        )
    if profile.narrow:
        return Group(_rich_doc_footer_docs_line(), _rich_doc_footer_run_line())
    from rich.columns import Columns

    return Columns(
        [_rich_doc_footer_docs_line(), _rich_doc_footer_run_line()],
        padding=(0, 2),
        expand=True,
    )


def _print_rich(
    by_group: dict[str, list[tuple[str, str, str]]],
    alias_map: dict[str, list[str]],
    *,
    intro: bool,
    verbose: bool,
) -> None:
    from rich import box
    from rich.console import Group
    from rich.rule import Rule
    from rich.table import Table
    from rich.text import Text

    profile = rich_layout_profile()
    cols = profile.columns
    narrow = profile.narrow
    console = contributor_console(width=cols, strip_highlight=True)

    if intro:
        console.print(_rich_quick_path_panel(profile=profile))
        console.print()
        console.print(_rich_doc_footer(profile=profile))
        console.print()
        if not verbose:
            console.print(_rich_more_recipes_hint(profile=profile))
            return
        console.print(Rule(style="contrib.rule"))

    rows = _ordered_recipe_rows(by_group)
    if not rows:
        return

    pad = (0, 0) if narrow else (0, 1)

    cap = Text()
    cap.append_text(command_line_text("just list --verbose"))
    cap.append(" — Justfile docs", style="contrib.muted")

    table = Table(
        box=box.SIMPLE,
        show_header=True,
        header_style="contrib.table_head",
        border_style="contrib.panel_border",
        padding=pad,
        expand=True,
        width=profile.table_width(),
        caption=None if verbose else cap,
        caption_style="",
    )
    table.add_column("#", justify="right", style="contrib.muted", width=2, no_wrap=True)
    if narrow:
        table.add_column("", overflow="fold", ratio=1)
    elif verbose:
        table.add_column("Run", overflow="fold", ratio=2)
        table.add_column("Justfile", style="contrib.summary", ratio=3, overflow="fold")
    else:
        table.add_column("Task", style="contrib.summary", ratio=2, overflow="fold", no_wrap=False)
        table.add_column("Run", overflow="fold", ratio=3)

    for i, (name, sig, doc) in enumerate(rows, start=1):
        full_line = f"just {name} {sig}".strip()
        cmd_line = full_line if verbose else _compact_just(name, sig)
        cmd_cell = command_line_highlight(cmd_line)
        alias_names = alias_map.get(name, [])
        if alias_names:
            cmd_cell = Group(
                cmd_cell,
                Text("  " + ", ".join(alias_names), style="contrib.alias"),
            )
        raw = doc or ""
        task_cell = Text(_goal_line_for_recipe(name, raw), style="contrib.summary", overflow="fold")
        doc_cell = Text(
            _summary_for_recipe(name, raw, verbose=True),
            style="contrib.summary",
            overflow="fold",
        )

        if narrow:
            block = Group(task_cell, cmd_cell) if not verbose else Group(cmd_cell, doc_cell)
            table.add_row(str(i), block)
        elif verbose:
            table.add_row(str(i), command_line_highlight(full_line), doc_cell)
        else:
            table.add_row(str(i), task_cell, cmd_cell)

    console.print(table)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="List public Just recipes in contributor-workflow order (Rich or plain).",
    )
    parser.add_argument(
        "--intro",
        action="store_true",
        help="Default `just` view: typical workflow only; use `just list` for the full recipe table.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show full Justfile [doc(...)] in the Justfile column",
    )
    parser.add_argument("justfile", type=Path, help="Path to the Justfile")
    args = parser.parse_args()
    if not args.justfile.is_file():
        print(f"not a file: {args.justfile}", file=sys.stderr)
        raise SystemExit(2)

    data = _run_just_dump(args.justfile)
    by_group, alias_map = _gather_public_recipes(data)

    if sys.stdout.isatty():
        _print_rich(by_group, alias_map, intro=args.intro, verbose=args.verbose)
    else:
        _print_plain(by_group, alias_map, intro=args.intro, verbose=args.verbose)


if __name__ == "__main__":
    main()
