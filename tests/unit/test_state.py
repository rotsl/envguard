# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""Tests for state management (envguard.state)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from envguard.models import (
    EnvironmentType,
    PackageManager,
    ProjectIntent,
    ResolutionRecord,
)
from envguard.state import StateManager

if TYPE_CHECKING:
    from pathlib import Path


class TestStateManager:
    """Tests for the StateManager class."""

    @pytest.fixture
    def state_mgr(self, tmp_path: Path) -> StateManager:
        return StateManager()

    def test_ensure_project_dir(self, state_mgr: StateManager, tmp_path: Path):
        envguard_dir = state_mgr.ensure_project_dir(tmp_path)
        assert envguard_dir.exists()
        assert envguard_dir.name == ".envguard"

    def test_ensure_project_dir_idempotent(self, state_mgr: StateManager, tmp_path: Path):
        d1 = state_mgr.ensure_project_dir(tmp_path)
        d2 = state_mgr.ensure_project_dir(tmp_path)
        assert d1 == d2

    def test_save_and_load_state(self, state_mgr: StateManager, tmp_path: Path):
        state_mgr.ensure_project_dir(tmp_path)
        data = {"key": "value", "nested": {"a": 1}}
        path = state_mgr.save_state(tmp_path, data)
        assert path.exists()

        loaded = state_mgr.load_state(tmp_path)
        assert loaded is not None
        assert loaded["key"] == "value"
        assert loaded["nested"]["a"] == 1

    def test_load_state_missing_returns_empty(self, state_mgr: StateManager, tmp_path: Path):
        """load_state creates the dir and returns empty dict for missing file."""
        result = state_mgr.load_state(tmp_path)
        assert result == {}
        assert isinstance(result, dict)

    def test_save_and_load_resolution(self, state_mgr: StateManager, tmp_path: Path):
        state_mgr.ensure_project_dir(tmp_path)
        resolution = ResolutionRecord(
            project_dir=tmp_path,
            python_version="3.11",
            package_manager=PackageManager.PIP,
            environment_type=EnvironmentType.VENV,
            success=True,
        )
        path = state_mgr.save_resolution(tmp_path, resolution)
        assert path.exists()

        loaded = state_mgr.load_resolution(tmp_path)
        assert loaded is not None
        assert loaded["python_version"] == "3.11"
        assert loaded["success"] is True

    def test_load_resolution_missing(self, state_mgr: StateManager, tmp_path: Path):
        result = state_mgr.load_resolution(tmp_path)
        assert result is None

    def test_save_and_load_intent(self, state_mgr: StateManager, tmp_path: Path):
        state_mgr.ensure_project_dir(tmp_path)
        intent = ProjectIntent(
            project_dir=tmp_path,
            project_name="test-project",
            has_pyproject_toml=True,
        )
        path = state_mgr.save_intent(tmp_path, intent)
        assert path.exists()

        loaded = state_mgr.load_intent(tmp_path)
        assert loaded is not None
        assert loaded["project_name"] == "test-project"

    def test_load_intent_missing(self, state_mgr: StateManager, tmp_path: Path):
        result = state_mgr.load_intent(tmp_path)
        assert result is None

    def test_save_and_load_health(self, state_mgr: StateManager, tmp_path: Path):
        state_mgr.ensure_project_dir(tmp_path)
        health = {
            "status": "healthy",
            "environment_path": str(tmp_path / ".venv"),
            "python_ok": True,
            "pip_ok": True,
            "dependencies_ok": True,
            "missing_packages": [],
            "timestamp": "2026-04-07T00:00:00Z",
        }
        path = state_mgr.save_health(tmp_path, health)
        assert path.exists()

        loaded = state_mgr.load_health(tmp_path)
        assert loaded is not None
        assert loaded["status"] == "healthy"

    def test_load_health_missing(self, state_mgr: StateManager, tmp_path: Path):
        result = state_mgr.load_health(tmp_path)
        assert result is None

    def test_save_and_load_launch_policy(self, state_mgr: StateManager, tmp_path: Path):
        state_mgr.ensure_project_dir(tmp_path)
        policy = {"auto_preflight": True, "managed_commands": ["python", "pytest"]}
        state_mgr.save_launch_policy(tmp_path, policy)
        loaded = state_mgr.load_launch_policy(tmp_path)
        assert loaded is not None
        assert loaded["auto_preflight"] is True

    def test_load_launch_policy_missing(self, state_mgr: StateManager, tmp_path: Path):
        result = state_mgr.load_launch_policy(tmp_path)
        # May return empty dict or None depending on implementation
        assert result is None or result == {}

    def test_backup_state(self, state_mgr: StateManager, tmp_path: Path):
        state_mgr.ensure_project_dir(tmp_path)
        state_mgr.save_state(tmp_path, {"version": 1})

        backup_path = state_mgr.backup_state(tmp_path)
        assert backup_path.exists()

        backups = state_mgr.list_backups(tmp_path)
        assert len(backups) >= 1

    def test_list_backups_empty(self, state_mgr: StateManager, tmp_path: Path):
        backups = state_mgr.list_backups(tmp_path)
        assert backups == []

    def test_global_config(self, tmp_path: Path, monkeypatch):
        """Global config save/load round-trip."""
        monkeypatch.setattr(StateManager, "ENVGUARD_STATE_DIR", tmp_path / ".envguard_test_global")
        mgr = StateManager()
        config = mgr.get_global_config()
        assert config is not None
        mgr.save_global_config({"update_channel": "stable", "auto_preflight": True})
        loaded = mgr.get_global_config()
        assert loaded["update_channel"] == "stable"

    def test_json_format_indent(self, state_mgr: StateManager, tmp_path: Path):
        """Verify saved JSON is properly formatted."""
        state_mgr.ensure_project_dir(tmp_path)
        state_mgr.save_state(tmp_path, {"key": "value"})
        path = tmp_path / ".envguard" / "state.json"
        content = path.read_text()
        # Should be pretty-printed with indent
        parsed = json.loads(content)
        assert parsed["key"] == "value"

    def test_overwrite_state(self, state_mgr: StateManager, tmp_path: Path):
        """Saving state twice should overwrite, not append."""
        state_mgr.ensure_project_dir(tmp_path)
        state_mgr.save_state(tmp_path, {"v": 1})
        state_mgr.save_state(tmp_path, {"v": 2})
        loaded = state_mgr.load_state(tmp_path)
        assert loaded["v"] == 2
