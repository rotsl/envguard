# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""
envguard CLI - the main entry point for the environment orchestration framework.

Usage::

    python -m envguard init [--python 3.12] [--env-type venv]
    python -m envguard doctor
    python -m envguard run -- pytest -v
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from envguard import (
    EXIT_ENV_NOT_FOUND,
    EXIT_GENERAL_ERROR,
    EXIT_OK,
    EXIT_PERMISSION_DENIED,
    EXIT_PREFLIGHT_FAILED,
    STATE_FILENAME,
    SUPPORTED_ENV_TYPES,
    SUPPORTED_SHELLS,
    __version__,
    check_xcode_tools,
    detect_active_env,
    detect_project_type,
    ensure_envguard_dir,
    get_envguard_dir,
    get_envguard_version,
    get_macos_version,
    get_platform_info,
    get_shell_type,
    get_user_home,
    is_macos,
    load_json_file,
    pip_freeze,
    resolve_project_dir,
    run_command,
    save_json_file,
)
from envguard.doctor import Doctor

# ======================================================================
# App & console
# ======================================================================

app = typer.Typer(
    name="envguard",
    help="macOS-first Python environment orchestration framework.",
    no_args_is_help=True,
    add_completion=False,
)

console = Console()
stderr_console = Console(stderr=True)

# Reusable option definitions
json_output_option = typer.Option(
    False,
    "--json",
    "-j",
    help="Output results as JSON",
)


# ======================================================================
# Helpers
# ======================================================================


def handle_error(error: Exception, json_output: bool = False) -> int:
    """Handle errors and return an appropriate exit code.

    Displays the error to the user (or prints JSON) and maps common
    exception types to envguard exit codes.
    """
    error_map: dict[type, int] = {
        FileNotFoundError: EXIT_ENV_NOT_FOUND,
        PermissionError: EXIT_PERMISSION_DENIED,
        KeyboardInterrupt: 130,  # SIGINT
    }

    exit_code = EXIT_GENERAL_ERROR
    for exc_type, code in error_map.items():
        if isinstance(error, exc_type):
            exit_code = code
            break

    msg = str(error) if str(error) else type(error).__name__

    if json_output:
        json.dump({"ok": False, "error": msg, "exit_code": exit_code}, sys.stdout, indent=2)
        console.print()  # trailing newline
    else:
        console.print(f"[bold red]Error:[/bold red] {msg}")

    return exit_code


def output_json(data: Any) -> None:
    """Print *data* as formatted JSON to stdout."""
    json.dump(data, sys.stdout, indent=2, default=str)
    console.print()


def _project_info_table(project_dir: Path) -> Table:
    """Build a Rich table summarising project info."""
    table = Table(title="Project Information", show_header=False, border_style="cyan")
    table.add_column("Key", style="bold cyan")
    table.add_column("Value")

    ptype = detect_project_type(project_dir)
    table.add_row("Directory", str(project_dir))
    table.add_row("Type", ptype or "unknown")
    table.add_row(
        "envguard", "initialized" if get_envguard_dir(project_dir).exists() else "not initialized"
    )

    env_path = detect_active_env(project_dir)
    table.add_row("Active env", env_path or "none")

    return table


def _host_info_table() -> Table:
    """Build a Rich table summarising host info."""
    info = get_platform_info()
    table = Table(title="Host Information", show_header=False, border_style="green")
    table.add_column("Key", style="bold green")
    table.add_column("Value")

    table.add_row("OS", f"{info['system']} {info.get('macos_version', info['release'])}")
    table.add_row("Architecture", info["machine"])
    table.add_row("Python", f"{info['python_version']} ({info['python_implementation']})")
    table.add_row("Python path", info["python_executable"])

    if is_macos():
        ver = get_macos_version()
        if ver:
            table.add_row("macOS version", ".".join(str(v) for v in ver))

    return table


def _run_preflight(project_dir: Path) -> tuple[int, str]:
    """Run the full preflight pipeline.

    Returns (exit_code, summary_message).
    """
    try:
        from envguard.preflight import PreflightEngine

        engine = PreflightEngine(project_dir=project_dir)
        result = engine.run()
        if result.success:
            return EXIT_OK, result.summary or "All preflight checks passed."
        return EXIT_PREFLIGHT_FAILED, result.summary or "Preflight failed."
    except Exception as exc:
        # Fall back to lightweight Doctor checks if PreflightEngine is unavailable
        import logging

        logging.getLogger("envguard").warning(
            "PreflightEngine unavailable (%s) - falling back to Doctor checks", exc
        )

    doc = Doctor(project_dir=project_dir)
    critical = [
        "host_system",
        "python_installation",
        "permissions",
        "project_configuration",
    ]
    for name in critical:
        r = doc.run_check(name)
        if r["status"] == "error":
            return EXIT_PREFLIGHT_FAILED, f"Preflight check '{name}' failed: {r['message']}"
    return EXIT_OK, "All critical preflight checks passed."


