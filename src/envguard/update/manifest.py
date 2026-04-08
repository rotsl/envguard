# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""Update manifest parsing and validation."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

try:
    from envguard.logging import get_logger
except ImportError:
    import logging

    def get_logger(name: str) -> logging.Logger:  # type: ignore[misc]
        return logging.getLogger(name)


try:
    from envguard.models import UpdateManifest
except ImportError:

    class UpdateManifest:  # type: ignore[no-redef]
        """Fallback UpdateManifest when the models module is unavailable."""

        def __init__(self, **kwargs):
            self.version = kwargs.get("version", "0.0.0")
            self.download_url = kwargs.get("download_url", "")
            self.checksum = kwargs.get("checksum", "")
            self.checksum_algorithm = kwargs.get("checksum_algorithm", "sha256")
            self.signature = kwargs.get("signature", "")
            self.min_python_version = kwargs.get("min_python_version", "3.9")
            self.platforms = kwargs.get("platforms", [])
            self.changelog = kwargs.get("changelog", "")
            self.release_date = kwargs.get("release_date", "")
            self.prerelease = kwargs.get("prerelease", False)
            self.size_bytes = kwargs.get("size_bytes", 0)
            self.package_url = kwargs.get("package_url", "")

        def __repr__(self) -> str:
            return f"UpdateManifest(version={self.version!r})"

        def to_dict(self) -> dict:
            return {
                "version": self.version,
                "download_url": self.download_url,
                "checksum": self.checksum,
                "checksum_algorithm": self.checksum_algorithm,
                "signature": self.signature,
                "min_python_version": self.min_python_version,
                "platforms": self.platforms,
                "changelog": self.changelog,
                "release_date": self.release_date,
                "prerelease": self.prerelease,
                "size_bytes": self.size_bytes,
                "package_url": self.package_url,
            }


logger = get_logger(__name__)

# Simple semver pattern: MAJOR.MINOR.PATCH with optional pre-release suffix
_SEMVER_RE = re.compile(
    r"^\s*(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:[-+].+)?\s*$"
)


