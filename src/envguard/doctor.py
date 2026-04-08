# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""
Doctor module - comprehensive diagnostic checks for the host system
and project environment.

Usage::

    from envguard.doctor import Doctor

    doc = Doctor(project_dir=Path("."))
    results = doc.run()
    print(doc.format_report(results))
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from envguard import (
    MACOS_VERSION_MIN,
    PYPI_URL,
    SUPPORTED_PLATFORMS,
    check_mps_available,
    check_network_connectivity,
    check_xcode_tools,
    detect_active_env,
    detect_project_type,
    get_envguard_dir,
    get_envguard_version,
    get_macos_version,
    get_platform_info,
    is_macos,
    load_json_file,
    resolve_project_dir,
)


class Doctor:
    """Run diagnostic checks against the host and project."""

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(self, project_dir: Path | str = Path.cwd()) -> None:
        project_dir = Path(project_dir)
        try:
            self.project_dir = resolve_project_dir(project_dir)
        except FileNotFoundError:
            self.project_dir = project_dir.resolve()
        self._results: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> dict[str, Any]:
        """Run **all** diagnostic checks and return the results dict.

        Returns a dict with keys ``"checks"`` (list of individual results)
        and ``"summary"`` (overall pass / warning / error counts).
        """
        all_names = self.get_all_checks()
        checks: list[dict[str, Any]] = []
        for name in all_names:
            checks.append(self.run_check(name))

        error_count = sum(1 for c in checks if c["status"] == "error")
        warning_count = sum(1 for c in checks if c["status"] == "warning")
        ok_count = sum(1 for c in checks if c["status"] == "ok")
        skip_count = sum(1 for c in checks if c["status"] == "skip")

        overall = "ok"
        if error_count:
            overall = "error"
        elif warning_count:
            overall = "warning"

        return {
            "project_dir": str(self.project_dir),
            "overall": overall,
            "summary": {
                "ok": ok_count,
                "warning": warning_count,
                "error": error_count,
                "skip": skip_count,
                "total": len(checks),
            },
            "checks": checks,
        }

    def run_check(self, check_name: str) -> dict[str, Any]:
        """Run a single named check and return its result dict.

        Each result dict has::

            {
                "name": <str>,
                "status": "ok" | "warning" | "error" | "skip",
                "message": <str>,
                "detail": <Any>,
            }
        """
        method_map = self._check_methods()
        method = method_map.get(check_name)
        if method is None:
            return {
                "name": check_name,
                "status": "skip",
                "message": f"Unknown check: {check_name}",
                "detail": None,
            }
        try:
            result = method()
        except Exception as exc:
            result = {
                "name": check_name,
                "status": "error",
                "message": f"Check raised an exception: {exc}",
                "detail": {"exception": str(exc)},
            }
        self._results[check_name] = result
        return result

    def get_all_checks(self) -> list[str]:
        """Return a list of all available check names."""
        return list(self._check_methods().keys())

    # ------------------------------------------------------------------
    # Formatting
    # ------------------------------------------------------------------

    def format_report(self, results: dict[str, Any]) -> str:
        """Format the results dict as a human-readable terminal string."""
        lines: list[str] = []
        lines.append(f"envguard doctor - {results['project_dir']}")
        lines.append("=" * 60)

        summary = results["summary"]
        lines.append(
            f"Results: {summary['ok']} OK, "
            f"{summary['warning']} warnings, "
            f"{summary['error']} errors, "
            f"{summary['skip']} skipped"
        )
        lines.append("")

        status_symbols = {
            "ok": "[OK]     ",
            "warning": "[WARNING]",
            "error": "[ERROR]  ",
            "skip": "[SKIP]   ",
        }

        for check in results["checks"]:
            sym = status_symbols.get(check["status"], "[????]   ")
            lines.append(f"  {sym} {check['name']}")
            lines.append(f"          {check['message']}")
            if check.get("detail"):
                detail_str = self._format_detail(check["detail"])
                if detail_str:
                    for dline in detail_str.splitlines():
                        lines.append(f"          {dline}")
            lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def check_host_system(self) -> dict[str, Any]:
        """Check macOS version, architecture, and general platform info."""
        system = platform.system()
        if system not in SUPPORTED_PLATFORMS:
            return {
                "name": "host_system",
                "status": "warning",
                "message": f"Unsupported platform: {system}. envguard is optimised for macOS.",
                "detail": get_platform_info(),
            }

        if not is_macos():
            return {
                "name": "host_system",
                "status": "ok",
                "message": f"Running on {system} {platform.release()} ({platform.machine()})",
                "detail": get_platform_info(),
            }

        ver = get_macos_version()
        if ver is None:
            return {
                "name": "host_system",
                "status": "warning",
                "message": "Could not determine macOS version.",
                "detail": {"macos_version": None},
            }

        if ver < MACOS_VERSION_MIN:
            min_str = ".".join(str(x) for x in MACOS_VERSION_MIN)
            cur_str = ".".join(str(x) for x in ver)
            return {
                "name": "host_system",
                "status": "warning",
                "message": (
                    f"macOS {cur_str} is below recommended minimum {min_str}. "
                    f"Some features may not work."
                ),
                "detail": {"macos_version": cur_str, "minimum": min_str},
            }

        cur_str = ".".join(str(x) for x in ver)
        return {
            "name": "host_system",
            "status": "ok",
            "message": f"macOS {cur_str} on {platform.machine()}",
            "detail": get_platform_info(),
        }

    def check_python_installation(self) -> dict[str, Any]:
        """Check Python version, path, and architecture."""
        py_ver = sys.version_info
        py_path = sys.executable

        if not py_path:
            return {
                "name": "python_installation",
                "status": "error",
                "message": "Could not locate Python executable.",
                "detail": {"python_version": None, "python_path": None},
            }

        py_ver_str = f"{py_ver.major}.{py_ver.minor}.{py_ver.micro}"
        arch = platform.architecture(py_path)[0]
        impl = platform.python_implementation()

        issues: list[str] = []
        if py_ver < (3, 9):
            issues.append(f"Python {py_ver_str} is below the recommended minimum 3.9.")

        status = "error" if issues else "ok"
        message = f"{impl} {py_ver_str} at {py_path} ({arch})"
        if issues:
            message += " - " + "; ".join(issues)

        return {
            "name": "python_installation",
            "status": status,
            "message": message,
            "detail": {
                "python_version": py_ver_str,
                "python_path": py_path,
                "architecture": arch,
                "implementation": impl,
                "issues": issues,
            },
        }

    def check_package_managers(self) -> dict[str, Any]:
        """Check availability of common package managers."""
        managers = {
            "pip": shutil.which("pip"),
            "pip3": shutil.which("pip3"),
            "conda": shutil.which("conda"),
            "mamba": shutil.which("mamba"),
            "uv": shutil.which("uv"),
            "pipx": shutil.which("pipx"),
            "poetry": shutil.which("poetry"),
        }

        found = {name: path for name, path in managers.items() if path}
        not_found = {name: None for name, path in managers.items() if not path}

        status = "ok"
        message = f"Found: {', '.join(found) or 'none'}"
        if not found.get("pip") and not found.get("pip3"):
            status = "warning"
            message += ". pip/pip3 not found - package installation may not work."

        return {
            "name": "package_managers",
            "status": status,
            "message": message,
            "detail": {
                "found": {name: path for name, path in found.items()},
                "missing": list(not_found.keys()),
            },
        }

    def check_xcode_tools(self) -> dict[str, Any]:
        """Check Xcode Command Line Tools status (macOS only)."""
        if not is_macos():
            return {
                "name": "xcode_tools",
                "status": "skip",
                "message": "Xcode tools check is only applicable on macOS.",
                "detail": None,
            }

        result = check_xcode_tools()
        if result["installed"] is True:
            return {
                "name": "xcode_tools",
                "status": "ok",
                "message": f"Xcode Command Line Tools installed: {result['path']}",
                "detail": result,
            }
        elif result["installed"] is False:
            return {
                "name": "xcode_tools",
                "status": "warning",
                "message": result["message"],
                "detail": result,
            }
        else:
            return {
                "name": "xcode_tools",
                "status": "skip",
                "message": result["message"],
                "detail": result,
            }

    def check_network_connectivity(self) -> dict[str, Any]:
        """Check connectivity to PyPI."""
        try:
            reachable = check_network_connectivity(PYPI_URL, timeout=5)
        except Exception:
            reachable = False

        if reachable:
            return {
                "name": "network_connectivity",
                "status": "ok",
                "message": f"Successfully connected to {PYPI_URL}.",
                "detail": {"url": PYPI_URL, "reachable": True},
            }
        return {
            "name": "network_connectivity",
            "status": "warning",
            "message": f"Could not reach {PYPI_URL}. Network may be offline.",
            "detail": {"url": PYPI_URL, "reachable": False},
        }

    def check_permissions(self) -> dict[str, Any]:
        """Check key permission statuses."""
        issues: list[str] = []
        details: dict[str, Any] = {}

        # Check write permission on project directory
        proj_write = os.access(self.project_dir, os.W_OK)
        details["project_dir_writable"] = proj_write
        if not proj_write:
            issues.append(f"No write permission on project directory: {self.project_dir}")

        # Check home directory write permission
        home = Path.home()
        home_write = os.access(home, os.W_OK)
        details["home_writable"] = home_write
        if not home_write:
            issues.append(f"No write permission on home directory: {home}")

        # Check .envguard directory
        eg_dir = get_envguard_dir(self.project_dir)
        if eg_dir.exists():
            eg_write = os.access(eg_dir, os.W_OK)
            details["envguard_dir_writable"] = eg_write
            if not eg_write:
                issues.append(f"No write permission on .envguard directory: {eg_dir}")
        else:
            details["envguard_dir_writable"] = None
            details["envguard_dir_exists"] = False

        # Check /tmp write
        tmp_write = os.access("/tmp", os.W_OK)
        details["tmp_writable"] = tmp_write
        if not tmp_write:
            issues.append("No write permission on /tmp")

        status = "ok" if not issues else "error"
        message = "All permission checks passed." if not issues else "; ".join(issues)

        return {
            "name": "permissions",
            "status": status,
            "message": message,
            "detail": details,
        }

    def check_project_configuration(self) -> dict[str, Any]:
        """Check project file presence and validity."""
        if not self.project_dir.is_dir():
            return {
                "name": "project_configuration",
                "status": "error",
                "message": f"Project directory does not exist: {self.project_dir}",
                "detail": None,
            }

        project_type = detect_project_type(self.project_dir)
        details: dict[str, Any] = {"project_type": project_type}

        files_found: list[str] = []
        marker_files = [
            "pyproject.toml", "setup.py", "setup.cfg",
            "requirements.txt", "Pipfile", "environment.yml",
            "poetry.lock", "pixi.toml",
        ]
        for fname in marker_files:
            if (self.project_dir / fname).exists():
                files_found.append(fname)

        details["marker_files"] = files_found

        # Check .envguard directory
        eg_dir = get_envguard_dir(self.project_dir)
        if eg_dir.exists():
            details["envguard_initialized"] = True
            # Check for state file
            state_file = eg_dir / "state.json"
            if state_file.exists():
                state_data = load_json_file(state_file)
                details["state_file"] = True
                details["state_data"] = state_data
            else:
                details["state_file"] = False
            # Check for config
            config_file = eg_dir / "envguard.toml"
            details["config_file"] = config_file.exists()
        else:
            details["envguard_initialized"] = False

        if not files_found:
            return {
                "name": "project_configuration",
                "status": "warning",
                "message": "No project marker files found (pyproject.toml, requirements.txt, etc.).",
                "detail": details,
            }

        type_str = project_type or "unknown"
        msg = f"Project type: {type_str}. Files: {', '.join(files_found)}."
        if details.get("envguard_initialized"):
            msg += " envguard initialized."
        else:
            msg += " envguard NOT initialized (run `envguard init`)."

        return {
            "name": "project_configuration",
            "status": "ok",
            "message": msg,
            "detail": details,
        }

    def check_environment_health(self) -> dict[str, Any]:
        """Check venv/conda environment status."""
        env_path = detect_active_env(self.project_dir)
        details: dict[str, Any] = {"active_env": env_path}

        if env_path is None:
            return {
                "name": "environment_health",
                "status": "warning",
                "message": "No active virtual environment detected.",
                "detail": details,
            }

        env_p = Path(env_path)
        # Check pyvenv.cfg for venv environments
        pyvenv_cfg = env_p / "pyvenv.cfg"
        details["pyvenv_cfg_exists"] = pyvenv_cfg.exists()

        # Check if the env has a bin directory with python
        bin_dir = env_p / "bin"
        python_bin = bin_dir / "python"
        details["bin_dir_exists"] = bin_dir.exists()
        details["python_bin_exists"] = python_bin.exists()

        # Determine env type
        env_type = "venv"
        conda_meta = env_p / "conda-meta"
        if conda_meta.exists():
            env_type = "conda"
        details["env_type"] = env_type

        # Try to get the env's Python version
        env_py_ver = None
        if python_bin.exists():
            try:
                result = subprocess.run(
                    [str(python_bin), "--version"],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0:
                    env_py_ver = result.stdout.strip()
            except (subprocess.TimeoutExpired, OSError):
                pass
        details["env_python_version"] = env_py_ver

        # Check site-packages
        site_packages = env_p / "lib"
        if site_packages.exists():
            sp_dirs = [d for d in site_packages.iterdir() if d.is_dir()]
            details["site_packages_dirs"] = [d.name for d in sp_dirs]
        else:
            details["site_packages_dirs"] = []

        # Check if the env matches current Python
        current_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        matches = env_py_ver and current_ver in env_py_ver if env_py_ver else None
        details["matches_host_python"] = matches

        status = "ok"
        message = f"Active {env_type} at {env_path}"
        if env_py_ver:
            message += f" (Python {env_py_ver})"
        if matches is False:
            status = "warning"
            message += f" - WARNING: env Python ({env_py_ver}) differs from host ({current_ver})"

        return {
            "name": "environment_health",
            "status": status,
            "message": message,
            "detail": details,
        }

    def check_envguard_installation(self) -> dict[str, Any]:
        """Check that envguard itself is properly installed."""
        version = get_envguard_version()
        details: dict[str, Any] = {
            "version": version,
            "python_path": sys.executable,
            "package_path": Path(__file__).resolve().parent,
        }

        # Verify key imports are available
        import_errors: list[str] = []
        for mod_name in ("typer", "rich"):
            try:
                __import__(mod_name)
                details[f"{mod_name}_available"] = True
            except ImportError:
                import_errors.append(mod_name)
                details[f"{mod_name}_available"] = False

        if import_errors:
            return {
                "name": "envguard_installation",
                "status": "error",
                "message": f"envguard {version} installed but missing dependencies: {', '.join(import_errors)}",
                "detail": details,
            }

        return {
            "name": "envguard_installation",
            "status": "ok",
            "message": f"envguard v{version} installed correctly.",
            "detail": details,
        }

    def check_accelerator_support(self) -> dict[str, Any]:
        """Check for MPS (Apple Silicon GPU) availability. CUDA is explicitly unsupported."""
        details: dict[str, Any] = {
            "platform": platform.system(),
            "machine": platform.machine(),
        }

        if not is_macos():
            return {
                "name": "accelerator_support",
                "status": "skip",
                "message": "Accelerator check only applicable on macOS.",
                "detail": {**details, "cuda_supported": False, "mps_checked": False},
            }

        # Check for Apple Silicon
        is_arm = platform.machine() == "arm64"
        details["is_apple_silicon"] = is_arm

        if not is_arm:
            return {
                "name": "accelerator_support",
                "status": "skip",
                "message": "Not on Apple Silicon - MPS not applicable.",
                "detail": {
                    **details,
                    "cuda_supported": False,
                    "mps_checked": False,
                    "mps_available": False,
                },
            }

        # Check MPS
        mps_available = check_mps_available()
        details["mps_checked"] = True
        details["mps_available"] = mps_available
        details["cuda_supported"] = False

        if mps_available:
            return {
                "name": "accelerator_support",
                "status": "ok",
                "message": "Apple MPS (Metal Performance Shaders) is available for GPU acceleration.",
                "detail": details,
            }

        # MPS not available - could be due to no PyTorch or no MPS support
        try:
            import torch  # noqa: F401
            reason = "PyTorch MPS backend reports unavailable (may need macOS 12.3+)."
        except ImportError:
            reason = "PyTorch not installed - cannot verify MPS. Install PyTorch for GPU acceleration."

        return {
            "name": "accelerator_support",
            "status": "warning",
            "message": f"Apple Silicon detected but MPS not available. {reason}",
            "detail": details,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_methods(self) -> dict[str, Any]:
        """Return a mapping of check_name -> bound method."""
        prefix = "check_"
        methods: dict[str, Any] = {}
        for attr in sorted(dir(self)):
            if attr.startswith(prefix) and callable(getattr(self, attr)):
                # Derive the check name: check_host_system -> host_system
                methods[attr[len(prefix):]] = getattr(self, attr)
        return methods

    @staticmethod
    def _format_detail(detail: Any) -> str:
        """Compact representation of *detail* for terminal display."""
        if detail is None:
            return ""
        if isinstance(detail, str):
            return detail
        if isinstance(detail, dict):
            # Show only first-level string/bool/int values
            parts: list[str] = []
            for k, v in detail.items():
                if isinstance(v, (str, int, float, bool)) or (isinstance(v, (list, tuple)) and len(v) <= 5):
                    parts.append(f"{k}={v}")
                elif isinstance(v, dict) and len(v) <= 3:
                    items = ", ".join(f"{dk}={dv}" for dk, dv in list(v.items())[:3])
                    parts.append(f"{k}={{{items}}}")
            return " | ".join(parts)
        return str(detail)
