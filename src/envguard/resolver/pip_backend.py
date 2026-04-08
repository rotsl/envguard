# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""pip-based resolver backend."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from envguard.resolver.base import BaseResolver
from envguard.resolver.wheelcheck import WheelChecker

if TYPE_CHECKING:
    from envguard.models import Architecture, FindingSeverity, RuleFinding

try:
    from packaging import tags as pkg_tags
except ImportError:
    pkg_tags = None  # type: ignore[assignment]

try:
    from packaging.tags import parse_tag
except ImportError:
    parse_tag = None  # type: ignore[assignment]

try:
    from envguard.logging import get_logger
except ImportError:
    import logging

    def get_logger(name: str) -> logging.Logger:  # type: ignore[misc]
        return logging.getLogger(name)

try:
    from envguard.models import (
        Architecture,
        FindingSeverity,
        RuleFinding,
    )
except ImportError:
    # Fallback definitions for standalone use / testing
    class FindingSeverity:  # type: ignore[no-redef]
        ERROR = "error"
        WARNING = "warning"
        INFO = "info"

    class RuleFinding:  # type: ignore[no-redef]
        def __init__(self, rule: str, message: str, severity: str = "warning"):
            self.rule = rule
            self.message = message
            self.severity = severity

    class Architecture:  # type: ignore[no-redef]
        ARM64 = "arm64"
        X86_64 = "x86_64"

logger = get_logger(__name__)


