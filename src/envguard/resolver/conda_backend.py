# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""Conda-based resolver backend."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from envguard.resolver.base import BaseResolver

try:
    from envguard.logging import get_logger
except ImportError:
    import logging

    def get_logger(name: str) -> logging.Logger:  # type: ignore[misc]
        return logging.getLogger(name)

try:
    from envguard.models import FindingSeverity, RuleFinding
except ImportError:
    class FindingSeverity:  # type: ignore[no-redef]
        ERROR = "error"
        WARNING = "warning"
        INFO = "info"

    class RuleFinding:  # type: ignore[no-redef]
        def __init__(self, rule: str, message: str, severity: str = "warning"):
            self.rule = rule
            self.message = message
            self.severity = severity

logger = get_logger(__name__)


class CondaBackend(BaseResolver):
    """Resolver backend that delegates to *conda*.

    All operations use ``subprocess`` to invoke the ``conda`` command-line
    tool.  Methods degrade gracefully when conda is not installed.
    """

    # ------------------------------------------------------------------
    # BaseResolver interface
    # ------------------------------------------------------------------

    def resolve(
        self,
        requirements: list[str],
        constraints: list[str] | None = None,
    ) -> list[str]:
        """Resolve dependencies via ``conda create --dry-run --json``."""
        if not self.is_available():
            return list(requirements)

        args = [
            "create",
            "--dry-run",
            "--json",
            "--prefix",
            "/dev/null",
        ]
        if constraints:
            for c in constraints:
                args.extend(["--constraint", c])
        args.extend(requirements)

        try:
            proc = self._run_conda(args, check=False)
            if proc.returncode == 0:
                data = json.loads(proc.stdout)
                packages: list[str] = []
                for pkg in data.get("actions", {}).get("LINK", []):
                    name = pkg.get("name", "")
                    version = pkg.get("version", "")
                    if name:
                        packages.append(f"{name}=={version}" if version else name)
                return packages
            # Conda returned an error - return raw requirements
            logger.debug("conda resolve failed (rc=%d): %s", proc.returncode, proc.stderr)
            return list(requirements)
        except (json.JSONDecodeError, OSError) as exc:
            logger.debug("conda resolve exception: %s", exc)
            return list(requirements)

    def install(self, packages: list[str], env_path: Path) -> bool:
        """Install *packages* into the conda environment at *env_path*.

        If the prefix does not already exist it is created.
        """
        if not packages:
            return True

        if not self.is_available():
            logger.error("conda is not available; cannot install packages")
            return False

        args = ["install", "--prefix", str(env_path), "--yes", *packages]

        try:
            proc = self._run_conda(args, check=False)
            if proc.returncode != 0:
                logger.error("conda install failed: %s", proc.stderr.strip())
                return False
            return True
        except subprocess.TimeoutExpired:
            logger.error("conda install timed out")
            return False

    def list_installed(self, env_path: Path) -> list[str]:
        """Return packages via ``conda list --json``."""
        if not self.is_available():
            return []

        args = ["list", "--prefix", str(env_path), "--json"]
        try:
            proc = self._run_conda(args, check=False)
            if proc.returncode == 0:
                data = json.loads(proc.stdout)
                return [
                    f"{item.get('name', '')}=={item.get('version', '')}"
                    for item in data
                    if item.get("name")
                ]
        except (json.JSONDecodeError, OSError):
            logger.debug("conda list failed for %s", env_path)
        return []

    def validate(self, env_path: Path) -> list[RuleFinding]:
        """Validate environment consistency.

        Conda does not have a direct equivalent of ``pip check``.  This
        method runs ``conda verify`` if available, and also checks for
        packages that were installed by pip inside the conda environment
        (a common source of breakage).
        """
        findings: list[RuleFinding] = []

        if not self.is_available():
            findings.append(
                RuleFinding(
                    rule="conda-validate",
                    message="conda is not installed; cannot validate environment",
                    severity=FindingSeverity.WARNING,
                )
            )
            return findings

        # Try ``conda verify`` (may not exist in all conda variants)
        try:
            proc = self._run_conda(
                ["verify", str(env_path)], check=False
            )
            if proc.returncode != 0 and proc.stderr.strip():
                for line in proc.stderr.strip().splitlines():
                    if line.strip():
                        findings.append(
                            RuleFinding(
                                rule="conda-verify",
                                message=line.strip(),
                                severity=FindingSeverity.ERROR,
                            )
                        )
        except FileNotFoundError:
            pass

        # Check for pip-installed packages that may conflict
        pip_conflicts = self.check_pip_conda_ownership(str(env_path))
        for conflict in pip_conflicts:
            findings.append(
                RuleFinding(
                    rule="conda-pip-conflict",
                    message=(
                        f"Package '{conflict['package']}' is pip-installed in conda env "
                        f"and may conflict with conda-managed dependencies"
                    ),
                    severity=FindingSeverity.WARNING,
                )
            )

        return findings

    def freeze(self, env_path: Path) -> list[str]:
        """Export environment via ``conda env export``."""
        if not self.is_available():
            return []

        args = ["env", "export", "--prefix", str(env_path)]
        try:
            proc = self._run_conda(args, check=False)
            if proc.returncode == 0:
                return [
                    line.strip()
                    for line in proc.stdout.splitlines()
                    if line.strip()
                ]
        except OSError:
            logger.debug("conda env export failed for %s", env_path)
        return []

    def is_available(self) -> bool:
        """Return ``True`` when ``conda`` is found on ``$PATH``."""
        return shutil.which("conda") is not None

    # ------------------------------------------------------------------
    # Conda-specific helpers
    # ------------------------------------------------------------------

    def _run_conda(
        self,
        args: list[str],
        check: bool = True,
    ) -> subprocess.CompletedProcess:
        """Execute a conda subcommand."""
        conda_exe = shutil.which("conda") or "conda"
        return subprocess.run(
            [conda_exe, *args],
            capture_output=True,
            text=True,
            check=check,
            timeout=300,
        )

    def detect_conda_prefix(self) -> Path | None:
        """Detect the root conda installation prefix."""
        if not self.is_available():
            return None
        try:
            proc = self._run_conda(["info", "--json"], check=False)
            if proc.returncode == 0:
                info = json.loads(proc.stdout)
                root_prefix = info.get("root_prefix") or info.get("conda_prefix")
                if root_prefix:
                    return Path(root_prefix)
        except (json.JSONDecodeError, OSError):
            pass
        # Fallback: check common environment variables
        for var in ("CONDA_PREFIX", "CONDA_ROOT"):
            val = os.environ.get(var)
            if val:
                return Path(val)
        return None

    def detect_active_env(self) -> str | None:
        """Return the name of the currently active conda environment."""
        # CONDA_DEFAULT_ENV is set when a conda env is activated
        env_name = os.environ.get("CONDA_DEFAULT_ENV")
        if env_name:
            return env_name
        # Check via conda info
        try:
            proc = self._run_conda(["info", "--json"], check=False)
            if proc.returncode == 0:
                info = json.loads(proc.stdout)
                return info.get("active_prefix_name")
        except (json.JSONDecodeError, OSError):
            pass
        return None

    def export_environment(self, env_name: str) -> dict:
        """Export a named conda environment as a dict.

        Returns a dict with keys ``name``, ``dependencies``, ``prefix``, and
        ``channels``, or an empty dict on failure.
        """
        if not self.is_available():
            return {}

        try:
            proc = self._run_conda(
                ["env", "export", "--name", env_name, "--json"],
                check=False,
            )
            if proc.returncode == 0:
                return json.loads(proc.stdout)
        except (json.JSONDecodeError, OSError):
            pass
        return {}

    def create_environment(
        self,
        env_name: str,
        python_version: str,
        packages: list[str] | None = None,
    ) -> bool:
        """Create a new conda environment.

        Args:
            env_name: Name of the environment.
            python_version: Python version string (e.g. ``"3.11"``).
            packages: Optional list of additional packages to install.

        Returns:
            ``True`` if the environment was created successfully.
        """
        if not self.is_available():
            logger.error("conda is not available; cannot create environment")
            return False

        args = [
            "create",
            "--name",
            env_name,
            f"python={python_version}",
            "--yes",
        ]
        if packages:
            args.extend(packages)

        try:
            proc = self._run_conda(args, check=False)
            if proc.returncode != 0:
                logger.error("conda create failed: %s", proc.stderr.strip())
                return False
            return True
        except subprocess.TimeoutExpired:
            logger.error("conda create timed out")
            return False

    def check_pip_conda_ownership(self, env_name: str) -> list[dict]:
        """Detect packages installed by pip inside a conda environment.

        Conda environments track pip-installed packages in ``conda.json``
        under the environment prefix.  This method cross-references the
        conda package list against packages known to pip.

        Args:
            env_name: Environment name or prefix path.

        Returns:
            A list of dicts, each with ``package`` and ``version`` keys,
            for packages installed by pip that are *not* managed by conda.
        """
        if not self.is_available():
            return []

        conflicts: list[dict] = []

        # Resolve env_name to prefix if it's a name
        prefix = self._resolve_env_prefix(env_name)
        if not prefix:
            return []

        # Get conda-managed packages
        try:
            proc = self._run_conda(
                ["list", "--prefix", str(prefix), "--json"],
                check=False,
            )
            if proc.returncode != 0:
                return []
            all_packages = json.loads(proc.stdout)
        except (json.JSONDecodeError, OSError):
            return []

        # Packages whose ``channel`` is ``pypi`` were installed by pip
        for pkg in all_packages:
            channel = pkg.get("channel", "")
            if channel.lower() == "pypi":
                conflicts.append(
                    {
                        "package": pkg.get("name", ""),
                        "version": pkg.get("version", ""),
                    }
                )

        return conflicts

    def get_conda_package_info(self, package: str) -> dict:
        """Return conda metadata for *package* via ``conda search --info``."""
        if not self.is_available():
            return {"name": package, "found": False}

        try:
            proc = self._run_conda(
                ["search", package, "--info", "--json"],
                check=False,
            )
            if proc.returncode != 0 or not proc.stdout.strip():
                return {"name": package, "found": False}

            data = json.loads(proc.stdout)
            results = data.get(package, data.get(package.lower(), []))
            if not results:
                return {"name": package, "found": False}

            latest = results[0]
            return {
                "name": package,
                "found": True,
                "version": latest.get("version", ""),
                "build": latest.get("build", ""),
                "build_number": latest.get("build_number", 0),
                "channel": latest.get("channel", ""),
                "url": latest.get("url", ""),
                "dependencies": latest.get("depends", []),
            }
        except (json.JSONDecodeError, OSError, KeyError):
            return {"name": package, "found": False}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_env_prefix(self, env_name: str) -> Path | None:
        """Resolve an environment name to its filesystem prefix.

        If *env_name* looks like an absolute path, return it directly.
        Otherwise query conda for the named environment's prefix.
        """
        p = Path(env_name)
        if p.is_absolute() and p.exists():
            return p

        try:
            proc = self._run_conda(
                ["env", "list", "--json"],
                check=False,
            )
            if proc.returncode == 0:
                envs = json.loads(proc.stdout).get("envs", [])
                for env_path in envs:
                    if env_path.rstrip("/").endswith(env_name):
                        return Path(env_path)
        except (json.JSONDecodeError, OSError):
            pass

        return None
