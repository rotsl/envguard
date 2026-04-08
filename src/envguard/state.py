# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""State manager - persistent project and global state for envguard."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from envguard.logging import get_logger
except ImportError:
    import logging

    def get_logger(name: str) -> logging.Logger:  # type: ignore[misc]
        return logging.getLogger(name)


logger = get_logger(__name__)


class StateManager:
    """Manage persistent JSON state files for envguard projects and globals.

    Class-level constants
    ---------------------
    ENVGUARD_STATE_DIR:
        Per-user global state directory (``~/.envguard``).
    PROJECT_DIR_NAME:
        Directory name used inside each project (``.envguard``).
    """

    ENVGUARD_STATE_DIR: Path = Path.home() / ".envguard"
    PROJECT_DIR_NAME: str = ".envguard"

    # ------------------------------------------------------------------
    # Project state
    # ------------------------------------------------------------------

    @classmethod
    def load_state(cls, project_dir: Path) -> dict[str, Any]:
        """Load the project ``state.json`` file.

        Parameters
        ----------
        project_dir:
            Root directory of the project.

        Returns
        -------
        dict[str, Any]
            The state dictionary, or an empty dict if the file is missing
            or corrupt.
        """
        path = cls.ensure_project_dir(project_dir) / "state.json"
        return cls._read_json(path)

    @classmethod
    def save_state(cls, project_dir: Path, data: dict[str, Any]) -> Path:
        """Save data to the project ``state.json`` file.

        Parameters
        ----------
        project_dir:
            Root directory of the project.
        data:
            Dictionary to persist.

        Returns
        -------
        Path
            Path to the written file.
        """
        path = cls.ensure_project_dir(project_dir) / "state.json"
        cls._write_json(path, data)
        return path

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    @classmethod
    def load_resolution(cls, project_dir: Path) -> dict[str, Any] | None:
        """Load the project ``resolution.json`` file.

        Parameters
        ----------
        project_dir:
            Root directory of the project.

        Returns
        -------
        Optional[dict[str, Any]]
            The resolution dictionary, or ``None`` if not found.
        """
        path = cls.ensure_project_dir(project_dir) / "resolution.json"
        data = cls._read_json(path)
        return data if data else None

    @classmethod
    def save_resolution(cls, project_dir: Path, resolution: Any) -> Path:
        """Save a resolution to the project ``resolution.json`` file.

        Parameters
        ----------
        project_dir:
            Root directory of the project.
        resolution:
            A ``ResolutionRecord`` dataclass, dict, or any object
            serializable via ``vars()``.

        Returns
        -------
        Path
            Path to the written file.
        """
        data = cls._to_dict(resolution)
        path = cls.ensure_project_dir(project_dir) / "resolution.json"
        cls._write_json(path, data)
        return path

    # ------------------------------------------------------------------
    # Intent
    # ------------------------------------------------------------------

    @classmethod
    def load_intent(cls, project_dir: Path) -> dict[str, Any] | None:
        """Load the project ``intent.json`` file.

        Parameters
        ----------
        project_dir:
            Root directory of the project.

        Returns
        -------
        Optional[dict[str, Any]]
            The intent dictionary, or ``None`` if not found.
        """
        path = cls.ensure_project_dir(project_dir) / "intent.json"
        data = cls._read_json(path)
        return data if data else None

    @classmethod
    def save_intent(cls, project_dir: Path, intent: Any) -> Path:
        """Save an intent to the project ``intent.json`` file.

        Parameters
        ----------
        project_dir:
            Root directory of the project.
        intent:
            A ``ProjectIntent`` dataclass, dict, or any object
            serializable via ``vars()``.

        Returns
        -------
        Path
            Path to the written file.
        """
        data = cls._to_dict(intent)
        path = cls.ensure_project_dir(project_dir) / "intent.json"
        cls._write_json(path, data)
        return path

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    @classmethod
    def load_health(cls, project_dir: Path) -> dict[str, Any] | None:
        """Load the project ``health.json`` file.

        Parameters
        ----------
        project_dir:
            Root directory of the project.

        Returns
        -------
        Optional[dict[str, Any]]
            The health dictionary, or ``None`` if not found.
        """
        path = cls.ensure_project_dir(project_dir) / "health.json"
        data = cls._read_json(path)
        return data if data else None

    @classmethod
    def save_health(cls, project_dir: Path, health: Any) -> Path:
        """Save a health report to the project ``health.json`` file.

        Parameters
        ----------
        project_dir:
            Root directory of the project.
        health:
            A ``HealthReport`` dataclass, dict, or any object serializable
            via ``vars()``.

        Returns
        -------
        Path
            Path to the written file.
        """
        data = cls._to_dict(health)
        path = cls.ensure_project_dir(project_dir) / "health.json"
        cls._write_json(path, data)
        return path

    # ------------------------------------------------------------------
    # Launch policy
    # ------------------------------------------------------------------

    @classmethod
    def load_launch_policy(cls, project_dir: Path) -> dict[str, Any]:
        """Load the project ``launch_policy.json`` file.

        Parameters
        ----------
        project_dir:
            Root directory of the project.

        Returns
        -------
        dict[str, Any]
            The launch policy dictionary, or an empty dict if not found.
        """
        path = cls.ensure_project_dir(project_dir) / "launch_policy.json"
        return cls._read_json(path)

    @classmethod
    def save_launch_policy(cls, project_dir: Path, policy: dict[str, Any]) -> Path:
        """Save a launch policy to the project ``launch_policy.json`` file.

        Parameters
        ----------
        project_dir:
            Root directory of the project.
        policy:
            Dictionary describing the launch policy.

        Returns
        -------
        Path
            Path to the written file.
        """
        path = cls.ensure_project_dir(project_dir) / "launch_policy.json"
        cls._write_json(path, policy)
        return path

    # ------------------------------------------------------------------
    # Directory management
    # ------------------------------------------------------------------

    @classmethod
    def ensure_project_dir(cls, project_dir: Path) -> Path:
        """Ensure the ``.envguard`` directory exists for *project_dir*.

        Parameters
        ----------
        project_dir:
            Root directory of the project.

        Returns
        -------
        Path
            Path to the ``.envguard`` directory.
        """
        eg_dir = Path(project_dir) / cls.PROJECT_DIR_NAME
        eg_dir.mkdir(parents=True, exist_ok=True)
        return eg_dir

    # ------------------------------------------------------------------
    # Backups
    # ------------------------------------------------------------------

    @classmethod
    def backup_state(cls, project_dir: Path) -> Path:
        """Create a timestamped backup of the project ``.envguard`` state.

        Copies the ``state.json``, ``resolution.json``, and ``intent.json``
        files (if they exist) into a timestamped subdirectory of
        ``.envguard/backups/``.

        Parameters
        ----------
        project_dir:
            Root directory of the project.

        Returns
        -------
        Path
            Path to the backup directory.
        """
        eg_dir = cls.ensure_project_dir(project_dir)
        backups_dir = eg_dir / "backups"
        backups_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_dir = backups_dir / timestamp
        backup_dir.mkdir(parents=True, exist_ok=True)

        files_to_backup = [
            "state.json",
            "resolution.json",
            "intent.json",
            "health.json",
            "launch_policy.json",
        ]

        for filename in files_to_backup:
            src = eg_dir / filename
            if src.exists():
                shutil.copy2(src, backup_dir / filename)
                logger.debug("Backed up %s to %s", filename, backup_dir)

        logger.info("State backup created at %s", backup_dir)
        return backup_dir

    @classmethod
    def list_backups(cls, project_dir: Path) -> list[Path]:
        """List all backup directories for a project.

        Parameters
        ----------
        project_dir:
            Root directory of the project.

        Returns
        -------
        list[Path]
            Sorted list of backup directory paths (newest last).
        """
        backups_dir = Path(project_dir) / cls.PROJECT_DIR_NAME / "backups"
        if not backups_dir.is_dir():
            return []

        backups = sorted(
            [p for p in backups_dir.iterdir() if p.is_dir()],
            key=lambda p: p.name,
        )
        return backups

    # ------------------------------------------------------------------
    # Global configuration
    # ------------------------------------------------------------------

    @classmethod
    def get_global_config(cls) -> dict[str, Any]:
        """Load the global envguard configuration.

        Reads from ``~/.envguard/config.json``.  Returns an empty dict if
        the file does not exist.

        Returns
        -------
        dict[str, Any]
            The global configuration dictionary.
        """
        cls.ENVGUARD_STATE_DIR.mkdir(parents=True, exist_ok=True)
        path = cls.ENVGUARD_STATE_DIR / "config.json"
        return cls._read_json(path)

    @classmethod
    def save_global_config(cls, config: dict[str, Any]) -> Path:
        """Save the global envguard configuration.

        Parameters
        ----------
        config:
            Dictionary to persist to ``~/.envguard/config.json``.

        Returns
        -------
        Path
            Path to the written file.
        """
        cls.ENVGUARD_STATE_DIR.mkdir(parents=True, exist_ok=True)
        path = cls.ENVGUARD_STATE_DIR / "config.json"
        cls._write_json(path, config)
        return path

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        """Read a JSON file, returning an empty dict on any failure."""
        path = Path(path)
        if not path.exists():
            return {}
        try:
            text = path.read_text(encoding="utf-8")
            data = json.loads(text)
            if isinstance(data, dict):
                return data
            logger.warning("Expected dict in %s, got %s", path, type(data).__name__)
            return {}
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to read %s: %s", path, exc)
            return {}

    @staticmethod
    def _write_json(path: Path, data: dict[str, Any]) -> None:
        """Atomically write a JSON file with ``indent=2``."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        try:
            tmp.write_text(
                json.dumps(data, indent=2, default=str) + "\n",
                encoding="utf-8",
            )
            tmp.replace(path)
            logger.debug("Wrote state to %s", path)
        except OSError as exc:
            logger.error("Failed to write %s: %s", path, exc)
            if tmp.exists():
                tmp.unlink(missing_ok=True)
            raise

    @staticmethod
    def _to_dict(obj: Any) -> dict[str, Any]:
        """Convert an object to a plain dict for JSON serialization.

        Handles dataclasses (via ``dataclasses.asdict``), dicts, and
        generic objects (via ``vars()``).
        """
        from dataclasses import asdict, is_dataclass

        if is_dataclass(obj) and not isinstance(obj, type):
            return asdict(obj)
        if isinstance(obj, dict):
            return obj
        try:
            return vars(obj)  # type: ignore[no-any-return]
        except TypeError:
            # Fallback: attribute-based extraction
            out: dict[str, Any] = {}
            for attr in dir(obj):
                if attr.startswith("_"):
                    continue
                try:
                    val = getattr(obj, attr)
                    if not callable(val):
                        out[attr] = val
                except Exception:
                    pass
            return out
