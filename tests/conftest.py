# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""Shared test fixtures for the envguard test suite."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from envguard.models import (
    AcceleratorTarget,
    Architecture,
    EnvironmentType,
    FindingSeverity,
    HostFacts,
    PackageManager,
    PermissionStatus,
    ProjectIntent,
    RepairAction,
    RuleFinding,
    ShellType,
)

# ---------------------------------------------------------------------------
# HostFacts fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def macos_host_facts() -> HostFacts:
    """Return a HostFacts instance mimicking an Apple Silicon Mac."""
    return HostFacts(
        os_name="Darwin",
        os_version="14.4",
        os_release="23.4.0",
        architecture=Architecture.ARM64,
        is_apple_silicon=True,
        is_rosetta=False,
        python_version="3.11.8",
        python_path="/usr/bin/python3",
        has_pip=True,
        has_venv=True,
        has_conda=False,
        has_mamba=False,
        is_native_python=True,
        shell=ShellType.ZSH,
        shell_type=ShellType.ZSH,
        has_xcode_cli=True,
        network_available=True,
        is_macos=True,
        username="testuser",
        home_dir=Path("/Users/testuser"),
        mps_available=True,
        launch_agent_write=PermissionStatus.GRANTED,
        subprocess_execution=PermissionStatus.GRANTED,
        network_access=PermissionStatus.GRANTED,
        shell_rc_write=PermissionStatus.GRANTED,
    )


@pytest.fixture
def intel_host_facts() -> HostFacts:
    """Return a HostFacts instance mimicking an Intel Mac."""
    return HostFacts(
        os_name="Darwin",
        os_version="13.6",
        os_release="22.6.0",
        architecture=Architecture.X86_64,
        is_apple_silicon=False,
        is_rosetta=False,
        python_version="3.10.13",
        python_path="/usr/bin/python3",
        has_pip=True,
        has_venv=True,
        has_conda=True,
        has_mamba=False,
        is_native_python=True,
        shell=ShellType.BASH,
        shell_type=ShellType.BASH,
        has_xcode_cli=True,
        network_available=True,
        is_macos=True,
        username="inteluser",
        home_dir=Path("/Users/inteluser"),
    )


@pytest.fixture
def rosetta_host_facts() -> HostFacts:
    """Return HostFacts for x86_64 Python running under Rosetta on ARM."""
    return HostFacts(
        os_name="Darwin",
        os_version="14.4",
        os_release="23.4.0",
        architecture=Architecture.ARM64,
        is_apple_silicon=True,
        is_rosetta=True,
        python_version="3.11.8",
        python_path="/usr/bin/python3",
        has_pip=True,
        has_venv=True,
        is_native_python=False,
        shell=ShellType.ZSH,
        shell_type=ShellType.ZSH,
        is_macos=True,
    )


@pytest.fixture
def offline_host_facts() -> HostFacts:
    """Return HostFacts with no network access."""
    facts = macos_host_facts()
    facts.network_available = False
    facts.network_access = PermissionStatus.DENIED
    return facts


# ---------------------------------------------------------------------------
# ProjectIntent fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def pip_project_intent(tmp_path: Path) -> ProjectIntent:
    """Return a ProjectIntent for a simple pip-based project."""
    return ProjectIntent(
        project_dir=tmp_path,
        environment_type=EnvironmentType.VENV,
        package_managers=[PackageManager.PIP],
        python_version_required=">=3.10",
        dependencies=["requests>=2.28", "numpy>=1.24", "click>=8.1"],
        dependency_count=3,
        has_pyproject_toml=True,
        has_requirements_txt=True,
        project_name="pip-demo",
        accelerator_target=AcceleratorTarget.CPU,
    )


@pytest.fixture
def conda_project_intent(tmp_path: Path) -> ProjectIntent:
    """Return a ProjectIntent for a conda-based project."""
    return ProjectIntent(
        project_dir=tmp_path,
        environment_type=EnvironmentType.CONDA,
        package_managers=[PackageManager.CONDA, PackageManager.PIP],
        python_version_required="3.11",
        dependencies=["numpy>=1.24", "pandas>=2.0"],
        conda_dependencies=["numpy>=1.24", "pandas>=2.0"],
        dependency_count=2,
        has_conda_env_file=True,
        project_name="conda-demo",
        accelerator_target=AcceleratorTarget.CPU,
    )


@pytest.fixture
def cuda_project_intent(tmp_path: Path) -> ProjectIntent:
    """Return a ProjectIntent that requires CUDA (unsupported on macOS)."""
    return ProjectIntent(
        project_dir=tmp_path,
        environment_type=EnvironmentType.VENV,
        package_managers=[PackageManager.PIP],
        dependencies=["torch>=2.0", "torchvision>=0.15"],
        dependency_count=2,
        has_requirements_txt=True,
        has_cuda_requirements=True,
        requires_cuda=True,
        project_name="cuda-demo",
        accelerator_target=AcceleratorTarget.CUDA,
        unsupported_features=["CUDA GPU acceleration is not available on macOS"],
        remediation_hints=["Use AcceleratorTarget.CPU or AcceleratorTarget.MPS instead of CUDA"],
    )


