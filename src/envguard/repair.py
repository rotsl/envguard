# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""Repair engine – diagnose and fix broken Python environments.

Provides automated repair operations including environment recreation,
dependency reinstallation, ownership fixes, and Python version switching.
Every mutation operation records enough state for rollback on failure.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from envguard.models import (
    HostFacts,
    ProjectIntent,
    RuleFinding,
    FindingSeverity,
    RepairAction,
    ResolutionRecord,
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
    RepairError,
    EnvironmentCreationError,
)
from envguard.logging import get_logger
from envguard.rules import RulesEngine

logger = get_logger("envguard.repair")


class RepairEngine:
    """Automated repair for broken or misconfigured Python environments.

    Parameters
    ----------
    project_dir:
        Root directory of the project whose environment needs repair.
    facts:
        Host system facts snapshot.
    intent:
        Project requirements.  When *None*, the engine will attempt to
        discover intent from the project directory.
    """

    def __init__(
        self,
        project_dir: Path,
        facts: HostFacts,
        intent: Optional[ProjectIntent] = None,
    ) -> None:
        self._project_dir = Path(project_dir)
        self._facts = facts
        self._intent = intent
        self._backup_path: Optional[Path] = None
        self._repair_log: list[str] = []
        self._env_path: Optional[Path] = None

        if intent is None:
            self._intent = self._discover_intent()

        # Normalise facts
        self._normalise_facts()
        # Normalise intent
        self._normalise_intent()

        # Infer the environment path
        self._env_path = self._infer_env_path()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def repair(self) -> ResolutionRecord:
        """Main repair entry point.

        Analyses the broken state, builds a repair plan, executes each
        repairable finding, and returns a :class:`ResolutionRecord`.

        Raises
        ------
        RepairError
            If the overall repair fails and rollback also fails.
        """
        logger.info("Starting repair for project at '%s'", self._project_dir)
        self._repair_log = []

        env_type = self._intent.environment_type if self._intent else EnvironmentType.VENV

        resolution = ResolutionRecord(
            project_dir=self._project_dir,
            environment_type=env_type,
            python_version=self._facts.python_version,
            environment_path=self._env_path or Path(""),
            accelerator_target=(self._intent.accelerator_target
                                if self._intent else AcceleratorTarget.CPU),
        )
        resolution.resolution_id = resolution.id

        # Step 1: Analyse the current broken state
        findings = self.analyze_broken_state()
        resolution.findings_addressed = [f.rule_id for f in findings]

        if not findings:
            resolution.success = True
            resolution.notes.append("No issues found - environment is healthy.")
            logger.info("No repair needed.")
            return resolution

        # Step 2: Determine which findings are auto-repairable
        repairable = [f for f in findings if f.auto_repairable]
        manual = [f for f in findings if not f.auto_repairable]

        if manual:
            for f in manual:
                recommendation = self.recommend_alternative(f)
                resolution.notes.append(f"MANUAL: {f.rule_id}: {recommendation}")
                logger.warning("Manual intervention required: %s - %s",
                               f.rule_id, recommendation)

        if not repairable:
            resolution.success = False
            resolution.notes.append("No auto-repairable findings. Manual intervention required.")
            return resolution

        # Step 3: Execute repairs
        for finding in repairable:
            logger.info("Repairing: %s (%s)", finding.rule_id, finding.repair_action)
            try:
                success = self.repair_finding(finding)
                if success:
                    self._repair_log.append(f"OK: {finding.rule_id}")
                    action_val = finding.repair_action.value if finding.repair_action else "unknown"
                    resolution.repair_actions_taken.append(f"{finding.rule_id}:{action_val}")
                else:
                    self._repair_log.append(f"FAIL: {finding.rule_id}")
                    resolution.notes.append(f"Repair failed for {finding.rule_id}: {finding.message}")
            except Exception as exc:
                error_msg = f"Exception during repair of {finding.rule_id}: {exc}"
                logger.error(error_msg)
                resolution.notes.append(error_msg)
                self._repair_log.append(f"ERROR: {finding.rule_id}: {exc}")

        # Step 4: Final validation
        if self._repair_log:
            all_ok = all(entry.startswith("OK:") for entry in self._repair_log)
            resolution.success = all_ok
        else:
            resolution.success = True

        resolution.timestamp = datetime.now(timezone.utc).isoformat()
        logger.info(
            "Repair complete - success=%s, actions=%s",
            resolution.success,
            len(resolution.repair_actions_taken),
        )
        return resolution

    def analyze_broken_state(self) -> list[RuleFinding]:
        """Evaluate the current state and return findings for issues."""
        if self._intent is None:
            self._intent = self._discover_intent()

        engine = RulesEngine(self._facts, self._intent)
        return engine.evaluate()

    def recreate_environment(self, resolution: ResolutionRecord) -> bool:
        """Tear down the old environment and create a fresh one.

        Steps:
        1. Back up the old environment (pip freeze backup)
        2. Remove the old environment directory
        3. Create a new environment (venv or conda)
        4. Install dependencies
        5. Validate the new environment
        """
        logger.info("Recreating environment at '%s'", self._env_path)
        env_path = self._env_path

        if env_path is None:
            env_path = self._infer_env_path()
            self._env_path = env_path

        if env_path is None:
            logger.error("Cannot determine environment path.")
            return False

        # -- 1. Backup ----------------------------------------------------------
        try:
            backup_path = self._backup_environment(env_path)
            self._backup_path = backup_path
            logger.info("Environment backed up to '%s'", backup_path)
        except Exception as exc:
            logger.warning("Backup failed (continuing anyway): %s", exc)
            self._backup_path = None

        # -- 2. Remove old environment ------------------------------------------
        try:
            if env_path.exists():
                shutil.rmtree(env_path, ignore_errors=False)
                logger.info("Old environment removed.")
        except OSError as exc:
            logger.error("Failed to remove old environment: %s", exc)
            if self._backup_path:
                self._rollback_on_failure(self._backup_path)
            return False

        # -- 3. Create new environment -------------------------------------------
        python_version = resolution.python_version or self._facts.python_version
        created = False

        if (self._intent
                and self._intent.environment_type == EnvironmentType.CONDA
                and self._facts.has_conda):
            env_name = self._project_dir.name
            created = self._create_conda_env(python_version, env_name)
            if created:
                conda_env_path = self._find_conda_env(env_name)
                if conda_env_path:
                    self._env_path = conda_env_path
                    resolution.environment_path = conda_env_path
                    env_path = conda_env_path
        else:
            created = self._create_venv(python_version, env_path)

        if not created:
            logger.error("Failed to create new environment.")
            if self._backup_path:
                self._rollback_on_failure(self._backup_path)
            return False

        # -- 4. Install dependencies ---------------------------------------------
        installed = self._install_dependencies(resolution)
        if not installed:
            logger.error("Dependency installation failed.")
            if self._backup_path:
                self._rollback_on_failure(self._backup_path)
            return False

        # -- 5. Validate --------------------------------------------------------
        validated = self._validate_repair()
        if not validated:
            logger.error("Environment validation failed after recreation.")
            if self._backup_path:
                self._rollback_on_failure(self._backup_path)
            return False

        resolution.environment_path = env_path
        resolution.success = True
        resolution.notes.append(f"Environment recreated at {env_path}")
        logger.info("Environment recreated successfully at '%s'", env_path)
        return True

    def fix_mixed_ownership(self) -> bool:
        """Fix pip/conda mixed ownership issues in a conda environment.

        Strategy:
        1. Export current pip packages with ``pip freeze``
        2. Uninstall all pip packages
        3. Reinstall packages that are available via conda
        4. Install remaining packages with ``pip --no-deps``
        """
        env_path = self._env_path
        if env_path is None or not env_path.exists():
            logger.warning("No environment path - cannot fix mixed ownership.")
            return False

        if not self._is_conda_env(env_path):
            logger.info("Not a conda environment - mixed ownership fix not applicable.")
            return True

        python_bin = self._find_env_python(env_path)
        if python_bin is None:
            logger.error("Cannot find Python binary in environment.")
            return False

        # Export pip packages
        try:
            result = subprocess.run(
                [str(python_bin), "-m", "pip", "freeze"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                logger.error("pip freeze failed: %s", result.stderr)
                return False
            pip_packages = result.stdout.strip().splitlines()
        except (subprocess.TimeoutExpired, OSError) as exc:
            logger.error("pip freeze raised: %s", exc)
            return False

        if not pip_packages:
            logger.info("No pip packages to fix.")
            return True

        # Try conda-unpack using the actual conda env name from environment.yml or path
        conda_env_name = self._get_conda_env_name(env_path)
        try:
            result = subprocess.run(
                ["conda", "run", "-n", conda_env_name, "conda-unpack"],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode == 0:
                logger.info("conda-unpack succeeded.")
                return True
        except (subprocess.TimeoutExpired, OSError):
            pass

        # Fallback: reinstall via conda where possible, pip --no-deps otherwise
        conda_installable: list[str] = []
        pip_only: list[str] = []

        conda_common = {
            "numpy", "scipy", "pandas", "matplotlib", "scikit-learn",
            "pillow", "requests", "flask", "django", "pytest",
            "click", "six", "pyyaml", "cryptography", "jinja2",
        }

        for pkg_line in pip_packages:
            pkg_name = pkg_line.split("==")[0].strip().lower()
            if pkg_name in conda_common:
                conda_installable.append(pkg_name)
            else:
                pip_only.append(pkg_line)

        success = True

        # Uninstall all pip packages first
        try:
            proc_input = "\n".join(pip_packages)
            result = subprocess.run(
                [str(python_bin), "-m", "pip", "uninstall", "-y", "-r", "/dev/stdin"],
                input=proc_input,
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode != 0:
                logger.warning("pip uninstall returned non-zero: %s", result.stderr)
        except (subprocess.TimeoutExpired, OSError):
            pass

        # Reinstall conda-available packages
        if conda_installable:
            try:
                result = subprocess.run(
                    ["conda", "install", "-y", "--name",
                     self._project_dir.name] + conda_installable,
                    capture_output=True, text=True, timeout=300,
                )
                if result.returncode != 0:
                    logger.warning("conda install failed for some packages.")
                    success = False
            except (subprocess.TimeoutExpired, OSError):
                logger.warning("conda install timed out.")
                success = False

        # Reinstall remaining via pip --no-deps
        if pip_only:
            try:
                pip_args = [str(python_bin), "-m", "pip", "install",
                            "--no-deps"] + pip_only
                result = subprocess.run(
                    pip_args, capture_output=True, text=True, timeout=300,
                )
                if result.returncode != 0:
                    logger.warning("pip install --no-deps failed for some packages.")
                    success = False
            except (subprocess.TimeoutExpired, OSError):
                logger.warning("pip install --no-deps timed out.")
                success = False

        if success:
            logger.info("Mixed ownership fix complete.")
        return success

    def switch_python_version(self, target_version: str) -> bool:
        """Switch the project's Python to a specific version.

        Parameters
        ----------
        target_version:
            Desired Python version (e.g. ``"3.11"`` or ``"3.11.5"``).
        """
        logger.info("Switching Python to version '%s'", target_version)

        match = re.match(r"(\d+)\.(\d+)", target_version.strip())
        if not match:
            logger.error("Invalid Python version format: '%s'", target_version)
            return False

        major, minor = match.group(1), match.group(2)
        version_str = f"{major}.{minor}"

        python_bin = self._find_python_version(version_str)
        if python_bin is None:
            logger.error("Python %s not found. Install via pyenv, brew, or conda.",
                         version_str)
            return False

        logger.info("Found Python %s at '%s'", version_str, python_bin)

        env_path = self._env_path or self._infer_env_path()
        if env_path is None:
            logger.error("Cannot determine environment path.")
            return False

        # Backup
        if env_path.exists():
            try:
                self._backup_environment(env_path)
            except Exception as exc:
                logger.warning("Backup failed: %s", exc)

        # Remove old env
        if env_path.exists():
            shutil.rmtree(env_path, ignore_errors=True)

        # Create new env
        resolution = ResolutionRecord(
            project_dir=self._project_dir,
            python_version=version_str,
            environment_path=env_path,
            environment_type=(self._intent.environment_type
                              if self._intent else EnvironmentType.VENV),
            packages_installed=(self._intent.dependencies[:]
                                if self._intent else []),
        )
        resolution.resolution_id = resolution.id

        result = subprocess.run(
            [str(python_bin), "-m", "venv", str(env_path)],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            logger.error("Failed to create venv with Python %s: %s",
                         version_str, result.stderr)
            return False

        # Install dependencies
        installed = self._install_dependencies(resolution)
        if not installed:
            logger.error("Dependency installation failed after Python switch.")
            return False

        logger.info("Python switched to %s successfully.", version_str)
        return True

    def recommend_alternative(self, finding: RuleFinding) -> str:
        """Generate a human-readable recommendation for a finding."""
        rule_id = finding.rule_id

        recommendations: dict[str, str] = {
            "CUDA_ON_MACOS": (
                "CUDA is not available on macOS. Alternatives:\n"
                "  1. Use Apple MPS: set accelerator='mps' in your framework config.\n"
                "     PyTorch: torch.backends.mps.is_available()\n"
                "  2. Use CPU fallback: set accelerator='cpu' for guaranteed compatibility.\n"
                "  3. Use a cloud GPU (e.g. AWS, GCP) for training workloads."
            ),
            "PLATFORM_NOT_MACOS": (
                "envguard is macOS-first. On Linux, consider:\n"
                "  1. Using standard Python tooling (venv, pip, conda).\n"
                "  2. The 'pyenv' ecosystem for version management."
            ),
            "ARCHITECTURE_MISMATCH": (
                f"Architecture mismatch detected. Recommended actions:\n"
                f"  1. Install a {finding.details.get('expected', 'native')} Python via:\n"
                f"     brew install python@3.x  (for arm64)\n"
                f"  2. Use pyenv to manage multiple Python installations."
            ),
            "PYTHON_VERSION_MISMATCH": (
                f"Python version mismatch. Recommended actions:\n"
                f"  1. Install the required version:\n"
                f"     brew install python@{finding.details.get('required', '3.x')}\n"
                f"     pyenv install {finding.details.get('required', '3.x')}\n"
                f"  2. Update .python-version or pyproject.toml to match."
            ),
            "MPS_NOT_AVAILABLE": (
                "MPS (Metal Performance Shaders) is not available:\n"
                "  1. Upgrade to macOS 12.3 (Monterey) or later.\n"
                "  2. Ensure you're on Apple Silicon hardware.\n"
                "  3. Fallback to CPU: set device='cpu' in your code."
            ),
            "ROSETTA_TRANSLATION_DETECTED": (
                "Running x86_64 Python under Rosetta 2:\n"
                "  1. Install native arm64 Python: brew install python@3.x\n"
                "  2. Ensure Terminal.app 'Open using Rosetta' is unchecked.\n"
                "  3. Use 'arch -arm64' prefix for commands."
            ),
            "INCOMPATIBLE_WHEEL": (
                f"Incompatible wheels detected: "
                f"{', '.join(finding.details.get('packages', []))}\n"
                "  1. Install Xcode CLI tools: xcode-select --install\n"
                "  2. Use --no-binary to force source builds.\n"
                "  3. Look for universal2 wheels on PyPI."
            ),
            "MIXED_PIP_CONDA_OWNERSHIP": (
                "Mixed pip/conda ownership detected:\n"
                "  1. Run 'envguard repair --fix-ownership' to auto-fix.\n"
                "  2. Or manually: pip freeze > backup.txt && pip uninstall -y -r backup.txt\n"
                "  3. Use 'conda-unpack' after pip operations."
            ),
            "SOURCE_BUILD_PREREQUISITES_MISSING": (
                "Xcode CLI tools required for building native extensions:\n"
                "  1. Install: xcode-select --install\n"
                "  2. Accept license: sudo xcodebuild -license accept"
            ),
            "STALE_ENVIRONMENT": (
                "Environment drift detected:\n"
                "  1. Update packages: pip install -r requirements.txt --upgrade\n"
                "  2. Or recreate: envguard repair --recreate"
            ),
            "NO_ENVIRONMENT": (
                "No environment found:\n"
                "  1. Create: python -m venv .venv && source .venv/bin/activate\n"
                "  2. Or use: envguard setup"
            ),
            "BROKEN_ENVIRONMENT": (
                "Broken environment detected:\n"
                "  1. Recreate: envguard repair --recreate\n"
                "  2. Manual: rm -rf .venv && python -m venv .venv"
            ),
            "NETWORK_UNAVAILABLE": (
                "Network access required but unavailable:\n"
                "  1. Check internet connection.\n"
                "  2. Set HTTPS_PROXY / HTTP_PROXY if behind proxy."
            ),
            "MISSING_PACKAGE_MANAGER": (
                f"Missing package manager: "
                f"{finding.details.get('required_manager', 'unknown')}\n"
                "  1. Install via Homebrew or official installer.\n"
                "  2. Ensure binary is on your PATH."
            ),
            "DEPENDENCY_CONFLICT": (
                f"Dependency conflict: {finding.message}\n"
                "  1. Pin conflicting packages to compatible versions.\n"
                "  2. Use pip's resolver: pip install --upgrade <packages>"
            ),
        }

        return recommendations.get(
            rule_id,
            f"No specific recommendation for '{rule_id}'. {finding.remediation}",
        )

    def repair_finding(self, finding: RuleFinding) -> bool:
        """Repair a single finding based on its repair action.

        Returns
        -------
        bool
            ``True`` if the repair succeeded, ``False`` otherwise.
        """
        action = finding.repair_action
        if action is None:
            logger.info("No repair action defined for %s - skipping.", finding.rule_id)
            return False

        dispatch = {
            RepairAction.RECOMMEND_ALTERNATIVE: self._repair_recommend_alternative,
            RepairAction.RECREATE_ENVIRONMENT: self._repair_recreate_environment,
            RepairAction.FIX_OWNERSHIP: self._repair_fix_ownership,
            RepairAction.SWITCH_PYTHON: self._repair_switch_python,
            RepairAction.INSTALL_MISSING: self._repair_install_missing,
            RepairAction.UPGRADE_TOOL: self._repair_upgrade_tool,
            RepairAction.REINSTALL_PACKAGES: self._repair_reinstall_packages,
            RepairAction.REBUILD_EXTENSIONS: self._repair_rebuild_extensions,
            RepairAction.MANUAL_INTERVENTION: self._repair_manual_intervention,
        }

        handler = dispatch.get(action)
        if handler is None:
            logger.warning("No repair handler for action '%s'", action.value)
            return False

        try:
            return handler(finding)
        except Exception as exc:
            logger.error("Repair handler for '%s' raised: %s", action.value, exc)
            return False

    def get_repair_plan(self) -> dict:
        """Analyse the current state and return a repair plan **without** executing.

        Returns
        -------
        dict
            Plan with keys: ``findings``, ``auto_repairable``, ``manual``,
            ``estimated_steps``, ``risks``, ``total_findings``, etc.
        """
        findings = self.analyze_broken_state()

        auto: list[dict[str, Any]] = []
        manual: list[dict[str, Any]] = []
        steps: list[str] = []
        risks: list[str] = []

        for f in findings:
            entry: dict[str, Any] = {
                "rule_id": f.rule_id,
                "severity": f.severity.value,
                "message": f.message,
                "remediation": f.remediation,
                "recommendation": self.recommend_alternative(f),
            }

            if f.auto_repairable:
                entry["action"] = (f.repair_action.value
                                   if f.repair_action else None)
                auto.append(entry)
                action_str = f.repair_action.value if f.repair_action else "unknown"
                steps.append(f"[AUTO] {f.rule_id}: {action_str}")
            else:
                manual.append(entry)
                steps.append(f"[MANUAL] {f.rule_id}: requires human intervention")

        if any(f.repair_action == RepairAction.RECREATE_ENVIRONMENT
               for f in findings):
            risks.append(
                "Environment recreation will remove all installed packages. "
                "A backup will be attempted.")

        if any(f.repair_action == RepairAction.FIX_OWNERSHIP
               for f in findings):
            risks.append(
                "Fixing pip/conda ownership may temporarily break imports "
                "until reinstallation completes.")

        if any(f.repair_action == RepairAction.SWITCH_PYTHON
               for f in findings):
            risks.append(
                "Switching Python version requires recreating the environment.")

        return {
            "findings": [f.rule_id for f in findings],
            "auto_repairable": auto,
            "manual": manual,
            "estimated_steps": steps,
            "risks": risks,
            "total_findings": len(findings),
            "auto_count": len(auto),
            "manual_count": len(manual),
        }

    # ------------------------------------------------------------------
    # Backup / rollback
    # ------------------------------------------------------------------

    def _backup_environment(self, env_path: Path) -> Path:
        """Create a backup of the environment.

        Returns
        -------
        Path
            Path to the backup directory.
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = self._project_dir / ".envguard" / "backups" / timestamp
        backup_dir.mkdir(parents=True, exist_ok=True)

        # Save pip freeze
        python_bin = self._find_env_python(env_path)
        if python_bin and python_bin.exists():
            try:
                result = subprocess.run(
                    [str(python_bin), "-m", "pip", "freeze"],
                    capture_output=True, text=True, timeout=30,
                )
                if result.returncode == 0:
                    freeze_file = backup_dir / "pip_freeze.txt"
                    freeze_file.write_text(result.stdout)
                    logger.debug("pip freeze saved to '%s'", freeze_file)
            except (subprocess.TimeoutExpired, OSError) as exc:
                logger.warning("pip freeze failed during backup: %s", exc)

        # Save conda env export
        if self._is_conda_env(env_path):
            try:
                result = subprocess.run(
                    ["conda", "env", "export"],
                    capture_output=True, text=True, timeout=30,
                )
                if result.returncode == 0:
                    conda_file = backup_dir / "conda_env.yml"
                    conda_file.write_text(result.stdout)
            except (subprocess.TimeoutExpired, OSError):
                pass

        # Save environment metadata
        meta = {
            "timestamp": timestamp,
            "original_path": str(env_path),
            "python_version": self._facts.python_version,
            "env_type": (self._intent.environment_type.value
                         if self._intent else "unknown"),
            "project_dir": str(self._project_dir),
        }
        meta_file = backup_dir / "backup_meta.json"
        meta_file.write_text(json.dumps(meta, indent=2))

        logger.info("Backup created at '%s'", backup_dir)
        return backup_dir

    def _rollback_on_failure(self, backup_path: Path) -> bool:
        """Attempt to restore from a backup after a failed repair."""
        logger.info("Attempting rollback from backup '%s'", backup_path)

        if not backup_path.exists():
            logger.error("Backup path does not exist: %s", backup_path)
            return False

        meta_file = backup_path / "backup_meta.json"
        if not meta_file.exists():
            logger.error("No backup metadata found - cannot rollback.")
            return False

        try:
            meta = json.loads(meta_file.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Cannot read backup metadata: %s", exc)
            return False

        original_path = Path(meta.get("original_path", ""))
        env_type = meta.get("env_type", "venv")

        if not original_path:
            logger.error("No original path in backup metadata.")
            return False

        # Remove current broken env
        if original_path.exists():
            try:
                shutil.rmtree(original_path)
            except OSError as exc:
                logger.error("Cannot remove broken environment: %s", exc)
                return False

        if env_type == "conda":
            conda_file = backup_path / "conda_env.yml"
            if conda_file.exists():
                try:
                    result = subprocess.run(
                        ["conda", "env", "create", "-f", str(conda_file)],
                        capture_output=True, text=True, timeout=300,
                    )
                    if result.returncode == 0:
                        logger.info("Conda environment restored from backup.")
                        return True
                except (subprocess.TimeoutExpired, OSError) as exc:
                    logger.error("conda env create failed: %s", exc)
            return False

        # For venv: recreate and reinstall from freeze
        try:
            result = subprocess.run(
                [sys.executable, "-m", "venv", str(original_path)],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode != 0:
                logger.error("venv creation failed during rollback: %s",
                             result.stderr)
                return False
        except (subprocess.TimeoutExpired, OSError) as exc:
            logger.error("venv creation failed during rollback: %s", exc)
            return False

        freeze_file = backup_path / "pip_freeze.txt"
        if freeze_file.exists():
            python_bin = self._find_env_python(original_path)
            if python_bin:
                try:
                    result = subprocess.run(
                        [str(python_bin), "-m", "pip", "install",
                         "-r", str(freeze_file)],
                        capture_output=True, text=True, timeout=300,
                    )
                    if result.returncode == 0:
                        logger.info("Rollback complete - packages restored.")
                        return True
                    else:
                        logger.warning("pip install from freeze failed during rollback.")
                except (subprocess.TimeoutExpired, OSError):
                    pass

        logger.warning("Partial rollback - venv created but packages may not be restored.")
        return True

    # ------------------------------------------------------------------
    # Environment creation
    # ------------------------------------------------------------------

    def _create_venv(self, python_version: str, env_path: Path) -> bool:
        """Create a virtual environment using ``python -m venv``."""
        logger.info("Creating venv at '%s' with Python %s", env_path, python_version)

        python_bin = self._find_python_version(python_version)
        if python_bin is None:
            python_bin = Path(sys.executable)
            logger.warning("Python %s not found - using system Python: %s",
                           python_version, python_bin)

        try:
            result = subprocess.run(
                [str(python_bin), "-m", "venv", str(env_path)],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode != 0:
                logger.error("venv creation failed: %s", result.stderr)
                return False
        except (subprocess.TimeoutExpired, OSError) as exc:
            logger.error("venv creation raised: %s", exc)
            return False

        # Upgrade pip
        new_python = self._find_env_python(env_path)
        if new_python:
            try:
                subprocess.run(
                    [str(new_python), "-m", "pip", "install",
                     "--upgrade", "pip", "--quiet"],
                    capture_output=True, text=True, timeout=60,
                )
            except (subprocess.TimeoutExpired, OSError):
                pass

        logger.info("venv created at '%s'", env_path)
        return True

    def _create_conda_env(self, python_version: str, env_name: str) -> bool:
        """Create a conda environment."""
        logger.info("Creating conda env '%s' with Python %s", env_name, python_version)

        self._remove_conda_env(env_name)

        try:
            result = subprocess.run(
                ["conda", "create", "-y", "-n", env_name,
                 f"python={python_version}", "pip"],
                capture_output=True, text=True, timeout=300,
            )
            if result.returncode != 0:
                logger.error("conda create failed: %s", result.stderr)
                return False
        except (subprocess.TimeoutExpired, OSError) as exc:
            logger.error("conda create raised: %s", exc)
            return False

        logger.info("conda env '%s' created.", env_name)
        return True

    def _remove_conda_env(self, env_name: str) -> bool:
        """Remove a conda environment by name."""
        try:
            result = subprocess.run(
                ["conda", "env", "remove", "-y", "-n", env_name],
                capture_output=True, text=True, timeout=60,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            return False

    # ------------------------------------------------------------------
    # Dependency installation
    # ------------------------------------------------------------------

    def _install_dependencies(self, resolution: ResolutionRecord) -> bool:
        """Install all project dependencies into the resolved environment."""
        env_path = resolution.environment_path
        if not env_path or not Path(env_path).exists():
            logger.error("No environment path in resolution.")
            return False

        python_bin = self._find_env_python(Path(env_path))
        if python_bin is None:
            logger.error("Cannot find Python in environment: %s", env_path)
            return False

        all_deps = list(resolution.packages_installed)
        if not all_deps:
            req_file = self._project_dir / "requirements.txt"
            if req_file.exists():
                return self._install_from_requirements(python_bin, req_file)

            pyproject = self._project_dir / "pyproject.toml"
            if pyproject.exists():
                return self._install_from_pyproject(python_bin, pyproject)

            logger.info("No dependencies to install.")
            return True

        try:
            result = subprocess.run(
                [str(python_bin), "-m", "pip", "install"] + all_deps,
                capture_output=True, text=True, timeout=600,
            )
            if result.returncode != 0:
                stderr_tail = (result.stderr[-500:]
                               if len(result.stderr) > 500
                               else result.stderr)
                logger.error("pip install failed: %s", stderr_tail)
                return False
        except subprocess.TimeoutExpired:
            logger.error("pip install timed out.")
            return False
        except OSError as exc:
            logger.error("pip install raised: %s", exc)
            return False

        # Update resolution
        installed = self._list_installed(python_bin)
        if installed:
            resolution.packages_installed = list(installed)

        logger.info("Dependencies installed successfully.")
        return True

    def _install_from_requirements(self, python_bin: Path,
                                    req_file: Path) -> bool:
        """Install from a requirements.txt file."""
        logger.info("Installing from requirements.txt: %s", req_file)
        try:
            result = subprocess.run(
                [str(python_bin), "-m", "pip", "install",
                 "-r", str(req_file)],
                capture_output=True, text=True, timeout=600,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, OSError) as exc:
            logger.error("pip install -r failed: %s", exc)
            return False

    def _install_from_pyproject(self, python_bin: Path,
                                 pyproject: Path) -> bool:
        """Install from a pyproject.toml file using pip."""
        logger.info("Installing from pyproject.toml: %s", pyproject)
        try:
            # Try editable install first
            result = subprocess.run(
                [str(python_bin), "-m", "pip", "install", "-e",
                 str(self._project_dir)],
                capture_output=True, text=True, timeout=600,
            )
            if result.returncode == 0:
                return True
            # Fallback
            result2 = subprocess.run(
                [str(python_bin), "-m", "pip", "install", "."],
                capture_output=True, text=True, timeout=600,
                cwd=str(self._project_dir),
            )
            return result2.returncode == 0
        except (subprocess.TimeoutExpired, OSError) as exc:
            logger.error("pip install from pyproject.toml failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate_repair(self) -> bool:
        """Validate that the repaired environment is functional."""
        if self._env_path is None or not self._env_path.exists():
            return False

        python_bin = self._find_env_python(self._env_path)
        if python_bin is None:
            return False

        try:
            result = subprocess.run(
                [str(python_bin), "--version"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                return False
        except (subprocess.TimeoutExpired, OSError):
            return False

        try:
            result = subprocess.run(
                [str(python_bin), "-m", "pip", "--version"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                return False
        except (subprocess.TimeoutExpired, OSError):
            return False

        return True

    # ------------------------------------------------------------------
    # Individual repair handlers
    # ------------------------------------------------------------------

    def _repair_recommend_alternative(self, finding: RuleFinding) -> bool:
        """Handle RECOMMEND_ALTERNATIVE."""
        if finding.rule_id == "CUDA_ON_MACOS":
            if self._intent:
                self._intent.requires_cuda = False
                self._intent.has_cuda_requirements = False
                self._intent.accelerator_target = AcceleratorTarget.MPS
                self._intent.has_mps_requirements = True
                self._intent.requires_mps = True
                logger.info("Updated intent: CUDA -> MPS")
                return True

        recommendation = self.recommend_alternative(finding)
        logger.info("Recommendation for %s: %s", finding.rule_id, recommendation)
        return True

    def _repair_recreate_environment(self, finding: RuleFinding) -> bool:
        """Handle RECREATE_ENVIRONMENT."""
        env_type = (self._intent.environment_type
                    if self._intent else EnvironmentType.VENV)
        resolution = ResolutionRecord(
            project_dir=self._project_dir,
            environment_type=env_type,
            python_version=self._facts.python_version,
            environment_path=self._env_path or Path(""),
            packages_installed=(self._intent.dependencies[:]
                                if self._intent else []),
        )
        resolution.resolution_id = resolution.id
        return self.recreate_environment(resolution)

    def _repair_fix_ownership(self, finding: RuleFinding) -> bool:
        """Handle FIX_OWNERSHIP."""
        return self.fix_mixed_ownership()

    def _repair_switch_python(self, finding: RuleFinding) -> bool:
        """Handle SWITCH_PYTHON."""
        target = (finding.details.get("required")
                  or finding.details.get("expected"))
        if not target:
            logger.error("No target Python version in finding details.")
            return False
        return self.switch_python_version(target)

    def _repair_install_missing(self, finding: RuleFinding) -> bool:
        """Handle INSTALL_MISSING."""
        missing = finding.details.get("missing", [])
        if not missing:
            return True

        python_bin = (self._find_env_python(Path(self._env_path))
                      if self._env_path else None)
        if python_bin is None:
            python_bin = Path(sys.executable)

        try:
            result = subprocess.run(
                [str(python_bin), "-m", "pip", "install"] + missing,
                capture_output=True, text=True, timeout=300,
            )
            if result.returncode == 0:
                logger.info("Installed missing packages: %s",
                            ", ".join(missing))
                return True
            logger.error("Failed to install missing packages: %s",
                         result.stderr[-300:])
            return False
        except (subprocess.TimeoutExpired, OSError) as exc:
            logger.error("pip install for missing packages failed: %s", exc)
            return False

    def _repair_upgrade_tool(self, finding: RuleFinding) -> bool:
        """Handle UPGRADE_TOOL."""
        if "pip" in finding.rule_id.lower() or "pip" in finding.remediation.lower():
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "install",
                     "--upgrade", "pip", "--force-reinstall"],
                    capture_output=True, text=True, timeout=60,
                )
                return result.returncode == 0
            except (subprocess.TimeoutExpired, OSError):
                return False

        if "conda" in finding.rule_id.lower() or "conda" in finding.remediation.lower():
            try:
                result = subprocess.run(
                    ["conda", "update", "-y", "conda"],
                    capture_output=True, text=True, timeout=120,
                )
                return result.returncode == 0
            except (subprocess.TimeoutExpired, OSError):
                return False

        return False

    def _repair_reinstall_packages(self, finding: RuleFinding) -> bool:
        """Handle REINSTALL_PACKAGES."""
        env_type = (self._intent.environment_type
                    if self._intent else EnvironmentType.VENV)
        resolution = ResolutionRecord(
            project_dir=self._project_dir,
            environment_type=env_type,
            python_version=self._facts.python_version,
            environment_path=self._env_path or Path(""),
            packages_installed=(self._intent.dependencies[:]
                                if self._intent else []),
        )
        resolution.resolution_id = resolution.id
        return self._install_dependencies(resolution)

    def _repair_rebuild_extensions(self, finding: RuleFinding) -> bool:
        """Handle REBUILD_EXTENSIONS."""
        packages = finding.details.get("packages", [])
        if not packages:
            return True

        python_bin = (self._find_env_python(Path(self._env_path))
                      if self._env_path else None)
        if python_bin is None:
            python_bin = Path(sys.executable)

        try:
            result = subprocess.run(
                [str(python_bin), "-m", "pip", "install",
                 "--no-binary", ":all:"] + packages,
                capture_output=True, text=True, timeout=600,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            return False

    def _repair_manual_intervention(self, finding: RuleFinding) -> bool:
        """Handle MANUAL_INTERVENTION - cannot auto-repair."""
        recommendation = self.recommend_alternative(finding)
        logger.info("Manual intervention required for %s: %s",
                    finding.rule_id, recommendation)
        return False

    # ------------------------------------------------------------------
    # Normalisation helpers
    # ------------------------------------------------------------------

    def _normalise_facts(self) -> None:
        """Ensure extended HostFacts fields are populated."""
        f = self._facts
        if not f.is_macos:
            f.is_macos = (f.os_name == "Darwin")
        if f.architecture == Architecture.ARM64:
            f.is_apple_silicon = True
        if (f.is_macos and f.is_apple_silicon
                and not f.mps_available and f.os_version != "unknown"):
            try:
                parts = f.os_version.split(".")
                major = int(parts[0]) if parts else 0
                minor = int(parts[1]) if len(parts) > 1 else 0
                f.mps_available = (major, minor) >= (12, 3)
            except (ValueError, IndexError):
                pass
        if not f.pip_path and f.has_pip and f.python_path != "unknown":
            f.pip_path = f"{f.python_path} -m pip"
        if not f.conda_path and f.has_conda:
            f.conda_path = "conda"

    def _normalise_intent(self) -> None:
        """Ensure extended ProjectIntent fields are populated."""
        i = self._intent
        if i is None:
            return
        if i.has_cuda_requirements and not i.requires_cuda:
            i.requires_cuda = True
        if i.has_mps_requirements and not i.requires_mps:
            i.requires_mps = True
        if not i.name and i.project_name and i.project_name != "unknown":
            i.name = i.project_name
        if not i.name:
            i.name = i.project_dir.name if i.project_dir else "unnamed-project"
        if i.dependencies and not i.requires_network:
            i.requires_network = True

    # ------------------------------------------------------------------
    # Utility methods
    # ------------------------------------------------------------------

    def _discover_intent(self) -> ProjectIntent:
        """Discover project intent from the project directory."""
        try:
            mod = __import__("envguard.preflight", fromlist=["PreflightEngine"])
            engine = mod.PreflightEngine(self._project_dir)
            return engine._discover_project()
        except Exception:
            pass

        intent = ProjectIntent(project_dir=self._project_dir)
        intent.project_name = self._project_dir.name
        if (self._project_dir / "requirements.txt").exists():
            intent.has_requirements_txt = True
            intent.dependencies = self._read_requirements(
                self._project_dir / "requirements.txt")
        if (self._project_dir / "pyproject.toml").exists():
            intent.has_pyproject_toml = True
        if (self._project_dir / "environment.yml").exists():
            intent.has_conda_env_file = True
            intent.environment_type = EnvironmentType.CONDA
        return intent

    @staticmethod
    def _read_requirements(path: Path) -> list[str]:
        """Read requirements from a requirements.txt file."""
        deps: list[str] = []
        if not path.exists():
            return deps
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and not line.startswith("-"):
                deps.append(line)
        return deps

    def _infer_env_path(self) -> Optional[Path]:
        """Infer the environment path from project directory."""
        candidates = [
            self._project_dir / ".venv",
            self._project_dir / "venv",
            self._project_dir / ".conda",
            self._project_dir / "env",
        ]
        for c in candidates:
            if c.exists():
                return c

        env_type = (self._intent.environment_type
                    if self._intent else EnvironmentType.VENV)
        if env_type == EnvironmentType.CONDA:
            return self._project_dir / ".conda"
        return self._project_dir / ".venv"

    @staticmethod
    def _find_env_python(env_path: Path) -> Optional[Path]:
        """Find the Python binary in an environment."""
        for name in ("python3", "python"):
            candidate = env_path / "bin" / name
            if candidate.exists():
                return candidate
        return None

    def _get_conda_env_name(self, env_path: Path) -> str:
        """Return the conda environment name for *env_path*.

        Reads the name from ``environment.yml`` if present, then falls back
        to the final path component of the environment directory.
        """
        env_yml = self._project_dir / "environment.yml"
        if env_yml.is_file():
            try:
                for line in env_yml.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line.startswith("name:"):
                        name = line.split(":", 1)[1].strip()
                        if name:
                            return name
            except OSError:
                pass
        return env_path.name

    @staticmethod
    def _is_conda_env(env_path: Path) -> bool:
        """Check if a path is a conda environment."""
        return (env_path / "conda-meta").is_dir()

    @staticmethod
    def _find_conda_env(env_name: str) -> Optional[Path]:
        """Find the path to a conda environment by name."""
        try:
            result = subprocess.run(
                ["conda", "env", "list", "--json"],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                envs = data.get("envs", [])
                for env_path in envs:
                    if env_path.endswith(env_name) or Path(env_path).name == env_name:
                        return Path(env_path)
        except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError, KeyError):
            pass
        return None

    @staticmethod
    def _find_python_version(version: str) -> Optional[Path]:
        """Find a Python binary for a specific version."""
        # pyenv
        try:
            result = subprocess.run(
                ["pyenv", "which", f"python{version}"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                p = Path(result.stdout.strip())
                if p.exists():
                    return p
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        # Homebrew
        brew_paths = [
            Path(f"/opt/homebrew/bin/python{version}"),
            Path(f"/usr/local/bin/python{version}"),
        ]
        for p in brew_paths:
            if p.exists():
                return p

        # System PATH
        import shutil as _shutil
        python_bin = _shutil.which(f"python{version}")
        if python_bin:
            p = Path(python_bin)
            if p.exists():
                return p

        return None

    @staticmethod
    def _list_installed(python_bin: Path) -> Optional[set[str]]:
        """List installed packages using pip."""
        try:
            result = subprocess.run(
                [str(python_bin), "-m", "pip", "list",
                 "--format=freeze"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                packages = set()
                for line in result.stdout.strip().splitlines():
                    if "==" in line:
                        packages.add(line.split("==")[0].strip())
                return packages
        except (subprocess.TimeoutExpired, OSError):
            pass
        return None
