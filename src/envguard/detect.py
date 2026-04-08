# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""Host environment detection for envguard.

Provides the HostDetector class and a convenience function to probe the
runtime environment: operating system, CPU architecture, Python toolchain,
user shell, Xcode CLI tools, network reachability, and filesystem
permissions.
"""

from __future__ import annotations

import os
import platform
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import Optional

from envguard.exceptions import (
    ArchitectureError,
    EnvguardError,
    NetworkUnavailableError,
    SubprocessTimeoutError,
    XcodeError,
)
from envguard.logging import get_logger
from envguard.models import Architecture, HostFacts, ShellType

logger = get_logger("detect")

# ── Helpers ────────────────────────────────────────────────────────────────

_NETWORK_TIMEOUT: float = 5.0
_SUBPROCESS_TIMEOUT: int = 30


def _run(
    cmd: list[str],
    timeout: int = _SUBPROCESS_TIMEOUT,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess and return the CompletedProcess result.

    Raises:
        SubprocessTimeoutError: if the process times out.
        EnvguardError: if the command is not found or OS error occurs.
    """
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        raise EnvguardError(f"Command not found: {' '.join(cmd)}")
    except subprocess.TimeoutExpired:
        raise SubprocessTimeoutError(
            f"Command timed out after {timeout}s: {' '.join(cmd)}"
        )
    except OSError as exc:
        raise EnvguardError(
            f"OS error running {' '.join(cmd)}: {exc}"
        )


# ── HostDetector ───────────────────────────────────────────────────────────


