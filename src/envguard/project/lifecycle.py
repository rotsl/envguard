# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""Project lifecycle – initialise, manage, repair, and inspect environments.

The :class:`ProjectLifecycle` class ties together host detection, project
discovery, intent analysis, and resolution management into a single
cohesive interface for end-users and higher-level tooling.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from envguard.detect import HostDetector, detect_host
from envguard.exceptions import (
    BrokenEnvironmentError,
    EnvguardError,
)
from envguard.logging import get_logger
from envguard.models import (
    AcceleratorTarget,
    EnvironmentType,
    FindingSeverity,
    HealthReport,
    HealthStatus,
    HostFacts,
    PreflightResult,
    ProjectIntent,
    ResolutionRecord,
)
from envguard.project.discovery import ProjectDiscovery, discover_project
from envguard.project.intent import IntentAnalyzer
from envguard.project.resolution import ResolutionManager

logger = get_logger("project.lifecycle")

#: The envguard state directory name (relative to project root)
_ENVGUARD_DIR = ".envguard"


class ProjectLifecycle:
    """High-level lifecycle manager for a Python project.

    Orchestrates host detection, project discovery, intent analysis,
    resolution, and environment creation in a single object.
    """

    def __init__(
        self,
        project_dir: Path,
        facts: Optional[HostFacts] = None,
        intent: Optional[ProjectIntent] = None,
    ) -> None:
        self.project_dir = Path(project_dir).resolve()
        self._facts: Optional[HostFacts] = facts
        self._intent: Optional[ProjectIntent] = intent
        self._resolution: Optional[ResolutionRecord] = None

    # ------------------------------------------------------------------ #
    # Properties
    # ------------------------------------------------------------------ #

    @property
    def facts(self) -> HostFacts:
        """Lazy-load host facts if not provided at construction."""
        if self._facts is None:
            self._facts = detect_host(self.project_dir)
        return self._facts

    @property
    def intent(self) -> ProjectIntent:
        """Lazy-discover project intent if not provided at construction."""
        if self._intent is None:
            self._intent = discover_project(self.project_dir)
        return self._intent

    @property
    def resolution(self) -> Optional[ResolutionRecord]:
        """The current resolution, if any."""
        if self._resolution is None:
            self._resolution = ResolutionManager.from_saved(self.project_dir)
        return self._resolution

    # ------------------------------------------------------------------ #
    # Full initialisation
    # ------------------------------------------------------------------ #

    def initialize(self) -> dict[str, Any]:
        """Full initialisation: detect, analyse, resolve, create env.

        Returns:
            A summary dict with keys: facts, intent, resolution, env_created.
        """
        logger.info("Initialising project at %s", self.project_dir)

        # 1. Detect host
        facts = self.facts

        # 2. Discover project
        intent = self.intent

        # 3. Analyse intent against host
        analyzer = IntentAnalyzer(intent, facts)
        intent = analyzer.analyze()

        # 4. Resolve
        resolver = ResolutionManager(self.project_dir, facts, intent)
        record = resolver.resolve()
        self._resolution = record

        # 5. Check for errors in findings
        errors = [f for f in record.findings if f.severity == FindingSeverity.ERROR]
        if errors:
            error_msgs = [f.message for f in errors]
            raise BrokenEnvironmentError(
                env_path=str(self.project_dir),
                reason=f"Resolution has {len(errors)} error(s): {'; '.join(error_msgs)}",
            )

        # 6. Create the environment
        env_created = self._create_environment(record)

        result: dict[str, Any] = {
            "project_dir": str(self.project_dir),
            "facts_summary": {
                "os": f"{facts.os_name} {facts.os_version}",
                "arch": facts.architecture.value,
                "python": facts.python_version,
                "apple_silicon": facts.is_apple_silicon,
            },
            "intent_summary": {
                "environment_type": intent.environment_type.value,
                "package_managers": [m.value for m in intent.package_managers],
                "dependencies": intent.dependency_count,
                "python_version": intent.python_version_required,
            },
            "resolution_summary": {
                "python_version": record.python_version,
                "package_manager": record.package_manager.value,
                "environment_type": record.environment_type.value,
                "accelerator": record.accelerator_target.value,
                "path": str(record.environment_path),
            },
            "environment_created": env_created,
            "findings": [
                {
                    "rule_id": f.rule_id,
                    "severity": f.severity.value,
                    "message": f.message,
                }
                for f in record.findings
            ],
        }

        logger.info("Initialisation complete: env_created=%s", env_created)
        return result

    # ------------------------------------------------------------------ #
    # Preflight checks
    # ------------------------------------------------------------------ #

    def preflight(self) -> PreflightResult:
        """Run preflight checks before initialisation.

        Returns:
            A PreflightResult with individual check outcomes.
        """
        logger.info("Running preflight checks for %s", self.project_dir)
        result = PreflightResult()
        facts = self.facts
        intent = self.intent

        # Check: valid project directory
        if self.project_dir.is_dir():
            result.checks["project_dir"] = (True, "Valid project directory")
        else:
            result.checks["project_dir"] = (False, "Not a valid directory")
            result.passed = False
            result.errors.append(f"Not a valid directory: {self.project_dir}")

        # Check: Python available
        if facts.python_version != "unknown":
            result.checks["python"] = (
                True,
                f"Python {facts.python_version} at {facts.python_path}",
            )
        else:
            result.checks["python"] = (False, "No Python interpreter found")
            result.passed = False
            result.errors.append("No Python interpreter found on PATH")

        # Check: pip available
        if facts.has_pip:
            result.checks["pip"] = (True, "pip is available")
        else:
            result.checks["pip"] = (False, "pip not found")
            result.warnings.append("pip is not installed; dependency installation may fail")

        # Check: venv available (for venv-based environments)
        if facts.has_venv:
            result.checks["venv"] = (True, "venv module is available")
        else:
            result.checks["venv"] = (False, "venv module not available")
            result.warnings.append(
                "venv module not available; consider installing python3-venv"
            )

        # Check: write permission
        if facts.project_dir_writable:
            result.checks["write_permission"] = (
                True,
                "Project directory is writable",
            )
        else:
            result.checks["write_permission"] = (
                False,
                "Project directory is not writable",
            )
            result.passed = False
            result.errors.append("Cannot write to project directory")

        # Check: network
        if facts.network_available is True:
            result.checks["network"] = (True, "pypi.org is reachable")
        elif facts.network_available is False:
            result.checks["network"] = (False, "pypi.org is not reachable")
            result.warnings.append(
                "No network connectivity; offline installation may be needed"
            )
            if not intent.has_wheelhouse:
                result.warnings.append(
                    "No wheelhouse found for offline installation"
                )
        else:
            result.checks["network"] = (True, "Network not checked")

        # Check: conda if needed
        if intent.environment_type in (EnvironmentType.CONDA, EnvironmentType.MAMBA):
            if facts.has_conda or facts.has_mamba:
                result.checks["conda"] = (True, "Conda/mamba is available")
            else:
                result.checks["conda"] = (False, "Conda/mamba not installed")
                result.passed = False
                result.errors.append(
                    "Project requires conda/mamba but neither is installed"
                )

        # Check: Python version compatibility
        if intent.python_version_required and facts.python_version != "unknown":
            req = self._parse_ver(intent.python_version_required)
            avail = self._parse_ver(facts.python_version)
            if req and avail and req > avail:
                result.checks["python_version"] = (
                    False,
                    f"Need Python {intent.python_version_required}, "
                    f"have {facts.python_version}",
                )
                result.warnings.append(
                    f"Python version mismatch: need {intent.python_version_required}, "
                    f"have {facts.python_version}"
                )
            else:
                result.checks["python_version"] = (
                    True,
                    f"Python {facts.python_version} satisfies "
                    f"{intent.python_version_required}",
                )

        # Check: macOS-specific
        if facts.os_name == "Darwin":
            if not facts.has_xcode_cli:
                result.checks["xcode_cli"] = (
                    False,
                    "Xcode CLI tools not installed",
                )
                result.warnings.append(
                    "Xcode CLI tools not installed; "
                    "native extension compilation may fail"
                )
            else:
                result.checks["xcode_cli"] = (
                    True,
                    "Xcode CLI tools installed",
                )

        logger.info(
            "Preflight complete: passed=%s, warnings=%d, errors=%d",
            result.passed, len(result.warnings), len(result.errors),
        )
        return result

    # ------------------------------------------------------------------ #
    # Command execution
    # ------------------------------------------------------------------ #

    def run_command(
        self,
        command: list[str],
        env_path: Optional[Path] = None,
    ) -> int:
        """Execute a command inside the managed environment.

        If *env_path* is not provided, the current resolution's
        environment path is used (if available).

        Args:
            command: Command and arguments as a list of strings.
            env_path: Override environment path.

        Returns:
            The process exit code.
        """
        resolved_env = env_path
        if resolved_env is None:
            rec = self.resolution
            if rec:
                resolved_env = rec.environment_path
            else:
                logger.warning("No environment path available; running in current shell")
                resolved_env = None

        # Build the environment dict
        env = os.environ.copy()
        if resolved_env is not None:
            bin_dir = resolved_env / "bin"
            if bin_dir.is_dir():
                env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
                env["VIRTUAL_ENV"] = str(resolved_env)

        logger.info(
            "Running command: %s (env=%s)",
            " ".join(command),
            resolved_env or "current",
        )

        try:
            proc = subprocess.run(
                command,
                env=env,
                capture_output=False,
                text=True,
                timeout=600,  # 10-minute timeout for user commands
            )
            return proc.returncode
        except FileNotFoundError as exc:
            logger.error("Command not found: %s", exc)
            return 127
        except subprocess.TimeoutExpired:
            logger.error("Command timed out after 600s: %s", " ".join(command))
            return 124
        except OSError as exc:
            logger.error("Failed to run command: %s", exc)
            return 1

    # ------------------------------------------------------------------ #
    # Repair
    # ------------------------------------------------------------------ #

    def repair(self) -> ResolutionRecord:
        """Repair the project environment.

        Attempts to:
        1. Reload host facts.
        2. Re-discover project intent.
        3. Re-analyse and re-resolve.
        4. Recreate the environment if needed.

        Returns:
            The new ResolutionRecord.
        """
        logger.info("Repairing environment for %s", self.project_dir)

        # Clear cached state
        self._facts = None
        self._intent = None
        self._resolution = None

        # Remove existing environment if present
        old_record = ResolutionManager.from_saved(self.project_dir)
        if old_record and old_record.environment_path.is_dir():
            logger.info(
                "Removing existing environment at %s",
                old_record.environment_path,
            )
            shutil.rmtree(old_record.environment_path, ignore_errors=True)

        # Re-initialise
        result = self.initialize()
        record = self._resolution
        if record is None:
            raise BrokenEnvironmentError(
                env_path=str(self.project_dir),
                reason="Repair failed: could not create resolution",
            )

        logger.info("Repair complete")
        return record

    # ------------------------------------------------------------------ #
    # Health check
    # ------------------------------------------------------------------ #

    def health_check(self) -> HealthReport:
        """Generate a health report for the current project environment.

        Returns:
            A HealthReport with detailed status information.
        """
        report = HealthReport()
        rec = self.resolution

        if rec is None:
            report.status = HealthStatus.UNKNOWN
            report.checks["resolution"] = (
                False,
                "No resolution found; run initialise first",
            )
            return report

        report.environment_path = rec.environment_path
        env_path = rec.environment_path

        # Check environment directory exists
        if env_path.is_dir():
            report.checks["env_dir"] = (True, "Environment directory exists")
        else:
            report.checks["env_dir"] = (False, "Environment directory missing")
            report.status = HealthStatus.UNHEALTHY
            return report

        # Check Python binary
        if sys.platform == "win32":
            python_bin = env_path / "Scripts" / "python.exe"
            pip_bin = env_path / "Scripts" / "pip.exe"
        else:
            python_bin = env_path / "bin" / "python"
            pip_bin = env_path / "bin" / "pip"

        if python_bin.is_file():
            try:
                proc = subprocess.run(
                    [str(python_bin), "--version"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                version = proc.stdout.strip() or proc.stderr.strip()
                report.python_ok = proc.returncode == 0
                report.checks["python"] = (
                    report.python_ok,
                    f"Python at {python_bin}: {version}"
                    if report.python_ok
                    else f"Python failed: {proc.stderr.strip()}",
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                report.checks["python"] = (False, str(exc))
        else:
            report.checks["python"] = (False, f"Python binary not found: {python_bin}")

        # Check pip
        if pip_bin.is_file():
            try:
                proc = subprocess.run(
                    [str(pip_bin), "--version"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                report.pip_ok = proc.returncode == 0
                report.checks["pip"] = (
                    report.pip_ok,
                    f"pip: {proc.stdout.strip()}"
                    if report.pip_ok
                    else f"pip failed: {proc.stderr.strip()}",
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                report.checks["pip"] = (False, str(exc))
        else:
            report.checks["pip"] = (False, f"pip binary not found: {pip_bin}")

        # Check installed dependencies
        report.dependencies_ok = self._check_dependencies(report, python_bin)

        # Check for the resolution file
        res_file = self.project_dir / _ENVGUARD_DIR / "resolution.json"
        report.checks["resolution_file"] = (
            res_file.is_file(),
            str(res_file) if res_file.is_file() else "Resolution file missing",
        )

        # Determine overall status
        all_ok = all(ok for ok, _ in report.checks.values())
        any_fail = any(not ok for ok, _ in report.checks.values())

        if all_ok:
            report.status = HealthStatus.HEALTHY
        elif any_fail:
            # Distinguish degraded from unhealthy
            critical_fails = [
                ok for k, (ok, _) in report.checks.items()
                if k in ("env_dir", "python")
            ]
            report.status = (
                HealthStatus.UNHEALTHY
                if any(not ok for ok in critical_fails)
                else HealthStatus.DEGRADED
            )

        logger.info("Health check: %s", report.status.value)
        return report

    def _check_dependencies(
        self, report: HealthReport, python_bin: Path
    ) -> bool:
        """Check whether project dependencies are installed.

        Updates the report's missing_packages and checks dict.
        """
        intent = self.intent
        all_deps = intent.dependencies + intent.dev_dependencies
        if not all_deps:
            report.checks["dependencies"] = (True, "No dependencies declared")
            return True

        # Extract package names from dependency specs
        pkg_names: list[str] = []
        for dep in all_deps:
            # Strip version specifiers
            name = dep.split(">")[0].split("<")[0].split("=")[0].split("~")[0]
            name = name.split("[")[0].strip()
            # Handle extras like "package[extra]"
            if name and name not in pkg_names:
                pkg_names.append(name)

        if not pkg_names:
            report.checks["dependencies"] = (True, "No parseable dependency names")
            return True

        # Use pip list to check
        missing: list[str] = []
        try:
            proc = subprocess.run(
                [str(python_bin), "-m", "pip", "list", "--format=json"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if proc.returncode == 0:
                import json as _json
                try:
                    installed = _json.loads(proc.stdout)
                    installed_names = {
                        p["name"].lower().replace("-", "_")
                        for p in installed
                    }
                    for pkg in pkg_names:
                        normalised = pkg.lower().replace("-", "_")
                        if normalised not in installed_names:
                            missing.append(pkg)
                except (_json.JSONDecodeError, KeyError):
                    report.checks["dependencies"] = (
                        False,
                        "Could not parse pip list output",
                    )
                    return False
            else:
                report.checks["dependencies"] = (
                    False,
                    f"pip list failed: {proc.stderr.strip()}",
                )
                return False
        except (OSError, subprocess.TimeoutExpired) as exc:
            report.checks["dependencies"] = (False, str(exc))
            return False

        report.missing_packages = missing
        ok = len(missing) == 0
        if ok:
            report.checks["dependencies"] = (
                True,
                f"All {len(pkg_names)} dependencies installed",
            )
        else:
            report.checks["dependencies"] = (
                False,
                f"Missing {len(missing)} of {len(pkg_names)} packages: "
                f"{', '.join(missing[:5])}"
                + (f" ... (+{len(missing)-5} more)" if len(missing) > 5 else ""),
            )
        return ok

    # ------------------------------------------------------------------ #
    # Freeze
    # ------------------------------------------------------------------ #

    def freeze(self) -> dict[str, Any]:
        """Capture the current environment state.

        Produces a snapshot of installed packages, Python version,
        and environment metadata suitable for reproducibility.

        Returns:
            A dict containing the frozen state.
        """
        logger.info("Freezing environment state for %s", self.project_dir)
        rec = self.resolution
        facts = self.facts

        frozen: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "project_dir": str(self.project_dir),
            "host": {
                "os": f"{facts.os_name} {facts.os_version}",
                "architecture": facts.architecture.value,
                "python": facts.python_version,
                "apple_silicon": facts.is_apple_silicon,
            },
            "environment": None,
            "packages": [],
        }

        env_path = rec.environment_path if rec else None
        if env_path and env_path.is_dir():
            python_bin = (
                env_path / "bin" / "python"
                if sys.platform != "win32"
                else env_path / "Scripts" / "python.exe"
            )

            if python_bin.is_file():
                frozen["environment"] = {
                    "path": str(env_path),
                    "exists": True,
                }

                # Get pip freeze output
                pip_bin = (
                    env_path / "bin" / "pip"
                    if sys.platform != "win32"
                    else env_path / "Scripts" / "pip.exe"
                )
                if pip_bin.is_file():
                    try:
                        proc = subprocess.run(
                            [str(pip_bin), "freeze"],
                            capture_output=True,
                            text=True,
                            timeout=30,
                        )
                        if proc.returncode == 0:
                            frozen["packages"] = [
                                line.strip()
                                for line in proc.stdout.splitlines()
                                if line.strip()
                            ]
                    except (OSError, subprocess.TimeoutExpired) as exc:
                        frozen["packages_error"] = str(exc)

                # Python version in env
                try:
                    proc = subprocess.run(
                        [str(python_bin), "--version"],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    frozen["environment"]["python_version"] = (
                        proc.stdout.strip() or proc.stderr.strip()
                    )
                except (OSError, subprocess.TimeoutExpired):
                    pass

                # Get pip list as JSON for richer data
                try:
                    proc = subprocess.run(
                        [str(python_bin), "-m", "pip", "list", "--format=json"],
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    if proc.returncode == 0:
                        import json as _json
                        frozen["packages_detailed"] = _json.loads(proc.stdout)
                except Exception:
                    pass
            else:
                frozen["environment"] = {"path": str(env_path), "exists": False}
        else:
            frozen["environment"] = {
                "path": str(env_path) if env_path else "none",
                "exists": False,
            }

        # Save freeze to disk
        envguard_dir = self.project_dir / _ENVGUARD_DIR
        try:
            envguard_dir.mkdir(parents=True, exist_ok=True)
            freeze_file = envguard_dir / "freeze.json"
            freeze_file.write_text(
                json.dumps(frozen, indent=2, default=str),
                encoding="utf-8",
            )
            logger.info("Freeze saved to %s", freeze_file)
        except OSError as exc:
            logger.warning("Could not save freeze: %s", exc)

        return frozen

    # ------------------------------------------------------------------ #
    # Status
    # ------------------------------------------------------------------ #

    def status(self) -> dict[str, Any]:
        """Get the current project status.

        Returns:
            A dict summarising the current state of the project.
        """
        rec = self.resolution
        facts = self.facts

        status: dict[str, Any] = {
            "project_dir": str(self.project_dir),
            "initialized": rec is not None,
            "host": {
                "os": f"{facts.os_name} {facts.os_version}",
                "architecture": facts.architecture.value,
                "python": facts.python_version,
                "apple_silicon": facts.is_apple_silicon,
                "rosetta": facts.is_rosetta,
                "shell": facts.shell.value,
                "xcode_cli": facts.has_xcode_cli,
                "network": facts.network_available,
            },
        }

        if rec:
            env_path = rec.environment_path
            status["resolution"] = {
                "id": rec.id,
                "python_version": rec.python_version,
                "package_manager": rec.package_manager.value,
                "environment_type": rec.environment_type.value,
                "accelerator": rec.accelerator_target.value,
                "path": str(env_path),
                "created_at": rec.created_at,
                "env_exists": env_path.is_dir(),
                "findings_count": len(rec.findings),
                "errors": [
                    f.message
                    for f in rec.findings
                    if f.severity == FindingSeverity.ERROR
                ],
                "warnings": [
                    f.message
                    for f in rec.findings
                    if f.severity == FindingSeverity.WARNING
                ],
            }
        else:
            status["resolution"] = None

        # Quick health summary
        if rec and rec.environment_path.is_dir():
            health = self.health_check()
            status["health"] = {
                "status": health.status.value,
                "python_ok": health.python_ok,
                "pip_ok": health.pip_ok,
                "dependencies_ok": health.dependencies_ok,
                "missing_packages": len(health.missing_packages),
            }
        else:
            status["health"] = None

        return status

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _create_environment(self, record: ResolutionRecord) -> bool:
        """Create the environment described by a resolution.

        Args:
            record: The resolution describing the environment.

        Returns:
            True if the environment was created successfully.
        """
        env_path = record.environment_path

        # Check if it already exists
        if env_path.is_dir():
            logger.info(
                "Environment already exists at %s – skipping creation",
                env_path,
            )
            return True

        plan = record.plan
        steps = plan.get("steps", [])

        for i, step in enumerate(steps):
            action = step.get("action", "")
            description = step.get("description", "")
            command = step.get("command", "")

            logger.info("Step %d/%d: %s", i + 1, len(steps), description)

            try:
                # Split the command for subprocess
                # Handle quoted arguments
                cmd_parts = self._parse_shell_command(command)
                if not cmd_parts:
                    logger.warning("Skipping empty command for step: %s", action)
                    continue

                proc = subprocess.run(
                    cmd_parts,
                    capture_output=True,
                    text=True,
                    timeout=300,
                )

                if proc.returncode != 0:
                    logger.error(
                        "Step %d failed (exit code %d): %s\nstdout: %s\nstderr: %s",
                        i + 1, proc.returncode, description,
                        proc.stdout[-500:] if proc.stdout else "",
                        proc.stderr[-500:] if proc.stderr else "",
                    )
                    raise BrokenEnvironmentError(
                        env_path=str(env_path),
                        reason=f"Step {i+1} failed with exit code {proc.returncode} ({action})",
                    )

                logger.debug("Step %d completed successfully", i + 1)

            except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
                logger.error("Step %d error: %s", i + 1, exc)
                raise BrokenEnvironmentError(
                    env_path=str(env_path),
                    reason=f"Step {i+1} error: {exc}",
                ) from exc

        # Verify the environment was created
        if env_path.is_dir():
            logger.info("Environment created at %s", env_path)
            return True

        logger.error("Environment directory not found after creation: %s", env_path)
        return False

    @staticmethod
    def _parse_shell_command(command: str) -> list[str]:
        """Parse a shell command string into a list of arguments.

        Handles simple quoting with single and double quotes.

        Args:
            command: A shell command string.

        Returns:
            A list of argument strings.
        """
        import shlex
        try:
            return shlex.split(command)
        except ValueError:
            # Fall back to simple split
            return command.split()

    @staticmethod
    def _parse_ver(version_str: str) -> Optional[tuple[int, ...]]:
        """Parse a version string into a comparable tuple.

        Args:
            version_str: A version-like string.

        Returns:
            A tuple of ints, or None.
        """
        import re as _re
        match = _re.match(r"(\d+)\.(\d+)", version_str.strip())
        if match:
            return (int(match.group(1)), int(match.group(2)))
        return None
