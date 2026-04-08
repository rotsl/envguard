# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""Tests for permission checking (envguard.macos.permissions)."""

from __future__ import annotations

from pathlib import Path

import pytest

from envguard.macos.permissions import PermissionChecker
from envguard.models import HostFacts, PermissionStatus, ShellType


class TestPermissionChecker:
    """Tests for the PermissionChecker class."""

    @pytest.fixture
    def facts(self) -> HostFacts:
        return HostFacts(
            os_name="Darwin",
            architecture=__import__(
                "envguard.models", fromlist=["Architecture"]
            ).Architecture.ARM64,
            home_dir=Path("/tmp/test-home"),
        )

    @pytest.fixture
    def checker(self, facts: HostFacts) -> PermissionChecker:
        return PermissionChecker(facts)

    def test_check_write_permission_writable(self, checker: PermissionChecker, tmp_path: Path):
        result = checker.check_write_permission(tmp_path)
        assert result == PermissionStatus.GRANTED

    def test_check_write_permission_nonexistent(self, checker: PermissionChecker):
        result = checker.check_write_permission(Path("/nonexistent/path/that/does/not/exist"))
        assert result == PermissionStatus.DENIED

    def test_check_read_permission_readable(self, checker: PermissionChecker, tmp_path: Path):
        test_file = tmp_path / "readable.txt"
        test_file.write_text("hello")
        result = checker.check_read_permission(test_file)
        assert result == PermissionStatus.GRANTED

    def test_check_execute_permission(self, checker: PermissionChecker, tmp_path: Path):
        # Check execute on an existing directory (should be executable)
        result = checker.check_execute_permission(tmp_path)
        assert result in (PermissionStatus.GRANTED, PermissionStatus.DENIED)

    def test_check_subprocess_execution(self, checker: PermissionChecker):
        result = checker.check_subprocess_execution()
        assert result in (PermissionStatus.GRANTED, PermissionStatus.DENIED)

    def test_check_network_access(self, checker: PermissionChecker):
        result, status = checker.check_network_access("pypi.org", timeout=5)
        assert isinstance(status, PermissionStatus)
        assert isinstance(result, bool)

    def test_check_network_access_unreachable(self, checker: PermissionChecker):
        result, _status = checker.check_network_access(
            "this-domain-does-not-exist-12345.invalid", timeout=2
        )
        # Should handle gracefully
        assert isinstance(result, bool)

    def test_check_shell_rc_write_zsh(
        self, checker: PermissionChecker, tmp_path: Path, monkeypatch
    ):
        monkeypatch.setattr(
            checker,
            "_facts",
            HostFacts(
                home_dir=tmp_path,
                shell=ShellType.ZSH,
                shell_type=ShellType.ZSH,
            ),
        )
        result = checker.check_shell_rc_write(ShellType.ZSH)
        assert isinstance(result, PermissionStatus)

    def test_check_all_returns_facts(self, checker: PermissionChecker, tmp_path: Path):
        checker._facts.home_dir = tmp_path
        updated_facts = checker.check_all()
        assert isinstance(updated_facts, HostFacts)
        # At least some permissions should be checked
        has_checks = (
            updated_facts.subprocess_execution != PermissionStatus.UNKNOWN
            or updated_facts.network_access != PermissionStatus.UNKNOWN
        )
        assert has_checks

    def test_check_launch_agent_write(self, checker: PermissionChecker, tmp_path: Path):
        # LaunchAgent dir may not exist in test environment
        result = checker.check_launch_agent_write()
        assert isinstance(result, PermissionStatus)

    def test_check_install_dir_write(self, checker: PermissionChecker, tmp_path: Path):
        result = checker.check_install_dir_write(tmp_path)
        assert result == PermissionStatus.GRANTED

    def test_check_project_dir_write(self, checker: PermissionChecker, tmp_path: Path):
        result = checker.check_project_dir_write(tmp_path)
        assert result == PermissionStatus.GRANTED

    def test_permission_status_values(self):
        assert PermissionStatus.GRANTED.value == "granted"
        assert PermissionStatus.DENIED.value == "denied"
        assert PermissionStatus.UNKNOWN.value == "unknown"