class ManifestParser:
    """Parse, validate, and compare update manifests.

    Manifests describe available envguard releases and contain metadata
    needed to download, verify, and install updates.
    """

    def parse(self, data: str | dict) -> UpdateManifest:
        """Parse an update manifest from a JSON string or dict.

        Args:
            data: A JSON string or a pre-parsed dict.

        Returns:
            An :class:`UpdateManifest` instance.

        Raises:
            ValueError: If the data cannot be parsed.
        """
        if isinstance(data, str):
            try:
                raw = json.loads(data)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON: {exc}") from exc
        elif isinstance(data, dict):
            raw = data
        else:
            raise ValueError(f"Expected str or dict, got {type(data).__name__}")

        return UpdateManifest(**raw)

    def parse_file(self, path: Path) -> UpdateManifest:
        """Read and parse a manifest file.

        Args:
            path: Path to a JSON manifest file.

        Returns:
            An :class:`UpdateManifest` instance.
        """
        if not path.is_file():
            raise FileNotFoundError(f"Manifest file not found: {path}")

        content = path.read_text(encoding="utf-8")
        return self.parse(content)

    def validate(self, manifest: UpdateManifest) -> list[str]:
        """Validate a manifest's required fields.

        Args:
            manifest: The manifest to validate.

        Returns:
            A list of issue strings.  An empty list indicates a valid manifest.
        """
        issues: list[str] = []

        # Version - required, must be semver-ish
        version = getattr(manifest, "version", "")
        if not version:
            issues.append("Missing required field: 'version'")
        elif not _SEMVER_RE.match(str(version)):
            issues.append(f"Invalid version format: '{version}' (expected semver)")

        # Download URL - required
        download_url = getattr(manifest, "download_url", "")
        if not download_url:
            issues.append("Missing required field: 'download_url'")
        elif not download_url.startswith(("http://", "https://")):
            issues.append(f"Invalid download_url: '{download_url}'")

        # Checksum - required
        checksum = getattr(manifest, "checksum", "")
        if not checksum:
            issues.append("Missing required field: 'checksum'")

        # Checksum algorithm - should be a known hash
        algo = getattr(manifest, "checksum_algorithm", "sha256")
        known_algos = {"sha256", "sha384", "sha512", "md5"}
        if algo.lower() not in known_algos:
            issues.append(f"Unknown checksum algorithm: '{algo}'")

        # Platforms - if present, should be a non-empty list
        platforms = getattr(manifest, "platforms", None)
        if platforms is not None:
            if not isinstance(platforms, list):
                issues.append("'platforms' should be a list")
            elif not platforms:
                issues.append("'platforms' is empty")

        # Min Python version - if present, should be a valid version
        min_py = getattr(manifest, "min_python_version", None)
        if min_py is not None:
            parts = str(min_py).split(".")
            if len(parts) < 2 or not all(p.isdigit() for p in parts if p):
                issues.append(f"Invalid min_python_version: '{min_py}'")

        # Size - if present, should be non-negative
        size = getattr(manifest, "size_bytes", None)
        if size is not None:
            try:
                if int(size) < 0:
                    issues.append("'size_bytes' should be non-negative")
            except (ValueError, TypeError):
                issues.append(f"'size_bytes' is not a valid number: '{size}'")

        # Release date - if present, should be parseable
        rel_date = getattr(manifest, "release_date", None)
        if rel_date is not None:
            try:
                datetime.fromisoformat(str(rel_date))
            except ValueError:
                issues.append(f"Invalid release_date format: '{rel_date}'")

        return issues

    def to_json(self, manifest: UpdateManifest) -> str:
        """Serialize an :class:`UpdateManifest` to a JSON string.

        Uses ``to_dict()`` if available, otherwise falls back to ``__dict__``.
        """
        data = manifest.to_dict() if hasattr(manifest, "to_dict") else vars(manifest)

        return json.dumps(data, indent=2, sort_keys=False)

    def compare_versions(self, current: str, latest: str) -> int:
        """Compare two semver version strings.

        Args:
            current: The currently installed version.
            latest: The version from the remote manifest.

        Returns:
            - ``-1`` if *current* < *latest* (update available)
            - ``0`` if they are equal
            - ``1`` if *current* > *latest*
        """
        cur_parts = _parse_version_parts(current)
        lat_parts = _parse_version_parts(latest)

        for c, lt in zip(cur_parts, lat_parts, strict=False):
            if c < lt:
                return -1
            if c > lt:
                return 1

        # Equal so far - the shorter version is considered older only if
        # the remaining parts of the longer version are non-zero
        if len(cur_parts) < len(lat_parts):
            if any(p > 0 for p in lat_parts[len(cur_parts) :]):
                return -1
        elif len(cur_parts) > len(lat_parts):
            if any(p > 0 for p in cur_parts[len(lat_parts) :]):
                return 1

        return 0

    def format_changelog(self, manifest: UpdateManifest) -> str:
        """Format the changelog from a manifest for display.

        Args:
            manifest: The manifest whose changelog to format.

        Returns:
            A formatted string suitable for terminal display.
        """
        version = getattr(manifest, "version", "unknown")
        changelog = getattr(manifest, "changelog", "")
        release_date = getattr(manifest, "release_date", "")
        prerelease = getattr(manifest, "prerelease", False)

        lines: list[str] = []
        lines.append(f"envguard v{version}")
        if prerelease:
            lines.append("⚠  Pre-release")
        if release_date:
            try:
                dt = datetime.fromisoformat(str(release_date))
                lines.append(f"Released: {dt.strftime('%Y-%m-%d')}")
            except ValueError:
                lines.append(f"Released: {release_date}")
        lines.append("")

        if changelog:
            lines.append(changelog.strip())
        else:
            lines.append("No changelog available.")

        return "\n".join(lines)

    @staticmethod
    def generate_sample_manifest() -> UpdateManifest:
        """Generate a sample manifest for testing or documentation.

        Returns:
            A fully populated :class:`UpdateManifest` with example data.
        """
        return UpdateManifest(
            version="0.2.0",
            download_url="https://releases.envguard.dev/envguard-0.2.0.tar.gz",
            checksum="a" * 64,  # placeholder sha256
            checksum_algorithm="sha256",
            signature="",
            min_python_version="3.9",
            platforms=["darwin", "linux"],
            changelog=(
                "## 0.2.0 (2026-07-01)\n\n"
                "### Added\n"
                "- Automatic preflight on directory change\n"
                "- Conda backend support\n"
                "- LaunchAgent scheduled updates\n\n"
                "### Fixed\n"
                "- Wheel compatibility checks for macOS 14\n"
            ),
            release_date="2026-07-01",
            prerelease=False,
            size_bytes=524288,
            package_url="https://pypi.org/project/envguard/0.2.0/",
        )


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def _parse_version_parts(version: str) -> list[int]:
    """Split a version string into a list of integer parts.

    Non-numeric suffixes (e.g. ``-rc1``, ``+local``) are stripped.
    """
    # Strip pre-release / build metadata
    version = version.split("-")[0].split("+")[0]

    parts: list[int] = []
    for segment in version.split("."):
        segment = segment.strip()
        if not segment:
            continue
        try:
            parts.append(int(segment))
        except ValueError:
            break
    return parts