def _managed_run(command: list[str], project_dir: Path, env_path: str | None = None) -> int:
    """Execute *command* inside a managed environment.

    Returns the process exit code.
    """
    cmd_env = os.environ.copy()

    # If we have a detected env, ensure its bin is first on PATH
    if env_path:
        env_bin = str(Path(env_path) / "bin")
        current_path = cmd_env.get("PATH", "")
        if env_bin not in current_path.split(os.pathsep):
            cmd_env["PATH"] = env_bin + os.pathsep + current_path
            cmd_env["VIRTUAL_ENV"] = env_path

    try:
        result = subprocess.run(
            command,
            env=cmd_env,
            cwd=str(project_dir),
            timeout=3600,  # 1-hour default timeout to prevent indefinite hangs
        )
        return result.returncode
    except subprocess.TimeoutExpired:
        console.print(f"[red]Command timed out after 1 hour:[/red] {' '.join(command[:5])}")
        return 124
    except FileNotFoundError:
        console.print(f"[red]Command not found:[/red] {command[0]}")
        return 127
    except PermissionError:
        console.print(f"[red]Permission denied:[/red] {command[0]}")
        return EXIT_PERMISSION_DENIED
    except Exception as exc:
        console.print(f"[red]Failed to run command:[/red] {exc}")
        return EXIT_GENERAL_ERROR


def _ensure_launchd_dir() -> Path:
    """Return (and create) the ~/Library/LaunchAgents directory."""
    return get_user_home() / "Library" / "LaunchAgents"


# ======================================================================
# Commands
# ======================================================================


@app.command()
def init(
    project_dir: Path = typer.Argument(
        Path.cwd(),
        help="Project directory to initialize",
    ),
    python_version: str | None = typer.Option(
        None,
        "--python",
        "-p",
        help="Python version to use (e.g. 3.12)",
    ),
    env_type: str | None = typer.Option(
        None,
        "--env-type",
        "-e",
        help="Environment type (venv, conda)",
    ),
    json_output: bool = json_output_option,
) -> None:
    """Initialize envguard for a project."""
    try:
        project_dir = resolve_project_dir(project_dir)
        eg_dir = ensure_envguard_dir(project_dir)

        # Gather project metadata
        ptype = detect_project_type(project_dir)
        active_env = detect_active_env(project_dir)
        platform_info = get_platform_info()

        # Build initial state
        state: dict[str, Any] = {
            "version": __version__,
            "project_type": ptype,
            "project_dir": str(project_dir),
            "active_env": active_env,
            "python_version": python_version or platform_info["python_version"],
            "env_type": env_type
            or ("conda" if active_env and "conda" in (active_env or "") else "venv"),
            "platform": {
                "system": platform_info["system"],
                "machine": platform_info["machine"],
                "python_version": platform_info["python_version"],
            },
            "initialized_at": _iso_now(),
            "last_updated": _iso_now(),
        }

        if active_env:
            state["env_path"] = active_env

        # Validate env_type
        if env_type and env_type not in SUPPORTED_ENV_TYPES:
            console.print(
                f"[yellow]Warning:[/yellow] Unknown env type '{env_type}'. "
                f"Supported: {', '.join(SUPPORTED_ENV_TYPES)}",
            )

        # Save state
        state_file = eg_dir / STATE_FILENAME
        save_json_file(state_file, state)

        # Create subdirectories
        for subdir in ("cache", "snapshots", "logs"):
            (eg_dir / subdir).mkdir(parents=True, exist_ok=True)

        # Write .gitignore inside .envguard
        gitignore = eg_dir / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text(
                "# envguard internal files\ncache/\nsnapshots/\nlogs/\n*.tmp\n",
                encoding="utf-8",
            )

        if json_output:
            output_json({"ok": True, "project_dir": str(project_dir), "state": state})
        else:
            console.print(
                Panel(
                    f"[bold green]envguard initialized[/bold green] in [cyan]{project_dir}[/cyan]\n\n"
                    f"  Project type : {ptype or 'auto-detected'}\n"
                    f"  Python       : {state['python_version']}\n"
                    f"  Env type     : {state['env_type']}\n"
                    f"  Active env   : {active_env or 'none'}\n"
                    f"  State file   : {state_file}",
                    title="envguard init",
                    border_style="green",
                )
            )

    except Exception as exc:
        raise typer.Exit(handle_error(exc, json_output)) from exc


