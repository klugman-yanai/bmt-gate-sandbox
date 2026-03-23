"""Full pre-push pipeline with Rich-staged reports: `uv run python -m tools ship` or `just ship`."""

from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Annotated

import typer
from rich import box
from rich.console import Console, Group
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from tools.repo.paths import repo_root
from tools.shared.artifact_registry_uri import (
    artifact_registry_tag_status,
    resolve_bmt_orchestrator_image_base,
)


@dataclass(frozen=True)
class _Step:
    just_target: str
    title: str
    blurb: str
    border: str  # rich color name


_STEPS: tuple[_Step, ...] = (
    _Step(
        "test",
        "Local verification suite",
        "uv sync · pytest · ruff · ty · actionlint · shellcheck · layout policy",
        "cyan",
    ),
    _Step(
        "preflight",
        "Bucket preflight",
        "Diff / checks vs GCS (needs GCS_BUCKET, gcloud)",
        "magenta",
    ),
    _Step(
        "deploy",
        "Runtime seed deploy",
        "Sync gcp/stage runtime seed to bucket + verify",
        "yellow",
    ),
    _Step(
        "image",
        "Container image",
        "docker buildx load + push to Artifact Registry (git-SHA tag for ship auto-skip)",
        "green",
    ),
)

# Rough pacing for --dry-run so each stage “breathes” like a real run (seconds).
_DRY_RUN_PAUSE_SEC: dict[str, float] = {
    "test": 2.2,
    "preflight": 0.85,
    "deploy": 0.75,
    "image": 1.6,
}

# Paths that invalidate the Cloud Run image (see gcp/image/Dockerfile COPY lines).
_IMAGE_GIT_PATHSPECS = ("gcp/image", "gcp/__init__.py")


def _console() -> Console:
    return Console(highlight=False, soft_wrap=True)


def _git_nonempty_lines(cmd: list[str], *, cwd: str) -> list[str]:
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
    if p.returncode != 0:
        return []
    return [ln.strip() for ln in p.stdout.splitlines() if ln.strip()]


