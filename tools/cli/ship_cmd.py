"""Full pre-push pipeline with Rich-staged reports: `uv run python -m tools ship` (also `just tools ship`)."""

from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer
from rich import box
from rich.console import Console, Group
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from tools.repo.core_main_workflows import run_drift_check
from tools.repo.just_image_gate import evaluate_image_skip
from tools.repo.paths import repo_root


@dataclass(frozen=True)
class _Step:
    """``key`` matches ship skip flags; run via ``just <argv>`` or ``uv run python -m tools <argv>``."""

    key: str
    argv: tuple[str, ...]
    title: str
    blurb: str
    border: str  # rich color name
    via_uv_tools: bool = False


_STEP_TEST = _Step(
    "test",
    ("test",),
    "Local verification suite",
    "uv sync · pytest · ruff · ty · actionlint · shellcheck · layout policy",
    "cyan",
)

_STEP_DEPLOY = _Step(
    "deploy",
    ("sync-to-bucket",),
    "Upload to GCS bucket",
    "Same as workspace deploy: local benchmarks/ stage mirror → bucket + verify",
    "yellow",
)

_STEP_IMAGE = _Step(
    "image",
    ("build", "orchestrator-image"),
    "Container image",
    "docker buildx load + push to Artifact Registry (git-SHA tag for ship auto-skip)",
    "green",
    via_uv_tools=True,
)


def _step_command_display(step: _Step) -> str:
    if step.via_uv_tools:
        return f"uv run python -m tools {' '.join(step.argv)}"
    return f"just {' '.join(step.argv)}"


def _step_preflight(*, image_skipped: bool, force_image: bool) -> _Step:
    argv_l: list[str] = ["workspace", "preflight"]
    if not image_skipped:
        argv_l.append("--with-image")
        if force_image:
            argv_l.append("--force-image")
    return _Step(
        "preflight",
        tuple(argv_l),
        "Bucket preflight",
        "Diff / checks vs GCS; tools build orchestrator-image when git + registry warrant",
        "magenta",
    )


def _build_active_steps(
    *,
    skip_test: bool,
    skip_preflight: bool,
    skip_deploy: bool,
    image_skipped: bool,
    force_image: bool,
    skip_image: bool,
) -> tuple[_Step, ...]:
    out: list[_Step] = []
    if not skip_test:
        out.append(_STEP_TEST)
    if not skip_preflight:
        out.append(_step_preflight(image_skipped=image_skipped, force_image=force_image))
    if not skip_deploy:
        out.append(_STEP_DEPLOY)
    if skip_preflight and not image_skipped and not skip_image:
        out.append(_STEP_IMAGE)
    return tuple(out)


# Rough pacing for --dry-run so each stage “breathes” like a real run (seconds).
_DRY_RUN_PAUSE_SEC: dict[str, float] = {
    "test": 2.2,
    "preflight": 0.85,
    "deploy": 0.75,
    "image": 1.6,
}


def _console() -> Console:
    return Console(highlight=False, soft_wrap=True)


