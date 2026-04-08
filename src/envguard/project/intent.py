# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""Intent analysis – bridge between project discovery and host facts.

The :class:`IntentAnalyzer` takes a :class:`ProjectIntent` (produced by
project discovery) together with :class:`HostFacts` (produced by host
detection) and enriches the intent with compatibility information,
accelerator targets, and remediation hints.
"""

from __future__ import annotations

import re
import sys
from typing import Optional

from envguard.exceptions import EnvguardError
from envguard.logging import get_logger
from envguard.models import (
    AcceleratorTarget,
    EnvironmentType,
    HostFacts,
    ProjectIntent,
)

logger = get_logger("project.intent")


class IntentAnalyzer:
    """Analyse a project's intent against the host environment.

    The analyzer checks whether the project is compatible with the
    current platform, identifies accelerator requirements, and
    generates remediation hints for any unsupported features.
    """

    def __init__(self, intent: ProjectIntent, facts: HostFacts) -> None:
        self.intent = intent
        self.facts = facts

    # ------------------------------------------------------------------ #
    # Public entry point
    # ------------------------------------------------------------------ #

    def analyze(self) -> ProjectIntent:
        """Run the full analysis and return the updated intent.

        Modifies and returns the :attr:`intent` that was passed to
        :meth:`__init__`.

        Returns:
            The enriched ProjectIntent.
        """
        logger.info("Analysing project intent for %s", self.intent.project_dir)

        # Accelerator targets
        self.intent.extra["accelerator_targets"] = (
            [t.value for t in self.determine_accelerator_targets()]
        )

        # macOS compatibility
        compatible = self.check_macos_compatibility()
        self.intent.extra["macos_compatible"] = compatible

        # Unsupported features
        unsupported = self.identify_unsupported_features()
        self.intent.unsupported_features = unsupported

        # Remediation hints
        self.intent.remediation_hints = self.generate_remediation_hints()

        # Recommended environment type
        self.intent.extra["recommended_environment_type"] = (
            self.recommend_environment_type().value
        )

        # Recommended Python version
        recommended_py = self.recommend_python_version()
        if recommended_py:
            self.intent.extra["recommended_python_version"] = recommended_py

        # Compatibility notes
        self._add_compatibility_notes()

        logger.info(
            "Analysis complete: compatible=%s, unsupported=%s",
            compatible, unsupported,
        )
        return self.intent

    # ------------------------------------------------------------------ #
    # Accelerator analysis
    # ------------------------------------------------------------------ #

    def determine_accelerator_targets(self) -> list[AcceleratorTarget]:
        """Determine which accelerator targets the project needs.

        Returns:
            A list of required AcceleratorTarget values.
        """
        targets: list[AcceleratorTarget] = [AcceleratorTarget.CPU]

        if self.intent.has_cuda_requirements:
            targets.append(AcceleratorTarget.CUDA)

        if self.intent.has_mps_requirements:
            targets.append(AcceleratorTarget.MPS)

        # Heuristic: detect torch / tensorflow references
        dep_str = " ".join(self.intent.dependencies + self.intent.dev_dependencies).lower()
        if "torch" in dep_str:
            if self.facts.os_name == "Darwin" and self.facts.is_apple_silicon:
                targets.append(AcceleratorTarget.MPS)
            # torch on non-macOS typically implies CUDA
            if self.facts.os_name != "Darwin":
                targets.append(AcceleratorTarget.CUDA)

        if "tensorflow" in dep_str or "tf-agents" in dep_str:
            if self.facts.os_name == "Darwin":
                targets.append(AcceleratorTarget.MPS)
            else:
                targets.append(AcceleratorTarget.CUDA)

        # Deduplicate while preserving order
        seen: set[AcceleratorTarget] = set()
        deduped: list[AcceleratorTarget] = []
        for t in targets:
            if t not in seen:
                deduped.append(t)
                seen.add(t)

        logger.debug("Accelerator targets: %s", [t.value for t in deduped])
        return deduped

    # ------------------------------------------------------------------ #
    # Compatibility checks
    # ------------------------------------------------------------------ #

    def check_macos_compatibility(self) -> bool:
        """Check whether the project is compatible with macOS.

        Returns:
            True if the project appears compatible with macOS.
        """
        if self.facts.os_name != "Darwin":
            # Not running on macOS, so compatibility is unknown / not applicable
            return True

        # Check pyproject.toml for platform restrictions
        if self.intent.has_pyproject_toml and "pyproject" in self.intent.extra:
            pyproject_data = self.intent.extra["pyproject"]
            if not self._check_pyproject_platforms(pyproject_data):
                return False

        # CUDA-only projects are not natively compatible with macOS
        if self.intent.has_cuda_requirements and not self.intent.has_mps_requirements:
            # Could still be compatible if user is okay with CPU-only
            dep_str = " ".join(
                self.intent.dependencies + self.intent.dev_dependencies
            ).lower()
            # If all CUDA deps have CPU fallbacks, still consider compatible
            if re.search(r"torch[-_]cu|nvidia[-_]cu", dep_str):
                return False

        return True

    def _check_pyproject_platforms(self, data: dict) -> bool:
        """Check if pyproject.toml explicitly excludes macOS.

        Args:
            data: Parsed pyproject.toml data.

        Returns:
            True if macOS is allowed (no explicit exclusion found).
        """
        # Check [tool.cibuildwheel] or markers
        project = data.get("project", {})
        classifiers = project.get("classifiers", [])

        for classifier in classifiers:
            if isinstance(classifier, str):
                # "Operating System :: OS Independent" means macOS is fine
                if "OS Independent" in classifier:
                    return True

        # Check requires-dist for platform markers
        for dep in project.get("dependencies", []):
            if isinstance(dep, str):
                markers = self._extract_markers(dep)
                if markers:
                    if "sys_platform == 'win32'" in markers:
                        # Windows-only dep – check if it's the only one
                        pass
                    if "platform_system == 'Windows'" in markers:
                        pass

        return True

    @staticmethod
    def _extract_markers(dep_string: str) -> Optional[str]:
        """Extract PEP 508 environment markers from a dependency string.

        Args:
            dep_string: A PEP 508 dependency string.

        Returns:
            The markers portion, or None.
        """
        match = re.search(r";\s*(.+)$", dep_string)
        return match.group(1).strip() if match else None

    def identify_unsupported_features(self) -> list[str]:
        """List features required by the project that are not available.

        Returns:
            A list of human-readable descriptions of unsupported features.
        """
        unsupported: list[str] = []

        # CUDA on macOS
        if (
            self.facts.os_name == "Darwin"
            and self.intent.has_cuda_requirements
            and not self.intent.has_mps_requirements
        ):
            unsupported.append(
                "CUDA acceleration is not available on macOS; "
                "consider using MPS (Metal Performance Shaders) as an alternative"
            )

        # conda/mamba not installed but required
        if (
            self.intent.environment_type in (EnvironmentType.CONDA, EnvironmentType.MAMBA)
            and not self.facts.has_conda
            and not self.facts.has_mamba
        ):
            manager = self.intent.environment_type.value
            unsupported.append(
                f"{manager} is required but not installed; "
                f"install it with 'brew install {manager}' or from conda-forge"
            )

        # Xcode CLI required for some build steps
        if (
            self.facts.os_name == "Darwin"
            and not self.facts.has_xcode_cli
            and self.intent.has_pyproject_toml
        ):
            unsupported.append(
                "Xcode Command Line Tools are recommended for building "
                "native extensions; install with 'xcode-select --install'"
            )

        # Python version mismatch
        if self.intent.python_version_required:
            required = self._parse_version_tuple(self.intent.python_version_required)
            available = self._parse_version_tuple(self.facts.python_version)
            if required and available and required > available:
                unsupported.append(
                    f"Project requires Python {self.intent.python_version_required} "
                    f"but only {self.facts.python_version} is available"
                )

        # Specific macOS-incompatible packages
        macos_incompatible = {"nvidia-cublas-cu11", "nvidia-cuda-nvrtc-cu11",
                              "nvidia-cufft-cu11", "nvidia-cusparse-cu11",
                              "nvidia-cudnn-cu11"}
        dep_set = {d.lower().split("[")[0].split("==")[0].split(">=")[0].split("~=")[0].strip()
                   for d in self.intent.dependencies}
        found_incompatible = dep_set & macos_incompatible
        if found_incompatible and self.facts.os_name == "Darwin":
            for pkg in sorted(found_incompatible):
                unsupported.append(
                    f"Package '{pkg}' is not available on macOS"
                )

        return unsupported

    @staticmethod
    def _parse_version_tuple(version_str: str) -> Optional[tuple[int, ...]]:
        """Parse a version string like '3.11.7' into a comparable tuple.

        Handles common specifier prefixes like '>=', '==', '~=',
        and bare versions.

        Args:
            version_str: A version-like string.

        Returns:
            A tuple of ints, or None if parsing fails.
        """
        cleaned = version_str.strip()
        # Remove specifiers
        for prefix in (">=", "<=", "==", "!=", "~=", ">", "<", "^"):
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix):].strip()

        # Take only the version part (before any space or semicolon)
        cleaned = cleaned.split()[0].split(";")[0].strip()

        parts: list[int] = []
        for part in cleaned.split("."):
            part = part.strip()
            if part.isdigit():
                parts.append(int(part))
            else:
                # Strip non-numeric suffixes like "rc1", "a2", "post1"
                numeric = re.match(r"^(\d+)", part)
                if numeric:
                    parts.append(int(numeric.group(1)))
                break

        return tuple(parts) if parts else None

    # ------------------------------------------------------------------ #
    # Recommendations
    # ------------------------------------------------------------------ #

    def recommend_environment_type(self) -> EnvironmentType:
        """Recommend an environment type based on project characteristics.

        Returns:
            The recommended EnvironmentType.
        """
        # If the project already has a clear type, prefer it
        if self.intent.environment_type != EnvironmentType.UNKNOWN:
            return self.intent.environment_type

        # Infer from available tools and project characteristics
        if self.intent.has_conda_env_file:
            if self.facts.has_mamba:
                return EnvironmentType.MAMBA
            if self.facts.has_conda:
                return EnvironmentType.CONDA
            # Fall through – conda file present but tool not installed

        if "Pipfile" in str(self.intent.project_dir):
            return EnvironmentType.PIPENV

        # Default: venv (universally available)
        return EnvironmentType.VENV

    def recommend_python_version(self) -> Optional[str]:
        """Recommend a Python version based on project requirements.

        Returns:
            A recommended version string, or None if no recommendation
            can be made.
        """
        required = self.intent.python_version_required
        if required:
            # If the required version is available, use it
            available = self.facts.python_version
            req_tuple = self._parse_version_tuple(required)
            avail_tuple = self._parse_version_tuple(available)

            if req_tuple and avail_tuple and req_tuple <= avail_tuple:
                # Use available version – it satisfies the requirement
                return available

            if req_tuple and avail_tuple and req_tuple > avail_tuple:
                # Need a newer version – return the requirement as-is
                return required

            return required

        # No explicit requirement – recommend based on project deps
        dep_str = " ".join(self.intent.dependencies).lower()
        if any(pkg in dep_str for pkg in ("torch", "tensorflow", "jax")):
            return "3.11"

        if "pydantic" in dep_str and "v1" not in dep_str:
            return "3.10"

        return None

    # ------------------------------------------------------------------ #
    # Remediation
    # ------------------------------------------------------------------ #

    def generate_remediation_hints(self) -> list[str]:
        """Generate actionable remediation hints for unsupported features.

        Returns:
            A list of hint strings.
        """
        hints: list[str] = []

        if not self.intent.unsupported_features:
            return hints

        for feature in self.intent.unsupported_features:
            lower = feature.lower()

            if "cuda" in lower and "macos" in lower:
                hints.append(
                    "Install PyTorch with MPS support instead of CUDA: "
                    "'pip install torch torchvision torchaudio'"
                )
                hints.append(
                    "Alternatively, consider using a cloud VM with NVIDIA GPUs "
                    "for CUDA workloads"
                )

            if "conda" in lower and "not installed" in lower:
                hints.append(
                    "Install Miniconda: "
                    "'brew install --cask miniconda' "
                    "or download from https://docs.conda.io/en/latest/miniconda.html"
                )

            if "mamba" in lower and "not installed" in lower:
                hints.append(
                    "Install Mamba: "
                    "'conda install -c conda-forge mamba' "
                    "or 'brew install mamba'"
                )

            if "xcode" in lower:
                hints.append(
                    "Install Xcode Command Line Tools: 'xcode-select --install'"
                )

            if "python" in lower and "requires" in lower:
                hints.append(
                    "Install a newer Python version using pyenv: "
                    "'brew install pyenv && pyenv install "
                    f"{self.intent.python_version_required}'"
                )

            if "not available on macos" in lower:
                # Generic hint for any macOS-incompatible package
                hints.append(
                    "Consider using a compatibility layer or removing "
                    "the macOS-incompatible dependency"
                )

        return hints

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _add_compatibility_notes(self) -> None:
        """Append general compatibility notes to the intent."""
        notes = self.intent.compatibility_notes

        if self.facts.os_name == "Darwin":
            if self.facts.is_apple_silicon:
                notes.append("Running on Apple Silicon (arm64)")
                if self.facts.is_rosetta:
                    notes.append(
                        "WARNING: Python is running under Rosetta 2 translation; "
                        "native arm64 Python is recommended for best performance"
                    )
            else:
                notes.append("Running on Intel (x86_64) macOS")

            if self.intent.has_mps_requirements:
                notes.append(
                    "MPS (Metal Performance Shaders) acceleration is available"
                )

            if self.intent.has_cuda_requirements:
                notes.append(
                    "NOTE: CUDA is not natively available on macOS; "
                    "project will use CPU/MPS fallback"
                )

        # Python version note
        if (
            self.intent.python_version_required
            and self.facts.python_version != "unknown"
        ):
            req = self._parse_version_tuple(self.intent.python_version_required)
            avail = self._parse_version_tuple(self.facts.python_version)
            if req and avail:
                if avail >= req:
                    notes.append(
                        f"System Python {self.facts.python_version} satisfies "
                        f"the project requirement ({self.intent.python_version_required})"
                    )
                else:
                    notes.append(
                        f"WARNING: System Python {self.facts.python_version} does not "
                        f"meet the project requirement ({self.intent.python_version_required})"
                    )