@pytest.fixture
def mps_project_intent(tmp_path: Path) -> ProjectIntent:
    """Return a ProjectIntent for MPS/Apple Silicon GPU."""
    return ProjectIntent(
        project_dir=tmp_path,
        environment_type=EnvironmentType.VENV,
        package_managers=[PackageManager.PIP],
        dependencies=["torch>=2.0", "torchvision>=0.15"],
        dependency_count=2,
        has_pyproject_toml=True,
        has_mps_requirements=True,
        requires_mps=True,
        project_name="mps-demo",
        accelerator_target=AcceleratorTarget.MPS,
    )


# ---------------------------------------------------------------------------
# RuleFinding fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def cuda_finding() -> RuleFinding:
    """Return a CRITICAL finding for CUDA on macOS."""
    return RuleFinding(
        rule_id="CUDA_ON_MACOS",
        severity=FindingSeverity.CRITICAL,
        message="CUDA is not supported as a runtime target on macOS",
        details={"platform": "Darwin", "architecture": "arm64"},
        remediation="Use CPU or Apple MPS (Metal Performance Shaders) instead of CUDA.",
        auto_repairable=True,
        repair_action=RepairAction.RECOMMEND_ALTERNATIVE,
    )


@pytest.fixture
def warning_finding() -> RuleFinding:
    """Return a WARNING finding."""
    return RuleFinding(
        rule_id="ROSETTA_RISK",
        severity=FindingSeverity.WARNING,
        message="Python is running under Rosetta 2 translation",
        details={"python_arch": "x86_64", "host_arch": "arm64"},
        remediation="Install a native arm64 Python for better performance.",
        auto_repairable=False,
    )


# ---------------------------------------------------------------------------
# Project file fixtures
# ---------------------------------------------------------------------------

def _write_toml(path: Path, data: dict) -> None:
    """Write a dict as TOML to *path* using tomli_w."""
    try:
        import tomli_w
        path.write_bytes(tomli_w.dumps(data).encode())
    except ImportError:
        import json
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


@pytest.fixture
def pip_simple_project(tmp_path: Path) -> Path:
    """Create a minimal pip-based project with pyproject.toml and requirements.txt."""
    pyproject = tmp_path / "pyproject.toml"
    _write_toml(pyproject, {
        "build-system": {"requires": ["setuptools>=68.0"], "build-backend": "setuptools.build_meta"},
        "project": {
            "name": "pip-simple",
            "version": "0.1.0",
            "requires-python": ">=3.10",
            "dependencies": ["requests>=2.28", "numpy>=1.24"],
        },
    })
    reqs = tmp_path / "requirements.txt"
    reqs.write_text("requests>=2.28\nnumpy>=1.24\n")
    reqs_dev = tmp_path / "requirements-dev.txt"
    reqs_dev.write_text("pytest>=7.0\n")
    return tmp_path


@pytest.fixture
def requirements_only_project(tmp_path: Path) -> Path:
    """Create a project with only requirements.txt."""
    reqs = tmp_path / "requirements.txt"
    reqs.write_text("flask>=3.0\nredis>=4.5\npython-dotenv>=1.0\n")
    return tmp_path


@pytest.fixture
def conda_project(tmp_path: Path) -> Path:
    """Create a project with environment.yml."""
    env_yml = tmp_path / "environment.yml"
    env_yml.write_text(
        "name: conda-demo\n"
        "channels:\n"
        "  - conda-forge\n"
        "dependencies:\n"
        "  - python=3.11\n"
        "  - numpy>=1.24\n"
        "  - pandas>=2.0\n"
        "  - pip\n"
        "  - pip:\n"
        "    - requests>=2.28\n"
    )
    return tmp_path


@pytest.fixture
def broken_mixed_project(tmp_path: Path) -> Path:
    """Create an intentionally broken mixed pip/conda project."""
    env_yml = tmp_path / "environment.yml"
    env_yml.write_text(
        "name: broken-mixed\n"
        "dependencies:\n"
        "  - numpy>=1.24\n"
    )
    reqs = tmp_path / "requirements.txt"
    reqs.write_text("numpy>=1.26  # conflicts with conda's numpy version\n")
    return tmp_path


@pytest.fixture
def sample_pyproject_toml() -> dict[str, Any]:
    """Return a sample pyproject.toml as a dict."""
    return {
        "build-system": {
            "requires": ["hatchling"],
            "build-backend": "hatchling.build",
        },
        "project": {
            "name": "demo-project",
            "version": "0.2.0",
            "requires-python": ">=3.11",
            "dependencies": ["rich>=13.0", "typer>=0.9", "pydantic>=2.0"],
            "optional-dependencies": {
                "dev": ["pytest>=7.0"],
                "ml": ["scikit-learn>=1.3"],
            },
        },
    }


@pytest.fixture
def sample_environment_yml() -> str:
    """Return a sample environment.yml content."""
    return (
        "name: test-env\n"
        "channels:\n"
        "  - conda-forge\n"
        "  - defaults\n"
        "dependencies:\n"
        "  - python=3.11\n"
        "  - numpy>=1.24\n"
        "  - pip\n"
        "  - pip:\n"
        "    - requests>=2.28\n"
    )


# ---------------------------------------------------------------------------
# Helper fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def envguard_project_dir(tmp_path: Path) -> Path:
    """Create a tmp project with .envguard/ state directory."""
    state_dir = tmp_path / ".envguard"
    state_dir.mkdir()
    (state_dir / "state.json").write_text("{}")
    return tmp_path
