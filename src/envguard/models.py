# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""Data models for envguard."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class Architecture(str, Enum):
    """CPU architecture types."""
    X86_64 = "x86_64"
    ARM64 = "arm64"
    AARCH64 = "aarch64"
    UNKNOWN = "unknown"


class ShellType(str, Enum):
    """Shell types on macOS/Linux."""
    BASH = "bash"
    ZSH = "zsh"
    FISH = "fish"
    SH = "sh"
    DASH = "dash"
    TCSH = "tcsh"
    KSH = "ksh"
    UNKNOWN = "unknown"


class EnvironmentType(str, Enum):
    """Types of Python environments."""
    VENV = "venv"
    CONDA = "conda"
    MAMBA = "mamba"
    PIPENV = "pipenv"
    POETRY = "poetry"
    PIXI = "pixi"
    SYSTEM = "system"
    UNKNOWN = "unknown"


class PackageManager(str, Enum):
    """Package manager identifiers."""
    PIP = "pip"
    CONDA = "conda"
    MAMBA = "mamba"
    UV = "uv"
    PIPENV = "pipenv"
    POETRY = "poetry"
    PIXI = "pixi"
    UNKNOWN = "unknown"


class AcceleratorTarget(str, Enum):
    """Hardware acceleration targets."""
    CPU = "cpu"
    CUDA = "cuda"
    MPS = "mps"
    ROCM = "rocm"
    VULKAN = "vulkan"
    AUTO = "auto"


class FindingSeverity(str, Enum):
    """Severity levels for rule findings."""
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
    CRITICAL = "critical"