@app.command()
def doctor(
    project_dir: Path = typer.Argument(
        Path.cwd(),
        help="Project directory",
    ),
    json_output: bool = json_output_option,
) -> None:
    """Run comprehensive diagnostics on the host and project."""
    try:
        project_dir = resolve_project_dir(project_dir)
        doc = Doctor(project_dir=project_dir)
        results = doc.run()

        if json_output:
            output_json(results)
        else:
            console.print(doc.format_report(results))

            # Also display a summary table
            table = Table(title="Diagnostic Summary", border_style="cyan")
            table.add_column("Check", style="bold")
            table.add_column("Status")
            table.add_column("Message", max_width=60)

            status_style = {"ok": "green", "warning": "yellow", "error": "red", "skip": "dim"}
            for check in results["checks"]:
                st = check["status"]
                style = status_style.get(st, "white")
                table.add_row(
                    check["name"],
                    Text(st, style=style),
                    check["message"],
                )

            console.print()
            console.print(table)

            overall = results["overall"]
            if overall == "error":
                raise typer.Exit(EXIT_GENERAL_ERROR)
            elif overall == "warning":
                console.print("[yellow]Some checks reported warnings.[/yellow]")

    except typer.Exit:
        raise
    except Exception as exc:
        raise typer.Exit(handle_error(exc, json_output)) from exc


@app.command()
def detect(
    project_dir: Path = typer.Argument(
        Path.cwd(),
        help="Project directory",
    ),
    json_output: bool = json_output_option,
) -> None:
    """Detect and display host and project information."""
    try:
        project_dir = resolve_project_dir(project_dir)
        platform_info = get_platform_info()
        ptype = detect_project_type(project_dir)
        active_env = detect_active_env(project_dir)
        eg_dir = get_envguard_dir(project_dir)

        data: dict[str, Any] = {
            "host": platform_info,
            "project": {
                "dir": str(project_dir),
                "type": ptype,
                "envguard_initialized": eg_dir.exists(),
                "active_env": active_env,
            },
        }

        if is_macos():
            xcode = check_xcode_tools()
            data["host"]["xcode_tools"] = xcode

        if json_output:
            output_json(data)
        else:
            console.print(_host_info_table())
            console.print()
            console.print(_project_info_table(project_dir))

    except Exception as exc:
        raise typer.Exit(handle_error(exc, json_output)) from exc


@app.command()
def preflight(
    project_dir: Path = typer.Argument(
        Path.cwd(),
        help="Project directory",
    ),
    command: list[str] | None = typer.Argument(
        None,
        help="Command to run after preflight checks pass",
    ),
    json_output: bool = json_output_option,
) -> None:
    """Run preflight checks and optionally execute a command."""
    try:
        project_dir = resolve_project_dir(project_dir)

        if json_output:
            # Run all doctor checks and return JSON
            doc = Doctor(project_dir=project_dir)
            results = doc.run()
            output_json(results)
            if results["overall"] in ("error",):
                raise typer.Exit(EXIT_PREFLIGHT_FAILED)
            if command:
                code = _managed_run(command, project_dir, detect_active_env(project_dir))
                if code:
                    raise typer.Exit(code)
            return

        # Rich output path
        console.print("[bold cyan]Running preflight checks…[/bold cyan]\n")

        doc = Doctor(project_dir=project_dir)
        all_results = doc.run()

        status_colors = {"ok": "green", "warning": "yellow", "error": "red", "skip": "dim"}
        for check in all_results["checks"]:
            st = check["status"]
            color = status_colors.get(st, "white")
            symbol = {"ok": "✓", "warning": "⚠", "error": "✗", "skip": "○"}.get(st, "?")
            console.print(f"  [{color}]{symbol}[/{color}] {check['name']}: {check['message']}")

        console.print()
        summary = all_results["summary"]
        console.print(
            f"  Results: [green]{summary['ok']} OK[/green], "
            f"[yellow]{summary['warning']} warnings[/yellow], "
            f"[red]{summary['error']} errors[/red]"
        )

        if all_results["overall"] == "error":
            console.print("\n[bold red]Preflight checks failed.[/bold red]")
            raise typer.Exit(EXIT_PREFLIGHT_FAILED)

        if all_results["overall"] == "warning":
            console.print("\n[yellow]Preflight checks passed with warnings.[/yellow]")
        else:
            console.print("\n[bold green]All preflight checks passed.[/bold green]")

        if command:
            console.print(f"\n[cyan]Running:[/cyan] {' '.join(command)}\n")
            env_path = detect_active_env(project_dir)
            code = _managed_run(command, project_dir, env_path)
            if code:
                raise typer.Exit(code)

    except typer.Exit:
        raise
    except Exception as exc:
        raise typer.Exit(handle_error(exc, json_output)) from exc


