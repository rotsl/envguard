# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""Permission checking for macOS filesystem, network, and subprocess access."""

from __future__ import annotations

import os
import socket
import subprocess
from typing import TYPE_CHECKING

from envguard.logging import get_logger
from envguard.macos.paths import MacPaths
from envguard.models import HostFacts, PermissionStatus, ShellType

if TYPE_CHECKING:
    from pathlib import Path

logger = get_logger(__name__)

# Default timeout for permission-probe operations (seconds)
_NETWORK_TIMEOUT = 5
_SUBPROCESS_TIMEOUT = 10


class PermissionChecker:
    """Check and record various permission facets on the current host.

    Instances are bound to a :class:`HostFacts` object that is progressively
    populated by :meth:`check_all`.
    """

    def __init__(self, facts: HostFacts) -> None:
        """Initialise the checker with a :class:`HostFacts` container.

        Args:
            facts: The facts object that will be updated with results.
        """
        self._facts = facts
        self._logger = get_logger(__name__)

    # ------------------------------------------------------------------
    # File-system permission checks
    # ------------------------------------------------------------------

    def check_write_permission(self, path: Path) -> PermissionStatus:
        """Check whether the current user can write to *path*.

        If *path* does not exist the check targets its parent directory,
        since ``os.access`` on a non-existent path always returns ``False``.

        Args:
            path: The file or directory to probe.

        Returns:
            :attr:`PermissionStatus.GRANTED` if writable,
            :attr:`PermissionStatus.DENIED` otherwise.
        """
        try:
            target = path
            if not path.exists():
                target = path.parent
                if not target.exists():
                    self._logger.debug("Write check: path and parent do not exist: %s", path)
                    return PermissionStatus.DENIED

            if os.access(target, os.W_OK):
                return PermissionStatus.GRANTED
            return PermissionStatus.DENIED
        except OSError as exc:
            self._logger.warning("Write permission check failed for %s: %s", path, exc)
            return PermissionStatus.DENIED

    def check_execute_permission(self, path: Path) -> PermissionStatus:
        """Check whether *path* is executable by the current user.

        Args:
            path: File to probe.

        Returns:
            :attr:`PermissionStatus.GRANTED` if executable,
            :attr:`PermissionStatus.DENIED` otherwise.
        """
        try:
            if not path.exists():
                self._logger.debug("Execute check: path does not exist: %s", path)
                return PermissionStatus.DENIED

            if os.access(path, os.X_OK):
                return PermissionStatus.GRANTED
            return PermissionStatus.DENIED
        except OSError as exc:
            self._logger.warning("Execute permission check failed for %s: %s", path, exc)
            return PermissionStatus.DENIED

    def check_read_permission(self, path: Path) -> PermissionStatus:
        """Check whether *path* is readable by the current user.

        Args:
            path: File or directory to probe.

        Returns:
            :attr:`PermissionStatus.GRANTED` if readable,
            :attr:`PermissionStatus.DENIED` otherwise.
        """
        try:
            if not path.exists():
                self._logger.debug("Read check: path does not exist: %s", path)
                return PermissionStatus.DENIED

            if os.access(path, os.R_OK):
                return PermissionStatus.GRANTED
            return PermissionStatus.DENIED
        except OSError as exc:
            self._logger.warning("Read permission check failed for %s: %s", path, exc)
            return PermissionStatus.DENIED

    # ------------------------------------------------------------------
    # macOS-specific permission checks
    # ------------------------------------------------------------------

    def check_launch_agent_write(self) -> PermissionStatus:
        """Check whether the user LaunchAgents directory is writable.

        Returns:
            :attr:`PermissionStatus.GRANTED` or :attr:`PermissionStatus.DENIED`.
        """
        return self.check_write_permission(MacPaths.user_launch_agent_dir)

    def check_install_dir_write(self, install_dir: Path) -> PermissionStatus:
        """Check whether the installation prefix directory is writable.

        Args:
            install_dir: Target installation directory.

        Returns:
            :attr:`PermissionStatus.GRANTED` or :attr:`PermissionStatus.DENIED`.
        """
        return self.check_write_permission(install_dir)

    def check_project_dir_write(self, project_dir: Path) -> PermissionStatus:
        """Check whether a project directory is writable.

        Args:
            project_dir: Path to the project root.

        Returns:
            :attr:`PermissionStatus.GRANTED` or :attr:`PermissionStatus.DENIED`.
        """
        return self.check_write_permission(project_dir)

    # ------------------------------------------------------------------
    # Subprocess permission check
    # ------------------------------------------------------------------

    def check_subprocess_execution(self) -> PermissionStatus:
        """Verify that the current user can spawn a subprocess.

        Attempts to run ``echo hello`` and checks the result.

        Returns:
            :attr:`PermissionStatus.GRANTED` if the subprocess ran
            successfully, :attr:`PermissionStatus.DENIED` otherwise.
        """
        try:
            result = subprocess.run(
                ["echo", "hello"],
                capture_output=True,
                text=True,
                timeout=_SUBPROCESS_TIMEOUT,
            )
            if result.returncode == 0 and "hello" in result.stdout:
                return PermissionStatus.GRANTED
            self._logger.warning(
                "Subprocess echo returned unexpected output (rc=%d): %s",
                result.returncode,
                result.stderr.strip(),
            )
            return PermissionStatus.DENIED
        except (subprocess.TimeoutExpired, OSError, PermissionError) as exc:
            self._logger.warning("Subprocess execution check failed: %s", exc)
            return PermissionStatus.DENIED

    # ------------------------------------------------------------------
    # Network permission check
    # ------------------------------------------------------------------

    def check_network_access(
        self, host: str = "pypi.org", timeout: int = 5
    ) -> tuple[bool, PermissionStatus]:
        """Check whether the current user can reach *host* on port 443 (HTTPS).

        Args:
            host: Hostname to connect to.
            timeout: Connection timeout in seconds.

        Returns:
            A tuple of ``(can_connect, status)`` where *can_connect* is a
            boolean and *status* is a :class:`PermissionStatus`.
        """
        try:
            sock = socket.create_connection((host, 443), timeout=timeout)
            sock.close()
            return True, PermissionStatus.GRANTED
        except TimeoutError:
            self._logger.warning("Network check timed out connecting to %s", host)
            return False, PermissionStatus.DENIED
        except OSError as exc:
            self._logger.warning("Network check failed for %s: %s", host, exc)
            return False, PermissionStatus.DENIED

    # ------------------------------------------------------------------
    # Shell rc-file write check
    # ------------------------------------------------------------------

    def check_shell_rc_write(self, shell: ShellType) -> PermissionStatus:
        """Check whether the current user can write to the shell's rc file(s).

        Tries each candidate rc file for the given *shell* (from
        :meth:`MacPaths.shell_rc_candidates`) and returns the first successful
        result.  If no candidate can be written, returns
        :attr:`PermissionStatus.DENIED`.

        Args:
            shell: The :class:`ShellType` to check.

        Returns:
            :attr:`PermissionStatus.GRANTED` if at least one rc file is
            writable, :attr:`PermissionStatus.DENIED` otherwise.
        """
        candidates = MacPaths.shell_rc_candidates().get(shell, [])
        if not candidates:
            self._logger.debug("No rc candidates for shell %s", shell.value)
            return PermissionStatus.NOT_APPLICABLE

        home = MacPaths.user_home
        for rc_name in candidates:
            rc_path = home / rc_name
            status = self.check_write_permission(rc_path)
            if status == PermissionStatus.GRANTED:
                return PermissionStatus.GRANTED

        return PermissionStatus.DENIED

    # ------------------------------------------------------------------
    # Composite check
    # ------------------------------------------------------------------

    def check_all(self) -> HostFacts:
        """Run every permission check and populate the bound :class:`HostFacts`.

        Returns:
            The updated :class:`HostFacts` instance with all permission
            statuses recorded.
        """
        facts = self._facts

        # LaunchAgent write
        facts.launch_agent_write = self.check_launch_agent_write()
        self._logger.info("LaunchAgent write: %s", facts.launch_agent_write.value)

        # Subprocess execution
        facts.subprocess_execution = self.check_subprocess_execution()
        self._logger.info("Subprocess execution: %s", facts.subprocess_execution.value)

        # Network access
        can_connect, net_status = self.check_network_access()
        facts.network_access = net_status
        self._logger.info("Network access: %s (connected=%s)", net_status.value, can_connect)

        # Shell rc write
        facts.shell_rc_write = self.check_shell_rc_write(facts.shell_type)
        self._logger.info("Shell rc write: %s", facts.shell_rc_write.value)

        # Install directory write
        if facts.project_dir is not None:
            facts.write_permissions["project_dir"] = self.check_project_dir_write(facts.project_dir)
            self._logger.info(
                "Project dir write: %s",
                facts.write_permissions["project_dir"].value,
            )

        # Config directory write
        facts.write_permissions["user_config"] = self.check_write_permission(
            MacPaths.user_config_dir
        )
        self._logger.info(
            "User config dir write: %s",
            facts.write_permissions["user_config"].value,
        )

        # State directory write
        facts.write_permissions["user_state"] = self.check_write_permission(MacPaths.user_state_dir)

        # Log directory write
        facts.write_permissions["user_log"] = self.check_write_permission(MacPaths.user_log_dir)

        # Cache directory write
        facts.write_permissions["user_cache"] = self.check_write_permission(MacPaths.user_cache_dir)

        # User install prefix write
        facts.write_permissions["user_install"] = self.check_write_permission(
            MacPaths.user_install_prefix
        )

        self._logger.info("All permission checks complete.")
        return facts
