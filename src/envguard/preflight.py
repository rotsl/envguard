# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""Preflight engine – orchestrates the full preflight pipeline.

Pipeline steps
--------------
1. Detect host facts  (:meth:`_detect_host`)
2. Discover project   (:meth:`_discover_project`)
3. Analyze intent     (:meth:`_analyze_intent`)
4. Evaluate rules     (:meth:`_evaluate_rules`)
5. Create resolution  (:meth:`_create_resolution`)
6. Create / repair environment (if needed)
7. Validate environment
8. Smoke-test key imports
9. Return :class:`PreflightResult`
"""

from __future__ import annotations

import re
import subprocess
import sys
import uuid
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
    PreflightResult,
)
from envguard.exceptions import (
    CudaNotSupportedOnMacosError,
    IncompatibleWheelError,
    DependencyConflictError,
    BrokenEnvironmentError,
    PlatformNotSupportedError,
)
from envguard.logging import get_logger
from envguard.rules import RulesEngine

logger = get_logger("envguard.preflight")


class PreflightEngine:
    """Run the full preflight pipeline for a project.

    Parameters
    ----------
    project_dir:
        Root directory of the project to preflight.
    config:
        Optional configuration overrides.  When *None*, defaults are used.
    """

    def __init__(self, project_dir: Path, config: Optional[dict] = None) -> None:
        self._project_dir = Path(project_dir)
        self._config = config or {}
        self._findings: list[RuleFinding] = []
        self._errors: list[str] = []
        self._warnings: list[str] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, command: Optional[list[str]] = None) -> PreflightResult:
        """Execute the full preflight pipeline and return a result.

        Parameters
        ----------
        command:
            Optional command the user intends to run.  Recorded for auditing
            but does not affect rule evaluation.

        Returns
        -------
        PreflightResult
            Comprehensive result containing findings, resolution, environment
            validation status, and a human-readable summary.
        """
        logger.info("Starting preflight for project at '%s'", self._project_dir)

        result = PreflightResult()

        # -- Step 1: Detect host ------------------------------------------------
        try:
            facts = self._detect_host()
            result.host_facts = facts
            logger.info("Host detected: %s %s / Python %s",
                        facts.os_name, facts.os_version, facts.python_version)
        except Exception as exc:
            error_msg = f"Host detection failed: {exc}"
            logger.error(error_msg)
            self._errors.append(error_msg)
            result.errors = self._errors
            result.passed = False
            result.success = False
            result.summary = self._generate_summary(result)
            return result

        # -- Step 2: Discover project -------------------------------------------
        try:
            intent = self._discover_project()
            result.project_intent = intent
            logger.info("Project discovered: %s (env=%s)",
                        intent.project_name, intent.environment_type.value)
        except Exception as exc:
            error_msg = f"Project discovery failed: {exc}"
            logger.error(error_msg)
            self._errors.append(error_msg)
            result.errors = self._errors
            result.passed = False
            result.success = False
            result.summary = self._generate_summary(result)
            return result

        # -- Step 3: Analyze intent ---------------------------------------------
        try:
            intent = self._analyze_intent(intent, facts)
            result.project_intent = intent
        except Exception as exc:
            error_msg = f"Intent analysis failed: {exc}"
            logger.error(error_msg)
            self._errors.append(error_msg)

        # -- Step 4: Evaluate rules ---------------------------------------------
        try:
            self._findings = self._evaluate_rules(facts, intent)
            result.findings = self._findings
        except Exception as exc:
            error_msg = f"Rule evaluation failed: {exc}"
            logger.error(error_msg)
            self._errors.append(error_msg)

        # Populate warnings/errors lists from findings
        for f in self._findings:
            if f.severity == FindingSeverity.CRITICAL:
                self._errors.append(f"[{f.rule_id}] {f.message}")
            elif f.severity in (FindingSeverity.WARNING, FindingSeverity.ERROR):
                self._warnings.append(f"[{f.rule_id}] {f.message}")
        result.errors = self._errors
        result.warnings = self._warnings

        # -- Step 5: Check if we should fail fast --------------------------------
        if self._should_fail(self._findings):
            logger.error("Critical findings detected – preflight FAILED.")
            result.passed = False
            result.success = False
            result.summary = self._generate_summary(result)
            return result

        # -- Step 6: Create or validate resolution ------------------------------
        try:
            resolution = self._create_resolution(facts, intent, self._findings)
            result.resolution = resolution
        except Exception as exc:
            error_msg = f"Resolution creation failed: {exc}"
            logger.error(error_msg)
            self._errors.append(error_msg)
            result.errors = self._errors
            result.passed = False
            result.success = False
            result.summary = self._generate_summary(result)
            return result

        # -- Step 7: Create / repair environment if needed ----------------------
        if resolution and not resolution.success:
            try:
                self._repair_environment(facts, intent, resolution)
            except Exception as exc:
                error_msg = f"Environment repair/creation failed: {exc}"
                logger.error(error_msg)
                self._errors.append(error_msg)

        # -- Step 8: Validate environment ----------------------------------------
        env_valid = False
        if result.resolution:
            try:
                env_valid = self._validate_environment(result.resolution)
                result.environment_valid = env_valid
            except Exception as exc:
                logger.warning("Environment validation raised an error: %s", exc)
                env_valid = False

        # -- Step 9: Smoke test imports -----------------------------------------
        smoke_results: list[tuple[str, bool, str]] = []
        if env_valid and result.resolution:
            try:
                smoke_results = self._smoke_test_imports(result.resolution)
                result.smoke_test_results = smoke_results
            except Exception as exc:
                logger.warning("Smoke tests raised an error: %s", exc)

        # -- Final verdict ------------------------------------------------------
        result.passed = env_valid and not self._should_fail(self._findings)
        result.success = result.passed
        result.summary = self._generate_summary(result)
        logger.info("Preflight complete – success=%s", result.success)
        return result

    # ------------------------------------------------------------------
    # Pipeline steps
    # ------------------------------------------------------------------

    def _detect_host(self) -> HostFacts:
        """Detect and return host system facts.

        Delegates to ``HostDetector`` when available; otherwise instantiates
        :class:`HostFacts` directly and populates fields.
        """
        # Try importing from sub-packages created by other tasks
        for module_path in ("envguard.macos.host", "envguard.host"):
            try:
                parts = module_path.split(".")
                mod = __import__(module_path, fromlist=["HostDetector"])
                if hasattr(mod, "HostDetector"):
                    detector = mod.HostDetector()
                    facts = detector.detect()
                    self._normalise_facts(facts)
                    return facts
            except (ImportError, AttributeError):
                continue

        logger.debug("HostDetector not available – using HostFacts directly.")
        facts = HostFacts()
        self._populate_facts(facts)
        self._normalise_facts(facts)
        return facts

    def _discover_project(self) -> ProjectIntent:
        """Discover project metadata from the project directory."""
        for module_path in ("envguard.project.discovery",):
            try:
                mod = __import__(module_path, fromlist=["ProjectDiscovery"])
                if hasattr(mod, "ProjectDiscovery"):
                    discovery = mod.ProjectDiscovery(self._project_dir, config=self._config)
                    intent = discovery.discover()
                    self._normalise_intent(intent)
                    return intent
            except (ImportError, AttributeError):
                continue

        logger.debug("ProjectDiscovery not available – using built-in discovery.")
        return self._builtin_discover()

    def _analyze_intent(self, intent: ProjectIntent, facts: HostFacts) -> ProjectIntent:
        """Enrich and normalise the project intent based on host facts."""
        for module_path in ("envguard.project.intent",):
            try:
                mod = __import__(module_path, fromlist=["IntentAnalyzer"])
                if hasattr(mod, "IntentAnalyzer"):
                    analyzer = mod.IntentAnalyzer()
                    intent = analyzer.analyze(intent, facts)
                    self._normalise_intent(intent)
                    return intent
            except (ImportError, AttributeError):
                continue

        logger.debug("IntentAnalyzer not available – using built-in analysis.")
        return self._builtin_analyze_intent(intent, facts)

    def _evaluate_rules(self, facts: HostFacts, intent: ProjectIntent) -> list[RuleFinding]:
        """Run the full rules engine and return all findings."""
        engine = RulesEngine(facts, intent)
        return engine.evaluate()

    def _create_resolution(
        self,
        facts: HostFacts,
        intent: ProjectIntent,
        findings: list[RuleFinding],
    ) -> ResolutionRecord:
        """Create a resolution record that addresses the findings."""
        for module_path in ("envguard.resolver.manager",):
            try:
                mod = __import__(module_path, fromlist=["ResolutionManager"])
                if hasattr(mod, "ResolutionManager"):
                    manager = mod.ResolutionManager(facts, intent, findings)
                    resolution = manager.resolve()
                    self._normalise_resolution(resolution, intent)
                    return resolution
            except (ImportError, AttributeError):
                continue

        logger.debug("ResolutionManager not available – using built-in resolution.")
        return self._builtin_resolution(facts, intent, findings)

    def _validate_environment(self, resolution: ResolutionRecord) -> bool:
        """Validate that the resolved environment is functional."""
        env_path = resolution.environment_path
        if not env_path or not Path(env_path).exists():
            logger.warning("No environment path in resolution – cannot validate.")
            return False

        env_path = Path(env_path)
        python_bin = self._find_env_python(env_path)
        if python_bin is None or not python_bin.exists():
            logger.warning("No Python binary found in environment: %s", env_path)
            return False

        try:
            result = subprocess.run(
                [str(python_bin), "--version"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                logger.warning("Python binary not functional: %s", python_bin)
                return False
        except (subprocess.TimeoutExpired, OSError) as exc:
            logger.warning("Cannot execute Python binary: %s", exc)
            return False

        try:
            result = subprocess.run(
                [str(python_bin), "-m", "pip", "--version"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                logger.warning("pip not functional in environment: %s", env_path)
                return False
        except (subprocess.TimeoutExpired, OSError):
            logger.warning("pip check timed out for environment: %s", env_path)
            return False

        logger.info("Environment validated successfully: %s", env_path)
        return True

    def _smoke_test_imports(self, resolution: ResolutionRecord) -> list[tuple[str, bool, str]]:
        """Try importing key packages mentioned in the resolution.

        Returns a list of ``(package_name, success, error_message)`` tuples.
        Imports are attempted in a subprocess to avoid polluting the current
        interpreter.
        """
        env_path = resolution.environment_path
        if not env_path:
            return []

        python_bin = self._find_env_python(Path(env_path))
        if python_bin is None:
            return []

        packages = resolution.packages_installed
        if not packages:
            return []

        results: list[tuple[str, bool, str]] = []

        for pkg in packages:
            module_name = self._package_to_module(pkg)
            if module_name is None:
                results.append((pkg, False, f"Cannot determine import name for '{pkg}'"))
                continue

            try:
                result = subprocess.run(
                    [str(python_bin), "-c",
                     f"import {module_name}; print(getattr({module_name}, '__version__', 'ok'))"],
                    capture_output=True, text=True, timeout=15,
                )
                if result.returncode == 0:
                    version = result.stdout.strip()
                    results.append((pkg, True, f"v{version}"))
                    logger.debug("Smoke test passed: %s (%s)", pkg, version)
                else:
                    error = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "Import failed"
                    results.append((pkg, False, error))
                    logger.debug("Smoke test FAILED: %s – %s", pkg, error)
            except subprocess.TimeoutExpired:
                results.append((pkg, False, "Import timed out (15s)"))
            except OSError as exc:
                results.append((pkg, False, str(exc)))

        passed = sum(1 for _, success, _ in results if success)
        logger.info("Smoke tests: %d/%d passed", passed, len(results))
        return results

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _should_fail(self, findings: list[RuleFinding]) -> bool:
        """Return ``True`` if any CRITICAL findings exist."""
        return any(f.severity == FindingSeverity.CRITICAL for f in findings)

    def _generate_summary(self, result: PreflightResult) -> str:
        """Produce a human-readable summary of the preflight result."""
        lines: list[str] = []
        lines.append("=" * 64)
        lines.append("  envguard preflight report")
        lines.append("=" * 64)

        # Host info
        if result.host_facts:
            h = result.host_facts
            lines.append(f"  Host    : {h.os_name} {h.os_version} ({h.architecture.value})")
            lines.append(f"  Python  : {h.python_version} @ {h.python_path}")

        # Project info
        if result.project_intent:
            p = result.project_intent
            lines.append(f"  Project : {p.project_name}")
            lines.append(f"  Dir     : {p.project_dir}")
            lines.append(f"  Env type: {p.environment_type.value}")

        # Findings
        critical = [f for f in result.findings if f.severity == FindingSeverity.CRITICAL]
        errors_f = [f for f in result.findings if f.severity == FindingSeverity.ERROR]
        warnings_f = [f for f in result.findings if f.severity == FindingSeverity.WARNING]
        info_f = [f for f in result.findings if f.severity == FindingSeverity.INFO]

        lines.append(f"  Findings: {len(critical)} critical, {len(errors_f)} error, "
                     f"{len(warnings_f)} warning, {len(info_f)} info")

        if critical:
            lines.append("")
            lines.append("  CRITICAL:")
            for f in critical:
                lines.append(f"    [{f.rule_id}] {f.message}")
                if f.remediation:
                    lines.append(f"      -> {f.remediation}")

        if errors_f:
            lines.append("")
            lines.append("  ERRORS:")
            for f in errors_f:
                lines.append(f"    [{f.rule_id}] {f.message}")
                if f.remediation:
                    lines.append(f"      -> {f.remediation}")

        if warnings_f:
            lines.append("")
            lines.append("  WARNINGS:")
            for f in warnings_f:
                lines.append(f"    [{f.rule_id}] {f.message}")

        # Resolution
        if result.resolution:
            r = result.resolution
            lines.append("")
            lines.append(f"  Resolution : {'OK success' if r.success else 'FAILED'}")
            if r.environment_path:
                lines.append(f"  Environment: {r.environment_path}")
            if r.repair_actions_taken:
                lines.append(f"  Repairs    : {', '.join(r.repair_actions_taken)}")

        # Environment validation
        lines.append(f"  Env valid  : {'yes' if result.environment_valid else 'no'}")

        # Smoke tests
        if result.smoke_test_results:
            passed = sum(1 for _, s, _ in result.smoke_test_results if s)
            total = len(result.smoke_test_results)
            lines.append(f"  Smoke tests: {passed}/{total} passed")
            for name, success, msg in result.smoke_test_results:
                status = "OK" if success else "FAIL"
                lines.append(f"    {status} {name}: {msg}")

        # Final verdict
        lines.append("")
        verdict = "PASSED" if result.success else "FAILED"
        lines.append(f"  Result: {verdict}")
        lines.append("=" * 64)

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Built-in fallback implementations
    # ------------------------------------------------------------------

    def _builtin_discover(self) -> ProjectIntent:
        """Minimal built-in project discovery."""
        project_dir = self._project_dir
        intent = ProjectIntent(project_dir=project_dir)
        intent.project_name = project_dir.name

        intent.has_pyproject_toml = (project_dir / "pyproject.toml").exists()
        intent.has_requirements_txt = (project_dir / "requirements.txt").exists()
        intent.has_setup_py = (project_dir / "setup.py").exists()
        intent.has_conda_env_file = (
            (project_dir / "environment.yml").exists()
            or (project_dir / "environment.yaml").exists()
        )

        if intent.has_requirements_txt:
            intent.dependencies = self._read_requirements_txt(project_dir / "requirements.txt")
        if intent.has_pyproject_toml:
            self._parse_pyproject_toml(project_dir / "pyproject.toml", intent)

        python_version_file = project_dir / ".python-version"
        if python_version_file.exists():
            content = python_version_file.read_text().strip()
            intent.python_version_required = content.splitlines()[0].strip()

        # Determine environment type
        if intent.has_conda_env_file:
            intent.environment_type = EnvironmentType.CONDA
        elif (project_dir / "Pipfile").exists():
            intent.environment_type = EnvironmentType.PIPENV
        elif (project_dir / "poetry.lock").exists():
            intent.environment_type = EnvironmentType.POETRY
        else:
            intent.environment_type = EnvironmentType.VENV

        self._normalise_intent(intent)
        return intent

    def _builtin_analyze_intent(self, intent: ProjectIntent, facts: HostFacts) -> ProjectIntent:
        """Minimal built-in intent analysis."""
        deps_lower = [d.lower() for d in intent.dependencies]

        cuda_markers = ["torch", "tensorflow", "jaxlib", "nvidia", "cuda"]
        if any(any(marker in d for marker in cuda_markers) for d in deps_lower):
            intent.has_cuda_requirements = True
            intent.requires_cuda = True
            if facts.is_macos or facts.os_name == "Darwin":
                intent.accelerator_target = AcceleratorTarget.MPS
                intent.has_mps_requirements = True
                intent.requires_mps = True

        build_markers = ["cython", "cffi", "pybind11", "setuptools-rust"]
        if any(any(marker in d for marker in build_markers) for d in deps_lower):
            intent.requires_source_build = True

        if intent.dependencies:
            intent.requires_network = True

        return intent

    def _builtin_resolution(
        self,
        facts: HostFacts,
        intent: ProjectIntent,
        findings: list[RuleFinding],
    ) -> ResolutionRecord:
        """Minimal built-in resolution creation."""
        resolution = ResolutionRecord(
            project_dir=intent.project_dir,
            environment_type=intent.environment_type,
            python_version=facts.python_version,
            accelerator_target=intent.accelerator_target,
        )
        resolution.resolution_id = resolution.id

        if intent.environment_type == EnvironmentType.CONDA:
            resolution.environment_path = intent.project_dir / ".conda"
        else:
            resolution.environment_path = intent.project_dir / ".venv"

        repair_actions: list[str] = []
        for finding in findings:
            if finding.auto_repairable and finding.repair_action is not None:
                resolution.findings_addressed.append(finding.rule_id)
                repair_actions.append(f"{finding.rule_id}:{finding.repair_action.value}")

        resolution.repair_actions_taken = repair_actions
        resolution.packages_installed = intent.dependencies[:]
        resolution.success = len(repair_actions) == 0
        return resolution

    def _repair_environment(
        self,
        facts: HostFacts,
        intent: ProjectIntent,
        resolution: ResolutionRecord,
    ) -> None:
        """Attempt to create or repair the environment."""
        try:
            from envguard.repair import RepairEngine
            repair = RepairEngine(self._project_dir, facts, intent)
            new_resolution = repair.repair()
            resolution.success = new_resolution.success
            resolution.environment_path = new_resolution.environment_path
            resolution.repair_actions_taken = new_resolution.repair_actions_taken
            resolution.packages_installed = new_resolution.packages_installed
            resolution.notes.extend(new_resolution.notes)
        except ImportError:
            logger.warning("RepairEngine not available – skipping environment repair.")

    # ------------------------------------------------------------------
    # Fact population and normalisation
    # ------------------------------------------------------------------

    @staticmethod
    def _populate_facts(facts: HostFacts) -> None:
        """Populate HostFacts fields using real system introspection."""
        import platform as _platform

        facts.os_name = _platform.system()
        facts.os_version = _platform.mac_ver()[0] or _platform.version()
        facts.os_release = _platform.release()
        facts.python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        facts.python_path = sys.executable

        machine = _platform.machine().lower()
        if machine == "arm64":
            facts.architecture = Architecture.ARM64
            facts.is_apple_silicon = True
        elif machine == "x86_64" or machine == "amd64":
            facts.architecture = Architecture.X86_64
        else:
            facts.architecture = Architecture.UNKNOWN

        facts.is_macos = (facts.os_name == "Darwin")

        # Detect Rosetta
        if facts.is_macos:
            try:
                result = subprocess.run(
                    ["sysctl", "-n", "sysctl.proc_translated"],
                    capture_output=True, text=True, timeout=5,
                )
                facts.is_rosetta = result.stdout.strip() == "1"
                facts.is_native_python = not facts.is_rosetta
            except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
                facts.is_rosetta = False

        # Detect Xcode CLI tools
        if facts.is_macos:
            try:
                result = subprocess.run(
                    ["xcode-select", "-p"],
                    capture_output=True, text=True, timeout=5,
                )
                facts.has_xcode_cli = result.returncode == 0
            except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
                facts.has_xcode_cli = False

        # Detect pip
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "--version"],
                capture_output=True, text=True, timeout=10,
            )
            facts.has_pip = result.returncode == 0
            if facts.has_pip:
                facts.pip_path = f"{sys.executable} -m pip"
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            facts.has_pip = False

        # Detect conda
        try:
            result = subprocess.run(
                ["conda", "--version"],
                capture_output=True, text=True, timeout=10,
            )
            facts.has_conda = result.returncode == 0
            if facts.has_conda:
                facts.conda_path = "conda"
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            facts.has_conda = False

        # Detect MPS availability (macOS 12.3+)
        if facts.is_macos and facts.is_apple_silicon:
            try:
                parts = facts.os_version.split(".")
                major = int(parts[0]) if parts else 0
                minor = int(parts[1]) if len(parts) > 1 else 0
                facts.mps_available = (major, minor) >= (12, 3)
            except (ValueError, IndexError):
                facts.mps_available = False

        # Detect network
        facts.network_available = _check_connectivity_quick()

        # Detect shell
        import os as _os
        shell = _os.environ.get("SHELL", "")
        if "zsh" in shell:
            facts.shell = ShellType.ZSH
        elif "bash" in shell:
            facts.shell = ShellType.BASH
        elif "fish" in shell:
            facts.shell = ShellType.FISH

        facts.home_dir = Path.home()
        facts.username = _os.environ.get("USER", "unknown")

    @staticmethod
    def _normalise_facts(facts: HostFacts) -> None:
        """Ensure extended fields are populated from base fields."""
        if not facts.is_macos:
            facts.is_macos = (facts.os_name == "Darwin")
        if facts.architecture == Architecture.ARM64:
            facts.is_apple_silicon = True
        if facts.is_macos and facts.is_apple_silicon and not facts.mps_available:
            try:
                parts = facts.os_version.split(".")
                major = int(parts[0]) if parts else 0
                minor = int(parts[1]) if len(parts) > 1 else 0
                facts.mps_available = (major, minor) >= (12, 3)
            except (ValueError, IndexError):
                pass
        if not facts.pip_path and facts.has_pip and facts.python_path != "unknown":
            facts.pip_path = f"{facts.python_path} -m pip"
        if not facts.conda_path and facts.has_conda:
            facts.conda_path = "conda"

    @staticmethod
    def _normalise_intent(intent: ProjectIntent) -> None:
        """Ensure extended intent fields are synced."""
        if intent.has_cuda_requirements and not intent.requires_cuda:
            intent.requires_cuda = True
        if intent.has_mps_requirements and not intent.requires_mps:
            intent.requires_mps = True
        if not intent.name and intent.project_name and intent.project_name != "unknown":
            intent.name = intent.project_name
        if not intent.name:
            intent.name = intent.project_dir.name if intent.project_dir else "unnamed-project"

    @staticmethod
    def _normalise_resolution(resolution: ResolutionRecord, intent: ProjectIntent) -> None:
        """Ensure resolution has resolution_id populated."""
        if not resolution.resolution_id:
            resolution.resolution_id = resolution.id
        if not resolution.packages_installed and intent.dependencies:
            resolution.packages_installed = list(intent.dependencies)

    # ------------------------------------------------------------------
    # Utility methods
    # ------------------------------------------------------------------

    @staticmethod
    def _read_requirements_txt(path: Path) -> list[str]:
        """Parse a requirements.txt file."""
        deps: list[str] = []
        if not path.exists():
            return deps
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            deps.append(line)
        return deps

    @staticmethod
    def _parse_pyproject_toml(path: Path, intent: ProjectIntent) -> None:
        """Parse a pyproject.toml for basic project metadata."""
        if not path.exists():
            return

        data: dict[str, Any] = {}

        try:
            import tomllib
            with open(path, "rb") as fh:
                data = tomllib.load(fh)
        except ImportError:
            try:
                import tomli as tomllib
                with open(path, "rb") as fh:
                    data = tomllib.load(fh)
            except ImportError:
                logger.debug("No TOML parser available – regex fallback.")

        if data:
            proj = data.get("project", {})
            requires_python = proj.get("requires-python")
            if requires_python:
                match = re.search(r"(\d+\.\d+)", requires_python)
                if match:
                    intent.python_version_required = match.group(1)

            deps = proj.get("dependencies", [])
            if isinstance(deps, list):
                intent.dependencies.extend(deps)

            optional = proj.get("optional-dependencies", {})
            dev_deps = optional.get("dev", []) or optional.get("devDependencies", [])
            if isinstance(dev_deps, list):
                intent.dev_dependencies.extend(dev_deps)

            if proj.get("name"):
                intent.project_name = proj["name"]
        else:
            content = path.read_text()
            match = re.search(r'requires-python\s*=\s*["\']([^"\']+)', content)
            if match:
                ver_match = re.search(r"(\d+\.\d+)", match.group(1))
                if ver_match:
                    intent.python_version_required = ver_match.group(1)

    @staticmethod
    def _find_env_python(env_path: Path) -> Optional[Path]:
        """Locate the Python binary inside an environment."""
        for name in ("python3", "python"):
            candidate = env_path / "bin" / name
            if candidate.exists():
                return candidate
        return None

    @staticmethod
    def _package_to_module(package_name: str) -> Optional[str]:
        """Convert a pip package name to its importable module name."""
        mapping: dict[str, str] = {
            "pillow": "PIL",
            "pyyaml": "yaml",
            "python-dateutil": "dateutil",
            "opencv-python": "cv2",
            "scikit-learn": "sklearn",
            "python-dotenv": "dotenv",
            "google-auth": "google.auth",
            "protobuf": "google.protobuf",
            "grpcio": "grpc",
        }
        key = package_name.lower().strip()
        if key in mapping:
            return mapping[key]
        return re.sub(r"[<>=!~\[].*", "", key).replace("-", "_")


def _check_connectivity_quick() -> bool:
    """Lightweight TCP connectivity check."""
    import socket
    for host in ("pypi.org", "files.pythonhosted.org"):
        try:
            socket.create_connection((host, 443), timeout=3)
            return True
        except (socket.timeout, socket.error, OSError):
            continue
    return False
