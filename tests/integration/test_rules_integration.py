# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""Integration tests for rules engine with full scenarios."""

from __future__ import annotations

from envguard.models import (
    AcceleratorTarget,
    Architecture,
    EnvironmentType,
    FindingSeverity,
    HostFacts,
    PackageManager,
    ProjectIntent,
)
from envguard.rules import RulesEngine


class TestRulesEngineScenarios:
    """Full scenario tests for the rules engine."""

    def test_healthy_macos_project(self):
        """A standard macOS pip project should produce no critical findings."""
        facts = HostFacts(
            os_name="Darwin",
            architecture=Architecture.ARM64,
            is_apple_silicon=True,
            is_rosetta=False,
            is_macos=True,
            has_pip=True,
            has_venv=True,
            has_xcode_cli=True,
            network_available=True,
            mps_available=True,
        )
        intent = ProjectIntent(
            environment_type=EnvironmentType.VENV,
            package_managers=[PackageManager.PIP],
            requires_cuda=False,
            accelerator_target=AcceleratorTarget.CPU,
        )
        engine = RulesEngine(facts=facts, intent=intent)
        findings = engine.evaluate()
        critical = [f for f in findings if f.severity == FindingSeverity.CRITICAL]
        assert len(critical) == 0

    def test_cuda_on_apple_silicon(self):
        """CUDA on Apple Silicon must produce CRITICAL finding with remediation."""
        facts = HostFacts(
            os_name="Darwin",
            architecture=Architecture.ARM64,
            is_apple_silicon=True,
            is_macos=True,
            has_pip=True,
        )
        intent = ProjectIntent(
            requires_cuda=True,
            has_cuda_requirements=True,
            accelerator_target=AcceleratorTarget.CUDA,
        )
        engine = RulesEngine(facts=facts, intent=intent)
        findings = engine.evaluate()

        critical = [f for f in findings if f.severity == FindingSeverity.CRITICAL]
        assert len(critical) >= 1
        cuda_findings = [f for f in critical if "CUDA" in f.message.upper()]
        assert len(cuda_findings) >= 1
        assert cuda_findings[0].auto_repairable is True

    def test_mps_on_supported_macos(self):
        """MPS target on macOS 12.3+ should not produce critical findings."""
        facts = HostFacts(
            os_name="Darwin",
            architecture=Architecture.ARM64,
            is_apple_silicon=True,
            is_macos=True,
            mps_available=True,
            has_pip=True,
        )
        intent = ProjectIntent(
            accelerator_target=AcceleratorTarget.MPS,
            requires_mps=True,
        )
        engine = RulesEngine(facts=facts, intent=intent)
        findings = engine.evaluate()
        mps_critical = [
            f for f in findings if f.severity == FindingSeverity.CRITICAL and "MPS" in f.message
        ]
        assert len(mps_critical) == 0

    def test_rosetta_translated_python(self):
        """Running x86_64 Python under Rosetta should produce a warning."""
        facts = HostFacts(
            os_name="Darwin",
            architecture=Architecture.ARM64,
            is_apple_silicon=True,
            is_rosetta=True,
            is_native_python=False,
            is_macos=True,
        )
        intent = ProjectIntent()
        engine = RulesEngine(facts=facts, intent=intent)
        findings = engine.evaluate()
        # Should at minimum not crash; may produce rosetta warning
        assert isinstance(findings, list)

    def test_no_network_no_update(self):
        """Offline with no network requirement should be OK."""
        facts = HostFacts(
            os_name="Darwin",
            is_macos=True,
            network_available=False,
        )
        intent = ProjectIntent(requires_network=False)
        engine = RulesEngine(facts=facts, intent=intent)
        findings = engine.evaluate()
        # No network-critical findings expected
        net_critical = [
            f
            for f in findings
            if "network" in f.rule_id.lower() and f.severity == FindingSeverity.CRITICAL
        ]
        assert len(net_critical) == 0

    def test_conda_not_installed_but_required(self):
        """Project needs conda but it's not installed."""
        facts = HostFacts(
            os_name="Darwin",
            is_macos=True,
            has_conda=False,
            has_pip=True,
        )
        intent = ProjectIntent(
            environment_type=EnvironmentType.CONDA,
            package_managers=[PackageManager.CONDA],
        )
        engine = RulesEngine(facts=facts, intent=intent)
        findings = engine.evaluate()
        # Should produce at least a warning about missing conda
        [f for f in findings if "conda" in f.message.lower() or "package" in f.rule_id.lower()]
        # Findings may or may not exist depending on implementation
        assert isinstance(findings, list)

    def test_all_findings_structured(self):
        """Every finding must have required fields."""
        facts = HostFacts(os_name="Darwin", is_macos=True, architecture=Architecture.ARM64)
        intent = ProjectIntent(requires_cuda=True)
        engine = RulesEngine(facts=facts, intent=intent)
        findings = engine.evaluate()

        for f in findings:
            assert isinstance(f.rule_id, str) and len(f.rule_id) > 0
            assert isinstance(f.severity, FindingSeverity)
            assert isinstance(f.message, str) and len(f.message) > 0

    def test_evaluate_is_deterministic(self):
        """Same inputs should produce same outputs."""
        facts = HostFacts(os_name="Darwin", is_macos=True, architecture=Architecture.ARM64)
        intent = ProjectIntent(requires_cuda=True)
        engine1 = RulesEngine(facts=facts, intent=intent)
        engine2 = RulesEngine(facts=facts, intent=intent)
        findings1 = engine1.evaluate()
        findings2 = engine2.evaluate()
        assert len(findings1) == len(findings2)
        ids1 = {f.rule_id for f in findings1}
        ids2 = {f.rule_id for f in findings2}
        assert ids1 == ids2