def _banner(console: Console) -> None:
    title = Text()
    title.append("SHIP", style="bold white on rgb(45,55,72)")
    title.append("  ", style="")
    title.append("bmt-gcloud", style="bold dim")
    body = Text.from_markup(
        "[dim]Full gate before push:[/] [cyan]just test[/] → [magenta]workspace preflight[/] "
        "[dim](folds in[/] [green]orchestrator image[/] [dim]when needed)[/] → [yellow]sync-to-bucket[/]\n"
        "[dim]With[/] [cyan]--skip-preflight[/][dim],[/] [green]image[/] [dim]runs as its own step when not auto-skipped.[/]\n"
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
    cmd = _step_command_display(step)
    head = Text.from_markup(f"[bold]{step.title}[/]\n[dim]{step.blurb}[/]\n[dim]Command:[/] [cyan]{cmd}[/]")
    return Panel(
        head,
        title=f"[bold {step.border}]Step {index}/{total} · {step.key}[/]",
        border_style=step.border,
        box=box.ROUNDED,
        padding=(0, 1),
    )


def _run_step(
    step: _Step,
    *,
    dry_run: bool,
    console: Console,
    pause_key: str,
) -> tuple[int, float]:
    """Return (exit_code, elapsed_or_simulated_seconds)."""
    if dry_run:
        pause = _DRY_RUN_PAUSE_SEC.get(pause_key, 0.5)
        time.sleep(pause)
        console.print("  [dim italic]dry-run — not executed[/]\n")
        return 0, pause
    root = repo_root()
    t0 = time.monotonic()
    if step.via_uv_tools:
        uv = shutil.which("uv")
        if not uv:
            console.print("[red]error:[/] [cyan]uv[/] not on PATH (needed for Cloud Run image build).")
            return 127, 0.0
        rc = subprocess.run(
            [uv, "run", "python", "-m", "tools", *step.argv],
            cwd=root,
            check=False,
        ).returncode
        return rc, time.monotonic() - t0
    exe = shutil.which("just")
    if not exe:
        console.print(
            "[red]error:[/] [cyan]just[/] not on PATH. Install just or use [cyan]uv run python -m tools[/] directly."
        )
        return 127, 0.0
    rc = subprocess.run([exe, *step.argv], cwd=root, check=False).returncode
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
            typer.Option("--dry-run", help="Print stages without running commands."),
        ] = False,
        skip_test: Annotated[bool, typer.Option("--skip-test", help="Skip the `just test` step.")] = False,
        skip_preflight: Annotated[
            bool,
            typer.Option("--skip-preflight", help="Skip `just workspace preflight`."),
        ] = False,
        skip_deploy: Annotated[
            bool, typer.Option("--skip-deploy", help="Skip `just sync-to-bucket` (same as workspace deploy).")
        ] = False,
        skip_image: Annotated[
            bool,
            typer.Option("--skip-image", help="Skip `tools build orchestrator-image` (always)."),
        ] = False,
        force_image: Annotated[
            bool,
            typer.Option(
                "--force-image",
                help="Always run `tools build orchestrator-image` (default: skip when git shows no edits under "
                "backend or backend/__init__.py and Artifact Registry has an image tagged with "
                "the current git HEAD commit, verified via the Artifact Registry API). "
                "If the registry probe is unavailable (network/ADC), ship runs the image build anyway "
                "(fail-open). If the probe reports permission denied (IAM), ship shows an error and "
                "still runs the image build so you are not silently skipped. "
                "Use after push or when the registry must refresh without local git diffs.",
            ),
        ] = False,
    ) -> None:
        """Run the full ship pipeline with staged Rich reports (stops on first failure)."""
        if skip_image and force_image:
            raise typer.BadParameter("use either --skip-image or --force-image, not both", param_hint="flags")

        console = _console()
        root_s = str(repo_root())
        if skip_preflight:
            drift_rc = run_drift_check(Path(root_s) / ".github" / "workflows", mode="preflight")
            if drift_rc != 0:
                raise typer.Exit(drift_rc)

        image_skipped, auto_skip_note = evaluate_image_skip(
            root=root_s,
            skip_image=skip_image,
            force_image=force_image,
            dry_run=dry_run,
        )

        skips = {
            "test": skip_test,
            "preflight": skip_preflight,
            "deploy": skip_deploy,
            "image": image_skipped,
        }
        active = _build_active_steps(
            skip_test=skip_test,
            skip_preflight=skip_preflight,
            skip_deploy=skip_deploy,
            image_skipped=image_skipped,
            force_image=force_image,
            skip_image=skip_image,
        )
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
            rc, elapsed = _run_step(
                step,
                dry_run=dry_run,
                console=console,
                pause_key=step.key,
            )
            status = "[green]ok[/]" if rc == 0 else "[red]failed[/]"
            timings.append((step.key, status, elapsed))
            if rc != 0:
                overall_rc = rc
                console.print(
                    Panel(
                        Text.from_markup(f"[bold red]Stopped[/] after [cyan]{step.key}[/] [dim](exit {rc})[/]"),
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
            foot.append("tools ship", style="cyan")

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
