# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""Rollback manager - snapshot and restore envguard installations."""

from __future__ import annotations

import contextlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

try:
    from envguard.logging import get_logger
except ImportError:
    import logging

    def get_logger(name: str) -> logging.Logger:  # type: ignore[misc]
        return logging.getLogger(name)


logger = get_logger(__name__)


class RollbackManager:
    """Create and restore installation snapshots for safe updates.

    Snapshots are stored under ``~/.envguard/rollback/`` with metadata
    tracking the version, timestamp, and description of each snapshot.
    """

    STATE_DIR_NAME = ".envguard/rollback"

    def __init__(self, state_dir: Path | None = None) -> None:
        if state_dir is not None:
            self._state_dir = state_dir.resolve()
        else:
            self._state_dir = Path.home() / self.STATE_DIR_NAME

        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._snapshots_dir = self._state_dir / "snapshots"
        self._snapshots_dir.mkdir(parents=True, exist_ok=True)

        # Metadata index
        self._index_path = self._state_dir / "index.json"
        self._index = self._load_index()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_snapshot(self, description: str = "") -> str:
        """Create a new installation snapshot.

        Backs up the current envguard package directory and records
        metadata about the snapshot.

        Args:
            description: Optional human-readable description for the snapshot.

        Returns:
            The snapshot ID (a UUID string).
        """
        snapshot_id = uuid4().hex[:12]

        logger.info("Creating snapshot %s: %s", snapshot_id, description or "(no description)")

        # Determine the current installation directory
        install_dir = self._get_install_dir()
        if install_dir is None:
            logger.error("Cannot determine installation directory for snapshot")
            # Still record the snapshot with a note
            self._index[snapshot_id] = {
                "id": snapshot_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "description": description,
                "version": self._get_current_version(),
                "success": False,
                "error": "Cannot determine installation directory",
            }
            self._save_index()
            return snapshot_id

        # Create the snapshot directory
        snap_path = self._snapshot_path(snapshot_id)
        snap_path.mkdir(parents=True, exist_ok=True)

        # Backup the installation
        backup_ok = self._backup_current_install(snapshot_id)

        # Record metadata
        self._index[snapshot_id] = {
            "id": snapshot_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "description": description
            or f"Snapshot before update (v{self._get_current_version()})",
            "version": self._get_current_version(),
            "install_dir": str(install_dir),
            "success": backup_ok,
            "error": None if backup_ok else "Backup failed",
        }

        self._save_index()

        if backup_ok:
            logger.info("Snapshot %s created successfully", snapshot_id)
        else:
            logger.error("Snapshot %s creation failed", snapshot_id)

        return snapshot_id

    def rollback(self, snapshot_id: str | None = None) -> dict:
        """Roll back to a previous snapshot.

        Args:
            snapshot_id: The snapshot to restore.  If ``None``, the most
                recent successful snapshot is used.

        Returns:
            Dict with ``success``, ``snapshot_id``, and optional ``error`` keys.
        """
        if snapshot_id is None:
            # Use the most recent successful snapshot
            snapshot_id = self.get_current_snapshot_id()
            if snapshot_id is None:
                # Fall back to the latest in the index
                snapshot_id = self._get_latest_snapshot_id()
                if snapshot_id is None:
                    return {
                        "success": False,
                        "snapshot_id": None,
                        "error": "No snapshots available for rollback",
                    }

        # Validate the snapshot
        if not self._validate_snapshot(snapshot_id):
            return {
                "success": False,
                "snapshot_id": snapshot_id,
                "error": f"Snapshot {snapshot_id} is not valid",
            }

        logger.info("Rolling back to snapshot %s", snapshot_id)

        # Restore from snapshot
        restored = self._restore_from_snapshot(snapshot_id)

        if restored:
            # Create a snapshot of the "failed" state for recovery
            self.create_snapshot(description=f"Auto-snapshot after rollback from {snapshot_id}")
            logger.info("Rollback to snapshot %s completed", snapshot_id)
        else:
            logger.error("Rollback to snapshot %s failed", snapshot_id)

        return {
            "success": restored,
            "snapshot_id": snapshot_id,
            "error": None if restored else "Rollback restore failed",
        }

    def list_snapshots(self) -> list[dict]:
        """Return a list of all available snapshots.

        Each snapshot dict contains: ``id``, ``timestamp``, ``description``,
        ``version``, ``success``.
        """
        snapshots: list[dict] = []

        for snap_id, meta in self._index.items():
            snapshots.append(
                {
                    "id": meta.get("id", snap_id),
                    "timestamp": meta.get("timestamp", ""),
                    "description": meta.get("description", ""),
                    "version": meta.get("version", "unknown"),
                    "success": meta.get("success", False),
                }
            )

        # Sort newest first
        snapshots.sort(key=lambda s: s["timestamp"], reverse=True)
        return snapshots

    def delete_snapshot(self, snapshot_id: str) -> bool:
        """Delete a snapshot.

        Args:
            snapshot_id: The snapshot to delete.

        Returns:
            ``True`` if the snapshot was deleted.
        """
        snap_path = self._snapshot_path(snapshot_id)

        # Remove from disk
        if snap_path.exists():
            try:
                shutil.rmtree(snap_path)
                logger.info("Deleted snapshot directory: %s", snap_path)
            except OSError as exc:
                logger.error("Failed to delete snapshot %s: %s", snapshot_id, exc)
                return False

        # Remove from index
        self._index.pop(snapshot_id, None)
        self._save_index()

        return True

    def get_current_snapshot_id(self) -> str | None:
        """Return the snapshot ID of the most recent *successful* snapshot.

        Returns:
            A snapshot ID string, or ``None`` if no successful snapshots
            exist.
        """
        best_id: str | None = None
        best_time = ""

        for snap_id, meta in self._index.items():
            if not meta.get("success", False):
                continue
            ts = meta.get("timestamp", "")
            if ts > best_time:
                best_time = ts
                best_id = snap_id

        return best_id

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _snapshot_path(self, snapshot_id: str) -> Path:
        """Return the filesystem path for a snapshot's data directory."""
        return self._snapshots_dir / snapshot_id

    def _backup_current_install(self, snapshot_id: str) -> bool:
        """Copy the current envguard installation to a snapshot directory.

        Args:
            snapshot_id: The snapshot to store the backup under.

        Returns:
            ``True`` if the backup was created successfully.
        """
        install_dir = self._get_install_dir()
        if install_dir is None:
            return False

        snap_path = self._snapshot_path(snapshot_id)
        backup_dir = snap_path / "install"

        try:
            if backup_dir.exists():
                shutil.rmtree(backup_dir)
            shutil.copytree(install_dir, backup_dir)
            logger.debug("Backed up %s to %s", install_dir, backup_dir)
            return True
        except OSError as exc:
            logger.error("Backup failed: %s", exc)
            return False

    def _restore_from_snapshot(self, snapshot_id: str) -> bool:
        """Copy a snapshot back to the installation directory.

        Args:
            snapshot_id: The snapshot to restore.

        Returns:
            ``True`` if the restore was successful.
        """
        snap_path = self._snapshot_path(snapshot_id)
        backup_dir = snap_path / "install"

        if not backup_dir.exists():
            logger.error("Snapshot backup directory not found: %s", backup_dir)
            return False

        install_dir = self._get_install_dir()
        if install_dir is None:
            logger.error("Cannot determine installation directory for restore")
            return False

        try:
            # Remove current installation
            if install_dir.exists():
                shutil.rmtree(install_dir)
                install_dir.mkdir(parents=True, exist_ok=True)

            # Copy snapshot contents
            for item in backup_dir.iterdir():
                dest = install_dir / item.name
                if item.is_dir():
                    shutil.copytree(item, dest)
                else:
                    shutil.copy2(item, dest)

            logger.info("Restored installation from snapshot %s", snapshot_id)
            return True

        except OSError as exc:
            logger.error("Restore failed: %s", exc)
            # Try to recover: re-create the install directory
            with contextlib.suppress(OSError):
                install_dir.mkdir(parents=True, exist_ok=True)
            return False

    def _validate_snapshot(self, snapshot_id: str) -> bool:
        """Check whether a snapshot is valid and restorable.

        A valid snapshot has:
        - An entry in the index with ``success=True``
        - A backup directory on disk with at least one file
        """
        meta = self._index.get(snapshot_id)
        if meta is None:
            logger.error("Snapshot %s not found in index", snapshot_id)
            return False

        if not meta.get("success", False):
            logger.error("Snapshot %s was not successfully created", snapshot_id)
            return False

        backup_dir = self._snapshot_path(snapshot_id) / "install"
        if not backup_dir.exists():
            logger.error("Snapshot %s backup directory missing: %s", snapshot_id, backup_dir)
            return False

        # Check that the backup contains files
        has_files = any(backup_dir.iterdir())
        if not has_files:
            logger.error("Snapshot %s backup directory is empty", snapshot_id)
            return False

        return True

    def _load_index(self) -> dict:
        """Load the snapshot index from disk."""
        if not self._index_path.is_file():
            return {}

        try:
            data = json.loads(self._index_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not load snapshot index: %s", exc)

        return {}

    def _save_index(self) -> None:
        """Persist the snapshot index to disk."""
        try:
            self._index_path.write_text(
                json.dumps(self._index, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.error("Could not save snapshot index: %s", exc)

    @staticmethod
    def _get_install_dir() -> Path | None:
        """Determine the filesystem path of the envguard package installation."""
        try:
            from importlib.util import find_spec

            spec = find_spec("envguard")
            if spec is not None and spec.origin is not None:
                return Path(spec.origin).resolve().parent
        except (ImportError, ValueError, AttributeError):
            pass
        return None

    @staticmethod
    def _get_current_version() -> str:
        """Return the current envguard version string."""
        try:
            from importlib.metadata import version

            return version("envguard")
        except Exception:
            pass
        try:
            from envguard import __version__

            return __version__
        except (ImportError, AttributeError):
            pass
        return "unknown"

    def _get_latest_snapshot_id(self) -> str | None:
        """Return the ID of the most recent snapshot (regardless of success)."""
        if not self._index:
            return None
        latest_id = None
        latest_time = ""
        for snap_id, meta in self._index.items():
            ts = meta.get("timestamp", "")
            if ts > latest_time:
                latest_time = ts
                latest_id = snap_id
        return latest_id