@app.command()
def run(
    command: list[str] = typer.Argument(
        ...,
        help="Command to run (use -- to separate from envguard args)",
    ),
    project_dir: Path = typer.Option(
        Path.cwd(),
        "--dir",
        "-d",
        help="Project directory",
    ),
    no_preflight: bool = typer.Option(
        False,
        "--no-preflight",
        help="Skip preflight checks",
    ),
    json_output: bool = json_output_option,
) -> None:
    """Run a command in a managed environment.

    Example: envguard run -- python app.py

    Example: envguard run -- pytest -v
    """
    try:
        project_dir = resolve_project_dir(project_dir)

        if not no_preflight:
            if not json_output:
                console.print("[bold cyan]Running preflight checks…[/bold cyan]")
            code, msg = _run_preflight(project_dir)
            if code != EXIT_OK:
                if json_output:
                    output_json({"ok": False, "error": msg, "exit_code": code})
                else:
                    console.print(f"[red]{msg}[/red]")
                raise typer.Exit(code)
            if not json_output:
                console.print("[green]Preflight passed.[/green]\n")

        env_path = detect_active_env(project_dir)

        if json_output:
            output_json(
                {
                    "ok": True,
                    "command": command,
                    "project_dir": str(project_dir),
                    "env_path": env_path,
                }
            )

        if not json_output:
            console.print(f"[cyan]Running:[/cyan] {' '.join(command)}\n")

        result_code = _managed_run(command, project_dir, env_path)
        if result_code:
            raise typer.Exit(result_code)

    except typer.Exit:
        raise
    except Exception as exc:
        raise typer.Exit(handle_error(exc, json_output)) from exc


@app.command()
def repair(
    project_dir: Path = typer.Argument(
        Path.cwd(),
        help="Project directory",
    ),
    json_output: bool = json_output_option,
) -> None:
    """Repair the managed environment for a project."""
    try:
        project_dir = resolve_project_dir(project_dir)
        eg_dir = get_envguard_dir(project_dir)

        if not eg_dir.exists():
            msg = "No .envguard directory found. Run `envguard init` first."
            if json_output:
                output_json({"ok": False, "error": msg})
            else:
                console.print(f"[yellow]{msg}[/yellow]")
            raise typer.Exit(EXIT_ENV_NOT_FOUND)

        repairs: list[str] = []

        # 1. Ensure state file exists and is valid JSON
        state_file = eg_dir / STATE_FILENAME
        state = load_json_file(state_file)
        if state is None:
            state = {
                "version": __version__,
                "project_dir": str(project_dir),
                "repaired": True,
                "repaired_at": _iso_now(),
            }
            save_json_file(state_file, state)
            repairs.append("Created missing state file")

        # 2. Ensure subdirectories exist
        for subdir in ("cache", "snapshots", "logs"):
            sub = eg_dir / subdir
            if not sub.exists():
                sub.mkdir(parents=True, exist_ok=True)
                repairs.append(f"Created missing {subdir}/ directory")

        # 3. Fix .gitignore
        gitignore = eg_dir / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text(
                "# envguard internal files\ncache/\nsnapshots/\nlogs/\n*.tmp\n",
                encoding="utf-8",
            )
            repairs.append("Created missing .gitignore")

        # 4. If active env detected, verify it exists
        env_path = state.get("env_path") or state.get("active_env")
        if env_path and not Path(env_path).exists():
            state.pop("env_path", None)
            state["active_env"] = detect_active_env(project_dir)
            state["repaired_at"] = _iso_now()
            save_json_file(state_file, state)
            repairs.append(f"Removed stale env path reference: {env_path}")

        # 5. Update platform info
        state["platform"] = get_platform_info()
        state["last_updated"] = _iso_now()
        save_json_file(state_file, state)
        repairs.append("Updated platform information")

        if not repairs:
            msg = "No repairs needed - environment looks healthy."
            if json_output:
                output_json({"ok": True, "repairs": [], "message": msg})
            else:
                console.print(f"[green]{msg}[/green]")
        else:
            if json_output:
                output_json({"ok": True, "repairs": repairs})
            else:
                console.print(
                    Panel(
                        "\n".join(f"  [green]✓[/green] {r}" for r in repairs),
                        title=f"[bold green]Repairs applied ({len(repairs)})[/bold green]",
                        border_style="green",
                    )
                )

    except typer.Exit:
        raise
    except Exception as exc:
        raise typer.Exit(handle_error(exc, json_output)) from exc


