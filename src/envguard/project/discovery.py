# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""Project discovery - scan a directory to infer project intent.

The :class:`ProjectDiscovery` class walks a project directory looking for
well-known configuration files (pyproject.toml, requirements.txt,
environment.yml, etc.) and assembles a :class:`ProjectIntent` that
captures the project's environment requirements.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

from envguard.exceptions import EnvguardError
from envguard.logging import get_logger
from envguard.models import (
    EnvironmentType,
    PackageManager,
    ProjectIntent,
)

logger = get_logger("project.discovery")

# ── TOML import (Python ≥ 3.11 stdlib, else tomli) ─────────────────────────

try:
    import tomllib  # type: ignore[import-not-found]
except ModuleNotFoundError:
    try:
        import tomli as tomllib  # type: ignore[import-not-found, no-redef]
    except ModuleNotFoundError:
        tomllib = None  # type: ignore[assignment]


# ── ProjectDiscovery ──────────────────────────────────────────────────────


class ProjectDiscovery:
    """Scan a project directory and build a :class:`ProjectIntent`.

    The discovery process checks for configuration files in a defined
    priority order, parses them, and infers the environment type, package
    manager(s), and dependency list.
    """

    #: File names checked during discovery, in priority order.
    DISCOVERY_ORDER: list[str] = [  # noqa: RUF012
        "pyproject.toml",
        "requirements.txt",
        "requirements-dev.txt",
        "constraints.txt",
        "environment.yml",
        "environment.yaml",
        "setup.py",
        ".python-version",
        "setup.cfg",
    ]

    #: Mapping of filename patterns to likely package-manager guesses.
    MANAGER_INDICATORS: dict[str, list[PackageManager]] = {  # noqa: RUF012
        "pyproject.toml": [PackageManager.POETRY, PackageManager.PIP, PackageManager.UV],
        "requirements.txt": [PackageManager.PIP, PackageManager.UV],
        "requirements-dev.txt": [PackageManager.PIP],
        "constraints.txt": [PackageManager.PIP],
        "environment.yml": [PackageManager.CONDA, PackageManager.MAMBA],
        "environment.yaml": [PackageManager.CONDA, PackageManager.MAMBA],
        "setup.py": [PackageManager.PIP],
        "setup.cfg": [PackageManager.PIP],
        "Pipfile": [PackageManager.PIPENV],
        "pixi.toml": [PackageManager.PIXI],
    }

    def __init__(self, project_dir: Path) -> None:
        self.project_dir = Path(project_dir).resolve()
        if not self.project_dir.is_dir():
            raise EnvguardError(f"Not a valid directory: {self.project_dir}")

    # ------------------------------------------------------------------ #
    # Public entry point
    # ------------------------------------------------------------------ #

    def discover(self) -> ProjectIntent:
        """Main entry - scan the project directory and build intent.

        Returns:
            A populated ProjectIntent describing the project.
        """
        logger.info("Discovering project at: %s", self.project_dir)
        scan_results = self.scan_files()
        intent = self.build_intent(scan_results)
        logger.info(
            "Discovery complete: env_type=%s, managers=%s, deps=%d",
            intent.environment_type.value,
            [m.value for m in intent.package_managers],
            intent.dependency_count,
        )
        return intent

    # ------------------------------------------------------------------ #
    # File scanning
    # ------------------------------------------------------------------ #

    def scan_files(self) -> dict[str, Path]:
        """Check which discovery files exist in the project directory.

        Returns:
            A dict mapping filename to its resolved Path for every file
            that was found.
        """
        found: dict[str, Path] = {}
        for name in self.DISCOVERY_ORDER:
            candidate = self.project_dir / name
            if candidate.is_file():
                found[name] = candidate
                logger.debug("Found project file: %s", name)

        # Also scan for Pipfile and pixi.toml which are not in DISCOVERY_ORDER
        for extra in ("Pipfile", "pixi.toml"):
            candidate = self.project_dir / extra
            if candidate.is_file():
                found[extra] = candidate
                logger.debug("Found project file: %s", extra)

        return found

    # ------------------------------------------------------------------ #
    # Individual detectors
    # ------------------------------------------------------------------ #

    def detect_pyproject(self) -> tuple[bool, dict]:
        """Parse pyproject.toml if present.

        Uses ``tomllib`` (Python 3.11+) or falls back to ``tomli``.

        Returns:
            A tuple of (found, parsed_data_dict).
        """
        toml_path = self.project_dir / "pyproject.toml"
        if not toml_path.is_file():
            return False, {}

        if tomllib is None:
            logger.warning("tomllib/tomli not available - cannot parse pyproject.toml")
            return True, {}

        try:
            with open(toml_path, "rb") as fh:
                data = tomllib.load(fh)
            logger.debug("Parsed pyproject.toml successfully")
            return True, data
        except Exception as exc:
            logger.error("Failed to parse pyproject.toml: %s", exc)
            raise EnvguardError(f"Could not parse {toml_path}: {exc}") from exc

    def detect_requirements(self) -> tuple[bool, list[Path]]:
        """Find all requirements*.txt files.

        Returns:
            A tuple of (any_found, list_of_paths).
        """
        files: list[Path] = []
        for pattern in ("requirements*.txt",):
            for p in sorted(self.project_dir.glob(pattern)):
                if p.is_file():
                    files.append(p)
        found = len(files) > 0
        logger.debug("Requirements files found: %s", files if found else "none")
        return found, files

    def detect_conda_env(self) -> tuple[bool, Path | None]:
        """Check for environment.yml or environment.yaml.

        Returns:
            A tuple of (found, path_or_None).
        """
        for name in ("environment.yml", "environment.yaml"):
            candidate = self.project_dir / name
            if candidate.is_file():
                logger.debug("Conda env file: %s", candidate)
                return True, candidate
        return False, None

    def detect_setup_py(self) -> tuple[bool, dict]:
        """Parse setup.py for dependency information using AST.

        .. note::
            This method does **not** execute setup.py.  It statically
            analyses the AST looking for ``install_requires`` and
            ``requires`` keyword arguments in ``setup()`` calls.

        Returns:
            A tuple of (found, info_dict) where *info_dict* may contain
            ``install_requires`` and ``requires`` lists.
        """
        setup_path = self.project_dir / "setup.py"
        if not setup_path.is_file():
            return False, {}

        try:
            source = setup_path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(setup_path))
        except (SyntaxError, OSError) as exc:
            logger.warning("Could not parse setup.py: %s", exc)
            return True, {}

        info: dict[str, Any] = {"install_requires": [], "requires": []}

        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and (
                getattr(node.func, "id", None) == "setup"
                or (isinstance(node.func, ast.Attribute) and node.func.attr == "setup")
            ):
                for kw in node.keywords:
                    if kw.arg in ("install_requires", "requires", "extras_require"):
                        if isinstance(kw.value, ast.List):
                            values = []
                            for elt in kw.value.elts:
                                if isinstance(elt, ast.Constant):
                                    values.append(str(elt.value))
                                elif isinstance(elt, ast.Str):
                                    values.append(elt.s)
                            info[kw.arg] = values
                        elif isinstance(kw.value, ast.Constant):
                            info[kw.arg] = str(kw.value)

        logger.debug("setup.py AST analysis result: %s", info)
        return True, info

    def detect_python_version_file(self) -> tuple[bool, str | None]:
        """Read .python-version if present.

        Returns:
            A tuple of (found, version_string_or_None).
        """
        pv_path = self.project_dir / ".python-version"
        if not pv_path.is_file():
            return False, None

        try:
            content = pv_path.read_text(encoding="utf-8").strip()
            # .python-version may contain multiple lines; take the first
            first_line = content.splitlines()[0].strip()
            logger.debug(".python-version: %s", first_line)
            return True, first_line
        except OSError as exc:
            logger.warning("Could not read .python-version: %s", exc)
            return True, None

    def detect_wheelhouse(self) -> tuple[bool, Path | None]:
        """Check for wheels/ or wheelhouse/ directories.

        Returns:
            A tuple of (found, path_or_None).
        """
        for name in ("wheels", "wheelhouse"):
            candidate = self.project_dir / name
            if candidate.is_dir():
                has_wheels = any(candidate.iterdir())
                if has_wheels:
                    logger.debug("Wheelhouse found: %s", candidate)
                    return True, candidate
        return False, None

    def detect_previous_state(self) -> bool:
        """Check whether a .envguard/ directory already exists.

        Returns:
            True if .envguard/ exists in the project root.
        """
        envguard_dir = self.project_dir / ".envguard"
        exists = envguard_dir.is_dir()
        logger.debug("Previous envguard state: %s", "yes" if exists else "no")
        return exists

    # ------------------------------------------------------------------ #
    # Inference helpers
    # ------------------------------------------------------------------ #

    def infer_environment_type(self, files: dict[str, Path]) -> EnvironmentType:
        """Infer the environment type from discovered files.

        Args:
            files: Mapping of filename to Path from :meth:`scan_files`.

        Returns:
            The inferred EnvironmentType.
        """
        # Conda/mamba takes precedence
        if any(n in files for n in ("environment.yml", "environment.yaml")):
            # Check if mamba is mentioned
            for name in ("environment.yml", "environment.yaml"):
                if name in files:
                    try:
                        content = files[name].read_text(encoding="utf-8").lower()
                        if "mamba" in content:
                            return EnvironmentType.MAMBA
                    except OSError:
                        pass
            return EnvironmentType.CONDA

        # Pipfile → pipenv
        if "Pipfile" in files:
            return EnvironmentType.PIPENV

        # pixi.toml → pixi
        if "pixi.toml" in files:
            return EnvironmentType.PIXI

        # pyproject.toml with poetry section
        if "pyproject.toml" in files:
            try:
                with open(files["pyproject.toml"], "rb") as fh:
                    if tomllib is not None:
                        data = tomllib.load(fh)
                        if "tool" in data and "poetry" in data.get("tool", {}):
                            return EnvironmentType.POETRY
            except Exception:
                pass
            return EnvironmentType.VENV

        # setup.py or requirements.txt → venv
        if "setup.py" in files or "requirements.txt" in files:
            return EnvironmentType.VENV

        return EnvironmentType.UNKNOWN

    def infer_package_managers(self, files: dict[str, Path]) -> list[PackageManager]:
        """Infer likely package managers from discovered files.

        Args:
            files: Mapping of filename to Path.

        Returns:
            A deduplicated list of inferred PackageManagers.
        """
        managers: list[PackageManager] = []
        seen: set[PackageManager] = set()

        for filename, candidates in self.MANAGER_INDICATORS.items():
            if filename in files:
                for mgr in candidates:
                    if mgr not in seen:
                        managers.append(mgr)
                        seen.add(mgr)

        return managers

    def count_dependencies(self, intent: ProjectIntent) -> int:
        """Count total dependencies from all sources.

        Args:
            intent: The partially built ProjectIntent.

        Returns:
            Total dependency count.
        """
        return len(intent.dependencies) + len(intent.dev_dependencies)

    # ------------------------------------------------------------------ #
    # CUDA / MPS detection
    # ------------------------------------------------------------------ #

    def detect_cuda_requirements(self, project_dir: Path) -> bool:
        """Search project files for CUDA / torch references.

        Args:
            project_dir: The project root directory.

        Returns:
            True if any file references CUDA-related packages.
        """
        cuda_patterns = re.compile(
            r"(?:torch[-_]cu|cuda|nvidia|tensorrt|cupy|jaxlib.*cuda)",
            re.IGNORECASE,
        )
        return self._search_files(project_dir, cuda_patterns)

    def detect_mps_requirements(self, project_dir: Path) -> bool:
        """Search project files for MPS / Metal references.

        Args:
            project_dir: The project root directory.

        Returns:
            True if any file references MPS/Metal-related packages.
        """
        mps_patterns = re.compile(
            r"(?:mps|metal|torch\.mps|torchvision.*mps|mlx|apple.*silicon)",
            re.IGNORECASE,
        )
        return self._search_files(project_dir, mps_patterns)

    def _search_files(self, project_dir: Path, pattern: re.Pattern[str]) -> bool:
        """Search text files in project_dir for *pattern*.

        Skips binary files and directories like .git, __pycache__, etc.
        """
        skip_dirs = {
            ".git",
            "__pycache__",
            "node_modules",
            ".envguard",
            ".tox",
            ".venv",
            "venv",
            ".mypy_cache",
            ".pytest_cache",
        }
        search_exts = {
            ".py",
            ".txt",
            ".toml",
            ".yml",
            ".yaml",
            ".cfg",
            ".ini",
            ".md",
            ".rst",
            ".sh",
        }

        project_dir = Path(project_dir)
        if not project_dir.is_dir():
            return False

        for p in project_dir.rglob("*"):
            if any(part in skip_dirs for part in p.parts):
                continue
            if not p.is_file():
                continue
            if p.suffix.lower() not in search_exts:
                continue
            try:
                content = p.read_text(encoding="utf-8", errors="ignore")
                if pattern.search(content):
                    logger.debug("Pattern matched in: %s", p)
                    return True
            except OSError:
                continue

        return False

    # ------------------------------------------------------------------ #
    # Intent assembly
    # ------------------------------------------------------------------ #

    def build_intent(self, scan_results: dict[str, Path]) -> ProjectIntent:
        """Assemble a final :class:`ProjectIntent` from scan results.

        Runs each individual detector and composes the results.

        Args:
            scan_results: Output of :meth:`scan_files`.

        Returns:
            A fully populated ProjectIntent.
        """
        intent = ProjectIntent(project_dir=self.project_dir)

        # ── pyproject.toml ──
        pyproject_found, pyproject_data = self.detect_pyproject()
        intent.has_pyproject_toml = pyproject_found

        if pyproject_found and pyproject_data:
            # Project metadata
            project_table = pyproject_data.get("project", {})
            intent.project_name = project_table.get("name", "unknown")
            intent.project_version = str(project_table.get("version", "unknown"))

            # Python version requirement
            requires_python = project_table.get("requires-python", "")
            if requires_python:
                intent.python_version_required = requires_python

            # Dependencies
            raw_deps = project_table.get("dependencies", [])
            intent.dependencies.extend(str(d) for d in raw_deps if isinstance(d, (str, dict)))

            # Optional / dev dependencies
            optional = project_table.get("optional-dependencies", {})
            for group, deps in optional.items():
                if group in ("dev", "testing", "test", "tests"):
                    intent.dev_dependencies.extend(str(d) for d in deps)
                else:
                    intent.dependencies.extend(str(d) for d in deps)

            # Build system
            build_sys = pyproject_data.get("build-system", {})
            build_backend = build_sys.get("build-backend", "")
            if "setuptools" in build_backend:
                intent.build_system = "setuptools"
            elif "hatchling" in build_backend:
                intent.build_system = "hatchling"
            elif "flit" in build_backend:
                intent.build_system = "flit"
            elif "poetry" in build_backend:
                intent.build_system = "poetry"
            elif "pdm" in build_backend:
                intent.build_system = "pdm"
            else:
                intent.build_system = build_backend or "unknown"

            intent.extra["pyproject"] = pyproject_data

        # ── requirements*.txt ──
        reqs_found, reqs_files = self.detect_requirements()
        intent.has_requirements_txt = "requirements.txt" in scan_results
        intent.requirements_files = reqs_files

        if reqs_found:
            for req_file in reqs_files:
                try:
                    lines = req_file.read_text(encoding="utf-8").splitlines()
                except OSError:
                    continue
                is_dev = "dev" in req_file.name.lower()
                for line in lines:
                    line = line.strip()
                    if not line or line.startswith("#") or line.startswith("-"):
                        continue
                    if is_dev:
                        intent.dev_dependencies.append(line)
                    else:
                        intent.dependencies.append(line)

        # ── conda env file ──
        conda_found, conda_path = self.detect_conda_env()
        intent.has_conda_env_file = conda_found
        intent.conda_env_path = conda_path

        if conda_found and conda_path is not None:
            self._parse_conda_env(conda_path, intent)

        # ── setup.py ──
        setup_found, setup_info = self.detect_setup_py()
        intent.has_setup_py = setup_found

        if setup_found and setup_info:
            for dep in setup_info.get("install_requires", []):
                if dep not in intent.dependencies:
                    intent.dependencies.append(dep)
            for dep in setup_info.get("requires", []):
                if dep not in intent.dependencies:
                    intent.dependencies.append(dep)

        # ── .python-version ──
        pv_found, pv_version = self.detect_python_version_file()
        if pv_found and pv_version and not intent.python_version_required:
            intent.python_version_required = pv_version

        # ── wheelhouse ──
        wh_found, wh_path = self.detect_wheelhouse()
        intent.has_wheelhouse = wh_found
        intent.wheelhouse_path = wh_path

        # ── previous state ──
        intent.has_previous_envguard_state = self.detect_previous_state()

        # ── CUDA / MPS ──
        intent.has_cuda_requirements = self.detect_cuda_requirements(self.project_dir)
        intent.has_mps_requirements = self.detect_mps_requirements(self.project_dir)

        # ── Inference ──
        intent.environment_type = self.infer_environment_type(scan_results)
        intent.package_managers = self.infer_package_managers(scan_results)
        intent.dependency_count = self.count_dependencies(intent)

        return intent

    @staticmethod
    def _parse_conda_env(path: Path, intent: ProjectIntent) -> None:
        """Best-effort YAML-like parse of a conda environment file.

        Does **not** require PyYAML - uses simple line scanning.
        """
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            return

        in_deps = False
        in_pip = False
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            # Detect Python version
            if stripped.startswith("python") and "=" in stripped:
                # e.g. "python=3.11" or "python >=3.10"
                ver = stripped.split("=", 1)[-1].split(">", 1)[0].strip()
                if not intent.python_version_required:
                    intent.python_version_required = ver

            # Detect dependencies section
            if stripped.startswith("dependencies:"):
                in_deps = True
                continue
            if stripped.startswith("  - pip"):
                in_pip = True
                in_deps = True
                continue

            if in_deps and stripped and not stripped[0].isspace() and ":" in stripped:
                in_deps = False
                in_pip = False
                continue

            if in_pip:
                # pip sub-dependency: "    - package==1.0"
                dep = stripped.lstrip("- ").strip()
                if dep and not dep.startswith("pip"):
                    intent.dependencies.append(dep)
            elif in_deps:
                dep = stripped.lstrip("- ").strip()
                if dep and dep not in ("pip", "python"):
                    intent.dependencies.append(dep)


# ── Convenience function ───────────────────────────────────────────────────


def discover_project(project_dir: Path) -> ProjectIntent:
    """Discover project intent from a directory.

    This is a convenience wrapper around :class:`ProjectDiscovery`.

    Args:
        project_dir: Path to the project root.

    Returns:
        A populated ProjectIntent.
    """
    discovery = ProjectDiscovery(project_dir)
    return discovery.discover()
