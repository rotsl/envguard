# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""Package builder — wraps ``python -m build`` to produce sdist and wheel."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from envguard.exceptions import PublishError
from envguard.logging import get_logger

logger = get_logger(__name__)


class Builder:
    """Build a Python package using ``python -m build``.

    Args:
        project_dir: Root of the project (must contain ``pyproject.toml``
            or ``setup.py``).
        dist_dir: Output directory for built artifacts.  Defaults to
            ``<project_dir>/dist``.
    """

    def __init__(
        self,
        project_dir: Path,
        dist_dir: Path | None = None,
    ) -> None:
        self.project_dir = Path(project_dir)
        self.dist_dir = dist_dir or (self.project_dir / "dist")

    def build(
        self,
        sdist: bool = True,
        wheel: bool = True,
        clean: bool = False,
    ) -> list[Path]:
        """Build the package and return paths to the produced artifacts.

        Args:
            sdist: Build a source distribution (``*.tar.gz``).
            wheel: Build a wheel (``*.whl``).
            clean: Remove the dist directory before building.

        Returns:
            Sorted list of :class:`~pathlib.Path` objects for the
            built artifacts.

        Raises:
            PublishError: If the build fails or ``build`` is not installed.
        """
        self._check_build_available()

        if clean and self.dist_dir.exists():
            import shutil

            shutil.rmtree(self.dist_dir)
            logger.debug("Cleaned dist directory: %s", self.dist_dir)

        self.dist_dir.mkdir(parents=True, exist_ok=True)

        cmd = [sys.executable, "-m", "build", "--outdir", str(self.dist_dir)]
        if sdist and not wheel:
            cmd.append("--sdist")
        elif wheel and not sdist:
            cmd.append("--wheel")
        # Both: omit flag — build produces both by default

        logger.info("Building package in %s...", self.project_dir)
        logger.debug("Build command: %s", " ".join(cmd))

        try:
            proc = subprocess.run(
                cmd,
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                timeout=300,
            )
        except subprocess.TimeoutExpired as exc:
            raise PublishError(
                operation="build",
                reason="Build timed out after 300 s",
            ) from exc
        except FileNotFoundError as exc:
            raise PublishError(
                operation="build",
                reason=f"Python executable not found: {exc}",
            ) from exc

        if proc.returncode != 0:
            raise PublishError(
                operation="build",
                reason=proc.stderr.strip()[:1000] or proc.stdout.strip()[:1000],
            )

        artifacts = sorted(self.dist_dir.glob("*.whl")) + sorted(self.dist_dir.glob("*.tar.gz"))
        if not artifacts:
            raise PublishError(
                operation="build",
                reason=f"Build succeeded but no artifacts found in {self.dist_dir}",
            )

        logger.info("Built %d artifact(s): %s", len(artifacts), [a.name for a in artifacts])
        return artifacts

    def _check_build_available(self) -> None:
        """Raise PublishError if the ``build`` package is not importable."""
        import importlib.util

        if importlib.util.find_spec("build") is None:
            raise PublishError(
                operation="build",
                reason=("The 'build' package is not installed. Install it with: pip install build"),
            )

    def list_artifacts(self) -> list[Path]:
        """Return existing artifacts in the dist directory."""
        if not self.dist_dir.exists():
            return []
        return sorted(self.dist_dir.glob("*.whl")) + sorted(self.dist_dir.glob("*.tar.gz"))