@app.command()
def freeze(
    project_dir: Path = typer.Argument(
        Path.cwd(),
        help="Project directory",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Output file path",
    ),
    json_output: bool = json_output_option,
) -> None:
    """Freeze and capture the current environment state."""
    try:
        project_dir = resolve_project_dir(project_dir)

        # Collect pip freeze output
        frozen = pip_freeze()
        env_path = detect_active_env(project_dir)
        ptype = detect_project_type(project_dir)

        snapshot: dict[str, Any] = {
            "created_at": _iso_now(),
            "envguard_version": __version__,
            "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "project_dir": str(project_dir),
            "project_type": ptype,
            "active_env": env_path,
            "packages": frozen,
            "package_count": len(frozen),
            "platform": get_platform_info(),
        }

        # Determine output path
        if output is None:
            eg_dir = get_envguard_dir(project_dir)
            if eg_dir.exists():
                snapshots_dir = eg_dir / "snapshots"
                snapshots_dir.mkdir(parents=True, exist_ok=True)
                ts = _iso_now().replace(":", "-").replace(".", "-")
                output = snapshots_dir / f"freeze-{ts}.json"
            else:
                output = project_dir / "requirements-frozen.txt"

        if output.suffix == ".json":
            save_json_file(output, snapshot)
        else:
            # Write as plain text (requirements format)
            output.write_text("\n".join(frozen) + "\n", encoding="utf-8")

        if json_output:
            output_json({"ok": True, "output": str(output), "packages": len(frozen)})
        else:
            console.print(
                Panel(
                    f"  Output     : {output}\n"
                    f"  Packages   : {len(frozen)}\n"
                    f"  Python     : {snapshot['python_version']}\n"
                    f"  Environment: {env_path or 'system'}",
                    title="[bold green]Environment frozen[/bold green]",
                    border_style="green",
                )
            )

    except Exception as exc:
        raise typer.Exit(handle_error(exc, json_output)) from exc


@app.command()
def health(
    project_dir: Path = typer.Argument(
        Path.cwd(),
        help="Project directory",
    ),
    json_output: bool = json_output_option,
) -> None:
    """Display health status of the managed environment."""
    try:
        project_dir = resolve_project_dir(project_dir)

        # Run a subset of doctor checks focused on environment health
        doc = Doctor(project_dir=project_dir)
        env_health = doc.run_check("environment_health")
        py_install = doc.run_check("python_installation")
        permissions = doc.run_check("permissions")

        checks = [env_health, py_install, permissions]
        overall = "ok"
        for c in checks:
            if c["status"] == "error":
                overall = "error"
            elif c["status"] == "warning" and overall != "error":
                overall = "warning"

        result = {
            "project_dir": str(project_dir),
            "overall": overall,
            "checks": checks,
        }

        if json_output:
            output_json(result)
        else:
            table = Table(title="Environment Health", border_style="cyan")
            table.add_column("Check", style="bold")
            table.add_column("Status")
            table.add_column("Message", max_width=60)

            status_style = {"ok": "green", "warning": "yellow", "error": "red", "skip": "dim"}
            for check in checks:
                st = check["status"]
                style = status_style.get(st, "white")
                table.add_row(
                    check["name"],
                    Text(st, style=style),
                    check["message"],
                )

            console.print(table)

            if overall == "error":
                console.print(
                    "\n[red]Environment has errors. Run [bold]envguard repair[/bold] to fix.[/red]"
                )
            elif overall == "warning":
                console.print("\n[yellow]Environment has warnings.[/yellow]")
            else:
                console.print("\n[green]Environment is healthy.[/green]")

    except Exception as exc:
        raise typer.Exit(handle_error(exc, json_output)) from exc


@app.command()
def update(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Check for updates without installing",
    ),
    channel: str | None = typer.Option(
        None,
        "--channel",
        "-c",
        help="Update channel (stable, beta)",
    ),
    json_output: bool = json_output_option,
) -> None:
    """Check for and apply envguard updates."""
    try:
        current = get_envguard_version()
        channel = channel or "stable"

        # Attempt update via UpdateManager (verified, rollback-capable)
        update_available = False
        latest = current
        update_error: str | None = None

        try:
            from envguard.update.updater import UpdateManager

            mgr = UpdateManager(config={"update_policy": channel})
            check = mgr.check_for_updates()
            update_available = check.update_available
            latest = check.latest_version or current
            if check.error:
                update_error = check.error
        except Exception as exc:
            # Fall back to pip index if UpdateManager fails (e.g. no manifest server)
            update_error = str(exc)
            pip_result = run_command(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "index",
                    "versions",
                    "envguard",
                    "--disable-pip-version-check",
                ],
                timeout=30,
            )
            if pip_result.returncode == 0 and pip_result.stdout:
                for line in pip_result.stdout.splitlines():
                    line_lower = line.lower()
                    if "available:" in line_lower or "latest:" in line_lower:
                        parts = line.split(":")
                        if len(parts) >= 2:
                            ver = parts[-1].strip().split()[0]
                            if ver:
                                latest = ver
                                if _version_newer(latest, current):
                                    update_available = True
                        break

        if json_output:
            output_json(
                {
                    "current": current,
                    "latest": latest,
                    "update_available": update_available,
                    "channel": channel,
                    "dry_run": dry_run,
                    "error": update_error,
                }
            )
        else:
            if update_available:
                console.print(
                    Panel(
                        f"  Current : {current}\n  Latest  : {latest}\n  Channel : {channel}",
                        title="[bold yellow]Update available[/bold yellow]",
                        border_style="yellow",
                    )
                )
                if not dry_run:
                    console.print("\n[cyan]Installing update…[/cyan]")
                    try:
                        from envguard.update.updater import UpdateManager

                        mgr = UpdateManager(config={"update_policy": channel})
                        up_result = mgr.perform_update()
                        if up_result.get("success"):
                            console.print("[bold green]Updated successfully![/bold green]")
                        else:
                            raise RuntimeError(up_result.get("error", "Unknown error"))
                    except Exception:
                        # Fallback to pip install
                        install_result = run_command(
                            [sys.executable, "-m", "pip", "install", "--upgrade", "envguard"],
                            timeout=120,
                        )
                        if install_result.returncode == 0:
                            console.print("[bold green]Updated successfully![/bold green]")
                        else:
                            console.print(f"[red]Update failed:[/red] {install_result.stderr}")
                            raise typer.Exit(EXIT_GENERAL_ERROR) from None
                else:
                    console.print("[dim]Dry run - no changes made.[/dim]")
            else:
                if update_error:
                    console.print(f"[dim]Could not check remote manifest: {update_error}[/dim]")
                console.print(f"[green]envguard is up to date[/green] (v{current}).")

    except typer.Exit:
        raise
    except Exception as exc:
        raise typer.Exit(handle_error(exc, json_output)) from exc