class PipBackend(BaseResolver):
    """Resolver backend that delegates to *pip*.

    All operations are executed via ``subprocess`` calls against the pip
    executable that lives inside the target virtual environment (or the
    system pip as a fallback).
    """

    def __init__(self) -> None:
        self._wheel_checker = WheelChecker()

    # ------------------------------------------------------------------
    # BaseResolver interface
    # ------------------------------------------------------------------

    def resolve(
        self,
        requirements: list[str],
        constraints: list[str] | None = None,
    ) -> list[str]:
        """Resolve dependencies using ``pip install --dry-run``.

        Falls back to returning the input requirements unchanged when dry-run
        is not supported (very old pip versions).
        """
        if not requirements:
            return []

        args = ["install", "--dry-run", "--report", "-"]
        if constraints:
            for c in constraints:
                args.extend(["--constraint", c])
        args.extend(requirements)

        try:
            proc = self._run_pip(args, Path(sys_prefix_fallback()), check=False)
            if proc.returncode == 0:
                report = json.loads(proc.stdout)
                packages: list[str] = []
                for pkg in report.get("install", []):
                    packages.append(
                        f"{pkg['metadata']['name']}=={pkg['metadata']['version']}"
                    )
                return packages
        except Exception:
            logger.debug("pip --dry-run failed, returning raw requirements")

        # Fallback: return the raw requirements
        return list(requirements)

    def install(self, packages: list[str], env_path: Path) -> bool:
        """Install *packages* into the virtual environment at *env_path*."""
        if not packages:
            return True

        pip = self._get_pip_path(env_path)
        args = ["install", *packages]

        try:
            proc = subprocess.run(
                [str(pip), *args],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if proc.returncode != 0:
                logger.error("pip install failed: %s", proc.stderr.strip())
                return False
            return True
        except FileNotFoundError:
            logger.error("pip not found at %s", pip)
            return False
        except subprocess.TimeoutExpired:
            logger.error("pip install timed out after 300s")
            return False

    def list_installed(self, env_path: Path) -> list[str]:
        """Return a list of ``name==version`` strings from ``pip list --format=json``."""
        pip = self._get_pip_path(env_path)
        try:
            proc = subprocess.run(
                [str(pip), "list", "--format=json"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if proc.returncode == 0:
                data = json.loads(proc.stdout)
                return [f"{item['name']}=={item['version']}" for item in data]
        except (FileNotFoundError, json.JSONDecodeError, subprocess.TimeoutExpired):
            logger.debug("pip list failed for %s", env_path)
        return []

    def validate(self, env_path: Path) -> list[RuleFinding]:
        """Run ``pip check`` and parse any dependency issues."""
        pip = self._get_pip_path(env_path)
        findings: list[RuleFinding] = []

        try:
            proc = subprocess.run(
                [str(pip), "check"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if proc.returncode == 0:
                return findings

            for line in proc.stdout.strip().splitlines():
                line = line.strip()
                if not line:
                    continue
                findings.append(
                    RuleFinding(
                        rule="pip-check",
                        message=line,
                        severity=FindingSeverity.ERROR,
                    )
                )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            findings.append(
                RuleFinding(
                    rule="pip-check",
                    message=f"Could not run pip check: {exc}",
                    severity=FindingSeverity.WARNING,
                )
            )

        return findings

    def freeze(self, env_path: Path) -> list[str]:
        """Return pinned requirements via ``pip freeze``."""
        pip = self._get_pip_path(env_path)
        try:
            proc = subprocess.run(
                [str(pip), "freeze"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if proc.returncode == 0:
                return [
                    line.strip()
                    for line in proc.stdout.splitlines()
                    if line.strip()
                ]
        except (FileNotFoundError, subprocess.TimeoutExpired):
            logger.debug("pip freeze failed for %s", env_path)
        return []

    def is_available(self) -> bool:
        """Return ``True`` when ``pip`` is found on ``$PATH``."""
        return shutil.which("pip") is not None

    def check_compatibility(
        self,
        package: str,
        arch: Architecture,
        platform: str,
    ) -> dict:
        """Check binary wheel compatibility via ``pip download --dry-run``."""
        if package.endswith(".whl"):
            return self.check_wheel_compatibility(package, arch)

        # Attempt pip-based platform probe
        plat_map = {
            Architecture.ARM64: "macosx_arm64",
            Architecture.X86_64: "macosx_x86_64",
        }
        target_platform = plat_map.get(arch, platform)

        pip = shutil.which("pip")
        if not pip:
            return {"compatible": True, "package": package, "reason": "pip not available for check"}

        try:
            proc = subprocess.run(
                [pip, "download", "--only-binary=:all:", f"--platform={target_platform}", "--dry-run", package],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if proc.returncode == 0:
                return {"compatible": True, "package": package, "reason": ""}
            return {
                "compatible": False,
                "package": package,
                "reason": proc.stderr.strip() or proc.stdout.strip(),
            }
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return {"compatible": True, "package": package, "reason": "check unavailable"}

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def check_wheel_compatibility(
        self,
        wheel_name: str,
        arch: Architecture,
    ) -> dict:
        """Parse *wheel_name* and verify its platform tags against *arch*."""
        return self._wheel_checker.check_wheel_filename(wheel_name, arch)

    def parse_requirements(self, req_file: Path) -> list[str]:
        """Parse a *requirements.txt* file, stripping comments and blanks."""
        if not req_file.is_file():
            return []

        requirements: list[str] = []
        for line in req_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            # Skip empty lines, comments, and options
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            # Strip inline comments (but not inside URLs)
            if " #" in line and "http" not in line.split(" #")[0]:
                line = line.split(" #")[0].strip()
            requirements.append(line)
        return requirements

    def parse_constraints(self, constraints_file: Path) -> list[str]:
        """Parse a *constraints.txt* file (same format as requirements)."""
        return self.parse_requirements(constraints_file)

    def get_package_info(self, package: str, env_path: Path) -> dict:
        """Return metadata dict for *package* via ``pip show``."""
        pip = self._get_pip_path(env_path)
        try:
            proc = subprocess.run(
                [str(pip), "show", package],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if proc.returncode != 0:
                return {"name": package, "found": False}
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return {"name": package, "found": False}

        info: dict = {"name": package, "found": True}
        for line in proc.stdout.splitlines():
            if ": " not in line:
                continue
            key, _, value = line.partition(": ")
            info[key.lower().replace("-", "_")] = value.strip()
        return info

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_pip_path(self, env_path: Path) -> Path:
        """Return the path to the pip executable inside *env_path*."""
        # Prefer the ``bin`` directory inside the virtualenv
        for candidate in (
            env_path / "bin" / "pip",
            env_path / "bin" / "pip3",
            env_path / "Scripts" / "pip.exe",  # Windows
        ):
            if candidate.exists():
                return candidate
        # Fallback to system pip
        system = shutil.which("pip")
        if system:
            return Path(system)
        return Path("pip")

    def _run_pip(
        self,
        args: list[str],
        env_path: Path,
        check: bool = True,
    ) -> subprocess.CompletedProcess:
        """Run a pip subcommand against the environment's pip."""
        pip = self._get_pip_path(env_path)
        cmd = [str(pip), *args]
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=check,
            timeout=120,
        )


# -----------------------------------------------------------------------
# Module-level helper
# -----------------------------------------------------------------------

def sys_prefix_fallback() -> str:
    """Return the current Python prefix (sys.prefix) or ``'.'``."""
    import sys
    return sys.prefix or "."
