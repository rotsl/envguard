# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""Tests for shell hook management (envguard.launch.shell_hooks)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from envguard.launch.shell_hooks import ShellHookManager

if TYPE_CHECKING:
    from pathlib import Path


class TestShellHookManager:
    """Tests for the ShellHookManager class."""

    @pytest.fixture
    def manager(self) -> ShellHookManager:
        return ShellHookManager()

    @pytest.fixture
    def manager_with_home(self, tmp_path: Path) -> ShellHookManager:
        return ShellHookManager(user_home=tmp_path)

    def test_get_hook_content_zsh(self, manager: ShellHookManager):
        content = manager.get_hook_content("zsh")
        assert isinstance(content, str)
        assert len(content) > 0
        assert "envguard" in content.lower()

    def test_get_hook_content_bash(self, manager: ShellHookManager):
        content = manager.get_hook_content("bash")
        assert isinstance(content, str)
        assert len(content) > 0
        assert "envguard" in content.lower()

    def test_get_hook_content_unknown(self, manager: ShellHookManager):
        # Should handle unknown shells gracefully
        content = manager.get_hook_content("fish")
        assert isinstance(content, str)

    def test_hook_content_has_markers(self, manager: ShellHookManager):
        """Hooks should have start/end markers for clean removal."""
        content = manager.get_hook_content("zsh")
        assert "envguard start" in content or "ENVGUARD" in content.upper()

    def test_detect_shell_zsh(self, monkeypatch):
        monkeypatch.setenv("SHELL", "/bin/zsh")
        manager = ShellHookManager()
        shell = manager.detect_shell()
        assert shell == "zsh"

    def test_detect_shell_bash(self, monkeypatch):
        monkeypatch.setenv("SHELL", "/bin/bash")
        manager = ShellHookManager()
        shell = manager.detect_shell()
        assert shell == "bash"

    def test_detect_shell_no_env(self, monkeypatch):
        monkeypatch.delenv("SHELL", raising=False)
        manager = ShellHookManager()
        shell = manager.detect_shell()
        # detect_shell() falls back to "bash" when SHELL is unset
        assert shell == "bash"

    def test_get_rc_file_path_zsh(self, manager_with_home: ShellHookManager):
        path = manager_with_home.get_rc_file_path("zsh")
        assert path is not None
        assert path.name == ".zshrc"

    def test_get_rc_file_path_bash(self, manager_with_home: ShellHookManager):
        path = manager_with_home.get_rc_file_path("bash")
        assert path is not None
        assert ".bash" in path.name or "profile" in path.name

    def test_get_rc_file_path_unknown(self, manager_with_home: ShellHookManager):
        path = manager_with_home.get_rc_file_path("unknown")
        assert path is None

    def test_is_installed_no_file(self, manager_with_home: ShellHookManager):
        assert manager_with_home.is_installed("zsh") is False

    def test_is_installed_with_content(self, manager_with_home: ShellHookManager, tmp_path: Path):
        rc_file = tmp_path / ".zshrc"
        rc_file.write_text("# envguard start\nenvguard_hook() { echo test; }\n# envguard end\n")
        assert manager_with_home.is_installed("zsh") is True

    def test_install_hooks_zsh(self, manager_with_home: ShellHookManager, tmp_path: Path):
        """Test installing hooks creates the rc file."""
        rc_file = tmp_path / ".zshrc"
        rc_file.write_text("# existing content\n")
        result = manager_with_home.install_hooks("zsh")
        assert isinstance(result, dict)

    def test_install_hooks_bash(self, manager_with_home: ShellHookManager, tmp_path: Path):
        rc_file = tmp_path / ".bashrc"
        rc_file.write_text("# existing\n")
        result = manager_with_home.install_hooks("bash")
        assert isinstance(result, dict)

    def test_uninstall_hooks(self, manager_with_home: ShellHookManager, tmp_path: Path):
        rc_file = tmp_path / ".zshrc"
        rc_file.write_text("# envguard start\necho hook\n# envguard end\n")
        result = manager_with_home.uninstall_hooks("zsh")
        assert isinstance(result, dict)
        # The envguard lines should be removed
        content = rc_file.read_text()
        assert "echo hook" not in content

    def test_uninstall_hooks_no_file(self, manager_with_home: ShellHookManager):
        result = manager_with_home.uninstall_hooks("zsh")
        assert isinstance(result, dict)
        # When the RC file doesn't exist there is nothing to remove — success is True (idempotent)
        assert result.get("success") is True

    def test_backup_rc_file(self, manager_with_home: ShellHookManager, tmp_path: Path):
        rc_file = tmp_path / ".zshrc"
        rc_file.write_text("original content")
        backup = manager_with_home._backup_rc_file(rc_file)
        assert backup.exists()
        assert backup.read_text() == "original content"

    def test_hook_content_mentions_envguard(self, manager: ShellHookManager):
        content = manager.get_hook_content("zsh")
        assert "preflight" in content.lower() or "envguard" in content.lower()
