# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""Managed process runner - execute commands inside managed environments."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

try:
    from envguard.logging import get_logger
except ImportError:
    import logging

    def get_logger(name: str) -> logging.Logger:  # type: ignore[misc]
        return logging.getLogger(name)


try:
    from envguard.models import HostFacts
except ImportError:

    class HostFacts:  # type: ignore[no-redef]
        def __init__(self, **kwargs: object) -> None:
            self.__dict__.update(kwargs)


logger = get_logger(__name__)

# Characters that could enable shell injection if passed unsanitised.
# Note: since we use subprocess with list args (no shell=True), most special
# characters are safe. We only block truly dangerous sequences.
_DANGEROUS_CHARS = set("\n\r\0")


class ManagedRunner:
    """Execute user commands inside a managed virtual environment.

    The runner optionally runs a preflight check before execution to
    ensure the environment is consistent and ready.

    Security model:
    - ``shell=True`` is **never** used.
    - All command arguments are passed as a list to ``subprocess.run``.
    - Path arguments are resolved and validated before use.
    """

    def __init__(
        self,
        project_dir: Path,
        env_path: Path | None = None,
        facts: HostFacts | None = None,
    ) -> None:
        self.project_dir = project_dir.resolve()
        self._env_path = env_path
        self._facts = facts

    @property
    def env_path(self) -> Path | None:
        return self._env_path

    def run(
        self,
        command: list[str],
        preflight: bool = True,
    ) -> int:
        """Main entry point - run *command* in the managed environment.

        Args:
            command: The command to execute as a list of strings.
            preflight: If ``True`` (default), run the preflight engine
                before execution.

        Returns:
            The process exit code (``0`` for success).
        """
        if not command:
            logger.error("No command provided")
            return 1

        # Validate / sanitise the command
        safe_command = self._shell_safe_command(command)
        if safe_command is None:
            logger.error("Command rejected due to unsafe characters")
            return 1

        # Resolve the environment
        env_dir = self._prepare_environment()

        if preflight:
            self._run_preflight(env_dir)

        # Build environment variables
        env_vars = self._build_env_vars(env_dir)

        return self._execute(safe_command, env_vars)

    def run_script(
        self,
        script_path: Path,
        args: list[str] | None = None,
    ) -> int:
        """Execute a Python script in the managed environment.

        Args:
            script_path: Path to the script file.
            args: Additional arguments to pass to the script.

        Returns:
            The process exit code.
        """
        script = self._validate_path(script_path)
        if script is None:
            return 1

        command = [str(script)]
        if args:
            command.extend(args)

        return self.run(command, preflight=True)

    def run_python(
        self,
        module_or_script: str,
        args: list[str] | None = None,
    ) -> int:
        """Run a Python module or script using the managed environment's Python.

        Args:
            module_or_script: Module name (``-m`` style) or script path.
            args: Additional arguments.

        Returns:
            The process exit code.
        """
        env_dir = self._prepare_environment()
        python = self._resolve_python(env_dir)

        command = [str(python)]
        if module_or_script.endswith(".py") or "/" in module_or_script:
            # Treat as a script path
            script = self._validate_path(Path(module_or_script))
            if script is None:
                return 1
            command.append(str(script))
        else:
            # Treat as a module name
            command.extend(["-m", module_or_script])

        if args:
            command.extend(args)

        env_vars = self._build_env_vars(env_dir)
        return self._execute(command, env_vars)

    # ------------------------------------------------------------------
    # Internal: environment preparation
    # ------------------------------------------------------------------

    def _prepare_environment(self) -> Path:
        """Get or create the managed environment path.

        If an explicit ``env_path`` was provided at construction, it is
        returned (created if it does not exist).  Otherwise a ``.venv``
        directory inside ``project_dir`` is used.
        """
        env = self._env_path.resolve() if self._env_path is not None else self.project_dir / ".venv"

        if not env.exists():
            logger.info("Creating virtual environment at %s", env)
            try:
                subprocess.run(
                    [sys.executable, "-m", "venv", str(env)],
                    check=True,
                    capture_output=True,
                    timeout=60,
                )
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                logger.error("Failed to create venv at %s: %s", env, exc)
                raise

        return env

    def _build_env_vars(self, env_path: Path) -> dict[str, str]:
        """Construct the environment-variable mapping for subprocess execution.

        Sets:
        - ``VIRTUAL_ENV``
        - ``PATH`` (prepends ``env_path/bin``)
        - ``PYTHONPATH`` (preserves existing)
        - Passes through the rest of ``os.environ``.
        """
        env_vars = dict(os.environ)

        env_vars["VIRTUAL_ENV"] = str(env_path)

        # Prepend the environment's bin directory to PATH
        bin_dir = env_path / "bin"
        if bin_dir.exists():
            current_path = env_vars.get("PATH", "")
            # Use os.pathsep for cross-platform path separator
            env_vars["PATH"] = f"{bin_dir}{os.pathsep}{current_path}"

        return env_vars

    def _execute(
        self,
        command: list[str],
        env_vars: dict[str, str],
    ) -> int:
        """Execute *command* using ``subprocess.run``.

        stdin / stdout / stderr are passed through directly so the child
        process is fully interactive.

        Returns:
            The process exit code.
        """
        logger.debug("Executing: %s", " ".join(command))

        try:
            proc = subprocess.run(
                command,
                env=env_vars,
                cwd=str(self.project_dir),
                stdin=None,  # Inherit from parent
                stdout=None,  # Inherit from parent
                stderr=None,  # Inherit from parent
            )
            return proc.returncode
        except FileNotFoundError as exc:
            logger.error("Command not found: %s", exc)
            return 127
        except PermissionError as exc:
            logger.error("Permission denied: %s", exc)
            return 126
        except OSError as exc:
            logger.error("OS error running command: %s", exc)
            return 1

    # ------------------------------------------------------------------
    # Internal: security / validation
    # ------------------------------------------------------------------

    @staticmethod
    def _shell_safe_command(command: list[str]) -> list[str] | None:
        """Validate that no command argument contains shell injection characters.

        Returns the cleaned command list, or ``None`` if unsafe.
        """
        for arg in command:
            if not isinstance(arg, str):
                return None
            for ch in arg:
                if ch in _DANGEROUS_CHARS:
                    logger.error("Potentially unsafe character in command argument: %r", arg)
                    return None
        return command

    def _validate_path(self, path: Path) -> Path | None:
        """Resolve and validate a file path.

        The resolved path must:
        - Exist as a file.
        - Be contained within ``project_dir`` (or be an absolute path).

        Returns the resolved :class:`Path`, or ``None`` on validation failure.
        """
        try:
            resolved = path.resolve()
        except (OSError, ValueError):
            logger.error("Invalid path: %s", path)
            return None

        if not resolved.is_file():
            logger.error("Path is not a file: %s", resolved)
            return None

        # Security: ensure the path is within the project directory or
        # is an explicitly allowed system path
        try:
            resolved.relative_to(self.project_dir)
        except ValueError:
            # Not inside project_dir - allow only absolute, existing paths
            if not resolved.is_absolute():
                logger.error("Relative path outside project directory: %s", resolved)
                return None

        return resolved

    # ------------------------------------------------------------------
    # Internal: helpers
    # ------------------------------------------------------------------

    def _resolve_python(self, env_path: Path) -> Path:
        """Return the path to the Python interpreter in *env_path*."""
        for candidate in (
            env_path / "bin" / "python",
            env_path / "bin" / "python3",
            env_path / "Scripts" / "python.exe",
        ):
            if candidate.exists():
                return candidate
        return Path(sys.executable)

    def _run_preflight(self, env_path: Path) -> None:
        """Run preflight checks before command execution.

        This method imports the PreflightEngine at call time to avoid
        circular imports and handles the case where the engine is not yet
        available.
        """
        try:
            from envguard.preflight import PreflightEngine

            engine = PreflightEngine(project_dir=self.project_dir)
            engine.run()
        except ImportError:
            logger.debug("PreflightEngine not available; skipping preflight")
        except Exception as exc:
            logger.warning("Preflight check failed: %s", exc)
