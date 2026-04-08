# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""Health reporter - generate HealthReport for a project environment."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from envguard.logging import get_logger
except ImportError:
    import logging

    def get_logger(name: str) -> logging.Logger:  # type: ignore[misc]
        return logging.getLogger(name)

try:
    from envguard.models import HealthReport, HealthStatus
except ImportError:
    from dataclasses import dataclass, field
    from enum import Enum

    class HealthStatus(str, Enum):  # type: ignore[no-redef]
        HEALTHY = "healthy"
        DEGRADED = "degraded"
        UNHEALTHY = "unhealthy"
        UNKNOWN = "unknown"

    @dataclass
    class HealthReport:  # type: ignore[no-redef]
        status: HealthStatus = HealthStatus.UNKNOWN
        environment_path: Path | None = None
        python_ok: bool = False
        pip_ok: bool = False
        dependencies_ok: bool = False
        missing_packages: list[str] = field(default_factory=list)
        outdated_packages: list[str] = field(default_factory=list)
        checks: dict[str, tuple[bool, str]] = field(default_factory=dict)
        timestamp: str = field(
            default_factory=lambda: datetime.now(timezone.utc).isoformat()
        )

logger = get_logger(__name__)


class HealthReporter:
    """Generate a :class:`HealthReport` for a project environment.

    Parameters
    ----------
    project_dir:
        Root directory of the project.
    env_path:
        Explicit path to the virtual/conda environment.  When *None* the
        reporter auto-detects ``.venv``, ``venv``, or the ``VIRTUAL_ENV``
        environment variable.
    """

    def __init__(
        self,
        project_dir: Path,
        env_path: Path | None = None,
    ) -> None:
        self.project_dir = Path(project_dir).resolve()
        self.env_path = Path(env_path) if env_path else self._detect_env_path()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(
        self,
        facts: Any = None,
        intent: Any = None,
    ) -> HealthReport:
        """Run all health checks and return a :class:`HealthReport`.

        Parameters
        ----------
        facts:
            Optional :class:`~envguard.models.HostFacts` - used to check
            Python version compatibility.
        intent:
            Optional :class:`~envguard.models.ProjectIntent` - used to
            verify that declared dependencies are present.

        Returns
        -------
        HealthReport
            A fully populated health report.
        """
        checks: dict[str, tuple[bool, str]] = {}

        # --- Environment existence ---
        env_exists = self._check_environment_exists()
        checks["environment_exists"] = (
            env_exists,
            "Environment directory found" if env_exists else "Environment directory not found",
        )

        # --- Python interpreter ---
        python_ok = False
        python_version: str | None = None
        if env_exists:
            python_ok, python_version = self._check_python()
        checks["python_ok"] = (
            python_ok,
            f"Python {python_version} functional" if python_ok else "Python interpreter not functional",
        )

        # --- pip ---
        pip_ok = False
        if env_exists:
            pip_ok = self._check_pip()
        checks["pip_ok"] = (
            pip_ok,
            "pip is functional" if pip_ok else "pip is not functional",
        )

        # --- Package count ---
        package_count = 0
        if env_exists and python_ok:
            package_count = self._count_packages()
        checks["package_count"] = (
            package_count >= 0,
            f"{package_count} packages installed",
        )

        # --- Broken packages ---
        broken_packages: list[str] = []
        if env_exists and python_ok:
            broken_packages = self._detect_broken_packages()
        checks["no_broken_packages"] = (
            len(broken_packages) == 0,
            f"{len(broken_packages)} broken package(s)" if broken_packages else "No broken packages",
        )

        # --- Ownership violations ---
        ownership_violations: list[str] = []
        if env_exists:
            ownership_violations = self._detect_ownership_violations()
        checks["no_ownership_violations"] = (
            len(ownership_violations) == 0,
            f"{len(ownership_violations)} ownership violation(s)" if ownership_violations else "No ownership violations",
        )

        # --- Dependency check (if intent provided) ---
        missing_packages: list[str] = []
        dependencies_ok = True
        if intent is not None and env_exists and python_ok:
            missing_packages = self._check_dependencies(intent)
            dependencies_ok = len(missing_packages) == 0
        checks["dependencies_ok"] = (
            dependencies_ok,
            "All dependencies present" if dependencies_ok else f"{len(missing_packages)} missing package(s)",
        )

        # --- Outdated packages ---
        outdated_packages: list[str] = []
        if env_exists and pip_ok:
            outdated_packages = self._detect_outdated_packages()

        # --- Determine overall status ---
        all_passed = all(result for result, _ in checks.values())
        any_critical_failed = not checks.get("environment_exists", (True, ""))[0] or not checks.get("python_ok", (True, ""))[0]

        if all_passed:
            status = HealthStatus.HEALTHY
        elif any_critical_failed:
            status = HealthStatus.UNHEALTHY
        else:
            status = HealthStatus.DEGRADED

        report = HealthReport(
            status=status,
            environment_path=self.env_path,
            python_ok=python_ok,
            pip_ok=pip_ok,
            dependencies_ok=dependencies_ok,
            missing_packages=missing_packages,
            outdated_packages=outdated_packages,
            checks=checks,
        )
        return report

    # ------------------------------------------------------------------
    # Environment detection
    # ------------------------------------------------------------------

    def _detect_env_path(self) -> Path | None:
        """Auto-detect the environment path from common locations."""
        # Check VIRTUAL_ENV first
        virtual_env = os.environ.get("VIRTUAL_ENV")
        if virtual_env:
            venv_path = Path(virtual_env).resolve()
            if venv_path.is_dir():
                return venv_path

        # Check CONDA_PREFIX
        conda_prefix = os.environ.get("CONDA_PREFIX")
        if conda_prefix:
            conda_path = Path(conda_prefix).resolve()
            if conda_path.is_dir():
                return conda_path

        # Check common directory names inside the project
        for name in (".venv", "venv", "env"):
            candidate = self.project_dir / name
            if candidate.is_dir() and (candidate / "pyvenv.cfg").exists():
                return candidate.resolve()

        return None

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_environment_exists(self) -> bool:
        """Return ``True`` if the environment directory exists."""
        if self.env_path is None:
            return False
        return self.env_path.is_dir()

    def _check_python(self) -> tuple[bool, str | None]:
        """Check that the Python interpreter inside the environment works.

        Returns
        -------
        tuple[bool, Optional[str]]
            ``(ok, version_string)`` - *version_string* is ``None`` when
            the check fails.
        """
        if self.env_path is None:
            return False, None

        # Locate the python binary
        if sys.platform == "win32":
            python_bin = self.env_path / "Scripts" / "python.exe"
        else:
            python_bin = self.env_path / "bin" / "python"

        if not python_bin.is_file():
            return False, None

        try:
            result = subprocess.run(
                [str(python_bin), "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                version_str = result.stderr.strip() or result.stdout.strip()
                # "Python 3.11.2" → "3.11.2"
                return True, version_str.replace("Python ", "", 1)
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.debug("Python check failed: %s", exc)

        return False, None

    def _check_pip(self) -> bool:
        """Check that pip is functional inside the environment."""
        if self.env_path is None:
            return False

        if sys.platform == "win32":
            pip_bin = self.env_path / "Scripts" / "pip.exe"
        else:
            pip_bin = self.env_path / "bin" / "pip"

        if not pip_bin.is_file():
            return False

        try:
            result = subprocess.run(
                [str(pip_bin), "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.returncode == 0
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.debug("pip check failed: %s", exc)
            return False

    def _count_packages(self) -> int:
        """Return the number of installed packages in the environment.

        Returns ``0`` when the check cannot be performed.
        """
        if self.env_path is None:
            return 0

        if sys.platform == "win32":
            pip_bin = self.env_path / "Scripts" / "pip.exe"
        else:
            pip_bin = self.env_path / "bin" / "pip"

        if not pip_bin.is_file():
            return 0

        try:
            result = subprocess.run(
                [str(pip_bin), "list", "--format=json", "--disable-pip-version-check"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                import json
                packages = json.loads(result.stdout.strip())
                return len(packages)
        except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
            logger.debug("Package count failed: %s", exc)

        return 0

    def _detect_broken_packages(self) -> list[str]:
        """Detect packages that fail to import or have metadata issues.

        Returns a list of package names that appear broken.
        """
        if self.env_path is None:
            return []

        broken: list[str] = []

        if sys.platform == "win32":
            pip_bin = self.env_path / "Scripts" / "pip.exe"
        else:
            pip_bin = self.env_path / "bin" / "pip"

        if not pip_bin.is_file():
            return broken

        try:
            result = subprocess.run(
                [str(pip_bin), "check", "--disable-pip-version-check"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0 and result.stdout.strip():
                for line in result.stdout.strip().splitlines():
                    # Lines look like: "package-name X.Y.Z has requirement other-package ..."
                    pkg = line.split(" ")[0] if line else ""
                    if pkg and pkg not in broken:
                        broken.append(pkg)
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.debug("Broken package detection failed: %s", exc)

        return broken

    def _detect_ownership_violations(self) -> list[str]:
        """Detect site-packages files not owned by the current user.

        This is primarily relevant on macOS where ``wheel`` may create
        files owned by ``root`` inside a virtual environment.

        Returns a list of file paths (relative to site-packages) that
        have unexpected ownership.
        """
        if self.env_path is None:
            return []

        violations: list[str] = []

        # Locate site-packages
        site_packages = self._find_site_packages()
        if site_packages is None:
            return violations

        try:
            import pwd
            current_uid = os.getuid()
            current_user = pwd.getpwuid(current_uid).pw_name
        except (ImportError, KeyError):
            # pwd is Unix-only; skip on other platforms
            return violations

        try:
            for entry in site_packages.rglob("*"):
                if not entry.is_file():
                    continue
                stat_info = entry.stat()
                try:
                    owner = pwd.getpwuid(stat_info.st_uid).pw_name
                except KeyError:
                    owner = str(stat_info.st_uid)
                if owner != current_user:
                    rel = entry.relative_to(site_packages)
                    violations.append(str(rel))
        except OSError as exc:
            logger.debug("Ownership check failed: %s", exc)

        return violations

    def _find_site_packages(self) -> Path | None:
        """Locate the ``site-packages`` directory inside the environment."""
        if self.env_path is None:
            return None

        if sys.platform == "win32":
            lib_dir = self.env_path / "Lib"
        else:
            lib_dir = self.env_path / "lib"

        if not lib_dir.is_dir():
            return None

        # Search for site-packages under lib/
        for candidate in lib_dir.rglob("site-packages"):
            if candidate.is_dir():
                return candidate

        return None

    # ------------------------------------------------------------------
    # Dependency verification
    # ------------------------------------------------------------------

    def _check_dependencies(self, intent: Any) -> list[str]:
        """Compare declared dependencies against installed packages.

        Parameters
        ----------
        intent:
            A ``ProjectIntent`` (or any object with ``dependencies`` and
            ``dev_dependencies`` list attributes).

        Returns
        -------
        list[str]
            Names of declared packages that are not installed.
        """
        required: list[str] = []
        if hasattr(intent, "dependencies"):
            required.extend(intent.dependencies)
        if hasattr(intent, "dev_dependencies"):
            required.extend(intent.dev_dependencies)

        if not required:
            return []

        # Normalize package names: "package>=1.0" → "package"
        normalized: set[str] = set()
        for dep in required:
            name = dep.split(">=")[0].split("==")[0].split("<=")[0].split("~=")[0].split("!=")[0].split("[")[0].strip()
            if name:
                normalized.add(name.lower())

        # Get installed packages
        installed: set[str] = set()
        if self.env_path is not None:
            if sys.platform == "win32":
                pip_bin = self.env_path / "Scripts" / "pip.exe"
            else:
                pip_bin = self.env_path / "bin" / "pip"

            if pip_bin.is_file():
                try:
                    import json as _json
                    result = subprocess.run(
                        [str(pip_bin), "list", "--format=json", "--disable-pip-version-check"],
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    if result.returncode == 0:
                        for pkg_info in _json.loads(result.stdout.strip()):
                            pkg_name = pkg_info.get("name", "").lower()
                            if pkg_name:
                                installed.add(pkg_name)
                except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
                    logger.debug("Dependency check failed: %s", exc)

        missing = sorted(normalized - installed)
        return missing

    # ------------------------------------------------------------------
    # Outdated packages
    # ------------------------------------------------------------------

    def _detect_outdated_packages(self) -> list[str]:
        """Return a list of outdated package names.

        Uses ``pip list --outdated`` under the hood.
        """
        if self.env_path is None:
            return []

        if sys.platform == "win32":
            pip_bin = self.env_path / "Scripts" / "pip.exe"
        else:
            pip_bin = self.env_path / "bin" / "pip"

        if not pip_bin.is_file():
            return []

        outdated: list[str] = []
        try:
            import json as _json
            result = subprocess.run(
                [str(pip_bin), "list", "--outdated", "--format=json", "--disable-pip-version-check"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode == 0 and result.stdout.strip():
                for pkg_info in _json.loads(result.stdout.strip()):
                    name = pkg_info.get("name", "")
                    if name:
                        outdated.append(name)
        except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
            logger.debug("Outdated package detection failed: %s", exc)

        return sorted(outdated)
