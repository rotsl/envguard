# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""
envguard - macOS-first Python environment orchestration framework.
"""

__version__ = "0.1.0"
__author__ = "Rohan R."

# ---------------------------------------------------------------------------
# Exit codes
# ---------------------------------------------------------------------------
EXIT_OK = 0
EXIT_GENERAL_ERROR = 1
EXIT_PREFLIGHT_FAILED = 2
EXIT_ENV_NOT_FOUND = 3
EXIT_ENV_CORRUPT = 4
EXIT_PERMISSION_DENIED = 5
EXIT_NETWORK_ERROR = 6
EXIT_UNSUPPORTED_PLATFORM = 7
EXIT_CONFIG_ERROR = 8
EXIT_UPDATE_AVAILABLE = 10
EXIT_ALREADY_UP_TO_DATE = 11
EXIT_ROLLBACK_FAILED = 12

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ENVGUARD_DIR_NAME = ".envguard"
STATE_FILENAME = "state.json"
CONFIG_FILENAME = "envguard.toml"
LOCK_FILENAME = "envguard.lock"
SNAPSHOTS_DIR_NAME = "snapshots"
CACHE_DIR_NAME = "cache"
LOG_FILENAME = "envguard.log"

SUPPORTED_ENV_TYPES = ("venv", "conda", "virtualenv", "pipenv")
SUPPORTED_SHELLS = ("zsh", "bash")
SUPPORTED_PLATFORMS = ("Darwin", "Linux")

PYPI_URL = "https://pypi.org"
MACOS_VERSION_MIN = (12, 0)  # Monterey

# ---------------------------------------------------------------------------
# Utility helpers used by CLI and Doctor
# ---------------------------------------------------------------------------

import json
import logging
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional


logger = logging.getLogger("envguard")


def resolve_project_dir(project_dir: Path) -> Path:
    """Resolve and validate a project directory path."""
    project_dir = project_dir.resolve()
    if not project_dir.is_dir():
        raise FileNotFoundError(f"Directory not found: {project_dir}")
    return project_dir


def get_envguard_dir(project_dir: Path) -> Path:
    """Return the .envguard directory for a project."""
    return project_dir / ENVGUARD_DIR_NAME


def ensure_envguard_dir(project_dir: Path) -> Path:
    """Ensure the .envguard directory exists and return its path."""
    eg_dir = get_envguard_dir(project_dir)
    eg_dir.mkdir(parents=True, exist_ok=True)
    return eg_dir


def load_json_file(path: Path, default: Optional[dict] = None) -> Optional[dict]:
    """Load a JSON file, returning *default* if the file doesn't exist."""
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to read %s: %s", path, exc)
        return default