@app.command()
def rollback(
    snapshot_id: str | None = typer.Argument(
        None,
        help="Snapshot ID to rollback to",
    ),
    json_output: bool = json_output_option,
) -> None:
    """Rollback envguard to a previous version."""
    try:
        if not snapshot_id:
            # List available snapshots
            home = get_user_home()
            eg_global = home / ".envguard"
            snapshots_dir = eg_global / "snapshots"
            if not snapshots_dir.exists():
                msg = "No snapshots found. No rollback history available."
                if json_output:
                    output_json({"ok": False, "error": msg})
                else:
                    console.print(f"[yellow]{msg}[/yellow]")
                return

            snapshots = sorted(snapshots_dir.glob("*.json"))
            if not snapshots:
                msg = "No snapshots found."
                if json_output:
                    output_json({"ok": False, "error": msg})
                else:
                    console.print(f"[yellow]{msg}[/yellow]")
                return

            if json_output:
                output_json(
                    {
                        "ok": True,
                        "available_snapshots": [s.stem for s in snapshots],
                    }
                )
            else:
                table = Table(title="Available Snapshots", border_style="cyan")
                table.add_column("Snapshot ID", style="bold cyan")
                table.add_column("File")
                for s in snapshots:
                    table.add_row(s.stem, str(s))
                console.print(table)
                console.print("\n[dim]Run: envguard rollback <snapshot-id>[/dim]")
            return

        # Rollback to specific snapshot
        home = get_user_home()
        snapshots_dir = home / ".envguard" / "snapshots"
        snapshot_file = None
        for ext in ("", ".json"):
            candidate = snapshots_dir / f"{snapshot_id}{ext}"
            if candidate.exists():
                snapshot_file = candidate
                break

        if snapshot_file is None:
            msg = f"Snapshot not found: {snapshot_id}"
            if json_output:
                output_json({"ok": False, "error": msg})
            else:
                console.print(f"[red]{msg}[/red]")
            raise typer.Exit(EXIT_GENERAL_ERROR)

        # Perform the actual rollback via RollbackManager
        try:
            from envguard.update.rollback import RollbackManager

            rb = RollbackManager()
            rb_result = rb.rollback(snapshot_id)
        except Exception as exc:
            msg = f"Rollback failed: {exc}"
            if json_output:
                output_json({"ok": False, "error": msg})
            else:
                console.print(f"[red]{msg}[/red]")
            raise typer.Exit(EXIT_GENERAL_ERROR) from exc

        if json_output:
            output_json(
                {
                    "ok": True,
                    "rolled_back_to": snapshot_id,
                    "result": rb_result,
                }
            )
        else:
            console.print(
                Panel(
                    f"  Snapshot : {snapshot_id}\n  File     : {snapshot_file}",
                    title="[bold green]Rollback complete[/bold green]",
                    border_style="green",
                )
            )

    except typer.Exit:
        raise
    except Exception as exc:
        raise typer.Exit(handle_error(exc, json_output)) from exc


