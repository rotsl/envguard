# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""Tests for host detection (envguard.detect)."""

from __future__ import annotations

import platform
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from envguard.detect import HostDetector
from envguard.exceptions import EnvguardError
from envguard.models import Architecture, ShellType


class TestHostDetector:
    """Tests for the HostDetector class."""

    def test_detect_os(self):
        detector = HostDetector()
        name, version, release = detector.detect_os()
        assert isinstance(name, str)
        assert isinstance(version, str)
        assert isinstance(release, str)

    def test_detect_architecture(self):
        detector = HostDetector()
        arch, is_apple_silicon, is_rosetta = detector.detect_architecture()
        assert isinstance(arch, Architecture)
        assert isinstance(is_apple_silicon, bool)
        assert isinstance(is_rosetta, bool)
        # On CI (linux), should be x86_64
        if platform.system() == "Linux":
            assert arch in (Architecture.X86_64, Architecture.ARM64)

    @patch("envguard.detect.shutil.which", return_value="/usr/bin/pip3")
    @patch("subprocess.run")
    def test_detect_python(self, mock_run, mock_which):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="3.11.8\narm64\n",
            stderr="",
        )
        detector = HostDetector()
        result = detector.detect_python()
        assert isinstance(result, dict)
        assert "version" in result
        assert "has_pip" in result
        assert "has_venv" in result

    @patch("envguard.detect.shutil.which", side_effect=lambda x: None)
    @patch("subprocess.run")
    def test_detect_python_no_tools(self, mock_run, mock_which):
        mock_run.return_value = MagicMock(returncode=0, stdout="3.10.0\nx86_64\n", stderr="")
        detector = HostDetector()
        result = detector.detect_python()
        assert result["has_pip"] is False
        assert result["has_conda"] is False

    def test_detect_shell_zsh(self, monkeypatch):
        monkeypatch.setenv("SHELL", "/bin/zsh")
        detector = HostDetector()
        assert detector.detect_shell() == ShellType.ZSH

    def test_detect_shell_bash(self, monkeypatch):
        monkeypatch.setenv("SHELL", "/bin/bash")
        detector = HostDetector()
        assert detector.detect_shell() == ShellType.BASH

    def test_detect_shell_unknown(self, monkeypatch):
        monkeypatch.delenv("SHELL", raising=False)
        detector = HostDetector()
        with pytest.raises(EnvguardError):
            detector.detect_shell()

    @patch("envguard.detect.subprocess.run")
    @patch("envguard.detect.sys")
    def test_detect_xcode_cli(self, mock_sys, mock_run):
        mock_sys.platform = "darwin"
        mock_run.return_value = MagicMock(
            returncode=0, stdout="/Library/Developer/CommandLineTools\n", stderr=""
        )
        detector = HostDetector()
        assert detector.detect_xcode_cli() is True

    @patch("envguard.detect.subprocess.run")
    @patch("envguard.detect.sys")
    def test_detect_xcode_cli_not_installed(self, mock_sys, mock_run):
        mock_sys.platform = "darwin"
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
        detector = HostDetector()
        assert detector.detect_xcode_cli() is False

    @patch("envguard.detect.subprocess.run")
    @patch("envguard.detect.sys")
    def test_detect_xcode_cli_with_subprocess(self, mock_sys, mock_run):
        """Test with xcode-select -p returning a path."""
        mock_sys.platform = "darwin"
        mock_run.return_value = MagicMock(
            returncode=0, stdout="/Applications/Xcode.app\n", stderr=""
        )
        detector = HostDetector()
        assert detector.detect_xcode_cli() is True

    @patch("socket.create_connection")
    def test_detect_network_available(self, mock_connect):
        mock_connect.return_value = MagicMock(close=lambda: None)
        detector = HostDetector()
        result = detector.detect_network()
        assert result is True

    @patch("socket.create_connection", side_effect=OSError("connection refused"))
    def test_detect_network_unavailable(self, mock_connect):
        detector = HostDetector()
        result = detector.detect_network()
        assert result is False

    @patch("socket.create_connection", side_effect=OSError("timeout"))
    def test_detect_network_timeout(self, mock_connect):
        detector = HostDetector()
        result = detector.detect_network()
        assert result is False

    def test_detect_user(self):
        detector = HostDetector()
        username, home = detector.detect_user()
        assert isinstance(username, str)
        assert isinstance(home, Path)
        assert home.exists()

    def test_gather_facts(self):
        detector = HostDetector()
        facts = detector.gather_facts()
        assert facts.os_name in ("Darwin", "Linux", "Windows", "unknown")
        assert isinstance(facts.architecture, Architecture)
        assert isinstance(facts.python_version, str)
        assert isinstance(facts.has_pip, bool)


class TestDetectHost:
    """Tests for the detect_host convenience function."""

    def test_detect_host_returns_facts(self):
        from envguard.detect import detect_host

        facts = detect_host()
        assert hasattr(facts, "os_name")
        assert hasattr(facts, "architecture")
        assert hasattr(facts, "python_version")

    def test_detect_host_with_project(self, tmp_path):
        from envguard.detect import detect_host

        facts = detect_host(project_dir=tmp_path)
        assert facts.project_dir is None