def save_json_file(path: Path, data: dict) -> None:
    """Atomically write a JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def find_executable(name: str) -> Optional[str]:
    """Return the path of an executable on ``$PATH`` or *None*."""
    return shutil.which(name)


def run_command(
    cmd: list[str],
    capture: bool = True,
    timeout: Optional[int] = 30,
    check: bool = False,
) -> subprocess.CompletedProcess:
    """Run a subprocess command with sensible defaults."""
    return subprocess.run(
        cmd,
        capture_output=capture,
        text=True,
        timeout=timeout,
        check=check,
    )


def is_macos() -> bool:
    return platform.system() == "Darwin"


def get_macos_version() -> Optional[tuple[int, ...]]:
    """Return macOS version as tuple, e.g. (14, 2, 1), or None."""
    if not is_macos():
        return None
    try:
        ver = platform.mac_ver()[0]
        return tuple(int(x) for x in ver.split("."))
    except (ValueError, IndexError):
        return None


def get_platform_info() -> dict[str, Any]:
    """Return a dict of host platform information."""
    info: dict[str, Any] = {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python_version": platform.python_version(),
        "python_executable": sys.executable,
        "python_implementation": platform.python_implementation(),
    }
    if is_macos():
        info["macos_version"] = platform.mac_ver()[0]
        info["architecture"] = platform.machine()
    return info


def detect_project_type(project_dir: Path) -> Optional[str]:
    """Detect the project type based on presence of marker files."""
    markers = [
        ("pyproject.toml", "pyproject"),
        ("setup.py", "setuptools"),
        ("setup.cfg", "setuptools-cfg"),
        ("requirements.txt", "requirements-txt"),
        ("Pipfile", "pipenv"),
        ("environment.yml", "conda"),
        ("poetry.lock", "poetry"),
        ("pixi.toml", "pixi"),
    ]
    for filename, ptype in markers:
        if (project_dir / filename).exists():
            return ptype
    return None


def detect_active_env(project_dir: Path) -> Optional[str]:
    """Detect if there's an active virtual environment in the project."""
    venv_markers = [".venv", "venv", "env"]
    for name in venv_markers:
        venv_path = project_dir / name
        if venv_path.is_dir():
            # Check for pyvenv.cfg marker
            if (venv_path / "pyvenv.cfg").exists():
                return str(venv_path)
    # Check VIRTUAL_ENV environment variable
    venv_env = os.environ.get("VIRTUAL_ENV")
    if venv_env:
        venv_p = Path(venv_env)
        if venv_p.exists() and (venv_p / "bin" / "python").is_file():
            return venv_env
    # Check CONDA_PREFIX
    conda_prefix = os.environ.get("CONDA_PREFIX")
    if conda_prefix:
        conda_p = Path(conda_prefix)
        if conda_p.exists() and (conda_p / "bin" / "python").is_file():
            return conda_prefix
    return None


def pip_freeze(venv_path: Optional[str] = None) -> list[str]:
    """Return the output of ``pip freeze`` as a list of lines."""
    if venv_path:
        python_bin = str(Path(venv_path) / "bin" / "python")
        if not Path(python_bin).is_file():
            # Fall back to current interpreter
            python_bin = sys.executable
    else:
        python_bin = sys.executable
    cmd = [python_bin, "-m", "pip", "freeze", "--disable-pip-version-check"]
    result = run_command(cmd, timeout=60)
    if result.returncode == 0:
        return [line.strip() for line in result.stdout.strip().splitlines() if line.strip()]
    return []


def check_network_connectivity(url: str = PYPI_URL, timeout: int = 5) -> bool:
    """Check basic network connectivity using a HEAD request (no deps)."""
    try:
        import urllib.request
        import urllib.error
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status < 500
    except Exception:
        # Last resort: try a simple socket connection
        try:
            import socket
            host = url.replace("https://", "").replace("http://", "").split("/")[0]
            with socket.create_connection((host, 443), timeout=timeout):
                return True
        except Exception:
            return False


def check_xcode_tools() -> dict[str, Any]:
    """Check if Xcode Command Line Tools are installed on macOS."""
    if not is_macos():
        return {"installed": None, "message": "Not applicable (not macOS)"}
    try:
        result = run_command(["xcode-select", "-p"], timeout=10)
        if result.returncode == 0:
            path = result.stdout.strip()
            return {"installed": True, "path": path, "message": f"Found at {path}"}
        else:
            return {"installed": False, "path": None, "message": "Not installed. Run: xcode-select --install"}
    except FileNotFoundError:
        return {"installed": False, "path": None, "message": "xcode-select not found"}
    except subprocess.TimeoutExpired:
        return {"installed": None, "path": None, "message": "Timed out checking xcode-select"}


def check_mps_available() -> bool:
    """Check if Apple Metal Performance Shaders (MPS) is available for PyTorch."""
    try:
        import torch
        return hasattr(torch.backends, "mps") and torch.backends.mps.is_available()
    except ImportError:
        return False


def get_user_home() -> Path:
    return Path.home()


def get_shell_type() -> str:
    """Detect the current shell type."""
    shell_path = os.environ.get("SHELL", "")
    if "zsh" in shell_path:
        return "zsh"
    elif "bash" in shell_path:
        return "bash"
    elif "fish" in shell_path:
        return "fish"
    return shell_path.split("/")[-1] if shell_path else "unknown"


def get_envguard_version() -> str:
    """Return the installed envguard version."""
    return __version__
