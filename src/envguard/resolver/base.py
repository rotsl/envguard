# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""Abstract base class for environment resolvers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from envguard.models import Architecture, RuleFinding


class BaseResolver(ABC):
    """Abstract base class that all package resolver backends must implement.

    Resolvers are responsible for dependency resolution, installation,
    environment validation, and requirements freezing. Each concrete
    resolver targets a specific package manager (pip, conda, etc.).
    """

    @abstractmethod
    def resolve(
        self,
        requirements: list[str],
        constraints: list[str] | None = None,
    ) -> list[str]:
        """Resolve dependencies and return list of packages to install.

        Args:
            requirements: List of requirement specifiers (e.g. ``["flask>=2.0"]``).
            constraints: Optional constraint specifiers that limit versions.

        Returns:
            A flat list of resolved package specifiers including transitive
            dependencies.
        """
        ...

    @abstractmethod
    def install(self, packages: list[str], env_path: Path) -> bool:
        """Install packages in the given environment.

        Args:
            packages: List of package specifiers to install.
            env_path: Path to the target virtual / conda environment.

        Returns:
            ``True`` if every package was installed successfully.
        """
        ...

    @abstractmethod
    def list_installed(self, env_path: Path) -> list[str]:
        """List installed packages.

        Args:
            env_path: Path to the environment to inspect.

        Returns:
            List of package names (with optional version) currently installed.
        """
        ...

    @abstractmethod
    def validate(self, env_path: Path) -> list[RuleFinding]:
        """Validate environment consistency.

        Runs dependency-consistency checks (e.g. ``pip check``) and returns
        any issues discovered.

        Args:
            env_path: Path to the environment to validate.

        Returns:
            A list of :class:`~envguard.models.RuleFinding` objects, one per
            issue found.  Returns an empty list when the environment is healthy.
        """
        ...

    @abstractmethod
    def freeze(self, env_path: Path) -> list[str]:
        """Return frozen requirements.

        Produces a fully-pinned requirements list suitable for reproducible
        installs.

        Args:
            env_path: Path to the environment to freeze.

        Returns:
            List of pinned requirement strings (e.g. ``["flask==2.3.3"]``).
        """
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this resolver is available on the system.

        Returns:
            ``True`` if the underlying package manager executable is found on
            ``$PATH``.
        """
        ...

    def check_compatibility(
        self,
        package: str,
        arch: Architecture,
        platform: str,
    ) -> dict:
        """Check if a package or wheel is compatible with the given architecture / platform.

        The default implementation naively returns *compatible*.  Subclasses
        should override this to perform real platform-tag checks.

        Args:
            package: Package name or wheel filename.
            arch: Target architecture enum.
            platform: Platform string (e.g. ``"macosx_arm64"``).

        Returns:
            A dict with keys ``compatible``, ``package``, and ``reason``.
        """
        return {"compatible": True, "package": package, "reason": ""}
