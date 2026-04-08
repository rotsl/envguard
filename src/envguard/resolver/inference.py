# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""Project inference engine - derive environment requirements from project files."""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

try:
    import yaml  # type: ignore[import-untyped]
except ImportError:
    yaml = None  # type: ignore[assignment]

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib  # type: ignore[import-untyped, no-redef]
    except ImportError:
        tomllib = None  # type: ignore[assignment]

try:
    from envguard.logging import get_logger
except ImportError:
    import logging

    def get_logger(name: str) -> logging.Logger:  # type: ignore[misc]
        return logging.getLogger(name)

try:
    from envguard.models import AcceleratorTarget
except ImportError:
    class AcceleratorTarget:  # type: ignore[no-redef]
        CPU = "cpu"
        MPS = "mps"
        CUDA = "cuda"

logger = get_logger(__name__)

# Packages that suggest GPU accelerator needs
_ACCELERATOR_HINTS: dict[str, dict[str, Any]] = {
    "torch": {
        "needs_cuda": True,
        "needs_mps": True,
        "recommended_target": AcceleratorTarget.CUDA,
        "reasoning": "PyTorch supports both CUDA and MPS; default recommendation is CUDA",
    },
    "tensorflow": {
        "needs_cuda": True,
        "needs_mps": True,
        "recommended_target": AcceleratorTarget.CUDA,
        "reasoning": "TensorFlow supports both CUDA and MPS via tensorflow-metal on macOS",
    },
    "jax": {
        "needs_cuda": True,
        "needs_mps": False,
        "recommended_target": AcceleratorTarget.CUDA,
        "reasoning": "JAX primarily targets CUDA; MPS support is experimental",
    },
    "jaxlib": {
        "needs_cuda": True,
        "needs_mps": False,
        "recommended_target": AcceleratorTarget.CUDA,
        "reasoning": "jaxlib is the XLA backend for JAX, primarily CUDA",
    },
    "cupy": {
        "needs_cuda": True,
        "needs_mps": False,
        "recommended_target": AcceleratorTarget.CUDA,
        "reasoning": "CuPy requires CUDA GPUs",
    },
    "torchvision": {
        "needs_cuda": True,
        "needs_mps": True,
        "recommended_target": AcceleratorTarget.CUDA,
        "reasoning": "torchvision follows PyTorch's accelerator support",
    },
    "torchaudio": {
        "needs_cuda": True,
        "needs_mps": True,
        "recommended_target": AcceleratorTarget.CUDA,
        "reasoning": "torchaudio follows PyTorch's accelerator support",
    },
    "paddlepaddle": {
        "needs_cuda": True,
        "needs_mps": False,
        "recommended_target": AcceleratorTarget.CUDA,
        "reasoning": "PaddlePaddle primarily supports CUDA",
    },
    "triton": {
        "needs_cuda": True,
        "needs_mps": False,
        "recommended_target": AcceleratorTarget.CUDA,
        "reasoning": "OpenAI Triton is a CUDA-specific compiler",
    },
    "deepspeed": {
        "needs_cuda": True,
        "needs_mps": False,
        "recommended_target": AcceleratorTarget.CUDA,
        "reasoning": "DeepSpeed requires CUDA for GPU acceleration",
    },
}

# Regex to extract package name from a requirement specifier
_REQ_NAME_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?")


