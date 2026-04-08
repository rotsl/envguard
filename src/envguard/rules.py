# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""Rules engine – evaluates a set of preflight rules against host facts and project intent.

Each rule is a method that returns ``None`` (pass) or a :class:`RuleFinding` (issue).
The :meth:`RulesEngine.evaluate` method runs **all** rules in sequence and returns the
complete list of findings.
"""

from __future__ import annotations

import os
import platform
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

from envguard.models import (
    HostFacts,
    ProjectIntent,
    RuleFinding,
    FindingSeverity,
    RepairAction,
    AcceleratorTarget,
    Architecture,
    EnvironmentType,
)
from envguard.exceptions import (
    CudaNotSupportedOnMacosError,
    IncompatibleWheelError,
    DependencyConflictError,
    BrokenEnvironmentError,
    PlatformNotSupportedError,
)
from envguard.logging import get_logger

logger = get_logger("envguard.rules")


class RulesEngine:
    """Evaluate a collection of rules and return findings.

    Parameters
    ----------
    facts:
        Immutable snapshot of host characteristics produced by :class:`HostDetector`.
    intent:
        Project requirements and preferences produced by :class:`IntentAnalyzer`.
    """

    def __init__(self, facts: HostFacts, intent: ProjectIntent) -> None:
        self._facts = facts
        self._intent = intent
        self._env_path: Optional[Path] = self._infer_env_path()
        self._normalise()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(self) -> list[RuleFinding]:
        """Run **all** registered rules and return every finding.

        Rules are executed in order.  A failing rule does **not** short-circuit
        the evaluation – every rule runs so the caller gets a complete picture.
        """
        findings: list[RuleFinding] = []
        rule_methods = [
            self.check_platform_compatibility,
            self.check_architecture_compatibility,
            self.check_python_version,
            self.check_cuda_on_macos,
            self.check_mps_availability,
            self.check_rosetta_risk,
            self.check_wheel_compatibility,
            self.check_mixed_pip_conda,
            self.check_source_build_prerequisites,
            self.check_network_for_operations,
            self.check_environment_exists,
            self.check_dependency_conflicts,
            self.check_stale_environment,
            self.check_missing_package_manager,
            self.check_package_manager_health,
        ]

        for rule_fn in rule_methods:
            try:
                finding = rule_fn()
            except Exception as exc:
                logger.error("Rule %s raised an unexpected error: %s", rule_fn.__name__, exc)
                finding = self._finding(
                    rule_id=f"{rule_fn.__name__.upper()}_ERROR",
                    severity=FindingSeverity.ERROR,
                    message=f"Rule '{rule_fn.__name__}' raised an unexpected error: {exc}",
                )
            if finding is not None:
                findings.append(finding)
                logger.info(
                    "Finding: [%s] %s – %s", finding.severity.value, finding.rule_id, finding.message
                )

        logger.info("Rules evaluation complete – %d finding(s)", len(findings))
        return findings

    # ------------------------------------------------------------------
    # Individual rules
    # ------------------------------------------------------------------

    def check_platform_compatibility(self) -> Optional[RuleFinding]:
        """Verify that the host platform is macOS.

        envguard is macOS-first; other platforms receive a CRITICAL finding.
        """
        if self._is_macos():
            logger.debug("Platform check passed – running on macOS %s", self._facts.os_version)
            return None

        return self._finding(
            rule_id="PLATFORM_NOT_MACOS",
            severity=FindingSeverity.CRITICAL,
            message=(
                f"envguard is macOS-first. Current platform is "
                f"{self._facts.os_name} {self._facts.os_version}."
            ),
            remediation="Run envguard on a macOS host (Intel or Apple Silicon).",
            auto_repairable=False,
            details={"os_name": self._facts.os_name, "os_version": self._facts.os_version},
        )

    def check_architecture_compatibility(self) -> Optional[RuleFinding]:
        """Verify that the host architecture matches project expectations.

        Some packages ship separate wheels for ``arm64`` and ``x86_64``.  If the
        project has an explicit architecture preference we check it here.
        """
        expected_arch = self._intent.extra.get("preferred_architecture")
        if expected_arch is None:
            return None

        host_arch = self._get_architecture()
        try:
            target = Architecture(expected_arch.lower())
        except ValueError:
            logger.warning("Unknown architecture preference '%s' – skipping check.", expected_arch)
            return None

        if host_arch == target:
            return None

        return self._finding(
            rule_id="ARCHITECTURE_MISMATCH",
            severity=FindingSeverity.ERROR,
            message=(
                f"Architecture mismatch: project expects '{target.value}' but "
                f"host is '{host_arch.value}'."
            ),
            remediation=(
                f"Switch to a {target.value} Python installation, or rebuild "
                f"packages for {host_arch.value}."
            ),
            auto_repairable=True,
            repair_action=RepairAction.SWITCH_PYTHON,
            details={"expected": target.value, "actual": host_arch.value},
        )

    def check_python_version(self) -> Optional[RuleFinding]:
        """Verify that the host Python version satisfies project requirements."""
        required = self._intent.python_version_required
        if required is None:
            logger.debug("No Python version requirement specified – skipping check.")
            return None

        req_parts = re.match(r"(\d+)\.(\d+)", required.strip())
        if req_parts is None:
            logger.warning("Could not parse python_version_required='%s' – skipping.", required)
            return None

        req_tuple = (int(req_parts.group(1)), int(req_parts.group(2)))
        host_version = self._facts.python_version or "0.0.0"
        host_parts = host_version.split(".")
        host_tuple = (int(host_parts[0]) if host_parts[0].isdigit() else 0,
                      int(host_parts[1]) if len(host_parts) > 1 and host_parts[1].isdigit() else 0)

        if host_tuple >= req_tuple:
            return None

        return self._finding(
            rule_id="PYTHON_VERSION_MISMATCH",
            severity=FindingSeverity.ERROR,
            message=(
                f"Python version mismatch: project requires >={req_parts.group(0)} "
                f"but host has {host_tuple[0]}.{host_tuple[1]}."
            ),
            remediation=(
                f"Install Python {req_parts.group(0)} or newer via Homebrew, pyenv, or conda."
            ),
            auto_repairable=True,
            repair_action=RepairAction.SWITCH_PYTHON,
            details={
                "required": req_parts.group(0),
                "host": f"{host_tuple[0]}.{host_tuple[1]}",
            },
        )

    def check_cuda_on_macos(self) -> Optional[RuleFinding]:
        """CRITICAL – if the project requires CUDA and we are on macOS.

        Apple Silicon does not support NVIDIA CUDA.  This rule fires when the
        project intent explicitly requests ``cuda`` as an accelerator target or
        lists CUDA-related dependencies while running on macOS.
        """
        wants_cuda = (
            self._intent.requires_cuda
            or self._intent.has_cuda_requirements
            or self._intent.accelerator_target == AcceleratorTarget.CUDA
        )

        if not wants_cuda:
            return None

        if not self._is_macos():
            return None

        cuda_deps = [
            dep for dep in self._intent.dependencies
            if any(tag in dep.lower() for tag in ("torch", "tensorflow", "jax", "cuda", "nvidia"))
        ]

        return self._finding(
            rule_id="CUDA_ON_MACOS",
            severity=FindingSeverity.CRITICAL,
            message="CUDA is not supported as a runtime target on macOS",
            remediation="Use CPU or Apple MPS (Metal Performance Shaders) instead",
            auto_repairable=True,
            repair_action=RepairAction.RECOMMEND_ALTERNATIVE,
            details={"cuda_related_deps": cuda_deps},
        )

    def check_mps_availability(self) -> Optional[RuleFinding]:
        """Check whether MPS (Metal Performance Shaders) is available.

        MPS requires macOS 12.3 (Monterey) or later on Apple Silicon.
        """
        wants_mps = (
            self._intent.requires_mps
            or self._intent.has_mps_requirements
            or self._intent.accelerator_target == AcceleratorTarget.MPS
        )

        if not wants_mps:
            return None

        if self._facts.mps_available:
            logger.debug("MPS is available on this host.")
            return None

        if not self._is_macos():
            return self._finding(
                rule_id="MPS_NOT_AVAILABLE",
                severity=FindingSeverity.ERROR,
                message="MPS is only available on macOS with Apple Silicon.",
                remediation="Use CPU or CUDA (non-macOS) as the accelerator target.",
                details={"os": self._facts.os_name},
            )

        if not self._is_arm64():
            return self._finding(
                rule_id="MPS_NOT_AVAILABLE",
                severity=FindingSeverity.ERROR,
                message="MPS requires Apple Silicon (arm64) hardware.",
                remediation="Use CPU as the accelerator target.",
                details={"machine": str(self._facts.architecture.value)},
            )

        return self._finding(
            rule_id="MPS_NOT_AVAILABLE",
            severity=FindingSeverity.WARNING,
            message=(
                f"MPS requires macOS 12.3 or later. Current version: {self._facts.os_version}"
            ),
            remediation="Upgrade macOS to 12.3 (Monterey) or later to enable MPS support.",
            auto_repairable=False,
            details={"os_version": self._facts.os_version},
        )

    def check_rosetta_risk(self) -> Optional[RuleFinding]:
        """Warn if running x86_64 Python under Rosetta 2 translation."""
        if not self._facts.is_rosetta:
            return None

        return self._finding(
            rule_id="ROSETTA_TRANSLATION_DETECTED",
            severity=FindingSeverity.WARNING,
            message=(
                "Python is running under Rosetta 2 translation (x86_64 on arm64 host). "
                "This may cause wheel architecture mismatches and reduced performance."
            ),
            remediation=(
                "Install a native arm64 Python via Homebrew ('brew install python@3.12') "
                "or use 'arch -arm64' to launch a native shell."
            ),
            auto_repairable=True,
            repair_action=RepairAction.SWITCH_PYTHON,
            details={
                "host_arch": "arm64",
                "python_arch": "x86_64",
            },
        )

    def check_wheel_compatibility(self) -> Optional[RuleFinding]:
        """Detect architecture-incompatible wheels in project dependencies.

        Scans dependencies for packages that are known to ship platform-specific
        wheels and verifies that a compatible wheel exists for the host architecture.
        """
        host_arch_str = "arm64" if self._is_arm64() else "x86_64"
        arch_sensitive_packages = {
            "torch", "pytorch", "tensorflow", "numpy", "scipy", "pandas",
            "scikit-learn", "opencv-python", "pillow", "psutil", "lxml",
            "cryptography", "pyyaml", "grpcio", "protobuf",
        }

        problematic: list[str] = []
        all_deps = self._intent.dependencies + self._intent.dev_dependencies

        for dep in all_deps:
            dep_name = re.split(r"[<>=!~\[]", dep.strip(), maxsplit=1)[0].lower().replace("-", "_")
            if dep_name in arch_sensitive_packages:
                if self._is_macos() and self._is_arm64():
                    compat = self._check_wheel_arch_compat(dep_name, host_arch_str)
                    if compat is False:
                        problematic.append(dep_name)

        if not problematic:
            return None

        return self._finding(
            rule_id="INCOMPATIBLE_WHEEL",
            severity=FindingSeverity.WARNING,
            message=(
                f"The following packages may not have compatible {host_arch_str} wheels: "
                f"{', '.join(problematic)}."
            ),
            remediation=(
                "Consider building from source or using universal2 wheels. "
                "Ensure Xcode CLI tools are installed for native compilation."
            ),
            auto_repairable=False,
            repair_action=RepairAction.REBUILD_EXTENSIONS,
            details={"packages": problematic, "host_arch": host_arch_str},
        )

    def check_mixed_pip_conda(self) -> Optional[RuleFinding]:
        """Detect broken mixed pip/conda ownership in an existing environment."""
        env_path = self._env_path
        if env_path is None or not env_path.exists():
            return None

        if not self._is_conda_env(env_path):
            return None

        conda_meta = env_path / "conda-meta"
        if not conda_meta.exists() or not conda_meta.is_dir():
            return None

        site_packages = self._find_site_packages(env_path)
        if site_packages is None:
            return None

        pip_dist_infos: list[str] = []
        conda_packages: set[str] = set()

        if conda_meta.is_dir():
            for json_file in conda_meta.glob("*.json"):
                conda_packages.add(json_file.stem.split("-")[0].lower())

        for dist_info in site_packages.glob("*.dist-info"):
            pkg_name = dist_info.name.split("-")[0].lower().replace("-", "_")
            pip_dist_infos.append(pkg_name)

        mixed = [pkg for pkg in pip_dist_infos if pkg in conda_packages]
        pip_only_in_conda = [pkg for pkg in pip_dist_infos if pkg not in conda_packages]

        if mixed:
            return self._finding(
                rule_id="MIXED_PIP_CONDA_OWNERSHIP",
                severity=FindingSeverity.WARNING,
                message=(
                    f"Packages installed by both pip and conda: {', '.join(sorted(set(mixed)))}. "
                    "This can cause import errors and environment corruption."
                ),
                remediation=(
                    "Reinstall conflicting packages using only conda, "
                    "or use 'conda-unpack' after pip operations."
                ),
                auto_repairable=True,
                repair_action=RepairAction.FIX_OWNERSHIP,
                details={"mixed_packages": sorted(set(mixed)), "pip_only_count": len(pip_only_in_conda)},
            )

        if len(pip_only_in_conda) > 10:
            return self._finding(
                rule_id="MIXED_PIP_CONDA_OWNERSHIP",
                severity=FindingSeverity.INFO,
                message=(
                    f"{len(pip_only_in_conda)} packages installed via pip inside conda environment. "
                    "Consider using conda for package management to avoid conflicts."
                ),
                remediation="Use 'conda install' for packages available in conda channels.",
                auto_repairable=False,
                details={"pip_only_packages": pip_only_in_conda[:20]},
            )

        return None

    def check_source_build_prerequisites(self) -> Optional[RuleFinding]:
        """Check if Xcode CLI tools are available when source builds are needed."""
        needs_build = self._intent.requires_source_build
        if not needs_build:
            build_required_deps = {"cython", "cffi", "pybind11", "setuptools-rust"}
            all_deps = self._intent.dependencies + self._intent.dev_dependencies
            for dep in all_deps:
                dep_name = re.split(r"[<>=!~\[]", dep.strip(), maxsplit=1)[0].lower()
                if dep_name in build_required_deps:
                    needs_build = True
                    break

        if not needs_build:
            return None

        if self._facts.has_xcode_cli:
            return None

        return self._finding(
            rule_id="SOURCE_BUILD_PREREQUISITES_MISSING",
            severity=FindingSeverity.ERROR,
            message=(
                "Source build required but Xcode CLI tools are not installed. "
                "Native extensions cannot be compiled."
            ),
            remediation="Install Xcode CLI tools: 'xcode-select --install'",
            auto_repairable=False,
            repair_action=RepairAction.MANUAL_INTERVENTION,
            details={"requires_source_build": True},
        )

    def check_network_for_operations(self) -> Optional[RuleFinding]:
        """Verify network availability when the project needs to download packages."""
        if not self._intent.requires_network and not self._intent.dependencies:
            return None

        if self._facts.network_available is True and self._check_connectivity():
            return None

        return self._finding(
            rule_id="NETWORK_UNAVAILABLE",
            severity=FindingSeverity.WARNING,
            message=(
                "Network access appears to be unavailable. Package downloads "
                "and installations may fail."
            ),
            remediation=(
                "Check your internet connection. If behind a proxy, set "
                "HTTPS_PROXY / HTTP_PROXY environment variables."
            ),
            auto_repairable=False,
            details={"requires_network": self._intent.requires_network},
        )

    def check_environment_exists(self) -> Optional[RuleFinding]:
        """Check if the project's virtual or conda environment already exists."""
        env_path = self._env_path
        if env_path is None:
            return self._finding(
                rule_id="NO_ENVIRONMENT",
                severity=FindingSeverity.INFO,
                message="No existing environment found. One will need to be created.",
                remediation="Run 'envguard setup' to create the environment.",
                auto_repairable=True,
                repair_action=RepairAction.RECREATE_ENVIRONMENT,
            )

        if env_path.exists():
            python_bin = self._find_env_python(env_path)
            if python_bin is not None and python_bin.exists():
                return None
            return self._finding(
                rule_id="BROKEN_ENVIRONMENT",
                severity=FindingSeverity.ERROR,
                message=f"Environment exists at '{env_path}' but appears to be broken (no Python binary).",
                remediation="Recreate the environment: 'envguard repair --recreate'",
                auto_repairable=True,
                repair_action=RepairAction.RECREATE_ENVIRONMENT,
                details={"env_path": str(env_path)},
            )

        return self._finding(
            rule_id="NO_ENVIRONMENT",
            severity=FindingSeverity.INFO,
            message=f"Expected environment at '{env_path}' does not exist.",
            remediation="Run 'envguard setup' to create the environment.",
            auto_repairable=True,
            repair_action=RepairAction.RECREATE_ENVIRONMENT,
            details={"expected_path": str(env_path)},
        )

    def check_dependency_conflicts(self) -> Optional[RuleFinding]:
        """Look for known dependency conflict patterns."""
        known_conflicts: list[tuple[str, str, str]] = [
            ("tensorflow", "torch", "TensorFlow and PyTorch can coexist but may cause library conflicts (e.g., protobuf version). Pin protobuf explicitly."),
            ("tensorflow", "jax", "TensorFlow and JAX share low-level dependencies; ensure compatible versions."),
            ("numpy<1.20", "torch>=1.10", "Old numpy versions are incompatible with recent PyTorch."),
            ("setuptools<58", "wheel>=0.37", "Old setuptools may not handle modern wheel metadata."),
        ]

        all_deps_lower = [
            re.split(r"[<>=!~\[]", d.strip(), maxsplit=1)[0].lower()
            for d in self._intent.dependencies + self._intent.dev_dependencies
        ]
        dep_set = set(all_deps_lower)

        for conflict_spec in self._intent.known_conflicts:
            known_conflicts.append(
                (conflict_spec, "*", f"User-flagged conflict: {conflict_spec}")
            )

        for pattern_a, pattern_b, description in known_conflicts:
            name_a = pattern_a.split("<")[0].split(">")[0].split("=")[0].split("!")[0].split("~")[0].strip().lower()
            name_b = pattern_b.split("<")[0].split(">")[0].split("=")[0].split("!")[0].split("~")[0].strip().lower()

            if name_b == "*":
                if name_a in dep_set:
                    return self._finding(
                        rule_id="DEPENDENCY_CONFLICT",
                        severity=FindingSeverity.WARNING,
                        message=f"Known dependency conflict detected: {description}",
                        remediation="Review dependency versions and resolve the conflict manually.",
                        auto_repairable=False,
                        details={"conflict": description, "trigger": name_a},
                    )
                continue

            if name_a in dep_set and name_b in dep_set:
                return self._finding(
                    rule_id="DEPENDENCY_CONFLICT",
                    severity=FindingSeverity.WARNING,
                    message=f"Known dependency conflict detected: {description}",
                    remediation="Review dependency versions and resolve the conflict manually.",
                    auto_repairable=False,
                    details={"package_a": name_a, "package_b": name_b, "description": description},
                )

        return None

    def check_stale_environment(self) -> Optional[RuleFinding]:
        """Check for drift between the project intent and the actual environment."""
        env_path = self._env_path
        if env_path is None or not env_path.exists():
            return None

        python_bin = self._find_env_python(env_path)
        if python_bin is None:
            return None

        installed = self._list_installed_packages(python_bin)
        if installed is None:
            return None

        required: set[str] = set()
        for dep in self._intent.dependencies + self._intent.dev_dependencies:
            pkg_name = re.split(r"[<>=!~\[]", dep.strip(), maxsplit=1)[0].lower().replace("-", "_")
            required.add(pkg_name)

        installed_names = {name.lower().replace("-", "_") for name in installed}
        missing = sorted(required - installed_names)
        extra = sorted(installed_names - required - {"pip", "setuptools", "wheel", "pkg_resources"})

        if not missing and not extra:
            return None

        parts: list[str] = []
        if missing:
            parts.append(f"Missing: {', '.join(missing)}")
        if extra:
            parts.append(f"Extra (not in requirements): {', '.join(extra[:10])}")

        severity = FindingSeverity.ERROR if missing else FindingSeverity.INFO
        remediation = ""
        auto_repair = False
        action: Optional[RepairAction] = None

        if missing:
            remediation = f"Install missing packages: pip install {' '.join(missing)}"
            auto_repair = True
            action = RepairAction.INSTALL_MISSING

        return self._finding(
            rule_id="STALE_ENVIRONMENT",
            severity=severity,
            message=f"Environment drift detected – {'; '.join(parts)}.",
            remediation=remediation,
            auto_repairable=auto_repair,
            repair_action=action,
            details={"missing": missing, "extra": extra[:20]},
        )

    def check_missing_package_manager(self) -> Optional[RuleFinding]:
        """Verify that the required package manager is available on the host."""
        env_type = self._intent.environment_type

        if env_type == EnvironmentType.CONDA:
            if not self._facts.has_conda:
                return self._finding(
                    rule_id="MISSING_PACKAGE_MANAGER",
                    severity=FindingSeverity.ERROR,
                    message=(
                        "Project requires conda but conda is not found on PATH. "
                        "Install Miniconda or Anaconda."
                    ),
                    remediation="Install Miniconda: 'brew install --cask miniconda' or from https://docs.conda.io",
                    auto_repairable=False,
                    repair_action=RepairAction.MANUAL_INTERVENTION,
                    details={"required_manager": "conda"},
                )

        elif env_type in (EnvironmentType.VENV, EnvironmentType.POETRY, EnvironmentType.PIPENV):
            if not self._facts.has_pip:
                return self._finding(
                    rule_id="MISSING_PACKAGE_MANAGER",
                    severity=FindingSeverity.ERROR,
                    message="pip is not available. Python environments cannot be managed without pip.",
                    remediation="Install pip: 'python -m ensurepip' or 'python -m pip install --upgrade pip'",
                    auto_repairable=True,
                    repair_action=RepairAction.UPGRADE_TOOL,
                    details={"required_manager": "pip"},
                )

        return None

    def check_package_manager_health(self) -> Optional[RuleFinding]:
        """Verify that pip/conda are functional and not in a broken state."""
        env_type = self._intent.environment_type
        findings: list[RuleFinding] = []

        if env_type in (EnvironmentType.VENV, EnvironmentType.POETRY, EnvironmentType.PIPENV):
            if self._facts.has_pip:
                if not self._check_pip_health():
                    findings.append(
                        self._finding(
                            rule_id="PIP_HEALTH_CHECK_FAILED",
                            severity=FindingSeverity.WARNING,
                            message="pip appears to be in a broken state. Package installations may fail.",
                            remediation="Upgrade pip: 'python -m pip install --upgrade pip --force-reinstall'",
                            auto_repairable=True,
                            repair_action=RepairAction.UPGRADE_TOOL,
                        )
                    )

        if env_type == EnvironmentType.CONDA and self._facts.has_conda:
            if not self._check_conda_health():
                findings.append(
                    self._finding(
                        rule_id="CONDA_HEALTH_CHECK_FAILED",
                        severity=FindingSeverity.WARNING,
                        message="conda appears to be in a broken state.",
                        remediation="Run 'conda update conda' to repair.",
                        auto_repairable=True,
                        repair_action=RepairAction.UPGRADE_TOOL,
                    )
                )

        if findings:
            return findings[0]
        return None

    # ------------------------------------------------------------------
    # Helper: build a RuleFinding
    # ------------------------------------------------------------------

    def _finding(
        self,
        rule_id: str,
        severity: FindingSeverity,
        message: str,
        *,
        remediation: str = "",
        auto_repairable: bool = False,
        repair_action: Optional[RepairAction] = None,
        details: Optional[dict[str, Any]] = None,
    ) -> RuleFinding:
        """Construct a :class:`RuleFinding` with the given parameters."""
        return RuleFinding(
            rule_id=rule_id,
            severity=severity,
            message=message,
            remediation=remediation,
            auto_repairable=auto_repairable,
            repair_action=repair_action,
            details=details or {},
        )

    # ------------------------------------------------------------------
    # Normalisation – bridge between our fields and the base model fields
    # ------------------------------------------------------------------

    def _normalise(self) -> None:
        """Copy values from base-model fields into our extended fields.

        This allows the rest of the code to use the extended field names
        regardless of how the HostFacts / ProjectIntent were populated.
        """
        f = self._facts
        if not f.is_macos and f.os_name == "Darwin":
            f.is_macos = True
        if not f.is_macos:
            f.is_macos = (f.os_name == "Darwin")
        if f.architecture == Architecture.ARM64:
            f.is_apple_silicon = True
        if not f.mps_available and f.is_macos and f.is_apple_silicon:
            # Detect MPS availability from OS version
            try:
                parts = f.os_version.split(".")
                major = int(parts[0]) if parts else 0
                minor = int(parts[1]) if len(parts) > 1 else 0
                f.mps_available = (major, minor) >= (12, 3)
            except (ValueError, IndexError):
                f.mps_available = False
        if f.pip_path is None and f.has_pip:
            f.pip_path = f"{f.python_path} -m pip"
        if f.conda_path is None and f.has_conda:
            f.conda_path = "conda"

        i = self._intent
        if not i.requires_cuda and i.has_cuda_requirements:
            i.requires_cuda = True
        if not i.requires_mps and i.has_mps_requirements:
            i.requires_mps = True
        if i.dependencies and not i.requires_network:
            i.requires_network = True
        if not i.name and i.project_name and i.project_name != "unknown":
            i.name = i.project_name
        if not i.name:
            i.name = i.project_dir.name if i.project_dir else "unnamed-project"
        # Sync accelerator target
        if (i.accelerator_target == AcceleratorTarget.CPU
                and i.requires_cuda
                and self._is_macos()):
            i.accelerator_target = AcceleratorTarget.MPS

    # ------------------------------------------------------------------
    # Convenience accessors
    # ------------------------------------------------------------------

    def _is_macos(self) -> bool:
        return self._facts.is_macos or self._facts.os_name == "Darwin"

    def _is_arm64(self) -> bool:
        return self._facts.is_apple_silicon or self._facts.architecture == Architecture.ARM64

    def _get_architecture(self) -> Architecture:
        if self._facts.architecture and self._facts.architecture != Architecture.UNKNOWN:
            return self._facts.architecture
        if self._is_arm64():
            return Architecture.ARM64
        return Architecture.X86_64

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _infer_env_path(self) -> Optional[Path]:
        """Infer the environment path from the project directory."""
        project_dir = self._intent.project_dir
        if project_dir is None:
            return None
        project_dir = Path(project_dir)

        candidates = [
            project_dir / ".venv",
            project_dir / "venv",
            project_dir / ".conda",
            project_dir / "env",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate

        if self._intent.environment_type == EnvironmentType.CONDA:
            return project_dir / ".conda"
        return project_dir / ".venv"

    @staticmethod
    def _find_env_python(env_path: Path) -> Optional[Path]:
        """Locate the Python binary inside an environment."""
        for name in ("python3", "python"):
            candidate = env_path / "bin" / name
            if candidate.exists():
                return candidate
        win = env_path / "Scripts" / "python.exe"
        if win.exists():
            return win
        return None

    @staticmethod
    def _find_site_packages(env_path: Path) -> Optional[Path]:
        """Locate the site-packages directory inside an environment."""
        bin_dir = env_path / "bin"
        if not bin_dir.exists():
            return None
        python_bin = bin_dir / "python3"
        if not python_bin.exists():
            python_bin = bin_dir / "python"
        if not python_bin.exists():
            return None

        try:
            result = subprocess.run(
                [str(python_bin), "-c", "import site; print(site.getsitepackages()[0])"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                return Path(result.stdout.strip())
        except (subprocess.TimeoutExpired, OSError):
            pass

        guess = env_path / "lib" / "python3" / "site-packages"
        if guess.exists():
            return guess
        return None

    @staticmethod
    def _is_conda_env(env_path: Path) -> bool:
        """Check if a path is a conda environment."""
        return (env_path / "conda-meta").is_dir()

    def _list_installed_packages(self, python_bin: Path) -> Optional[set[str]]:
        """List installed packages using the environment's Python."""
        try:
            result = subprocess.run(
                [str(python_bin), "-m", "pip", "list", "--format=freeze"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                packages = set()
                for line in result.stdout.strip().splitlines():
                    if "==" in line:
                        packages.add(line.split("==")[0].strip())
                return packages
        except (subprocess.TimeoutExpired, OSError):
            logger.warning("Could not list installed packages from %s", python_bin)
        return None

    @staticmethod
    def _check_wheel_arch_compat(package_name: str, host_arch: str) -> Optional[bool]:
        """Check PyPI for wheel compatibility with the host architecture."""
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "index", "versions", package_name,
                 "--pre", "--format", "json"],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0:
                output = result.stdout
                if host_arch in output and ("macosx" in output or "darwin" in output):
                    return True
                if output.strip() and host_arch not in output:
                    return False
        except (subprocess.TimeoutExpired, OSError):
            pass
        return None

    @staticmethod
    def _check_connectivity() -> bool:
        """Lightweight network connectivity check via TCP."""
        import socket
        for host in ("pypi.org", "files.pythonhosted.org"):
            try:
                socket.create_connection((host, 443), timeout=3)
                return True
            except (socket.timeout, socket.error, OSError):
                continue
        return False

    @staticmethod
    def _check_pip_health() -> bool:
        """Run a quick pip health check."""
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "--version"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                return False
            result2 = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--dry-run", "--quiet", "six"],
                capture_output=True, text=True, timeout=15,
            )
            return result2.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            return False

    @staticmethod
    def _check_conda_health() -> bool:
        """Run a quick conda health check."""
        try:
            result = subprocess.run(
                ["conda", "info"],
                capture_output=True, text=True, timeout=15,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            return False