@app.command()
def install_shell_hooks(
    shell: str | None = typer.Option(
        None,
        "--shell",
        "-s",
        help="Shell type (zsh, bash)",
    ),
    json_output: bool = json_output_option,
) -> None:
    """Install optional shell integration hooks."""
    try:
        from envguard.launch.shell_hooks import ShellHookManager

        manager = ShellHookManager()
        shell = shell or get_shell_type()

        if shell not in SUPPORTED_SHELLS:
            msg = f"Unsupported shell: {shell}. Supported: {', '.join(SUPPORTED_SHELLS)}"
            if json_output:
                output_json({"ok": False, "error": msg})
            else:
                console.print(f"[yellow]{msg}[/yellow]")
            return

        result = manager.install_hooks(shell)

        if json_output:
            output_json(result)
        else:
            if result["success"]:
                console.print(
                    Panel(
                        f"  Shell  : {result.get('installed_for', shell)}\n"
                        f"  RC file: {result.get('rc_file', 'none')}",
                        title="[bold green]Shell hooks installed[/bold green]",
                        border_style="green",
                    )
                )
            else:
                console.print("[yellow]Failed to install hooks.[/yellow]")

    except Exception as exc:
        raise typer.Exit(handle_error(exc, json_output)) from exc


@app.command(name="uninstall-shell-hooks")
def uninstall_shell_hooks(
    shell: str | None = typer.Option(
        None,
        "--shell",
        "-s",
        help="Shell type (zsh, bash)",
    ),
    json_output: bool = json_output_option,
) -> None:
    """Uninstall shell integration hooks."""
    try:
        from envguard.launch.shell_hooks import ShellHookManager

        manager = ShellHookManager()
        shell = shell or get_shell_type()

        if shell not in SUPPORTED_SHELLS:
            msg = f"Unsupported shell: {shell}. Supported: {', '.join(SUPPORTED_SHELLS)}"
            if json_output:
                output_json({"ok": False, "error": msg})
            else:
                console.print(f"[yellow]{msg}[/yellow]")
            return

        result = manager.uninstall_hooks(shell)

        if json_output:
            output_json(result)
        else:
            if result["success"]:
                console.print(
                    Panel(
                        f"  Shell  : {result.get('uninstalled_from', shell)}",
                        title="[bold green]Shell hooks uninstalled[/bold green]",
                        border_style="green",
                    )
                )
            else:
                console.print("[yellow]Failed to uninstall hooks.[/yellow]")

    except Exception as exc:
        raise typer.Exit(handle_error(exc, json_output)) from exc


@app.command()
def install_launch_agent(
    json_output: bool = json_output_option,
) -> None:
    """Install the envguard update LaunchAgent for macOS."""
    try:
        if not is_macos():
            msg = "LaunchAgent installation is only supported on macOS."
            if json_output:
                output_json({"ok": False, "error": msg})
            else:
                console.print(f"[yellow]{msg}[/yellow]")
            return

        from envguard.launch.launch_agent import LaunchAgentManager

        la_manager = LaunchAgentManager()
        envguard_bin = shutil.which("envguard") or sys.executable + " -m envguard"
        result = la_manager.install(envguard_bin)

        if json_output:
            output_json(
                {
                    "ok": result["success"],
                    "plist_path": result["plist_path"],
                    "loaded": result["loaded"],
                }
            )
        else:
            if result["success"]:
                console.print(
                    Panel(
                        f"  Plist : {result['plist_path']}\n"
                        f"  Loaded: {'yes' if result['loaded'] else 'no (load manually with launchctl load -w)'}",
                        title="[bold green]LaunchAgent installed[/bold green]",
                        border_style="green",
                    )
                )
            else:
                console.print("[yellow]LaunchAgent plist written but failed to load.[/yellow]")

    except Exception as exc:
        raise typer.Exit(handle_error(exc, json_output)) from exc


@app.command(name="uninstall-launch-agent")
def uninstall_launch_agent(
    json_output: bool = json_output_option,
) -> None:
    """Uninstall the envguard update LaunchAgent."""
    try:
        if not is_macos():
            msg = "LaunchAgent uninstallation is only supported on macOS."
            if json_output:
                output_json({"ok": False, "error": msg})
            else:
                console.print(f"[yellow]{msg}[/yellow]")
            return

        launch_agents_dir = _ensure_launchd_dir()
        plist_path = launch_agents_dir / "com.envguard.update.plist"

        if not plist_path.exists():
            msg = "LaunchAgent not found - nothing to uninstall."
            if json_output:
                output_json({"ok": True, "message": msg})
            else:
                console.print(f"[green]{msg}[/green]")
            return

        # Unload if loaded
        run_command(["launchctl", "unload", str(plist_path)], check=False, timeout=5)

        plist_path.unlink()

        if json_output:
            output_json({"ok": True, "plist_path": str(plist_path)})
        else:
            console.print(
                Panel(
                    f"  Removed: {plist_path}",
                    title="[bold green]LaunchAgent uninstalled[/bold green]",
                    border_style="green",
                )
            )

    except Exception as exc:
        raise typer.Exit(handle_error(exc, json_output)) from exc


