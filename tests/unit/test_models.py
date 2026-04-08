# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""Tests for envguard data models."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from envguard.models import (
    AcceleratorTarget,
    Architecture,
    EnvironmentType,
    FindingSeverity,
    HealthStatus,
    HostFacts,
    PackageManager,
    PermissionStatus,
    ProjectIntent,
    RepairAction,
    RuleFinding,
    ResolutionRecord,
    PreflightResult,
    HealthReport,
    ShellType,
)


class TestEnumerations:
    """Verify enum values and behaviour."""

    def test_architecture_values(self):
        assert Architecture.ARM64.value == "arm64"
        assert Architecture.X86_64.value == "x86_64"
        assert len(Architecture) >= 4  # arm64, x86_64, aarch64, unknown

    def test_shell_type_values(self):
        assert ShellType.ZSH.value == "zsh"
        assert ShellType.BASH.value == "bash"
        assert ShellType.UNKNOWN.value == "unknown"

    def test_environment_type_values(self):
        assert EnvironmentType.VENV.value == "venv"
        assert EnvironmentType.CONDA.value == "conda"
        assert EnvironmentType.SYSTEM.value == "system"

    def test_package_manager_values(self):
        assert PackageManager.PIP.value == "pip"
        assert PackageManager.CONDA.value == "conda"
        assert PackageManager.UV.value == "uv"

    def test_accelerator_target_values(self):
        assert AcceleratorTarget.CPU.value == "cpu"
        assert AcceleratorTarget.MPS.value == "mps"
        assert AcceleratorTarget.CUDA.value == "cuda"

    def test_finding_severity_order(self):
        # CRITICAL > ERROR > WARNING > INFO  (conceptual, no __lt__ defined)
        assert FindingSeverity.CRITICAL.value == "critical"
        assert FindingSeverity.ERROR.value == "error"
        assert FindingSeverity.WARNING.value == "warning"
        assert FindingSeverity.INFO.value == "info"

    def test_repair_action_values(self):
        assert RepairAction.RECOMMEND_ALTERNATIVE.value == "recommend_alternative"
        assert RepairAction.MANUAL_INTERVENTION.value == "manual_intervention"

    def test_permission_status_values(self):
        assert PermissionStatus.GRANTED.value == "granted"
        assert PermissionStatus.DENIED.value == "denied"

    def test_health_status_values(self):
        assert HealthStatus.HEALTHY.value == "healthy"
        assert HealthStatus.UNHEALTHY.value == "unhealthy"


class TestHostFacts:
    """Tests for the HostFacts dataclass."""

    def test_default_creation(self):
        facts = HostFacts()
        assert facts.os_name == "unknown"
        assert facts.architecture == Architecture.UNKNOWN
        assert facts.is_apple_silicon is False
        assert facts.is_rosetta is False
        assert facts.has_pip is False
        assert facts.has_conda is False
        assert facts.network_available is None

    def test_custom_creation(self):
        facts = HostFacts(
            os_name="Darwin",
            architecture=Architecture.ARM64,
            is_apple_silicon=True,
            has_pip=True,
            python_version="3.11.8",
        )
        assert facts.os_name == "Darwin"
        assert facts.architecture == Architecture.ARM64
        assert facts.is_apple_silicon is True
        assert facts.has_pip is True
        assert facts.python_version == "3.11.8"

    def test_asdict(self):
        facts = HostFacts(os_name="Darwin", architecture=Architecture.ARM64)
        d = dataclasses.asdict(facts)
        assert d["os_name"] == "Darwin"
        assert d["architecture"] == "arm64"

    def test_permission_fields(self):
        facts = HostFacts()
        assert facts.launch_agent_write == PermissionStatus.UNKNOWN
        assert facts.subprocess_execution == PermissionStatus.UNKNOWN
        facts.launch_agent_write = PermissionStatus.GRANTED
        assert facts.launch_agent_write == PermissionStatus.GRANTED

    def test_extra_dict(self):
        facts = HostFacts(extra={"custom_key": "value"})
        assert facts.extra["custom_key"] == "value"


