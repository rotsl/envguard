# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""Package installation dispatcher.

Detects the active environment type and delegates install/uninstall
operations to the appropriate backend (uv, pip, conda, mamba).
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

from envguard.logging import get_logger
from envguard.models import InstallResult

logger = get_logger(__name__)


def _detect_backend(env_path: Path | None) -> str:
    """Detect the best available package manager for *env_path*.

    Priority: uv > pip (inside venv) > conda > mamba > system pip.
    """
    if shutil.which("uv"):
        return "uv"
    if env_path is not None:
        pip_bin = env_path / "bin" / "pip"
        if pip_bin.exists():
            return "pip"
    if shutil.which("conda"):
        return "conda"
    if shutil.which("mamba"):
        return "mamba"
    if shutil.which("pip"):
        return "pip"
    return "pip"


class Installer:
    """Dispatch package installation to the right backend.

    Args:
        project_dir: Root of the project (used to locate envguard.lock).
        env_path: Path to the virtual / conda environment.  When ``None``
            the installer targets the current active environment.
    """

    def __init__(
        self,
        project_dir: Path,
        env_path: Path | None = None,
    ) -> None:
        self.project_dir = Path(project_dir)
        self.env_path = env_path

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def install(self, packages: list[str]) -> InstallResult:
        """Install *packages* into the managed environment.

        Args:
            packages: PEP 508 requirement strings or bare package names.

        Returns:
            :class:`~envguard.models.InstallResult` with outcome details.
        """
        if not packages:
            return InstallResult(ok=True, backend=_detect_backend(self.env_path))

        backend = _detect_backend(self.env_path)
        logger.info("Installing %d package(s) via %s", len(packages), backend)
        start = time.monotonic()

        if backend == "uv":
            result = self._install_uv(packages)
        elif backend in ("conda", "mamba"):
            result = self._install_conda(packages, backend)
        else:
            result = self._install_pip(packages)

        result.elapsed_seconds = round(time.monotonic() - start, 2)
        result.backend = backend
        return result

    def uninstall(self, packages: list[str]) -> InstallResult:
        """Uninstall *packages* from the managed environment."""
        if not packages:
            return InstallResult(ok=True, backend=_detect_backend(self.env_path))

        backend = _detect_backend(self.env_path)
        cmd = [*self._pip_cmd(), "uninstall", "-y", *packages]
        if backend in ("conda", "mamba"):
            cmd = [backend, "remove", "-y", *packages]

        result = self._run_install_cmd(cmd)
        result.backend = backend
        return result

    def sync_from_lock(self, pinned_packages: list[str]) -> InstallResult:
        """Bring the environment into sync with a list of pinned specifiers.

        Installs missing packages and removes packages that are not in
        *pinned_packages*.

        Args:
            pinned_packages: Fully-pinned requirement strings (``name==version``).
        """
        backend = _detect_backend(self.env_path)
        currently_installed = self._list_installed()

        installed_names = {s.split("==")[0].lower() for s in currently_installed if "==" in s}
        desired_names = {s.split("==")[0].lower() for s in pinned_packages if "==" in s}

        to_install = [p for p in pinned_packages if p.split("==")[0].lower() not in installed_names]
        to_remove = [n for n in installed_names if n not in desired_names]

        result = InstallResult(backend=backend)

        if to_install:
            install_r = self.install(to_install)
            result.packages_installed.extend(install_r.packages_installed)
            result.packages_failed.extend(install_r.packages_failed)
            result.warnings.extend(install_r.warnings)
            if not install_r.ok:
                result.ok = False
                return result

        if to_remove:
            uninstall_r = self.uninstall(to_remove)
            if not uninstall_r.ok:
                result.warnings.append(f"Could not remove: {', '.join(to_remove)}")

        result.ok = True
        return result

    # ------------------------------------------------------------------
    # Backend-specific helpers
    # ------------------------------------------------------------------

    def _pip_cmd(self) -> list[str]:
        """Return the pip executable command for the managed environment."""
        if self.env_path:
            pip_bin = self.env_path / "bin" / "pip"
            if pip_bin.exists():
                return [str(pip_bin)]
        return ["pip"]

    def _install_pip(self, packages: list[str]) -> InstallResult:
        cmd = [*self._pip_cmd(), "install", *packages]
        return self._run_install_cmd(cmd)

    def _install_uv(self, packages: list[str]) -> InstallResult:
        cmd = ["uv", "pip", "install"]
        if self.env_path:
            python_bin = self.env_path / "bin" / "python"
            cmd += ["--python", str(python_bin)]
        cmd += packages
        return self._run_install_cmd(cmd)

    def _install_conda(self, packages: list[str], manager: str) -> InstallResult:
        cmd = [manager, "install", "-y", *packages]
        if self.env_path:
            cmd += ["-p", str(self.env_path)]
        return self._run_install_cmd(cmd)

    def _run_install_cmd(self, cmd: list[str]) -> InstallResult:
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
            )
            ok = proc.returncode == 0
            pkgs_installed = []
            pkgs_failed = []
            warnings = []

            for line in proc.stdout.splitlines():
                if line.startswith("Successfully installed "):
                    pkgs_installed.extend(line.replace("Successfully installed ", "").split())
                elif "WARNING" in line:
                    warnings.append(line.strip())

            if not ok:
                pkgs_failed = [cmd[-1]] if cmd else []
                logger.error("Install failed: %s", proc.stderr.strip()[:500])

            return InstallResult(
                ok=ok,
                packages_installed=pkgs_installed,
                packages_failed=pkgs_failed,
                warnings=warnings,
                stdout=proc.stdout[:2000],
                stderr=proc.stderr[:2000],
            )
        except subprocess.TimeoutExpired:
            return InstallResult(
                ok=False,
                warnings=["Installation timed out after 300 s"],
            )
        except FileNotFoundError as exc:
            return InstallResult(ok=False, warnings=[f"Executable not found: {exc}"])

    def _list_installed(self) -> list[str]:
        """Return list of installed packages as ``name==version`` strings."""
        pip_cmd = self._pip_cmd()
        try:
            proc = subprocess.run(
                [*pip_cmd, "list", "--format=freeze"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if proc.returncode == 0:
                return [line.strip() for line in proc.stdout.splitlines() if "==" in line]
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return []

    def detect_backend(self) -> str:
        """Return the name of the backend that would be used."""
        return _detect_backend(self.env_path)
