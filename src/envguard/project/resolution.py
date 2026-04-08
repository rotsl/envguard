# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""Resolution management - decide how to create an environment.

The :class:`ResolutionManager` takes host facts and project intent and
produces a :class:`ResolutionRecord` that describes exactly which Python
version, package manager, environment type, and accelerator target to
use, along with a step-by-step creation plan.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from envguard.exceptions import BrokenEnvironmentError
from envguard.logging import get_logger
from envguard.models import (
    AcceleratorTarget,
    EnvironmentType,
    FindingSeverity,
    HostFacts,
    PackageManager,
    ProjectIntent,
    ResolutionRecord,
    RuleFinding,
)

logger = get_logger("project.resolution")

#: Default directory name for virtual environments
_DEFAULT_VENV_DIR = ".venv"
#: Default conda environment name prefix
_CONDA_PREFIX = "envguard"
#: Path within the project root where resolutions are persisted
_RESOLUTION_DIR = ".envguard"


class ResolutionManager:
    """Resolve how to create a project environment.

    The resolution process considers the host capabilities (detected
    Python versions, available package managers, hardware) together with
    the project's requirements and produces a deterministic plan.
    """

    def __init__(
        self,
        project_dir: Path,
        facts: HostFacts,
        intent: ProjectIntent,
    ) -> None:
        self.project_dir = Path(project_dir).resolve()
        self.facts = facts
        self.intent = intent

    # ------------------------------------------------------------------ #
    # Public entry point
    # ------------------------------------------------------------------ #

    def resolve(self) -> ResolutionRecord:
        """Create a resolution record for the project.

        Returns:
            A fully populated ResolutionRecord.
        """
        logger.info("Creating resolution for %s", self.project_dir)

        record = ResolutionRecord(project_dir=self.project_dir)

        # Determine key parameters
        record.python_version = self.determine_python_version()
        record.package_manager = self.determine_package_manager()
        record.environment_type = self.determine_environment_type()
        record.accelerator_target = self.determine_accelerator()
        record.environment_path = self.determine_environment_path(
            record.environment_type, record.python_version
        )

        # Build creation plan
        record.plan = self.create_environment_plan()

        # Validate
        record.findings = self.validate_resolution(record)

        # Persist
        self.save_resolution(record)

        logger.info(
            "Resolution created: py=%s, pm=%s, env=%s, acc=%s, path=%s",
            record.python_version,
            record.package_manager.value,
            record.environment_type.value,
            record.accelerator_target.value,
            record.environment_path,
        )
        return record

    # ------------------------------------------------------------------ #
    # Individual decision methods
    # ------------------------------------------------------------------ #

    def determine_python_version(self) -> str:
        """Decide which Python version to use.

        Priority:
        1. Recommended version from intent analysis (if available).
        2. Explicitly required version from project files.
        3. System Python version.

        Returns:
            A Python version string like ``'3.11'``.
        """
        # Check for a recommendation from IntentAnalyzer
        recommended = self.intent.extra.get("recommended_python_version")
        if recommended:
            logger.debug("Using recommended Python: %s", recommended)
            return self._normalise_version(recommended)

        # Check explicit requirement
        if self.intent.python_version_required:
            version = self._normalise_version(self.intent.python_version_required)
            logger.debug("Using required Python: %s", version)
            return version

        # Fall back to system Python
        version = self._normalise_version(self.facts.python_version)
        if version != "unknown":
            logger.debug("Using system Python: %s", version)
            return version

        # Ultimate fallback
        logger.debug("Using default Python: 3.11")
        return "3.11"

    def determine_package_manager(self) -> PackageManager:
        """Decide which package manager to use.

        Priority:
        1. First inferred package manager that is available on the host.
        2. ``pip`` (universal fallback).

        Returns:
            The chosen PackageManager.
        """
        # Map managers to availability checks
        availability: dict[PackageManager, bool] = {
            PackageManager.PIP: self.facts.has_pip,
            PackageManager.CONDA: self.facts.has_conda,
            PackageManager.MAMBA: self.facts.has_mamba,
        }

        for mgr in self.intent.package_managers:
            if availability.get(mgr, False):
                logger.debug("Using package manager: %s", mgr.value)
                return mgr

        # Environment type-based fallback
        if self.intent.environment_type in (
            EnvironmentType.CONDA,
            EnvironmentType.MAMBA,
        ):
            if self.facts.has_mamba:
                return PackageManager.MAMBA
            if self.facts.has_conda:
                return PackageManager.CONDA

        # Default: pip
        logger.debug("Defaulting to pip")
        return PackageManager.PIP

    def determine_environment_type(self) -> EnvironmentType:
        """Decide the environment type.

        Returns:
            The chosen EnvironmentType.
        """
        # Use the recommendation from IntentAnalyzer if available
        recommended = self.intent.extra.get("recommended_environment_type")
        if recommended:
            try:
                env_type = EnvironmentType(recommended)
                logger.debug("Using recommended env type: %s", env_type.value)
                return env_type
            except ValueError:
                pass

        # Use the detected type from discovery
        if self.intent.environment_type != EnvironmentType.UNKNOWN:
            return self.intent.environment_type

        return EnvironmentType.VENV

    def determine_environment_path(
        self,
        env_type: EnvironmentType,
        python_ver: str,
    ) -> Path:
        """Determine where the environment should be created.

        Args:
            env_type: The resolved environment type.
            python_ver: The resolved Python version.

        Returns:
            A Path for the environment directory.
        """
        safe_name = self._safe_dirname(self.intent.project_name or "project")

        if env_type in (EnvironmentType.CONDA, EnvironmentType.MAMBA):
            # Conda environments go into $HOME/envs or the conda envs dir
            # but we keep them local by default
            env_name = f"{_CONDA_PREFIX}-{safe_name}-py{python_ver}"
            return self.project_dir / _DEFAULT_VENV_DIR / env_name

        # venv, poetry, etc. → local .venv
        return self.project_dir / _DEFAULT_VENV_DIR

    def determine_accelerator(self) -> AcceleratorTarget:
        """Decide which accelerator target to use.

        Returns:
            The chosen AcceleratorTarget.
        """
        targets = self.intent.extra.get("accelerator_targets", [])

        if self.facts.os_name == "Darwin":
            # On macOS, prefer MPS if available
            if AcceleratorTarget.MPS.value in targets:
                logger.debug("Accelerator: MPS (macOS + Apple Silicon)")
                return AcceleratorTarget.MPS
            # CUDA is not available on macOS
            if AcceleratorTarget.CUDA.value in targets:
                logger.debug(
                    "CUDA requested but not available on macOS; falling back to CPU"
                )
                return AcceleratorTarget.CPU

        # If CUDA is available and needed
        if AcceleratorTarget.CUDA.value in targets:
            logger.debug("Accelerator: CUDA")
            return AcceleratorTarget.CUDA

        logger.debug("Accelerator: CPU (default)")
        return AcceleratorTarget.CPU

    # ------------------------------------------------------------------ #
    # Plan creation
    # ------------------------------------------------------------------ #

    def create_environment_plan(self) -> dict[str, Any]:
        """Build a full environment creation plan.

        Returns:
            A dict describing each step of the environment creation.
        """
        env_type = self.determine_environment_type()
        pkg_mgr = self.determine_package_manager()
        py_ver = self.determine_python_version()
        acc = self.determine_accelerator()
        env_path = self.determine_environment_path(env_type, py_ver)

        steps: list[dict[str, str]] = []

        if env_type in (EnvironmentType.CONDA, EnvironmentType.MAMBA):
            steps.append({
                "action": "create_conda_env",
                "description": f"Create {env_type.value} environment with Python {py_ver}",
                "command": self._conda_create_cmd(py_ver, env_type, env_path),
            })
            steps.append({
                "action": "activate_conda_env",
                "description": "Activate the conda environment",
                "command": f"conda activate {env_path}",
            })
            if self.intent.dependencies:
                steps.append({
                    "action": "install_dependencies",
                    "description": f"Install {len(self.intent.dependencies)} dependencies",
                    "command": "conda install --yes " + " ".join(
                        f'"{d}"' for d in self.intent.dependencies[:20]
                    ),
                })
            # Install remaining deps with pip if needed
            if pkg_mgr == PackageManager.PIP and self.intent.dependencies:
                steps.append({
                    "action": "pip_install_dependencies",
                    "description": "Install pip-only dependencies",
                    "command": "pip install " + " ".join(
                        f'"{d}"' for d in self.intent.dependencies[:20]
                    ),
                })
        else:
            # venv-based
            steps.append({
                "action": "create_venv",
                "description": f"Create virtual environment with Python {py_ver}",
                "command": f"python3 -m venv {env_path}",
            })
            steps.append({
                "action": "upgrade_pip",
                "description": "Upgrade pip in the virtual environment",
                "command": f"{env_path / 'bin' / 'pip'} install --upgrade pip",
            })
            if self.intent.dependencies:
                steps.append({
                    "action": "install_dependencies",
                    "description": f"Install {len(self.intent.dependencies)} dependencies",
                    "command": f"{env_path / 'bin' / 'pip'} install " + " ".join(
                        f'"{d}"' for d in self.intent.dependencies[:20]
                    ),
                })
            if self.intent.dev_dependencies:
                steps.append({
                    "action": "install_dev_dependencies",
                    "description": f"Install {len(self.intent.dev_dependencies)} dev dependencies",
                    "command": f"{env_path / 'bin' / 'pip'} install " + " ".join(
                        f'"{d}"' for d in self.intent.dev_dependencies[:20]
                    ),
                })

        # Wheelhouse
        if self.intent.has_wheelhouse and self.intent.wheelhouse_path:
            steps.append({
                "action": "install_from_wheelhouse",
                "description": f"Install wheels from {self.intent.wheelhouse_path}",
                "command": (
                    f"{env_path / 'bin' / 'pip'} install --no-index "
                    f"--find-links {self.intent.wheelhouse_path} ."
                ),
            })

        plan: dict[str, Any] = {
            "project_dir": str(self.project_dir),
            "environment_type": env_type.value,
            "package_manager": pkg_mgr.value,
            "python_version": py_ver,
            "accelerator_target": acc.value,
            "environment_path": str(env_path),
            "dependency_count": self.intent.dependency_count,
            "steps": steps,
            "estimated_disk_mb": max(
                50, self.intent.dependency_count * 15
            ),
        }

        return plan

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #

    def validate_resolution(self, resolution: ResolutionRecord) -> list[RuleFinding]:
        """Validate a resolution for potential issues.

        Args:
            resolution: The resolution to validate.

        Returns:
            A list of RuleFinding objects (may include warnings/errors).
        """
        findings: list[RuleFinding] = []

        # Check Python version
        if resolution.python_version == "unknown":
            findings.append(RuleFinding(
                rule_id="resolution.python-version",
                severity=FindingSeverity.ERROR,
                message="Could not determine a suitable Python version",
            ))

        # Check for unsupported features on macOS
        if (
            self.facts.os_name == "Darwin"
            and resolution.accelerator_target == AcceleratorTarget.CUDA
        ):
            findings.append(RuleFinding(
                rule_id="resolution.cuda-on-macos",
                severity=FindingSeverity.ERROR,
                message="CUDA acceleration is not available on macOS",
                details={"suggestion": "Use MPS or CPU instead"},
            ))

        # Check that the package manager is available
        if resolution.package_manager == PackageManager.CONDA and not self.facts.has_conda:
            findings.append(RuleFinding(
                rule_id="resolution.conda-not-available",
                severity=FindingSeverity.ERROR,
                message="Conda is required but not installed",
                details={"suggestion": "Install miniconda or switch to pip"},
            ))

        if resolution.package_manager == PackageManager.MAMBA and not self.facts.has_mamba:
            findings.append(RuleFinding(
                rule_id="resolution.mamba-not-available",
                severity=FindingSeverity.WARNING,
                message="Mamba is preferred but not installed; falling back to conda",
                details={"suggestion": "Install mamba via conda"},
            ))

        # Check project directory write permission
        if not self.facts.project_dir_writable:
            findings.append(RuleFinding(
                rule_id="resolution.project-dir-writable",
                severity=FindingSeverity.ERROR,
                message="Project directory is not writable",
                details={"path": str(self.project_dir)},
            ))

        # Check network for initial dependency installation
        if self.facts.network_available is False and not self.intent.has_wheelhouse:
            findings.append(RuleFinding(
                rule_id="resolution.network-unavailable",
                severity=FindingSeverity.WARNING,
                message="Network is unavailable and no wheelhouse exists; "
                        "offline installation may fail",
            ))

        # Check Python availability
        if resolution.python_version != "unknown":
            sys_ver = self._parse_version_tuple(self.facts.python_version)
            req_ver = self._parse_version_tuple(resolution.python_version)
            if sys_ver and req_ver and req_ver > sys_ver:
                findings.append(RuleFinding(
                    rule_id="resolution.python-version-mismatch",
                    severity=FindingSeverity.WARNING,
                    message=(
                        f"Required Python {resolution.python_version} is newer "
                        f"than system Python {self.facts.python_version}"
                    ),
                    details={"suggestion": "Install the required Python version via pyenv"},
                ))

        # Warn if no venv module
        if (
            resolution.environment_type == EnvironmentType.VENV
            and not self.facts.has_venv
        ):
            findings.append(RuleFinding(
                rule_id="resolution.venv-unavailable",
                severity=FindingSeverity.ERROR,
                message="venv module is not available; cannot create virtual environment",
            ))

        return findings

    # ------------------------------------------------------------------ #
    # Persistence
    # ------------------------------------------------------------------ #

    def save_resolution(self, resolution: ResolutionRecord) -> Path:
        """Persist a resolution to disk.

        Args:
            resolution: The resolution to save.

        Returns:
            Path to the saved JSON file.
        """
        res_dir = self.project_dir / _RESOLUTION_DIR
        try:
            res_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise BrokenEnvironmentError(
                env_path=str(res_dir),
                reason=f"Cannot create resolution directory: {exc}",
            ) from exc

        res_file = res_dir / "resolution.json"

        # Serialise
        data = {
            "id": resolution.id,
            "project_dir": str(resolution.project_dir),
            "python_version": resolution.python_version,
            "package_manager": resolution.package_manager.value,
            "environment_type": resolution.environment_type.value,
            "environment_path": str(resolution.environment_path),
            "accelerator_target": resolution.accelerator_target.value,
            "created_at": resolution.created_at,
            "findings": [
                {
                    "rule_id": f.rule_id,
                    "severity": f.severity.value,
                    "message": f.message,
                    "details": f.details,
                }
                for f in resolution.findings
            ],
            "plan": resolution.plan,
            "extra": resolution.extra,
        }

        try:
            res_file.write_text(
                json.dumps(data, indent=2, default=str),
                encoding="utf-8",
            )
            logger.info("Resolution saved to %s", res_file)
        except OSError as exc:
            raise BrokenEnvironmentError(
                env_path=str(res_file),
                reason=f"Cannot save resolution: {exc}",
            ) from exc

        return res_file

    @classmethod
    def from_saved(cls, project_dir: Path) -> ResolutionRecord | None:
        """Load a previously saved resolution.

        Args:
            project_dir: The project root directory.

        Returns:
            A ResolutionRecord if a saved resolution exists, else None.
        """
        res_file = Path(project_dir).resolve() / _RESOLUTION_DIR / "resolution.json"
        if not res_file.is_file():
            logger.debug("No saved resolution found at %s", res_file)
            return None

        try:
            data = json.loads(res_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load saved resolution: %s", exc)
            return None

        record = ResolutionRecord(
            id=data.get("id", ""),
            project_dir=Path(data.get("project_dir", ".")),
            python_version=data.get("python_version", "3.11"),
            package_manager=PackageManager(data.get("package_manager", "pip")),
            environment_type=EnvironmentType(data.get("environment_type", "venv")),
            environment_path=Path(data.get("environment_path", ".")),
            accelerator_target=AcceleratorTarget(
                data.get("accelerator_target", "cpu")
            ),
            created_at=data.get("created_at", ""),
            findings=[
                RuleFinding(
                    rule_id=f["rule_id"],
                    severity=FindingSeverity(f["severity"]),
                    message=f["message"],
                    details=f.get("details", {}),
                )
                for f in data.get("findings", [])
            ],
            plan=data.get("plan", {}),
            extra=data.get("extra", {}),
        )

        logger.info("Loaded saved resolution from %s", res_file)
        return record

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _normalise_version(version_str: str) -> str:
        """Normalise a version string to ``'X.Y'`` format.

        Handles specifiers like ``>=3.11``, ``~=3.10.5``, bare
        ``3.11.7``, etc.

        Args:
            version_str: A version-like string.

        Returns:
            A ``'X.Y'`` version string, or the original if unparseable.
        """
        cleaned = version_str.strip()
        # Remove specifiers
        for prefix in (">=", "<=", "==", "!=", "~=", ">", "<", "^"):
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix):].strip()

        parts = cleaned.replace(" ", "").split(".")
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            return f"{parts[0]}.{parts[1]}"
        return version_str.strip()

    @staticmethod
    def _parse_version_tuple(version_str: str) -> tuple[int, ...] | None:
        """Parse a version string into a tuple of ints."""
        import re as _re
        cleaned = version_str.strip()
        match = _re.match(r"(\d+)\.(\d+)", cleaned)
        if match:
            return (int(match.group(1)), int(match.group(2)))
        return None

    @staticmethod
    def _safe_dirname(name: str) -> str:
        """Convert a project name into a safe directory name.

        Args:
            name: Arbitrary project name.

        Returns:
            A filesystem-safe string.
        """
        import re as _re
        safe = _re.sub(r"[^a-zA-Z0-9._-]", "_", name)
        safe = safe.strip("._-")
        return safe or "project"

    @staticmethod
    def _conda_create_cmd(
        py_ver: str,
        env_type: EnvironmentType,
        env_path: Path,
    ) -> str:
        """Build the conda/mamba environment creation command.

        Args:
            py_ver: Python version.
            env_type: Environment type (conda or mamba).
            env_path: Target path.

        Returns:
            A shell command string.
        """
        mgr = "mamba" if env_type == EnvironmentType.MAMBA else "conda"
        return (
            f"{mgr} create --prefix {env_path} "
            f"python={py_ver} --yes"
        )