class TestProjectIntent:
    """Tests for the ProjectIntent dataclass."""

    def test_default_creation(self):
        intent = ProjectIntent()
        assert intent.environment_type == EnvironmentType.UNKNOWN
        assert intent.dependency_count == 0
        assert intent.has_cuda_requirements is False
        assert intent.unsupported_features == []

    def test_pip_project(self, tmp_path):
        intent = ProjectIntent(
            project_dir=tmp_path,
            environment_type=EnvironmentType.VENV,
            package_managers=[PackageManager.PIP],
            has_pyproject_toml=True,
            project_name="test",
        )
        assert intent.project_dir == tmp_path
        assert PackageManager.PIP in intent.package_managers
        assert intent.has_pyproject_toml is True

    def test_cuda_flags(self, tmp_path):
        intent = ProjectIntent(
            project_dir=tmp_path,
            has_cuda_requirements=True,
            requires_cuda=True,
        )
        assert intent.has_cuda_requirements is True
        assert intent.requires_cuda is True

    def test_asdict_roundtrip(self, tmp_path):
        intent = ProjectIntent(project_dir=tmp_path, project_name="test")
        d = dataclasses.asdict(intent)
        assert d["project_name"] == "test"


class TestRuleFinding:
    """Tests for the RuleFinding dataclass."""

    def test_default_creation(self):
        finding = RuleFinding()
        assert finding.rule_id == ""
        assert finding.severity == FindingSeverity.INFO
        assert finding.auto_repairable is False
        assert finding.repair_action is None

    def test_cuda_finding(self, cuda_finding: RuleFinding):
        assert cuda_finding.rule_id == "CUDA_ON_MACOS"
        assert cuda_finding.severity == FindingSeverity.CRITICAL
        assert cuda_finding.auto_repairable is True
        assert cuda_finding.repair_action == RepairAction.RECOMMEND_ALTERNATIVE

    def test_finding_with_remediation(self):
        finding = RuleFinding(
            rule_id="TEST_RULE",
            severity=FindingSeverity.WARNING,
            message="Something is wrong",
            remediation="Do something about it",
        )
        assert finding.remediation == "Do something about it"

    def test_finding_details(self):
        finding = RuleFinding(
            rule_id="DETAIL_TEST",
            details={"key": "value", "count": 42},
        )
        assert finding.details["key"] == "value"
        assert finding.details["count"] == 42


class TestResolutionRecord:
    """Tests for the ResolutionRecord dataclass."""

    def test_default_creation(self):
        rec = ResolutionRecord()
        assert rec.python_version == "3.11"
        assert rec.package_manager == PackageManager.PIP
        assert rec.environment_type == EnvironmentType.VENV
        assert rec.success is False

    def test_custom_creation(self, tmp_path):
        rec = ResolutionRecord(
            project_dir=tmp_path,
            python_version="3.12",
            package_manager=PackageManager.CONDA,
            environment_type=EnvironmentType.CONDA,
        )
        assert rec.python_version == "3.12"
        assert rec.package_manager == PackageManager.CONDA

    def test_id_generation(self):
        rec1 = ResolutionRecord()
        rec2 = ResolutionRecord()
        assert rec1.id != rec2.id  # each should get unique id

    def test_findings_list(self):
        rec = ResolutionRecord()
        finding = RuleFinding(rule_id="TEST", severity=FindingSeverity.ERROR)
        rec.findings.append(finding)
        assert len(rec.findings) == 1
        assert rec.findings[0].rule_id == "TEST"


class TestPreflightResult:
    """Tests for the PreflightResult dataclass."""

    def test_default_passed(self):
        result = PreflightResult()
        assert result.passed is True
        assert result.success is True
        assert result.errors == []

    def test_failed_preflight(self):
        result = PreflightResult(passed=False, success=False)
        result.errors.append("CUDA not supported on macOS")
        assert result.passed is False
        assert len(result.errors) == 1

    def test_with_findings(self, cuda_finding: RuleFinding):
        result = PreflightResult()
        result.findings.append(cuda_finding)
        assert len(result.findings) == 1

    def test_smoke_test_results(self):
        result = PreflightResult()
        result.smoke_test_results = [
            ("numpy", True, ""),
            ("torch", False, "ImportError: No module named 'torch'"),
        ]
        assert result.smoke_test_results[0][0] == "numpy"
        assert result.smoke_test_results[0][1] is True
        assert result.smoke_test_results[1][1] is False


class TestHealthReport:
    """Tests for the HealthReport dataclass."""

    def test_default(self):
        report = HealthReport()
        assert report.status == HealthStatus.UNKNOWN
        assert report.python_ok is False
        assert report.missing_packages == []

    def test_healthy_report(self, tmp_path):
        report = HealthReport(
            status=HealthStatus.HEALTHY,
            environment_path=tmp_path / ".venv",
            python_ok=True,
            pip_ok=True,
            dependencies_ok=True,
        )
        assert report.status == HealthStatus.HEALTHY

    def test_with_checks(self):
        report = HealthReport()
        report.checks["python"] = (True, "Python 3.11.8")
        report.checks["pip"] = (True, "pip 24.0")
        assert report.checks["python"][0] is True
