# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""Tests for wheel compatibility checking (envguard.resolver.wheelcheck)."""

from __future__ import annotations

import pytest

from envguard.models import Architecture
from envguard.resolver.wheelcheck import WheelChecker


class TestWheelChecker:
    """Tests for the WheelChecker class."""

    @pytest.fixture
    def checker(self) -> WheelChecker:
        return WheelChecker()

    # ------------------------------------------------------------------
    # Filename parsing
    # ------------------------------------------------------------------

    def test_parse_standard_wheel(self, checker: WheelChecker):
        result = checker.parse_wheel_filename("numpy-1.24.0-cp311-cp311-macosx_11_0_arm64.whl")
        assert result["dist"] == "numpy"
        assert result["version"] == "1.24.0"
        assert result["platform_tag"] == "macosx_11_0_arm64"

    def test_parse_x86_64_wheel(self, checker: WheelChecker):
        result = checker.parse_wheel_filename("pandas-2.0.0-cp311-cp311-macosx_10_9_x86_64.whl")
        assert result["dist"] == "pandas"
        assert result["platform_tag"] == "macosx_10_9_x86_64"

    def test_parse_pure_python_wheel(self, checker: WheelChecker):
        result = checker.parse_wheel_filename("requests-2.31.0-py3-none-any.whl")
        assert result["dist"] == "requests"
        assert result["platform_tag"] == "any"

    def test_parse_wheel_with_build_tag(self, checker: WheelChecker):
        result = checker.parse_wheel_filename("package-1.0-1-cp311-cp311-macosx_11_0_arm64.whl")
        assert result["dist"] == "package"
        assert result["build"] == "1"

    # ------------------------------------------------------------------
    # Pure Python detection
    # ------------------------------------------------------------------

    def test_is_pure_python_any_tag(self, checker: WheelChecker):
        assert checker.is_pure_python_wheel("pkg-1.0-py3-none-any.whl") is True

    def test_is_not_pure_python_arm64(self, checker: WheelChecker):
        assert checker.is_pure_python_wheel("pkg-1.0-cp311-cp311-macosx_11_0_arm64.whl") is False

    def test_is_not_pure_python_x86(self, checker: WheelChecker):
        assert checker.is_pure_python_wheel("pkg-1.0-cp311-cp311-macosx_10_9_x86_64.whl") is False

    # ------------------------------------------------------------------
    # Compatibility checks
    # ------------------------------------------------------------------

    def test_arm64_wheel_on_arm64_host(self, checker: WheelChecker):
        result = checker.check_wheel_filename(
            "numpy-1.24.0-cp311-cp311-macosx_11_0_arm64.whl",
            Architecture.ARM64,
        )
        assert result["compatible"] is True

    def test_x86_64_wheel_on_x86_64_host(self, checker: WheelChecker):
        result = checker.check_wheel_filename(
            "pandas-2.0.0-cp311-cp311-macosx_10_9_x86_64.whl",
            Architecture.X86_64,
        )
        assert result["compatible"] is True

    def test_x86_64_wheel_on_arm64_host(self, checker: WheelChecker):
        """x86_64 wheel should be incompatible on native arm64."""
        result = checker.check_wheel_filename(
            "numpy-1.24.0-cp311-cp311-macosx_10_9_x86_64.whl",
            Architecture.ARM64,
        )
        assert result["compatible"] is False

    def test_arm64_wheel_on_x86_64_host(self, checker: WheelChecker):
        """arm64 wheel should be incompatible on x86_64."""
        result = checker.check_wheel_filename(
            "numpy-1.24.0-cp311-cp311-macosx_11_0_arm64.whl",
            Architecture.X86_64,
        )
        assert result["compatible"] is False

    def test_pure_python_compatible_everywhere(self, checker: WheelChecker):
        result = checker.check_wheel_filename(
            "requests-2.31.0-py3-none-any.whl",
            Architecture.ARM64,
        )
        assert result["compatible"] is True

    def test_pure_python_compatible_x86(self, checker: WheelChecker):
        result = checker.check_wheel_filename(
            "click-8.1.0-py3-none-any.whl",
            Architecture.X86_64,
        )
        assert result["compatible"] is True

    # ------------------------------------------------------------------
    # Incompatibility classification
    # ------------------------------------------------------------------

    def test_classify_arm64_on_x86(self, checker: WheelChecker):
        reason = checker.classify_incompatibility(
            "pkg-1.0-cp311-cp311-macosx_11_0_arm64.whl",
            Architecture.X86_64,
        )
        assert reason is not None

    def test_classify_x86_on_arm64(self, checker: WheelChecker):
        reason = checker.classify_incompatibility(
            "pkg-1.0-cp311-cp311-macosx_10_9_x86_64.whl",
            Architecture.ARM64,
        )
        assert reason is not None

    def test_classify_compatible_returns_none(self, checker: WheelChecker):
        reason = checker.classify_incompatibility(
            "pkg-1.0-py3-none-any.whl",
            Architecture.ARM64,
        )
        assert reason is None

    # ------------------------------------------------------------------
    # Compatible tags
    # ------------------------------------------------------------------

    def test_get_compatible_tags_arm64(self, checker: WheelChecker):
        tags = checker.get_compatible_tags(Architecture.ARM64, "3.11")
        assert len(tags) > 0
        assert any("arm64" in t for t in tags)

    def test_get_compatible_tags_x86_64(self, checker: WheelChecker):
        tags = checker.get_compatible_tags(Architecture.X86_64, "3.11")
        assert len(tags) > 0
        assert any("x86_64" in t for t in tags)

    def test_get_compatible_tags_no_any(self, checker: WheelChecker):
        """get_compatible_tags returns macOS platform tags only, not 'any'."""
        tags = checker.get_compatible_tags(Architecture.ARM64, "3.11")
        assert "any" not in tags
