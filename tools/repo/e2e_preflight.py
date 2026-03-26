"""Staged checks for GitHub Actions + GCS E2E readiness (vars, secrets, gh, bucket preflight)."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass

from backend.github.github_auth import DEV_PROFILE, github_app_profile_for_repository
from tools.repo.paths import repo_root


@dataclass(frozen=True)
class PreflightStep:
    """One stage in the e2e-preflight pipeline."""

    name: str
    just_on_fail: str
    title: str
    blurb: str


GITHUB_APP_SECRETS_PRIMARY: tuple[str, ...] = (
    "BMT_GITHUB_APP_ID",
    "BMT_GITHUB_APP_INSTALLATION_ID",
    "BMT_GITHUB_APP_PRIVATE_KEY",
)

GITHUB_APP_SECRETS_DEV: tuple[str, ...] = (
    "BMT_GITHUB_APP_DEV_ID",
    "BMT_GITHUB_APP_DEV_INSTALLATION_ID",
    "BMT_GITHUB_APP_DEV_PRIVATE_KEY",
)


def required_actions_app_secret_names(repo_slug: str) -> tuple[str, ...]:
    """Secret names that must exist on the GitHub repo for Actions handoff/reporting."""
    profile = github_app_profile_for_repository(repo_slug)
    return GITHUB_APP_SECRETS_DEV if profile == DEV_PROFILE else GITHUB_APP_SECRETS_PRIMARY


def _run(cmd: list[str], *, cwd: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)


def gh_repo_slug() -> tuple[str | None, str]:
    """Return (`owner/repo`, error_message) when gh succeeds."""
    if not shutil.which("gh"):
        return None, "gh is not on PATH"
    p = _run(
        ["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"],
        cwd=str(repo_root()),
    )
    if p.returncode != 0:
        return None, (p.stderr.strip() or p.stdout.strip() or "gh repo view failed")
    slug = p.stdout.strip()
    if not slug or "/" not in slug:
        return None, f"unexpected gh repo view output: {slug!r}"
    return slug, ""


def gh_secret_names() -> tuple[set[str] | None, str]:
    """Return (names, error). None set means could not list (auth or gh missing)."""
    if not shutil.which("gh"):
        return None, "gh is not on PATH"
    p = _run(["gh", "secret", "list", "--json", "name"], cwd=str(repo_root()))
    if p.returncode != 0:
        return None, p.stderr.strip() or "gh secret list failed"
    try:
        rows = json.loads(p.stdout)
    except json.JSONDecodeError as e:
        return None, f"gh secret list JSON: {e}"
    if not isinstance(rows, list):
        return None, "gh secret list returned non-list"
    names = {str(s.get("name", "")).strip() for s in rows if str(s.get("name", "")).strip()}
    return names, ""


def gh_auth_ok() -> tuple[bool, str]:
    if not shutil.which("gh"):
        return False, "install GitHub CLI and run: gh auth login"
    p = _run(["gh", "auth", "status"], cwd=str(repo_root()))
    if p.returncode != 0:
        msg = p.stderr.strip() or p.stdout.strip() or "not authenticated"
        return False, msg
    return True, ""


def check_github_app_secrets(repo_slug: str) -> tuple[list[str], str]:
    """Return (missing_secret_names, diagnostic). Empty missing => ok."""
    required = required_actions_app_secret_names(repo_slug)
    names, err = gh_secret_names()
    if names is None:
        return list(required), err
    missing = [n for n in required if n not in names]
    return missing, ""


STEPS: tuple[PreflightStep, ...] = (
    PreflightStep(
        name="validate",
        just_on_fail="just workspace pulumi",
        title="Repository variables",
        blurb="Pulumi-desired GitHub repo vars vs live (just workspace validate)",
    ),
    PreflightStep(
        name="github",
        just_on_fail="just tools repo show-env",
        title="GitHub CLI + App secrets",
        blurb="gh auth + Actions secrets for this repo profile (see docs/configuration.md)",
    ),
    PreflightStep(
        name="preflight",
        just_on_fail="just workspace preflight",
        title="Bucket + workflow drift",
        blurb="GCS preflight and core-main workflow drift (same as ship step 2)",
    ),
    PreflightStep(
        name="test",
        just_on_fail="just test",
        title="Local CI suite",
        blurb="pytest · ruff · ty · actionlint · shellcheck · layout (optional)",
    ),
)


def run_just(*recipe: str, dry_run: bool) -> int:
    if dry_run:
        return 0
    exe = shutil.which("just")
    if not exe:
        return 127
    return subprocess.run([exe, *recipe], cwd=repo_root(), check=False).returncode


def run_e2e_preflight(
    *,
    skip_bucket: bool,
    with_tests: bool,
    dry_run: bool,
) -> int:
    """Run staged preflight. Return 0 if all executed stages pass."""
    from tools.repo.gh_repo_vars import GhRepoVars

    active: list[PreflightStep] = [STEPS[0], STEPS[1]]
    if not skip_bucket:
        active.append(STEPS[2])
    if with_tests:
        active.append(STEPS[3])

    if dry_run:
        return _emit_result(
            active=active,
            first_fail=None,
            skip_bucket=skip_bucket,
            with_tests=with_tests,
            dry_run=True,
        )

    first_fail: tuple[PreflightStep, int, str] | None = None

    for step in active:
        detail = ""
        rc = 0
        if step.name == "validate":
            rc = GhRepoVars().run()
            if rc != 0:
                detail = "Repo vars missing or drift vs Pulumi. Apply infra outputs to GitHub."
        elif step.name == "github":
            ok, auth_err = gh_auth_ok()
            if not ok:
                rc = 1
                detail = auth_err
            else:
                slug, slug_err = gh_repo_slug()
                if not slug:
                    rc = 1
                    detail = slug_err or "could not resolve repository (owner/repo)"
                else:
                    missing, sec_err = check_github_app_secrets(slug)
                    if sec_err:
                        rc = 1
                        detail = sec_err
                    elif missing:
                        rc = 1
                        profile = github_app_profile_for_repository(slug)
                        need = ", ".join(missing)
                        detail = (
                            f"Missing Actions secrets for profile {profile!r}: {need}. "
                            "Add them under GitHub → Settings → Secrets and variables → Actions."
                        )
        elif step.name == "preflight":
            rc = run_just("workspace", "preflight", dry_run=False)
            if rc != 0:
                detail = (
                    "Bucket listing/diff failed or workflow drift vs core-main. Check GCS_BUCKET, ADC, and network."
                )
        elif step.name == "test":
            rc = run_just("test", dry_run=False)
            if rc != 0:
                detail = "A linter, test, or policy check failed; see log above."

        if rc != 0:
            first_fail = (step, rc, detail)
            break

    return _emit_result(
        active=active,
        first_fail=first_fail,
        skip_bucket=skip_bucket,
        with_tests=with_tests,
        dry_run=False,
    )


def _emit_result(
    *,
    active: list[PreflightStep],
    first_fail: tuple[PreflightStep, int, str] | None,
    skip_bucket: bool,
    with_tests: bool,
    dry_run: bool,
) -> int:
    try:
        from rich import box
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table
        from rich.text import Text
    except ImportError:
        overall = 0 if first_fail is None else first_fail[1]
        if dry_run:
            print("e2e-preflight dry-run — would run:", ", ".join(s.name for s in active))
            return 0
        for s in active:
            if first_fail and s == first_fail[0]:
                print(f"FAILED: {s.name}")
                break
            print(f"ok: {s.name}")
        if first_fail:
            step, rc, detail = first_fail
            print(detail)
            print(f"Try: {step.just_on_fail}")
            if step.name == "validate":
                print("Then: just workspace validate")
            if step.name == "github":
                print("Docs: docs/configuration.md")
        else:
            print("e2e-preflight: all stages passed.")
        return overall

    console = Console(highlight=False, soft_wrap=True)
    console.print()
    title = Text()
    title.append("E2E PREFLIGHT", style="bold white on rgb(55,65,95)")
    title.append("  ", style="")
    title.append("bmt-gcloud", style="bold dim")
    subtitle = Text.from_markup(
        "[dim]Readiness for Actions → handoff → GCS/Cloud Run. Not a substitute for a real PR run on GitHub.[/]"
    )
    if dry_run:
        subtitle = Text.from_markup("[yellow]dry-run:[/] no checks executed; planned stages below.")
    console.print(
        Panel.fit(
            Text.assemble(title, "\n\n", subtitle),
            border_style="bright_cyan",
            box=box.DOUBLE_EDGE,
            padding=(1, 2),
        )
    )
    console.print()

    table = Table(title="[bold]Stages[/]", box=box.SIMPLE_HEAD)
    table.add_column("Step", style="cyan")
    table.add_column("Status", justify="center")

    fail_step = first_fail[0] if first_fail else None
    for step in active:
        if dry_run:
            table.add_row(step.name, "[dim]planned[/]")
        elif fail_step is None:
            table.add_row(step.name, "[green]ok[/]")
        elif step.name == fail_step.name:
            table.add_row(step.name, "[red]failed[/]")
            break
        else:
            table.add_row(step.name, "[green]ok[/]")

    console.print(table)
    console.print()

    if dry_run:
        console.print(
            Panel(
                Text.from_markup(
                    "[dim]Run without[/] [cyan]--dry-run[/] [dim]to execute. "
                    "Fix hints appear on failure ([cyan]just tools workspace pulumi[/], [cyan]just tools repo show-env[/], …).[/]"
                ),
                border_style="dim",
            )
        )
        console.print()
        return 0

    if first_fail:
        step, rc, detail = first_fail
        fix = Text.from_markup(
            f"[bold red]Stopped[/] at [cyan]{step.name}[/] [dim](exit {rc})[/]\n"
            f"{detail}\n\n"
            f"[bold]Try:[/] [cyan]{step.just_on_fail}[/]"
        )
        if step.name == "validate":
            fix.append_text(Text.from_markup("\n[dim]Then re-check:[/] [cyan]just workspace validate[/]"))
        if step.name == "github":
            fix.append_text(
                Text.from_markup(
                    "\n[dim]Reference:[/] [cyan]docs/configuration.md[/] [dim](GitHub + GCP Secret Manager).[/]"
                )
            )
        if step.name == "preflight":
            fix.append_text(
                Text.from_markup(
                    "\n[dim]Also:[/] [cyan]gcloud auth application-default login[/] [dim]if ADC is missing.[/]"
                )
            )
        console.print(Panel(fix, border_style="red", box=box.HEAVY))
        console.print()
        return rc

    foot = Text.from_markup(
        "[bold green]All selected stages passed.[/]\n"
        "[dim]Open a PR or run workflows on GitHub for the true E2E. "
        "GCP Secret Manager parity is documented only — not probed here.[/]"
    )
    if skip_bucket:
        foot.append_text(Text.from_markup("\n[dim]Note:[/] bucket preflight was [yellow]skipped[/]."))
    if not with_tests:
        foot.append_text(
            Text.from_markup("\n[dim]Note:[/] full [cyan]just test[/] was not run; use [cyan]--with-tests[/].")
        )
    console.print(Panel(foot, border_style="green", box=box.DOUBLE))
    console.print()
    return 0