def _git_merge_base_with_remote_head(root: str) -> str | None:
    """Best-effort merge-base(HEAD, origin/dev | origin/main | @{upstream})."""
    for ref in ("origin/dev", "origin/main", "@{upstream}"):
        p = subprocess.run(
            ["git", "merge-base", "HEAD", ref],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        if p.returncode == 0 and (sha := p.stdout.strip()):
            return sha
    return None


def _git_head_sha(root: str) -> str | None:
    p = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if p.returncode != 0:
        return None
    s = p.stdout.strip()
    return s if len(s) >= 7 else None


def image_context_git_dirty(root: str | None = None) -> bool:
    """True if git suggests the Docker context may have changed (rebuild may be needed).

    Conservative: returns True when merge-base cannot be resolved (auto-skip disabled).

    When this returns False, ``uv run python -m tools ship`` may still run ``just image`` unless
    Artifact Registry already has ``bmt-orchestrator:<git HEAD>`` (via the Artifact Registry API
    and Application Default Credentials).

    Does not imply the opposite: base-image tag bumps, a failed registry push, or needing a
    no-code rebuild still require running ship with --force-image.
    """
    r = root or str(repo_root())
    specs = list(_IMAGE_GIT_PATHSPECS)
    mb = _git_merge_base_with_remote_head(r)
    if mb is None:
        return True
    if _git_nonempty_lines(["git", "diff", "--name-only", f"{mb}...HEAD", "--", *specs], cwd=r):
        return True
    # Staged + unstaged vs HEAD (single pick-up for uncommitted edits).
    return bool(_git_nonempty_lines(["git", "diff", "--name-only", "HEAD", "--", *specs], cwd=r))


def _banner(console: Console) -> None:
    title = Text()
    title.append("SHIP", style="bold white on rgb(45,55,72)")
    title.append("  ", style="")
    title.append("bmt-gcloud", style="bold dim")
    body = Text.from_markup(
        "[dim]Full gate before push:[/] [cyan]just test[/] → [magenta]preflight[/] → [yellow]deploy[/] → [green]image[/]\n"
        "[dim]External library docs (e.g. Context7) are separate from this pipeline.[/]"
    )
    console.print()
    console.print(
        Panel.fit(
            Group(title, Text(""), body),
            border_style="bright_blue",
            box=box.DOUBLE_EDGE,
            padding=(1, 2),
        )
    )
    console.print()


def _step_panel(step: _Step, index: int, total: int) -> Panel:
    head = Text.from_markup(
        f"[bold]{step.title}[/]\n[dim]{step.blurb}[/]\n[dim]Command:[/] [cyan]just {step.just_target}[/]"
    )
    return Panel(
        head,
        title=f"[bold {step.border}]Step {index}/{total} · {step.just_target}[/]",
        border_style=step.border,
        box=box.ROUNDED,
        padding=(0, 1),
    )


def _run_just(
    target: str,
    *,
    dry_run: bool,
    console: Console,
) -> tuple[int, float]:
    """Return (exit_code, elapsed_or_simulated_seconds)."""
    if dry_run:
        pause = _DRY_RUN_PAUSE_SEC.get(target, 0.5)
        time.sleep(pause)
        console.print("  [dim italic]dry-run — not executed[/]\n")
        return 0, pause
    exe = shutil.which("just")
    if not exe:
        console.print(
            "[red]error:[/] [cyan]just[/] not on PATH. Install just or use the underlying commands from the Justfile."
        )
        return 127, 0.0
    t0 = time.monotonic()
    rc = subprocess.run(
        [exe, target],
        cwd=repo_root(),
        check=False,
    ).returncode
    return rc, time.monotonic() - t0


def register_ship(root: typer.Typer) -> None:
    """Register [code]ship[/] on the root tools CLI."""

    @root.command(
        "ship",
        rich_help_panel="Pre-push",
    )
    def ship_command(
        dry_run: Annotated[
            bool,
            typer.Option("--dry-run", help="Print stages and skip executing just recipes."),
        ] = False,
        skip_test: Annotated[bool, typer.Option("--skip-test", help="Skip `just test`.")] = False,
        skip_preflight: Annotated[
            bool,
            typer.Option("--skip-preflight", help="Skip `just preflight`."),
        ] = False,
        skip_deploy: Annotated[bool, typer.Option("--skip-deploy", help="Skip `just deploy`.")] = False,
        skip_image: Annotated[bool, typer.Option("--skip-image", help="Skip `just image` (always).")] = False,
        force_image: Annotated[
            bool,
            typer.Option(
                "--force-image",
                help="Always run `just image` (default: skip when git shows no edits under "
                "gcp/image or gcp/__init__.py and Artifact Registry has an image tagged with "
                "the current git HEAD commit, verified via the Artifact Registry API). "
                "Use after push or when the registry must refresh without local git diffs.",
            ),
        ] = False,
    ) -> None:
        """Run the full ship pipeline with staged Rich reports (stops on first failure)."""
        if skip_image and force_image:
            raise typer.BadParameter("use either --skip-image or --force-image, not both", param_hint="flags")

        console = _console()
        root_s = str(repo_root())
        skips = {
            "test": skip_test,
            "preflight": skip_preflight,
            "deploy": skip_deploy,
            "image": skip_image,
        }
        auto_skip_note: str | None = None
        if not skips["image"] and not force_image and not image_context_git_dirty(root_s):
            if dry_run:
                skips["image"] = True
                head_preview = (_git_head_sha(root_s) or "?")[:7]
                auto_skip_note = (
                    "[dim]image auto-skipped (dry-run):[/] no git changes under [cyan]gcp/image[/] or [cyan]gcp/__init__.py[/].\n"
                    "[dim]Artifact Registry is not queried in dry-run;[/] run without [cyan]--dry-run[/] to check "
                    f"[cyan]bmt-orchestrator:{head_preview}[/] [dim]before skipping the image step.[/]"
                )
            head_sha = _git_head_sha(root_s)
            if not dry_run and head_sha:
                image_base = resolve_bmt_orchestrator_image_base(repo_root())
                ar_status = artifact_registry_tag_status(image_base=image_base, tag=head_sha)
                if ar_status == "present":
                    skips["image"] = True
                    short = head_sha[:7]
                    auto_skip_note = (
                        "[dim]image auto-skipped:[/] no git changes under [cyan]gcp/image[/] or [cyan]gcp/__init__.py[/]; "
                        f"Artifact Registry has [cyan]bmt-orchestrator:{short}[/].\n"
                        "[dim]Still wrong bits?[/] base-image-only updates or policy rebuilds — "
                        "[dim]run[/] [cyan]just ship --force-image[/][dim].[/]"
                    )
                elif ar_status == "absent":
                    # Git-clean for image paths but no published tag for this commit — build/push.
                    pass
                else:
                    # unavailable: ADC missing, API error, or invalid tag/URI — git-only skip.
                    skips["image"] = True
                    auto_skip_note = (
                        "[dim]image auto-skipped:[/] no git changes under [cyan]gcp/image[/] or [cyan]gcp/__init__.py[/].\n"
                        "[dim]Git cannot see:[/] stale registry, failed prior push, base-image-only updates, or rebuild-for-policy. "
                        "[dim]Run[/] [cyan]just ship --force-image[/] [dim]to build and push anyway.[/]\n"
                        "[dim]Artifact Registry API check unavailable[/] (configure Application Default Credentials, e.g. "
                        "[cyan]gcloud auth application-default login[/], or set [cyan]GOOGLE_APPLICATION_CREDENTIALS[/]); "
                        "only git paths were used to decide. With ADC, ship requires a "
                        "[cyan]bmt-orchestrator:<git-sha>[/] tag before skipping.[/]"
                    )
            elif not dry_run and not head_sha:
                # Cannot resolve HEAD — run `just image` rather than guess.
                pass

        active = [s for s in _STEPS if not skips[s.just_target]]
        if not active:
            raise typer.BadParameter("all steps skipped", param_hint="flags")

        _banner(console)
        if auto_skip_note:
            console.print(Panel(Text.from_markup(auto_skip_note), border_style="dim", box=box.HEAVY))
            console.print()
        if dry_run:
            console.print(Rule("[bold dim]dry-run mode[/] (staged pacing)", style="dim"))
            console.print()

        timings: list[tuple[str, str, float | None]] = []
        overall_rc = 0
        total = len(active)
        for i, step in enumerate(active, start=1):
            console.print(_step_panel(step, i, total))
            rc, elapsed = _run_just(step.just_target, dry_run=dry_run, console=console)
            status = "[green]ok[/]" if rc == 0 else "[red]failed[/]"
            timings.append((step.just_target, status, elapsed))
            if rc != 0:
                overall_rc = rc
                console.print(
                    Panel(
                        Text.from_markup(f"[bold red]Stopped[/] after [cyan]{step.just_target}[/] [dim](exit {rc})[/]"),
                        border_style="red",
                        box=box.HEAVY,
                    )
                )
                break
            if not dry_run:
                console.print(Text.from_markup(f"  [dim]completed in {elapsed:.1f}s[/]\n"))
            else:
                console.print(Text.from_markup(f"  [dim](simulated {elapsed:.1f}s)[/]\n"))

        table = Table(
            title="[bold]Ship summary[/]",
            box=box.SIMPLE_HEAD,
            show_header=True,
            header_style="bold dim",
        )
        table.add_column("Step", style="cyan", no_wrap=True)
        table.add_column("Status", justify="center")
        table.add_column("Time", justify="right", style="dim")

        for name, status, sec in timings:
            tcell = "—" if sec is None else f"{sec:.1f}s"
            table.add_row(name, status, tcell)

        if skips["image"] and auto_skip_note:
            table.add_row("image", "[dim]skipped (auto)[/]", "—")
        elif skips["image"] and skip_image:
            table.add_row("image", "[dim]skipped[/]", "—")

        summary_style = "green" if overall_rc == 0 else "red"
        foot = Text()
        if overall_rc == 0:
            foot.append("All stages completed.\n", style="bold green")
            foot.append("You can push when ready; pre-push hooks still run ty + fast pytest.", style="dim")
        else:
            foot.append("Fix the failing stage and re-run: ", style="bold yellow")
            foot.append("just ship", style="cyan")

        console.print()
        console.print(
            Panel(
                Group(table, Text(""), foot),
                border_style=summary_style,
                box=box.DOUBLE,
                padding=(0, 1),
            )
        )
        console.print()
        raise typer.Exit(overall_rc)