class HostDetector:
    """Detect the characteristics of the current host environment.

    Each ``detect_*`` method probes a specific aspect of the host.  The
    top-level :meth:`detect_all` (or :meth:`gather_facts`) methods
    compose the individual results into a single :class:`HostFacts`
    instance.
    """

    # ------------------------------------------------------------------ #
    # Public entry points
    # ------------------------------------------------------------------ #

    def detect_all(self, project_dir: Optional[Path] = None) -> HostFacts:
        """Orchestrate all detection methods and return complete HostFacts.

        Args:
            project_dir: Optional project directory for permission checks.

        Returns:
            A fully populated HostFacts dataclass.
        """
        logger.info("Starting full host detection")

        facts = HostFacts()

        # OS
        os_name, os_version, os_release = self.detect_os()
        facts.os_name = os_name
        facts.os_version = os_version
        facts.os_release = os_release

        # Architecture
        arch, is_apple_silicon, is_rosetta = self.detect_architecture()
        facts.architecture = arch
        facts.is_apple_silicon = is_apple_silicon
        facts.is_rosetta = is_rosetta

        # Python toolchain
        py_info = self.detect_python()
        facts.python_version = py_info.get("version", "unknown")
        facts.python_path = py_info.get("path", "unknown")
        facts.has_pip = py_info.get("has_pip", False)
        facts.has_venv = py_info.get("has_venv", False)
        facts.has_conda = py_info.get("has_conda", False)
        facts.has_mamba = py_info.get("has_mamba", False)
        facts.is_native_python = py_info.get("is_native", True)
        facts.extra["python_info"] = py_info

        # Shell
        try:
            facts.shell = self.detect_shell()
        except EnvguardError as exc:
            logger.warning("Shell detection failed: %s", exc)
            facts.shell = ShellType.UNKNOWN

        # Xcode CLI
        facts.has_xcode_cli = self.detect_xcode_cli()

        # Network
        try:
            facts.network_available = self.detect_network()
        except NetworkUnavailableError as exc:
            logger.warning("Network detection failed: %s", exc)
            facts.network_available = None

        # User
        username, home_dir = self.detect_user()
        facts.username = username
        facts.home_dir = home_dir

        # Permissions
        perm = self.detect_permissions(project_dir)
        facts.project_dir_writable = perm.get("project_dir_writable", False)
        facts.home_writable = perm.get("home_writable", False)
        facts.permissions_notes = perm.get("notes", [])

        logger.info("Host detection complete: %s %s, Python %s",
                     facts.os_name, facts.architecture.value, facts.python_version)
        return facts

    def gather_facts(self, project_dir: Optional[Path] = None) -> HostFacts:
        """Alias for :meth:`detect_all` – the main entry point."""
        return self.detect_all(project_dir)

    # ------------------------------------------------------------------ #
    # Individual detection methods
    # ------------------------------------------------------------------ #

    def detect_os(self) -> tuple[str, str, str]:
        """Detect the operating system.

        Returns:
            A tuple of (os_name, os_version, os_release).
        """
        try:
            os_name = platform.system()
            os_version = platform.version()
            os_release = platform.release()
            logger.debug("OS detected: %s %s (%s)", os_name, os_version, os_release)
            return os_name, os_version, os_release
        except Exception as exc:
            logger.error("OS detection failed: %s", exc)
            return "unknown", "unknown", "unknown"

    def detect_architecture(self) -> tuple[Architecture, bool, bool]:
        """Detect CPU architecture and Apple Silicon / Rosetta status.

        Returns:
            A tuple of (architecture, is_apple_silicon, is_rosetta).
        """
        try:
            machine = platform.machine().lower()
            # Normalise common aliases
            arch_map = {
                "x86_64": Architecture.X86_64,
                "amd64": Architecture.X86_64,
                "arm64": Architecture.ARM64,
                "aarch64": Architecture.AARCH64,
            }
            arch = arch_map.get(machine, Architecture.UNKNOWN)
            is_apple_silicon = machine in ("arm64", "aarch64")

            # Rosetta check: compare the Python executable architecture with
            # the platform-reported machine.  Under Rosetta on Apple Silicon
            # the platform.machine() reports arm64, but the running binary is
            # x86_64.
            is_rosetta = False
            if sys.platform == "darwin":
                try:
                    proc = _run(["file", sys.executable], timeout=10)
                    output = proc.stdout
                    # Rosetta-translated binaries include "(for architecture x86_64)"
                    # when the host is arm64.
                    if "x86_64" in output and machine == "arm64":
                        is_rosetta = True
                except (EnvguardError, OSError):
                    # Fallback: check if sys.maxsize behaviour hints at 32-bit
                    # or compare uname vs platform.machine()
                    pass

            logger.debug(
                "Architecture: %s, apple_silicon=%s, rosetta=%s",
                arch.value, is_apple_silicon, is_rosetta,
            )
            return arch, is_apple_silicon, is_rosetta
        except Exception as exc:
            logger.error("Architecture detection failed: %s", exc)
            return Architecture.UNKNOWN, False, False

    def detect_python(self) -> dict:
        """Detect Python interpreter capabilities.

        Uses ``shutil.which`` to locate executables and ``subprocess``
        to query version / architecture information.

        Returns:
            A dictionary with keys: version, path, has_pip, has_venv,
            has_conda, has_mamba, is_native.
        """
        info: dict = {
            "version": "unknown",
            "path": "unknown",
            "has_pip": False,
            "has_venv": False,
            "has_conda": False,
            "has_mamba": False,
            "is_native": True,
        }

        # Python path
        python_path = shutil.which("python3") or shutil.which("python")
        if python_path:
            info["path"] = python_path

            # Version
            try:
                proc = _run([python_path, "--version"], timeout=10)
                version_line = proc.stdout.strip() or proc.stderr.strip()
                # "Python 3.11.7" -> "3.11.7"
                if version_line.startswith("Python "):
                    info["version"] = version_line.split(" ", 1)[1]
            except EnvguardError as exc:
                logger.warning("Could not determine Python version: %s", exc)

            # Architecture of the binary
            try:
                proc = _run([python_path, "-c",
                             "import platform; print(platform.machine())"],
                            timeout=10)
                exe_arch = proc.stdout.strip().lower()
                host_arch = platform.machine().lower()
                info["is_native"] = (exe_arch == host_arch)
            except EnvguardError:
                pass

            # venv module check
            try:
                proc = _run([python_path, "-m", "venv", "--help"],
                            timeout=10)
                info["has_venv"] = proc.returncode == 0
            except EnvguardError:
                pass
        else:
            logger.warning("No Python interpreter found on PATH")

        # pip
        pip_path = shutil.which("pip") or shutil.which("pip3")
        if pip_path:
            info["has_pip"] = True

        # conda
        conda_path = shutil.which("conda")
        if conda_path:
            info["has_conda"] = True

        # mamba
        mamba_path = shutil.which("mamba")
        if mamba_path:
            info["has_mamba"] = True

        logger.debug("Python info: %s", info)
        return info

    def detect_shell(self) -> ShellType:
        """Detect the current user's preferred shell.

        Inspects the ``SHELL`` environment variable and maps it to a
        :class:`ShellType`.

        Returns:
            Detected ShellType.

        Raises:
            EnvguardError: If the shell cannot be determined.
        """
        shell_path = os.environ.get("SHELL", "")
        if not shell_path:
            raise EnvguardError("SHELL environment variable not set")

        shell_name = Path(shell_path).stem.lower()

        mapping = {
            "bash": ShellType.BASH,
            "zsh": ShellType.ZSH,
            "fish": ShellType.FISH,
            "sh": ShellType.SH,
            "dash": ShellType.DASH,
            "tcsh": ShellType.TCSH,
            "ksh": ShellType.KSH,
        }

        try:
            result = mapping[shell_name]
        except KeyError:
            raise EnvguardError(f"Unknown shell: {shell_name}")

        logger.debug("Shell detected: %s (%s)", result.value, shell_path)
        return result

    def detect_xcode_cli(self) -> bool:
        """Check whether Xcode Command Line Tools are installed.

        Runs ``xcode-select -p`` and returns True on success.

        Returns:
            True if Xcode CLI tools are available.
        """
        if sys.platform != "darwin":
            logger.debug("Skipping Xcode CLI check on non-macOS")
            return False

        try:
            proc = subprocess.run(
                ["xcode-select", "-p"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            installed = proc.returncode == 0
            if installed:
                logger.debug("Xcode CLI tools found at: %s", proc.stdout.strip())
            else:
                logger.debug("Xcode CLI tools not installed")
            return installed
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            logger.warning("Xcode CLI check failed: %s", exc)
            return False

    def detect_network(self) -> Optional[bool]:
        """Check network connectivity by attempting to reach pypi.org.

        Uses a plain TCP socket connection with a 5-second timeout.

        Returns:
            True if pypi.org is reachable, False otherwise.  Returns None
            if the check could not be performed at all.

        Raises:
            NetworkUnavailableError: On unexpected failures during the check.
        """
        try:
            sock = socket.create_connection(
                ("pypi.org", 443),
                timeout=_NETWORK_TIMEOUT,
            )
            sock.close()
            logger.debug("Network: pypi.org is reachable")
            return True
        except TimeoutError:
            logger.debug("Network: connection to pypi.org timed out")
            return False
        except OSError as exc:
            # Connection refused, DNS failure, etc.
            logger.debug("Network: could not reach pypi.org – %s", exc)
            return False
        except Exception as exc:
            raise NetworkUnavailableError(f"Unexpected network check error: {exc}") from exc

    def detect_user(self) -> tuple[str, Path]:
        """Detect the current user and home directory.

        Returns:
            A tuple of (username, home_dir).
        """
        try:
            username = os.getlogin()
        except OSError:
            username = os.environ.get("USER", os.environ.get("USERNAME", "unknown"))

        home = Path.home()
        logger.debug("User: %s, Home: %s", username, home)
        return username, home

    def detect_permissions(self, project_dir: Optional[Path]) -> dict:
        """Check key permission statuses.

        Args:
            project_dir: Optional project directory to check write access for.

        Returns:
            A dict with keys: project_dir_writable, home_writable, notes.
        """
        result: dict = {
            "project_dir_writable": False,
            "home_writable": False,
            "notes": [],
        }

        # Home directory
        home = Path.home()
        try:
            home_writable = os.access(home, os.W_OK)
            result["home_writable"] = home_writable
            if not home_writable:
                result["notes"].append(f"Home directory is not writable: {home}")
        except OSError as exc:
            result["notes"].append(f"Cannot check home dir permissions: {exc}")

        # Project directory
        if project_dir is not None:
            proj = Path(project_dir).resolve()
            try:
                proj_writable = os.access(proj, os.W_OK)
                result["project_dir_writable"] = proj_writable
                if not proj_writable:
                    result["notes"].append(
                        f"Project directory is not writable: {proj}"
                    )
                # Also check if we can create files in it
                test_file = proj / ".envguard_permission_test"
                try:
                    test_file.write_text("test")
                    test_file.unlink(missing_ok=True)
                except OSError:
                    result["project_dir_writable"] = False
                    result["notes"].append(
                        f"Cannot create files in project directory: {proj}"
                    )
            except OSError as exc:
                result["notes"].append(
                    f"Cannot check project dir permissions: {exc}"
                )

        logger.debug("Permission checks: %s", result)
        return result


# ── Convenience function ───────────────────────────────────────────────────


def detect_host(project_dir: Optional[Path] = None) -> HostFacts:
    """Detect the current host environment and return HostFacts.

    This is a convenience wrapper around :class:`HostDetector`.

    Args:
        project_dir: Optional project directory for permission checks.

    Returns:
        A fully populated HostFacts instance.
    """
    detector = HostDetector()
    return detector.detect_all(project_dir)
