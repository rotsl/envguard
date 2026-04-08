# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""Integration tests for project discovery."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from envguard.models import PackageManager
from envguard.project.discovery import ProjectDiscovery

if TYPE_CHECKING:
    from pathlib import Path


def _write_toml(path: Path, data: dict) -> None:
    """Write a dict structure as TOML (simplified)."""
    lines = []

    def _write_section(obj: dict, indent: int = 0) -> None:
        prefix = "    " * indent
        for key, value in obj.items():
            if isinstance(value, dict):
                lines.append(f"{prefix}[{key}]")
                _write_section(value, indent + 1)
                lines.append("")
            elif isinstance(value, list):
                lines.append(f"{prefix}{key} = {json.dumps(value)}")
            else:
                lines.append(f"{prefix}{key} = {json.dumps(value)}")

    _write_section(data)
    path.write_text("\n".join(lines) + "\n")


class TestProjectDiscovery:
    """Integration tests for discovering project configuration files."""

    # ------------------------------------------------------------------
    # pyproject.toml-based projects
    # ------------------------------------------------------------------

    def test_discover_pyproject_only(self, pip_simple_project: Path):
        discovery = ProjectDiscovery(pip_simple_project)
        intent = discovery.discover()
        assert intent.has_pyproject_toml is True
        assert intent.has_requirements_txt is True
        assert intent.project_name != "unknown"
        assert intent.dependency_count >= 2

    def test_discover_pyproject_deps(self, pyproject_based_project: Path):
        discovery = ProjectDiscovery(pyproject_based_project)
        intent = discovery.discover()
        assert intent.has_pyproject_toml is True
        assert len(intent.dependencies) >= 3

    # ------------------------------------------------------------------
    # requirements.txt-only projects
    # ------------------------------------------------------------------

    def test_discover_requirements_only(self, requirements_only_project: Path):
        discovery = ProjectDiscovery(requirements_only_project)
        intent = discovery.discover()
        assert intent.has_requirements_txt is True
        assert intent.has_pyproject_toml is False
        assert intent.dependency_count >= 2

    # ------------------------------------------------------------------
    # Conda projects
    # ------------------------------------------------------------------

    def test_discover_conda_env(self, conda_project: Path):
        discovery = ProjectDiscovery(conda_project)
        intent = discovery.discover()
        assert intent.has_conda_env_file is True
        assert PackageManager.CONDA in intent.package_managers

    # ------------------------------------------------------------------
    # Broken mixed projects
    # ------------------------------------------------------------------

    def test_discover_broken_mixed(self, broken_mixed_project: Path):
        discovery = ProjectDiscovery(broken_mixed_project)
        intent = discovery.discover()
        assert intent.has_conda_env_file is True
        assert intent.has_requirements_txt is True

    # ------------------------------------------------------------------
    # Empty / no-project directories
    # ------------------------------------------------------------------

    def test_discover_empty_dir(self, tmp_path: Path):
        discovery = ProjectDiscovery(tmp_path)
        intent = discovery.discover()
        assert intent.has_pyproject_toml is False
        assert intent.has_requirements_txt is False
        assert intent.dependency_count == 0

    # ------------------------------------------------------------------
    # .python-version detection
    # ------------------------------------------------------------------

    def test_discover_python_version_file(self, tmp_path: Path):
        (tmp_path / ".python-version").write_text("3.11\n")
        discovery = ProjectDiscovery(tmp_path)
        intent = discovery.discover()
        assert intent.python_version_required is not None or "3.11" in str(intent.extra)

    # ------------------------------------------------------------------
    # Previous envguard state
    # ------------------------------------------------------------------

    def test_discover_previous_state(self, envguard_project_dir: Path):
        discovery = ProjectDiscovery(envguard_project_dir)
        intent = discovery.discover()
        assert intent.has_previous_envguard_state is True

    def test_no_previous_state(self, tmp_path: Path):
        discovery = ProjectDiscovery(tmp_path)
        intent = discovery.discover()
        assert intent.has_previous_envguard_state is False


# We need to define the fixtures used above that create actual project files


@pytest.fixture
def pip_simple_project(tmp_path: Path) -> Path:
    _write_toml(
        tmp_path / "pyproject.toml",
        {
            "build-system": {"requires": ["setuptools"], "build-backend": "setuptools.build_meta"},
            "project": {
                "name": "pip-simple",
                "version": "0.1.0",
                "requires-python": ">=3.10",
                "dependencies": ["requests>=2.28", "numpy>=1.24"],
            },
        },
    )
    (tmp_path / "requirements.txt").write_text("requests>=2.28\nnumpy>=1.24\n")
    return tmp_path


@pytest.fixture
def pyproject_based_project(tmp_path: Path) -> Path:
    _write_toml(
        tmp_path / "pyproject.toml",
        {
            "build-system": {"requires": ["hatchling"], "build-backend": "hatchling.build"},
            "project": {
                "name": "pyproject-demo",
                "version": "0.2.0",
                "requires-python": ">=3.11",
                "dependencies": ["rich>=13.0", "typer>=0.9", "pydantic>=2.0"],
            },
        },
    )
    return tmp_path


@pytest.fixture
def requirements_only_project(tmp_path: Path) -> Path:
    (tmp_path / "requirements.txt").write_text("flask>=3.0\nredis>=4.5\npython-dotenv>=1.0\n")
    return tmp_path


@pytest.fixture
def conda_project(tmp_path: Path) -> Path:
    (tmp_path / "environment.yml").write_text(
        "name: conda-demo\nchannels:\n  - conda-forge\ndependencies:\n  - python=3.11\n  - numpy>=1.24\n  - pip\n"
    )
    return tmp_path


@pytest.fixture
def broken_mixed_project(tmp_path: Path) -> Path:
    (tmp_path / "environment.yml").write_text("name: broken\ndependencies:\n  - numpy>=1.24\n")
    (tmp_path / "requirements.txt").write_text("numpy>=1.26\n")
    return tmp_path


@pytest.fixture
def envguard_project_dir(tmp_path: Path) -> Path:
    (tmp_path / ".envguard").mkdir()
    (tmp_path / ".envguard" / "state.json").write_text("{}")
    return tmp_path
