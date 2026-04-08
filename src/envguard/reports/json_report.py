# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""JSON report writer – serialize envguard data models to JSON files."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

try:
    from envguard.logging import get_logger
except ImportError:
    import logging

    def get_logger(name: str) -> logging.Logger:  # type: ignore[misc]
        return logging.getLogger(name)

logger = get_logger(__name__)


def _serialize(value: Any) -> Any:
    """Recursively convert values to JSON-safe types.

    Handles dataclasses, ``Path`` objects, enums, and ``datetime``
    instances so that ``json.dumps`` can serialize the result.
    """
    if is_dataclass(value) and not isinstance(value, type):
        return _serialize(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _serialize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize(v) for v in value]
    return value


def _to_dict(obj: Any) -> dict[str, Any]:
    """Convert an arbitrary object to a plain ``dict`` for JSON output.

    If *obj* is a dataclass it is serialized via ``dataclasses.asdict``
    (with recursive value conversion).  If it is already a dict it is
    returned with values converted.  Otherwise ``vars(obj)`` is used.
    """
    if is_dataclass(obj) and not isinstance(obj, type):
        return _serialize(asdict(obj))
    if isinstance(obj, dict):
        return _serialize(obj)
    try:
        return _serialize(vars(obj))
    except TypeError:
        # Fallback: try attribute-based extraction
        out: dict[str, Any] = {}
        for attr in dir(obj):
            if attr.startswith("_"):
                continue
            try:
                out[attr] = getattr(obj, attr)
            except Exception:
                pass
        return _serialize(out)


# Import Enum at module level after the helper functions
from enum import Enum  # noqa: E402


class JSONReportWriter:
    """Serialize envguard data models to JSON and optionally write to disk.

    Each ``write_*`` method accepts the corresponding model object and an
    optional *path*.  When *path* is provided the JSON is written to that
    file (creating parent directories as needed).  The serialized ``dict``
    is always returned, making the methods usable both for file output and
    for programmatic consumption.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def write_host_report(
        self,
        facts: Any,
        path: Optional[Path] = None,
    ) -> dict[str, Any]:
        """Serialize :class:`~envguard.models.HostFacts` to JSON.

        Parameters
        ----------
        facts:
            A ``HostFacts`` dataclass (or compatible object).
        path:
            Optional file path to write the JSON to.

        Returns
        -------
        dict[str, Any]
            Plain dictionary representation of the host facts.
        """
        data = _to_dict(facts)
        data.setdefault("_report_type", "host_report")
        if path is not None:
            self._write_json(data, path)
        return data

    def write_project_report(
        self,
        intent: Any,
        path: Optional[Path] = None,
    ) -> dict[str, Any]:
        """Serialize :class:`~envguard.models.ProjectIntent` to JSON.

        Parameters
        ----------
        intent:
            A ``ProjectIntent`` dataclass (or compatible object).
        path:
            Optional file path to write the JSON to.

        Returns
        -------
        dict[str, Any]
            Plain dictionary representation of the project intent.
        """
        data = _to_dict(intent)
        data.setdefault("_report_type", "project_report")
        if path is not None:
            self._write_json(data, path)
        return data

    def write_preflight_report(
        self,
        result: Any,
        path: Optional[Path] = None,
    ) -> dict[str, Any]:
        """Serialize :class:`~envguard.models.PreflightResult` to JSON.

        Parameters
        ----------
        result:
            A ``PreflightResult`` dataclass (or compatible object).
        path:
            Optional file path to write the JSON to.

        Returns
        -------
        dict[str, Any]
            Plain dictionary representation of the preflight result.
        """
        data = _to_dict(result)
        data.setdefault("_report_type", "preflight_report")
        if path is not None:
            self._write_json(data, path)
        return data

    def write_health_report(
        self,
        report: Any,
        path: Optional[Path] = None,
    ) -> dict[str, Any]:
        """Serialize :class:`~envguard.models.HealthReport` to JSON.

        Parameters
        ----------
        report:
            A ``HealthReport`` dataclass (or compatible object).
        path:
            Optional file path to write the JSON to.

        Returns
        -------
        dict[str, Any]
            Plain dictionary representation of the health report.
        """
        data = _to_dict(report)
        data.setdefault("_report_type", "health_report")
        if path is not None:
            self._write_json(data, path)
        return data

    def write_repair_report(
        self,
        resolution: Any,
        path: Optional[Path] = None,
    ) -> dict[str, Any]:
        """Serialize :class:`~envguard.models.ResolutionRecord` (repair) to JSON.

        Parameters
        ----------
        resolution:
            A ``ResolutionRecord`` dataclass (or compatible object).
        path:
            Optional file path to write the JSON to.

        Returns
        -------
        dict[str, Any]
            Plain dictionary representation of the repair resolution.
        """
        data = _to_dict(resolution)
        data.setdefault("_report_type", "repair_report")
        if path is not None:
            self._write_json(data, path)
        return data

    def write_update_report(
        self,
        check: Any,
        path: Optional[Path] = None,
    ) -> dict[str, Any]:
        """Serialize an update check result to JSON.

        Parameters
        ----------
        check:
            An ``UpdateCheckResult`` object (or any object with a ``vars``
            representation).
        path:
            Optional file path to write the JSON to.

        Returns
        -------
        dict[str, Any]
            Plain dictionary representation of the update check.
        """
        data = _to_dict(check)
        data.setdefault("_report_type", "update_report")
        if path is not None:
            self._write_json(data, path)
        return data

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _write_json(data: dict[str, Any], path: Path) -> None:
        """Atomically write *data* as JSON to *path*."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        try:
            tmp.write_text(
                json.dumps(data, indent=2, default=str) + "\n",
                encoding="utf-8",
            )
            tmp.replace(path)
            logger.debug("Wrote report to %s", path)
        except OSError as exc:
            logger.error("Failed to write report to %s: %s", path, exc)
            if tmp.exists():
                tmp.unlink(missing_ok=True)
            raise