@app.command()
def status(
    project_dir: Path = typer.Argument(
        Path.cwd(),
        help="Project directory",
    ),
    json_output: bool = json_output_option,
) -> None:
    """Display status of envguard and the managed environment."""
    try:
        project_dir = resolve_project_dir(project_dir)
        eg_dir = get_envguard_dir(project_dir)
        state = load_json_file(eg_dir / STATE_FILENAME) if eg_dir.exists() else None
        env_path = detect_active_env(project_dir)
        ptype = detect_project_type(project_dir)

        status_data: dict[str, Any] = {
            "envguard_version": __version__,
            "project_dir": str(project_dir),
            "project_type": ptype,
            "envguard_initialized": eg_dir.exists(),
            "active_env": env_path,
            "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "platform": platform_info_summary(),
        }

        if state:
            status_data["state"] = state
            status_data["initialized_at"] = state.get("initialized_at")
            status_data["last_updated"] = state.get("last_updated")
            status_data["env_type"] = state.get("env_type")

        if json_output:
            output_json(status_data)
        else:
            # Header
            console.print(
                Panel(
                    f"  envguard v{__version__}\n"
                    f"  Python   : {status_data['python_version']}\n"
                    f"  Platform : {status_data['platform']}",
                    title="[bold cyan]envguard[/bold cyan]",
                    border_style="cyan",
                )
            )

            # Project status
            table = Table(title="Project Status", border_style="green", show_header=False)
            table.add_column("Key", style="bold green")
            table.add_column("Value")

            table.add_row("Directory", str(project_dir))
            table.add_row("Type", ptype or "unknown")
            table.add_row("Initialized", "yes" if eg_dir.exists() else "no")

            if state:
                table.add_row("Env type", state.get("env_type", "unknown"))
                table.add_row("Initialized at", state.get("initialized_at", "unknown"))
                table.add_row("Last updated", state.get("last_updated", "unknown"))

            table.add_row("Active env", env_path or "none")

            console.print(table)

            # Quick health check
            if eg_dir.exists():
                doc = Doctor(project_dir=project_dir)
                env_health = doc.run_check("environment_health")
                st = env_health["status"]
                color = {"ok": "green", "warning": "yellow", "error": "red"}.get(st, "white")
                console.print(f"\nEnvironment: [{color}]{env_health['message']}[/{color}]")

    except Exception as exc:
        raise typer.Exit(handle_error(exc, json_output)) from exc


# ======================================================================
# Internal utilities
# ======================================================================


def _iso_now() -> str:
    """Return the current UTC time in ISO 8601 format."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _version_newer(latest: str, current: str) -> bool:
    """Return True if *latest* is a newer version than *current*."""
    try:
        from packaging.version import Version

        return Version(latest) > Version(current)
    except Exception:
        # Fallback: simple tuple comparison
        def _parse(v: str) -> tuple[int, ...]:
            cleaned = v.lstrip("vV")
            parts: list[int] = []
            for seg in cleaned.split("."):
                try:
                    parts.append(int(seg))
                except ValueError:
                    break
            return tuple(parts) if parts else (0,)

        return _parse(latest) > _parse(current)


def platform_info_summary() -> str:
    """Return a one-line platform summary."""
    info = get_platform_info()
    parts = [info["system"]]
    if is_macos():
        parts.append(info.get("macos_version", info["release"]))
    else:
        parts.append(info["release"])
    parts.append(info["machine"])
    return " ".join(parts)


@app.command(name="shell-hook")
def shell_hook(
    shell: str | None = typer.Option(
        None,
        "--shell",
        "-s",
        help="Shell type (zsh, bash)",
    ),
) -> None:
    """Output shell integration code suitable for eval in RC files.

    Usage: eval "$(envguard shell-hook)"
    """
    shell_type = shell or get_shell_type()
    # Output valid shell code - at minimum a no-op comment so eval succeeds
    print(f"# envguard shell integration ({shell_type}) - v{__version__}")


def _generate_launch_agent_plist() -> str:
    """Generate the XML content for the envguard update LaunchAgent plist."""
    python_path = sys.executable
    # Determine the envguard module path
    import envguard as _eg

    module_path = str(Path(_eg.__file__).resolve().parent)
    return f"""\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.envguard.update</string>

    <key>ProgramArguments</key>
    <array>
        <string>{python_path}</string>
        <string>-m</string>
        <string>envguard</string>
        <string>update</string>
    </array>

    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>12</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>

    <key>StandardOutPath</key>
    <string>/tmp/envguard-update.log</string>

    <key>StandardErrorPath</key>
    <string>/tmp/envguard-update.err</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONPATH</key>
        <string>{module_path}</string>
    </dict>
</dict>
</plist>
"""


# ======================================================================
# Entry point
# ======================================================================


def main() -> None:
    """Entry point for `envguard` CLI invocation."""
    app()


if __name__ == "__main__":
    main()
