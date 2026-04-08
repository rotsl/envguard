# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""Static paths and directory management for macOS envguard installation."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from envguard.logging import get_logger
from envguard.models import ShellType

logger = get_logger(__name__)


class MacPaths:
    """Centralised static paths for envguard on macOS.

    Provides every well-known directory and file path that envguard
    may read from or write to, along with helpers for bootstrapping
    the directory tree.
    """

    # ------------------------------------------------------------------
    # User-level paths
    # ------------------------------------------------------------------
    user_home: ClassVar[Path] = Path.home()
    user_launch_agent_dir: ClassVar[Path] = user_home / "Library" / "LaunchAgents"
    user_cache_dir: ClassVar[Path] = user_home / "Library" / "Caches" / "envguard"
    user_log_dir: ClassVar[Path] = user_home / ".envguard" / "logs"
    user_config_dir: ClassVar[Path] = user_home / ".envguard"
    user_state_dir: ClassVar[Path] = user_home / ".envguard"

    # ------------------------------------------------------------------
    # Install prefixes
    # ------------------------------------------------------------------
    default_install_prefix: ClassVar[Path] = Path("/usr/local/envguard")
    user_install_prefix: ClassVar[Path] = user_home / ".local" / "envguard"

    # ------------------------------------------------------------------
    # Project-level names
    # ------------------------------------------------------------------
    project_state_dir_name: ClassVar[str] = ".envguard"
    backup_dir_name: ClassVar[str] = "backups"

    # ------------------------------------------------------------------
    # LaunchAgent identifiers
    # ------------------------------------------------------------------
    launch_agent_bundle_id: ClassVar[str] = "com.envguard.update"
    launch_agent_plist_name: ClassVar[str] = "com.envguard.update.plist"

    # ------------------------------------------------------------------
    # Shell rc-file candidates
    # ------------------------------------------------------------------

    @classmethod
    def shell_rc_candidates(cls) -> dict[ShellType, list[str]]:
        """Return a mapping of shell types to their candidate rc files.

        Returns:
            Dictionary mapping each :class:`ShellType` to a list of rc file
            basenames (not full paths) that envguard should probe.
        """
        return {
            ShellType.ZSH: [".zshrc", ".zprofile"],
            ShellType.BASH: [".bashrc", ".bash_profile", ".profile"],
            ShellType.FISH: [".config/fish/config.fish"],
            ShellType.TCSH: [".tcshrc", ".cshrc"],
            ShellType.UNKNOWN: [".profile"],
        }

    # ------------------------------------------------------------------
    # Directory helpers
    # ------------------------------------------------------------------

    @classmethod
    def ensure_dirs(cls) -> list[Path]:
        """Create all required envguard directories that do not yet exist.

        Returns:
            List of directories that were created (or already existed).
        """
        dirs_to_ensure: list[Path] = [
            cls.user_config_dir,
            cls.user_state_dir,
            cls.user_log_dir,
            cls.user_cache_dir,
            cls.user_launch_agent_dir,
            cls.user_install_prefix,
        ]

        created: list[Path] = []
        for directory in dirs_to_ensure:
            try:
                directory.mkdir(parents=True, exist_ok=True)
                created.append(directory)
                logger.debug("Ensured directory exists: %s", directory)
            except OSError as exc:
                logger.warning("Failed to create directory %s: %s", directory, exc)
                created.append(directory)  # still return it; caller can check

        return created

    @classmethod
    def get_log_file(cls, name: str = "envguard.log") -> Path:
        """Return the path to a log file inside the user log directory.

        Args:
            name: Basename of the log file.

        Returns:
            Full :class:`Path` to the requested log file.
        """
        log_dir = cls.user_log_dir
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir / name
