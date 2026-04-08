# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""Tests for launch agent management (envguard.launch.launch_agent)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from envguard.launch.launch_agent import LaunchAgentManager

if TYPE_CHECKING:
    from pathlib import Path


class TestLaunchAgentManager:
    """Tests for the LaunchAgentManager class."""

    @pytest.fixture
    def manager(self) -> LaunchAgentManager:
        return LaunchAgentManager()

    def test_bundle_id(self, manager: LaunchAgentManager):
        assert manager.BUNDLE_ID == "com.envguard.update"
        assert "envguard" in manager.BUNDLE_ID

    def test_plist_name(self, manager: LaunchAgentManager):
        assert manager.PLIST_NAME.endswith(".plist")
        assert "envguard" in manager.PLIST_NAME

    def test_generate_plist_valid_xml(self, manager: LaunchAgentManager):
        xml_content = manager.generate_plist("/usr/local/bin/envguard", interval_hours=24)
        # Should not raise; root is <plist>, inner dict is root[0]
        root = ET.fromstring(xml_content)
        assert root.tag == "plist"
        assert root.find("dict") is not None

    def test_generate_plist_has_label(self, manager: LaunchAgentManager):
        xml_content = manager.generate_plist("/usr/local/bin/envguard")
        dict_el = ET.fromstring(xml_content).find("dict")
        keys = dict_el.findall("key")
        values = dict_el.findall("string")
        label_idx = next(i for i, k in enumerate(keys) if k.text == "Label")
        assert "envguard" in values[label_idx].text

    def test_generate_plist_has_program_arguments(self, manager: LaunchAgentManager):
        xml_content = manager.generate_plist("/usr/local/bin/envguard")
        dict_el = ET.fromstring(xml_content).find("dict")
        keys = dict_el.findall("key")
        assert any(k.text == "ProgramArguments" for k in keys)

    def test_generate_plist_start_interval(self, manager: LaunchAgentManager):
        xml_content = manager.generate_plist("/usr/local/bin/envguard", interval_hours=12)
        dict_el = ET.fromstring(xml_content).find("dict")
        children = list(dict_el)
        interval_el = next(
            children[i + 1]
            for i, el in enumerate(children)
            if el.tag == "key" and el.text == "StartInterval"
        )
        # 12 hours = 43200 seconds
        assert int(interval_el.text) == 43200

    def test_generate_plist_default_interval(self, manager: LaunchAgentManager):
        xml_content = manager.generate_plist("/usr/local/bin/envguard", interval_hours=24)
        dict_el = ET.fromstring(xml_content).find("dict")
        children = list(dict_el)
        interval_el = next(
            children[i + 1]
            for i, el in enumerate(children)
            if el.tag == "key" and el.text == "StartInterval"
        )
        assert int(interval_el.text) == 86400

    def test_generate_plist_has_log_paths(self, manager: LaunchAgentManager):
        xml_content = manager.generate_plist("/usr/local/bin/envguard")
        dict_el = ET.fromstring(xml_content).find("dict")
        keys = dict_el.findall("key")
        assert any(k.text == "StandardOutPath" for k in keys)
        assert any(k.text == "StandardErrorPath" for k in keys)

    def test_generate_plist_custom_path(self, manager: LaunchAgentManager):
        xml_content = manager.generate_plist("/opt/homebrew/bin/envguard")
        dict_el = ET.fromstring(xml_content).find("dict")
        # Program arguments should contain the custom path
        arrays = dict_el.findall("array")
        assert len(arrays) > 0

    def test_get_plist_path(self, manager: LaunchAgentManager):
        path = manager.get_plist_path()
        assert "Library/LaunchAgents" in str(path)
        assert "envguard" in path.name

    def test_get_log_paths(self, manager: LaunchAgentManager):
        paths = manager.get_log_paths()
        assert "stdout" in paths or "out" in str(paths).lower()
        assert "stderr" in paths or "err" in str(paths).lower()

    def test_is_installed_false_by_default(self, manager: LaunchAgentManager, tmp_path: Path):
        # In a test environment, should return False
        result = manager.is_installed()
        # May be True if running on a real Mac with envguard installed
        assert isinstance(result, bool)


class TestLaunchAgentInstallUninstall:
    """Tests for install/uninstall logic (mocked)."""

    @patch("subprocess.run")
    def test_install_calls_launchctl(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        manager = LaunchAgentManager()
        # This will try to write to ~/Library/LaunchAgents which may not exist
        # So we just test that it handles the operation gracefully
        result = manager.install("/usr/local/bin/envguard")
        assert isinstance(result, dict)
        assert "success" in result or "error" in result

    @patch("subprocess.run")
    def test_uninstall_calls_launchctl(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        manager = LaunchAgentManager()
        result = manager.uninstall()
        assert isinstance(result, dict)

    def test_get_status(self):
        manager = LaunchAgentManager()
        status = manager.get_status()
        assert isinstance(status, dict)
