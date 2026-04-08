# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""System-level installation and management for envguard on macOS."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from envguard.logging import get_logger
from envguard.macos.paths import MacPaths

logger = get_logger(__name__)

# Name of the marker file placed inside an installation prefix
_MARKER_FILE = ".envguard_installed"


class SystemInstaller:
    """Manage the installation of envguard at a given prefix.

    The installer creates the directory layout, writes a marker file, and
    provides verification / uninstall helpers.

    Args:
        prefix: Override the installation prefix.  When ``None`` the prefix is
            chosen automatically based on *user_level*.
        user_level: If ``True`` the user-local prefix (``~/.local/envguard/``)
            is used; otherwise the system prefix (``/usr/local/envguard/``).
    """

    def __init__(
        self,
        prefix: Path | None = None,
        user_level: bool = True,
    ) -> None:
        self._user_level = user_level

        if prefix is not None:
            self._prefix = Path(prefix).resolve()
        elif user_level:
            self._prefix = MacPaths.user_install_prefix
        else:
            self._prefix = MacPaths.default_install_prefix

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def prefix(self) -> Path:
        """Return the effective installation prefix."""
        return self._prefix

    @property
    def user_level(self) -> bool:
        """Return whether this is a user-level installation."""
        return self._user_level

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_install_prefix(self) -> Path:
        """Return the installation prefix path.

        Returns:
            The :class:`Path` to the installation prefix directory.
        """
        return self._prefix

    def check_install_location(self) -> dict[str, object]:
        """Inspect the installation location and report its status.

        Returns:
            A dictionary with keys:

            - ``path`` (*str*): Absolute path to the prefix.
            - ``exists`` (*bool*): Whether the prefix directory exists.
            - ``writable`` (*bool*): Whether the current user can write there.
            - ``is_user_level`` (*bool*): Whether this is a user-level prefix.
            - ``requires_privilege`` (*bool*): Whether elevated privileges are needed.
            - ``is_empty`` (*bool*): Whether the directory is empty (or non-existent).
            - ``already_installed`` (*bool*): Whether envguard marker is present.
        """
        path = self._prefix
        exists = path.exists()
        writable = False
        is_empty = not exists

        if exists:
            writable = os.access(path, os.W_OK)
            try:
                is_empty = not any(path.iterdir())
            except OSError:
                is_empty = False
        else:
            # Check the parent for writability (to decide if we can mkdir).
            writable = os.access(path.parent, os.W_OK)

        already_installed = (path / _MARKER_FILE).exists() if exists else False
        requires_priv = self.requires_privilege(path)

        return {
            "path": str(path),
            "exists": exists,
            "writable": writable,
            "is_user_level": self._user_level,
            "requires_privilege": requires_priv,
            "is_empty": is_empty,
            "already_installed": already_installed,
        }

    def install_self(self) -> bool:
        """Install envguard to the configured prefix.

        Creates the prefix directory (and parents), writes sub-directories
        (``bin/``, ``lib/``, ``etc/``), and drops a marker file.

        Returns:
            ``True`` if the installation succeeded.
        """
        try:
            location = self.check_install_location()

            if location["already_installed"]:
                logger.info("envguard is already installed at %s", self._prefix)
                return True

            if location["requires_privilege"]:
                logger.warning(
                    "Installation at %s likely requires elevated privileges "
                    "(sudo). Attempting without sudo …",
                    self._prefix,
                )

            # Create the prefix directory
            self._prefix.mkdir(parents=True, exist_ok=True)

            # Create standard sub-directories
            sub_dirs = ["bin", "lib", "etc", "share", "logs"]
            for name in sub_dirs:
                (self._prefix / name).mkdir(parents=True, exist_ok=True)

            # Write the marker file with version information
            marker_path = self._prefix / _MARKER_FILE
            marker_content = (
                "# This file marks an envguard installation.\n"
                f"# prefix: {self._prefix}\n"
                f"# user_level: {self._user_level}\n"
            )
            marker_path.write_text(marker_content, encoding="utf-8")

            logger.info("envguard installed successfully at %s", self._prefix)
            return True

        except PermissionError as exc:
            logger.error("Permission denied installing to %s: %s", self._prefix, exc)
            return False
        except OSError as exc:
            logger.error("OS error installing to %s: %s", self._prefix, exc)
            return False

    def uninstall_self(self) -> bool:
        """Remove the envguard installation from the prefix.

        .. warning::
            This deletes the entire prefix directory tree.  Use with caution.

        Returns:
            ``True`` if the uninstallation succeeded (or nothing was
            installed).
        """
        try:
            if not self._prefix.exists():
                logger.info("Nothing to uninstall at %s", self._prefix)
                return True

            if not self.requires_privilege(self._prefix):
                shutil.rmtree(self._prefix)
                logger.info("Uninstalled envguard from %s", self._prefix)
                return True

            # If we need privilege but don't have it, try anyway and let
            # the exception surface.
            shutil.rmtree(self._prefix)
            logger.info("Uninstalled envguard from %s", self._prefix)
            return True

        except PermissionError as exc:
            logger.error("Permission denied uninstalling from %s: %s", self._prefix, exc)
            return False
        except OSError as exc:
            logger.error("OS error uninstalling from %s: %s", self._prefix, exc)
            return False

    def verify_installation(self) -> dict[str, object]:
        """Verify the integrity of the envguard installation at the prefix.

        Returns:
            A dictionary with keys:

            - ``installed`` (*bool*): Whether the marker file exists.
            - ``prefix_exists`` (*bool*): Whether the prefix directory exists.
            - ``marker_present`` (*bool*): Whether the marker file is present.
            - ``marker_valid`` (*bool*): Whether the marker content is readable.
            - ``subdirs_present`` (*list[str]*): Names of expected subdirectories
              that are present.
            - ``missing_subdirs`` (*list[str]*): Names of expected subdirectories
              that are missing.
            - ``writable`` (*bool*): Whether the prefix is writable.
        """
        expected_subdirs = ["bin", "lib", "etc", "share", "logs"]
        prefix_exists = self._prefix.exists()
        marker_path = self._prefix / _MARKER_FILE
        marker_present = marker_path.exists() if prefix_exists else False
        marker_valid = False

        if marker_present:
            try:
                content = marker_path.read_text(encoding="utf-8")
                marker_valid = "envguard" in content
            except OSError:
                marker_valid = False

        subdirs_present: list[str] = []
        missing_subdirs: list[str] = []
        for name in expected_subdirs:
            sub = self._prefix / name
            if sub.is_dir():
                subdirs_present.append(name)
            else:
                missing_subdirs.append(name)

        writable = os.access(self._prefix, os.W_OK) if prefix_exists else False

        installed = marker_present and marker_valid

        return {
            "installed": installed,
            "prefix_exists": prefix_exists,
            "marker_present": marker_present,
            "marker_valid": marker_valid,
            "subdirs_present": subdirs_present,
            "missing_subdirs": missing_subdirs,
            "writable": writable,
        }

    def requires_privilege(self, target: Path) -> bool:
        """Determine whether writing to *target* requires elevated privileges.

        Checks ownership of *target* (or its parent) against the effective
        user ID.

        Args:
            target: The file or directory to check.

        Returns:
            ``True`` if the effective user does not own the path and it is
            not world-writable.
        """
        try:
            check_path = target if target.exists() else target.parent
            if not check_path.exists():
                # Fall back: assume system paths need privilege
                return str(self._prefix).startswith("/usr") or str(self._prefix).startswith("/opt")

            stat_info = os.stat(check_path)
            euid = os.geteuid()

            # If current user owns the path, no privilege needed
            if stat_info.st_uid == euid:
                return False

            # Check if group or other has write permission
            mode = stat_info.st_mode
            if mode & 0o002:  # other-write
                return False
            if mode & 0o020 and stat_info.st_gid in os.getgroups():  # group-write
                return False
            return True

        except OSError as exc:
            logger.debug("Privilege check failed for %s: %s", target, exc)
            # Assume privilege needed on error for system paths
            return str(self._prefix).startswith("/usr") or str(self._prefix).startswith("/opt")

    def get_required_privileges(self) -> list[str]:
        """Return a human-readable list of privileges that may be required.

        Returns:
            A list of privilege descriptions.  Empty if no special
            privileges are required.
        """
        location = self.check_install_location()
        privileges: list[str] = []

        if location["requires_privilege"]:
            privileges.append(f"write access to installation prefix ({self._prefix})")

        # Check LaunchAgent directory
        launch_dir = MacPaths.user_launch_agent_dir
        if launch_dir.exists() and not os.access(launch_dir, os.W_OK):
            privileges.append(f"write access to {launch_dir} (for LaunchAgent plist)")

        # Check system-level path
        if not self._user_level:
            privileges.append("root/sudo to write to /usr/local/envguard")

        return privileges
