# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""uv resolver backend — wraps the ``uv`` CLI."""

from __future__ import annotations

import contextlib
import shutil
import subprocess
from typing import TYPE_CHECKING

from envguard.resolver.base import BaseResolver

if TYPE_CHECKING:
    from pathlib import Path

try:
    from envguard.logging import get_logger
except ImportError:
    import logging

    def get_logger(name: str) -> logging.Logger:  # type: ignore[misc]
        return logging.getLogger(name)


try:
    from envguard.models import FindingSeverity, RuleFinding
except ImportError:

    class FindingSeverity:  # type: ignore[no-redef]
        WARNING = "warning"
        ERROR = "error"

    class RuleFinding:  # type: ignore[no-redef]
        def __init__(self, **kwargs: object) -> None:
            self.__dict__.update(kwargs)


logger = get_logger(__name__)


class UvBackend(BaseResolver):
    """Package resolver/installer backend using ``uv``.

    ``uv`` is a drop-in replacement for ``pip`` and ``venv`` written in Rust.
    When available it is significantly faster than pip for both installs and
    environment creation.
    """

    def is_available(self) -> bool:
        return shutil.which("uv") is not None

    def resolve(
        self,
        requirements: list[str],
        constraints: list[str] | None = None,
    ) -> list[str]:
        """Use ``uv pip compile`` to resolve a requirement set."""
        if not self.is_available():
            return []

        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as req_file:
            req_file.write("\n".join(requirements))
            req_path = req_file.name

        try:
            cmd = ["uv", "pip", "compile", req_path, "--no-header", "--quiet"]
            if constraints:
                import tempfile as _tf

                with _tf.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as cf:
                    cf.write("\n".join(constraints))
                    cmd += ["--constraint", cf.name]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode == 0:
                return [
                    line.strip()
                    for line in result.stdout.splitlines()
                    if line.strip() and not line.startswith("#")
                ]
            logger.warning("uv pip compile failed: %s", result.stderr.strip())
            return []
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            logger.warning("uv resolve error: %s", exc)
            return []
        finally:
            import os

            with contextlib.suppress(OSError):
                os.unlink(req_path)

    def install(self, packages: list[str], env_path: Path) -> bool:
        """Install *packages* into *env_path* using ``uv pip install``."""
        if not packages:
            return True
        python = env_path / "bin" / "python"
        cmd = ["uv", "pip", "install", "--python", str(python), *packages]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode != 0:
                logger.error("uv install failed: %s", result.stderr.strip())
                return False
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            logger.error("uv install error: %s", exc)
            return False

    def list_installed(self, env_path: Path) -> list[str]:
        python = env_path / "bin" / "python"
        try:
            result = subprocess.run(
                ["uv", "pip", "list", "--python", str(python), "--format=freeze"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                return [line.strip() for line in result.stdout.splitlines() if line.strip()]
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return []

    def validate(self, env_path: Path) -> list[RuleFinding]:
        """uv does not provide a ``pip check`` equivalent; returns empty list."""
        return []

    def freeze(self, env_path: Path) -> list[str]:
        return self.list_installed(env_path)