class HealthStatus(str, Enum):
    """Health check statuses."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class RepairAction(str, Enum):
    """Types of repair actions that can be automatically applied."""
    RECOMMEND_ALTERNATIVE = "recommend_alternative"
    RECREATE_ENVIRONMENT = "recreate_environment"
    FIX_OWNERSHIP = "fix_ownership"
    SWITCH_PYTHON = "switch_python"
    INSTALL_MISSING = "install_missing"
    UPGRADE_TOOL = "upgrade_tool"
    REINSTALL_PACKAGES = "reinstall_packages"
    REBUILD_EXTENSIONS = "rebuild_extensions"
    MANUAL_INTERVENTION = "manual_intervention"


class PermissionStatus(str, Enum):
    """Result of a permission check."""
    GRANTED = "granted"
    DENIED = "denied"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class HostFacts:
    """Complete host detection results.

    Attributes:
        os_name: Operating system name (e.g. 'Darwin').
        os_version: Operating system version string.
        os_release: Full OS release string.
        architecture: Detected CPU architecture.
        is_apple_silicon: True if running on Apple Silicon (arm64).
        is_rosetta: True if running under Rosetta 2 translation.
        python_version: Detected Python version string.
        python_path: Path to the Python interpreter.
        has_pip: Whether pip is available.
        has_venv: Whether the venv module is available.
        has_conda: Whether conda is available.
        has_mamba: Whether mamba is available.
        is_native_python: Whether Python is native (not under Rosetta).
        shell: Detected user shell.
        has_xcode_cli: Whether Xcode Command Line Tools are installed.
        network_available: Whether PyPI is reachable (None if untested).
        username: Current username.
        home_dir: User home directory.
        project_dir_writable: Whether the project directory is writable.
        home_writable: Whether the home directory is writable.
        permissions_notes: List of permission-related notes.
        extra: Additional arbitrary host information.
    """

    os_name: str = "unknown"
    os_version: str = "unknown"
    os_release: str = "unknown"
    architecture: Architecture = Architecture.UNKNOWN
    is_apple_silicon: bool = False
    is_rosetta: bool = False
    python_version: str = "unknown"
    python_path: str = "unknown"
    has_pip: bool = False
    has_venv: bool = False
    has_conda: bool = False
    has_mamba: bool = False
    is_native_python: bool = True
    shell: ShellType = ShellType.UNKNOWN
    shell_type: ShellType = ShellType.UNKNOWN  # alias for compatibility
    has_xcode_cli: bool = False
    network_available: Optional[bool] = None
    # --- Extended fields used by rules/repair engines ---
    mps_available: bool = False
    conda_path: Optional[str] = None
    pip_path: Optional[str] = None
    total_ram_gb: Optional[float] = None
    is_macos: bool = False  # convenience alias: True when os_name == "Darwin"
    username: str = "unknown"
    home_dir: Path = field(default_factory=Path)
    project_dir: Optional[Path] = None
    project_dir_writable: bool = False
    home_writable: bool = False
    permissions_notes: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    # Permission check results (populated by PermissionChecker)
    write_permissions: dict[str, "PermissionStatus"] = field(default_factory=dict)
    execute_permissions: dict[str, "PermissionStatus"] = field(default_factory=dict)
    read_permissions: dict[str, "PermissionStatus"] = field(default_factory=dict)
    launch_agent_write: "PermissionStatus" = PermissionStatus.UNKNOWN
    subprocess_execution: "PermissionStatus" = PermissionStatus.UNKNOWN
    network_access: "PermissionStatus" = PermissionStatus.UNKNOWN
    shell_rc_write: "PermissionStatus" = PermissionStatus.UNKNOWN


@dataclass
class ProjectIntent:
    """Detected project intent and metadata.

    Attributes:
        project_dir: Absolute path to the project root.
        environment_type: Inferred environment type.
        package_managers: Inferred package managers.
        python_version_required: Required Python version from project files.
        dependencies: List of raw dependency strings.
        dev_dependencies: List of dev dependency strings.
        dependency_count: Total number of dependencies.
        has_pyproject_toml: Whether pyproject.toml exists.
        has_requirements_txt: Whether requirements.txt exists.
        has_conda_env_file: Whether environment.yml/yaml exists.
        has_setup_py: Whether setup.py exists.
        conda_env_path: Path to conda env file if found.
        requirements_files: Paths to all requirements*.txt files.
        build_system: Build system name from pyproject.toml.
        project_name: Project name extracted from config.
        project_version: Project version extracted from config.
        has_wheelhouse: Whether a wheels/ or wheelhouse/ directory exists.
        wheelhouse_path: Path to the wheelhouse directory if found.
        has_cuda_requirements: Whether CUDA dependencies are referenced.
        has_mps_requirements: Whether MPS/Metal dependencies are referenced.
        has_previous_envguard_state: Whether .envguard/ directory exists.
        unsupported_features: List of features unsupported on current host.
        remediation_hints: Hints for fixing unsupported features.
        compatibility_notes: General compatibility notes.
        extra: Additional arbitrary project information.
    """

    project_dir: Path = field(default_factory=Path)
    environment_type: EnvironmentType = EnvironmentType.UNKNOWN
    package_managers: list[PackageManager] = field(default_factory=list)
    python_version_required: Optional[str] = None
    dependencies: list[str] = field(default_factory=list)
    dev_dependencies: list[str] = field(default_factory=list)
    dependency_count: int = 0
    has_pyproject_toml: bool = False
    has_requirements_txt: bool = False
    has_conda_env_file: bool = False
    has_setup_py: bool = False
    conda_env_path: Optional[Path] = None
    requirements_files: list[Path] = field(default_factory=list)
    build_system: str = "unknown"
    project_name: str = "unknown"
    project_version: str = "unknown"
    has_wheelhouse: bool = False
    wheelhouse_path: Optional[Path] = None
    has_cuda_requirements: bool = False
    has_mps_requirements: bool = False
    has_previous_envguard_state: bool = False
    # --- Extended fields used by rules/repair engines ---
    requires_cuda: bool = False  # alias: same as has_cuda_requirements
    requires_mps: bool = False   # alias: same as has_mps_requirements
    requires_network: bool = False
    requires_source_build: bool = False
    known_conflicts: list[str] = field(default_factory=list)
    conda_dependencies: list[str] = field(default_factory=list)
    accelerator_target: AcceleratorTarget = AcceleratorTarget.CPU
    name: str = ""  # convenience alias for project_name
    unsupported_features: list[str] = field(default_factory=list)
    remediation_hints: list[str] = field(default_factory=list)
    compatibility_notes: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResolutionRecord:
    """A stored resolution for a project.

    Attributes:
        id: Unique resolution identifier.
        project_dir: Absolute path to the project.
        python_version: Resolved Python version.
        package_manager: Resolved package manager.
        environment_type: Resolved environment type.
        environment_path: Path where the environment will be created.
        accelerator_target: Resolved accelerator target.
        created_at: Timestamp when the resolution was created.
        findings: Validation findings from the resolution.
        plan: Full environment creation plan.
        extra: Additional resolution metadata.
    """

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    resolution_id: str = ""  # alias populated from id after creation
    project_dir: Path = field(default_factory=Path)
    python_version: str = "3.11"
    package_manager: PackageManager = PackageManager.PIP
    environment_type: EnvironmentType = EnvironmentType.VENV
    environment_path: Path = field(default_factory=Path)
    accelerator_target: AcceleratorTarget = AcceleratorTarget.CPU
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    findings: list[RuleFinding] = field(default_factory=list)
    plan: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)
    # --- Extended fields used by rules/repair engines ---
    packages_installed: list[str] = field(default_factory=list)
    packages_skipped: list[str] = field(default_factory=list)
    repair_actions_taken: list[str] = field(default_factory=list)
    success: bool = False
    notes: list[str] = field(default_factory=list)
    findings_addressed: list[str] = field(default_factory=list)


@dataclass
class RuleFinding:
    """A single finding from a validation or analysis rule.

    Attributes:
        rule_id: Identifier of the rule that produced this finding.
        severity: Severity level.
        message: Human-readable description.
        details: Additional structured details.
        remediation: Suggested fix steps.
        auto_repairable: Whether the issue can be fixed automatically.
        repair_action: Which repair strategy to apply.
        timestamp: When the finding was produced.
    """

    rule_id: str = ""
    severity: FindingSeverity = FindingSeverity.INFO
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    # --- Extended fields used by rules/repair engines ---
    remediation: str = ""
    auto_repairable: bool = False
    repair_action: Optional["RepairAction"] = None
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class PreflightResult:
    """Result of preflight checks.

    Attributes:
        passed: Whether all critical checks passed.
        checks: Dict of check name to (passed: bool, message: str).
        warnings: List of warning messages.
        errors: List of error messages.
        success: Alias for passed, used by the preflight engine.
        host_facts: Detected host facts (populated by PreflightEngine).
        project_intent: Analysed project intent.
        findings: Rule findings from RulesEngine.
        resolution: Resolution record (if created).
        environment_valid: Whether the resolved environment passed validation.
        smoke_test_results: Results of import smoke tests.
        summary: Human-readable summary string.
        timestamp: When the result was produced.
    """

    passed: bool = True
    success: bool = True  # alias
    checks: dict[str, tuple[bool, str]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    # --- Extended fields used by preflight engine ---
    host_facts: Optional[HostFacts] = None
    project_intent: Optional[ProjectIntent] = None
    findings: list[RuleFinding] = field(default_factory=list)
    resolution: Optional[ResolutionRecord] = None
    environment_valid: bool = False
    smoke_test_results: list[tuple[str, bool, str]] = field(default_factory=list)
    summary: str = ""
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class HealthReport:
    """Health check report for a project environment.

    Attributes:
        status: Overall health status.
        environment_path: Path to the checked environment.
        python_ok: Whether the Python interpreter is functional.
        pip_ok: Whether pip is functional.
        dependencies_ok: Whether all dependencies are installed.
        missing_packages: List of missing package names.
        outdated_packages: List of outdated package names.
        checks: Individual check results.
        timestamp: When the report was generated.
    """

    status: HealthStatus = HealthStatus.UNKNOWN
    environment_path: Optional[Path] = None
    python_ok: bool = False
    pip_ok: bool = False
    dependencies_ok: bool = False
    missing_packages: list[str] = field(default_factory=list)
    outdated_packages: list[str] = field(default_factory=list)
    checks: dict[str, tuple[bool, str]] = field(default_factory=dict)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