class InferenceEngine:
    """Infer environment requirements from various project metadata files.

    Supports ``pyproject.toml``, ``requirements.txt``, ``environment.yml``,
    and ``setup.py`` (via AST parsing).
    """

    def infer_from_pyproject(self, pyproject_path: Path) -> dict:
        """Parse a ``pyproject.toml`` and extract dependency information.

        Returns a dict with keys:
        - ``dependencies`` (list[str]): project dependencies
        - ``python_version`` (str | None): required Python version
        - ``extras`` (dict[str, list[str]]): optional dependency groups
        - ``build_system`` (dict): build-system information
        """
        if not pyproject_path.is_file():
            return {
                "dependencies": [],
                "python_version": None,
                "extras": {},
                "build_system": {},
            }

        try:
            raw = pyproject_path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Cannot read %s: %s", pyproject_path, exc)
            return {
                "dependencies": [],
                "python_version": None,
                "extras": {},
                "build_system": {},
            }

        if tomllib is None:
            logger.warning("tomllib/tomli not available; cannot parse pyproject.toml")
            return {
                "dependencies": [],
                "python_version": None,
                "extras": {},
                "build_system": {},
            }

        try:
            data = tomllib.loads(raw)
        except Exception as exc:
            logger.warning("Failed to parse %s: %s", pyproject_path, exc)
            return {
                "dependencies": [],
                "python_version": None,
                "extras": {},
                "build_system": {},
            }

        result: dict[str, Any] = {
            "dependencies": [],
            "python_version": None,
            "extras": {},
            "build_system": {},
        }

        # Build system
        bs = data.get("build-system", {})
        if bs:
            result["build_system"] = bs

        # PEP 621 project metadata
        project = data.get("project", {})
        result["dependencies"] = list(project.get("dependencies", []))

        # Python requires
        py_req = project.get("requires-python")
        if py_req:
            result["python_version"] = py_req

        # Optional dependencies (extras)
        for group_name, group_deps in project.get("optional-dependencies", {}).items():
            result["extras"][group_name] = list(group_deps)

        # Also check [tool.poetry] for Poetry projects
        poetry = data.get("tool", {}).get("poetry", {})
        if poetry and not result["dependencies"]:
            result["dependencies"] = [
                _format_poetry_dep(name, spec)
                for name, spec in poetry.get("dependencies", {}).items()
                if name.lower() != "python"
            ]
            py_ver = poetry.get("dependencies", {}).get("python", "")
            if py_ver:
                result["python_version"] = str(py_ver)
            for group_name, group_data in poetry.get("group", {}).items():
                result["extras"][group_name] = [
                    _format_poetry_dep(n, s)
                    for n, s in group_data.get("dependencies", {}).items()
                ]

        # Poetry dev-dependencies (legacy)
        dev_deps = poetry.get("dev-dependencies", {})
        if dev_deps:
            result["extras"]["dev"] = [
                _format_poetry_dep(n, s) for n, s in dev_deps.items()
            ]

        return result

    def infer_from_requirements(self, req_path: Path) -> dict:
        """Parse a ``requirements.txt`` file.

        Returns a dict with:
        - ``dependencies`` (list[str]): requirement lines
        - ``constraints_markers`` (list[dict]): entries with ``requirement``
          and optional ``marker`` keys
        """
        if not req_path.is_file():
            return {"dependencies": [], "constraints_markers": []}

        try:
            text = req_path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Cannot read %s: %s", req_path, exc)
            return {"dependencies": [], "constraints_markers": []}

        dependencies: list[str] = []
        constraints_markers: list[dict] = []

        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue

            # Handle markers: e.g. ``package; python_version >= "3.8"``
            requirement, _, marker = line.partition(";")
            requirement = requirement.strip()
            if not requirement:
                continue

            dependencies.append(requirement)

            entry: dict = {"requirement": requirement}
            marker = marker.strip()
            if marker:
                entry["marker"] = marker
            constraints_markers.append(entry)

        return {"dependencies": dependencies, "constraints_markers": constraints_markers}

    def infer_from_conda_env(self, env_path: Path) -> dict:
        """Parse a ``environment.yml`` Conda environment file.

        Returns a dict with:
        - ``dependencies`` (list[str]): all dependency strings
        - ``conda_deps`` (list[str]): conda-native dependencies
        - ``pip_deps`` (list[str]): pip sub-section dependencies
        - ``channels`` (list[str]): channel list
        - ``python_version`` (str | None): extracted Python version
        """
        if not env_path.is_file():
            return {
                "dependencies": [],
                "conda_deps": [],
                "pip_deps": [],
                "channels": [],
                "python_version": None,
            }

        try:
            text = env_path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Cannot read %s: %s", env_path, exc)
            return {
                "dependencies": [],
                "conda_deps": [],
                "pip_deps": [],
                "channels": [],
                "python_version": None,
            }

        if yaml is None:
            logger.warning("PyYAML not available; cannot parse environment.yml")
            return {
                "dependencies": [],
                "conda_deps": [],
                "pip_deps": [],
                "channels": [],
                "python_version": None,
            }

        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            logger.warning("Failed to parse %s: %s", env_path, exc)
            return {
                "dependencies": [],
                "conda_deps": [],
                "pip_deps": [],
                "channels": [],
                "python_version": None,
            }

        if not isinstance(data, dict):
            return {
                "dependencies": [],
                "conda_deps": [],
                "pip_deps": [],
                "channels": [],
                "python_version": None,
            }

        raw_deps = data.get("dependencies", [])
        conda_deps: list[str] = []
        pip_deps: list[str] = []
        python_version: str | None = None

        for dep in raw_deps:
            if isinstance(dep, dict) and "pip" in dep:
                pip_deps.extend(dep["pip"])
            elif isinstance(dep, str):
                conda_deps.append(dep)
                # Extract Python version
                if dep.startswith("python") and "=" in dep:
                    py_part = dep.split("=")[-1].strip()
                    if re.match(r"^\d+(\.\d+)*", py_part):
                        python_version = py_part

        return {
            "dependencies": conda_deps + pip_deps,
            "conda_deps": conda_deps,
            "pip_deps": pip_deps,
            "channels": data.get("channels", []),
            "python_version": python_version,
        }

    def infer_from_setup_py(self, setup_path: Path) -> dict:
        """Parse a ``setup.py`` using AST analysis (never ``exec``).

        Returns a dict with:
        - ``dependencies`` (list[str]): install_requires
        - ``python_requires`` (str | None)
        - ``extras_require`` (dict[str, list[str]])
        """
        if not setup_path.is_file():
            return {
                "dependencies": [],
                "python_requires": None,
                "extras": {},
            }

        try:
            source = setup_path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Cannot read %s: %s", setup_path, exc)
            return {
                "dependencies": [],
                "python_requires": None,
                "extras": {},
            }

        parsed = self._parse_setup_ast(source)
        return {
            "dependencies": parsed.get("install_requires", []),
            "python_requires": parsed.get("python_requires"),
            "extras": parsed.get("extras_require", {}),
        }

    def infer_all(self, project_dir: Path) -> dict:
        """Combine inferences from all detected project files.

        Scans *project_dir* for ``pyproject.toml``, ``requirements.txt``,
        ``environment.yml``, and ``setup.py``, merging results.

        Returns a dict with merged ``dependencies``, ``python_version``,
        ``extras``, ``conda_deps``, ``pip_deps``, ``channels``, and
        ``sources`` keys.
        """
        merged: dict[str, Any] = {
            "dependencies": [],
            "python_version": None,
            "extras": {},
            "conda_deps": [],
            "pip_deps": [],
            "channels": [],
            "sources": [],
        }

        # pyproject.toml
        pyproject = project_dir / "pyproject.toml"
        if pyproject.is_file():
            info = self.infer_from_pyproject(pyproject)
            merged["dependencies"].extend(info.get("dependencies", []))
            if info.get("python_version"):
                merged["python_version"] = info["python_version"]
            merged["extras"].update(info.get("extras", {}))
            if info.get("build_system"):
                merged["build_system"] = info["build_system"]
            merged["sources"].append("pyproject.toml")

        # requirements.txt
        req_file = project_dir / "requirements.txt"
        if req_file.is_file():
            info = self.infer_from_requirements(req_file)
            merged["dependencies"].extend(info.get("dependencies", []))
            merged["sources"].append("requirements.txt")

        # requirements-dev.txt
        req_dev = project_dir / "requirements-dev.txt"
        if req_dev.is_file():
            info = self.infer_from_requirements(req_dev)
            merged["extras"]["dev"] = info.get("dependencies", [])
            merged["sources"].append("requirements-dev.txt")

        # environment.yml
        env_file = project_dir / "environment.yml"
        if env_file.is_file():
            info = self.infer_from_conda_env(env_file)
            merged["conda_deps"].extend(info.get("conda_deps", []))
            merged["pip_deps"].extend(info.get("pip_deps", []))
            merged["channels"].extend(info.get("channels", []))
            if info.get("python_version") and not merged["python_version"]:
                merged["python_version"] = info["python_version"]
            merged["sources"].append("environment.yml")

        # setup.py
        setup_file = project_dir / "setup.py"
        if setup_file.is_file() and "pyproject.toml" not in merged["sources"]:
            info = self.infer_from_setup_py(setup_file)
            if not merged["dependencies"]:
                merged["dependencies"].extend(info.get("dependencies", []))
            if info.get("python_requires") and not merged["python_version"]:
                merged["python_version"] = info["python_requires"]
            merged["extras"].update(info.get("extras", {}))
            merged["sources"].append("setup.py")

        # Deduplicate dependencies while preserving order
        seen: set[str] = set()
        deduped: list[str] = []
        for dep in merged["dependencies"]:
            name = _extract_package_name(dep)
            if name and name.lower() not in seen:
                seen.add(name.lower())
                deduped.append(dep)
        merged["dependencies"] = deduped

        return merged

    def detect_accelerator_need(self, dependencies: list[str]) -> dict:
        """Analyse *dependencies* to determine GPU / accelerator needs.

        Checks whether any of the known accelerator packages (torch,
        tensorflow, jax, etc.) appear in the dependency list and returns
        a recommendation.

        Returns a dict with:
        - ``needs_cuda`` (bool)
        - ``needs_mps`` (bool)
        - ``recommended_target`` (str)
        - ``reasoning`` (str)
        - ``matching_packages`` (list[str])
        """
        dep_names = {_extract_package_name(d).lower() for d in dependencies}

        needs_cuda = False
        needs_mps = False
        reasons: list[str] = []
        matching: list[str] = []
        recommended = AcceleratorTarget.CPU

        for pkg_name, hint in _ACCELERATOR_HINTS.items():
            if pkg_name in dep_names:
                matching.append(pkg_name)
                if hint["needs_cuda"]:
                    needs_cuda = True
                if hint["needs_mps"]:
                    needs_mps = True
                reasons.append(hint["reasoning"])
                if recommended == AcceleratorTarget.CPU:
                    recommended = hint["recommended_target"]

        if not matching:
            return {
                "needs_cuda": False,
                "needs_mps": False,
                "recommended_target": AcceleratorTarget.CPU,
                "reasoning": "No accelerator-dependent packages detected",
                "matching_packages": [],
            }

        # If on macOS and only MPS-compatible packages found, recommend MPS
        import sys
        if sys.platform == "darwin" and not needs_cuda:
            recommended = AcceleratorTarget.MPS
            reasons.append(
                "macOS detected and no CUDA-only packages; recommending MPS"
            )

        return {
            "needs_cuda": needs_cuda,
            "needs_mps": needs_mps,
            "recommended_target": recommended,
            "reasoning": "; ".join(reasons),
            "matching_packages": matching,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_setup_ast(source: str) -> dict:
        """Walk the AST of *source* to extract ``setup()`` keyword arguments.

        This method never uses ``exec`` or ``eval``; it relies entirely on
        safe AST traversal.

        Returns a dict with any of:
        - ``install_requires`` (list[str])
        - ``python_requires`` (str)
        - ``extras_require`` (dict[str, list[str]])
        """
        result: dict[str, Any] = {}

        try:
            tree = ast.parse(source)
        except SyntaxError:
            return result

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            func_name: str
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                func_name = node.func.attr
            else:
                continue

            if func_name != "setup":
                continue

            # Extract keyword arguments
            for kw in node.keywords:
                key = kw.arg
                if key is None:
                    continue

                value = _ast_value_to_python(kw.value)
                if value is not None:
                    result[key] = value

        return result


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------

def _ast_value_to_python(node: ast.expr) -> Any:
    """Safely convert an AST node to a Python value.

    Supports: strings, numbers, lists, dicts, ``None``, ``True``, ``False``.
    """
    if isinstance(node, ast.Constant):
        return node.value

    if isinstance(node, ast.List):
        return [_ast_value_to_python(elt) for elt in node.elts]

    if isinstance(node, ast.Dict):
        keys = [_ast_value_to_python(k) for k in node.keys]
        values = [_ast_value_to_python(v) for v in node.values]
        return dict(zip(keys, values, strict=False))

    if isinstance(node, ast.Tuple):
        return tuple(_ast_value_to_python(elt) for elt in node.elts)

    # ast.NameConstant (Python 3.7)
    if hasattr(ast, "NameConstant") and isinstance(node, ast.NameConstant):
        return node.value  # type: ignore[attr-defined]

    # ast.Num / ast.Str (Python 3.7)
    if hasattr(ast, "Num") and isinstance(node, ast.Num):
        return node.n  # type: ignore[attr-defined]
    if hasattr(ast, "Str") and isinstance(node, ast.Str):
        return node.s  # type: ignore[attr-defined]

    return None


def _extract_package_name(requirement: str) -> str:
    """Extract the package name from a PEP 508 requirement string."""
    m = _REQ_NAME_RE.match(requirement.strip())
    return m.group(0) if m else requirement.strip().split("[")[0].split(";")[0].strip()


def _format_poetry_dep(name: str, spec: Any) -> str:
    """Format a Poetry-style dependency as a PEP 508 string."""
    if isinstance(spec, str):
        # ">=1.0" style
        return f"{name}{spec}"
    if isinstance(spec, dict):
        version = spec.get("version", "")
        extras = spec.get("extras", [])
        marker = spec.get("markers", "")

        parts = [name]
        if version:
            parts.append(version)
        if extras:
            parts.append(f"[{','.join(extras)}]")
        if marker:
            parts.append(f"; {marker}")
        return " ".join(parts)
    return name
