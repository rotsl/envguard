# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""Update manager - check for, download, and apply envguard updates."""

from __future__ import annotations

import shutil
import urllib.request
import zipfile
from pathlib import Path

try:
    from envguard.logging import get_logger
except ImportError:
    import logging

    def get_logger(name: str) -> logging.Logger:  # type: ignore[misc]
        return logging.getLogger(name)


try:
    from envguard.models import UpdateCheckResult, UpdateManifest
except ImportError:

    class UpdateManifest:  # type: ignore[no-redef]
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class UpdateCheckResult:  # type: ignore[no-redef]
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)


try:
    from envguard.update.manifest import ManifestParser
    from envguard.update.rollback import RollbackManager
    from envguard.update.verifier import UpdateVerifier
except ImportError:
    ManifestParser = None  # type: ignore[assignment,misc]
    UpdateVerifier = None  # type: ignore[assignment,misc]
    RollbackManager = None  # type: ignore[assignment,misc]

logger = get_logger(__name__)

# URL for the release manifest
DEFAULT_MANIFEST_URL = "https://releases.envguard.dev/manifest.json"

# Current version - read from package metadata or fallback
_PACKAGE_VERSION = "0.1.0"


class UpdateManager:
    """Manage envguard self-updates.

    Checks a remote manifest for new versions, downloads the update,
    verifies integrity, and applies the update with rollback support.
    """

    DEFAULT_MANIFEST_URL = DEFAULT_MANIFEST_URL

    def __init__(self, config: dict | None = None) -> None:
        self._config = config or {}
        self._manifest_url = self._config.get("manifest_url", self.DEFAULT_MANIFEST_URL)
        self._cache_dir = Path.home() / ".envguard" / "cache" / "updates"
        self._cache_dir.mkdir(parents=True, exist_ok=True)

        # Lazy-loaded helpers
        self._manifest_parser: ManifestParser | None = None
        self._verifier: UpdateVerifier | None = None
        self._rollback: RollbackManager | None = None

    @property
    def manifest_parser(self) -> ManifestParser:
        if self._manifest_parser is None:
            self._manifest_parser = ManifestParser()
        return self._manifest_parser

    @property
    def verifier(self) -> UpdateVerifier:
        if self._verifier is None:
            self._verifier = UpdateVerifier()
        return self._verifier

    @property
    def rollback_manager(self) -> RollbackManager:
        if self._rollback is None:
            self._rollback = RollbackManager()
        return self._rollback

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @staticmethod
    def current_version() -> str:
        """Return the currently installed envguard version.

        Attempts to read from package metadata; falls back to the
        hardcoded ``_PACKAGE_VERSION``.
        """
        try:
            from importlib.metadata import version

            return version("envguard")
        except Exception:
            pass

        # Try reading __version__ from the package
        try:
            from envguard import __version__

            return __version__
        except (ImportError, AttributeError):
            pass

        return _PACKAGE_VERSION

    def check_for_updates(self) -> UpdateCheckResult:
        """Check the remote manifest for available updates.

        Returns:
            An :class:`UpdateCheckResult` with ``update_available``,
            ``current_version``, ``latest_version``, ``manifest``, and
            ``error`` fields.
        """
        current = self.current_version()

        try:
            manifest = self._fetch_manifest()
        except Exception as exc:
            return UpdateCheckResult(
                update_available=False,
                current_version=current,
                latest_version=current,
                manifest=None,
                error=f"Failed to fetch manifest: {exc}",
            )

        latest = getattr(manifest, "version", "0.0.0")

        comparison = self.manifest_parser.compare_versions(current, latest)
        update_available = comparison < 0

        return UpdateCheckResult(
            update_available=update_available,
            current_version=current,
            latest_version=latest,
            manifest=manifest,
            error=None,
        )

    def perform_update(self) -> dict:
        """Download, verify, stage, and apply an update.

        Returns:
            Dict with ``success``, ``version``, and optional ``error`` keys.
        """
        # Check for updates first
        check = self.check_for_updates()
        if check.error:
            return {"success": False, "version": None, "error": check.error}

        if not check.update_available:
            return {
                "success": True,
                "version": check.current_version,
                "error": "Already up to date",
            }

        if check.manifest is None:
            return {
                "success": False,
                "version": None,
                "error": "No manifest available",
            }

        manifest = check.manifest

        # Create a rollback snapshot before updating
        try:
            snapshot_id = self.rollback_manager.create_snapshot(
                description=f"Before update to v{manifest.version}"
            )
            logger.info("Created rollback snapshot: %s", snapshot_id)
        except Exception as exc:
            logger.warning("Could not create rollback snapshot: %s", exc)
            snapshot_id = None

        try:
            # Download
            download_path = self._download_update(manifest)

            # Verify
            if not self._verify_update(download_path, manifest):
                return {
                    "success": False,
                    "version": manifest.version,
                    "error": "Update verification failed",
                }

            # Stage
            staged_path = self._stage_update(download_path)

            # Apply
            applied = self._apply_update(staged_path)
            if not applied:
                return {
                    "success": False,
                    "version": manifest.version,
                    "error": "Failed to apply update",
                }

            return {
                "success": True,
                "version": manifest.version,
                "error": None,
                "snapshot_id": snapshot_id,
            }

        except Exception as exc:
            logger.error("Update failed: %s", exc)
            return {
                "success": False,
                "version": manifest.version,
                "error": str(exc),
                "snapshot_id": snapshot_id,
            }

    def is_update_available(self) -> bool:
        """Quick check: is an update available?

        Returns:
            ``True`` if a newer version exists in the remote manifest.
        """
        try:
            check = self.check_for_updates()
            return check.update_available
        except Exception:
            return False

    def get_update_policy(self) -> str:
        """Return the current update policy.

        Policies: ``"stable"``, ``"beta"``, or ``"off"``.
        """
        return self._config.get("update_policy", "stable")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_manifest(self) -> UpdateManifest:
        """Download and parse the remote update manifest."""
        logger.debug("Fetching manifest from %s", self._manifest_url)

        req = urllib.request.Request(
            self._manifest_url,
            headers={
                "User-Agent": f"envguard/{self.current_version()}",
                "Accept": "application/json",
            },
        )

        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read().decode("utf-8")

        return self.manifest_parser.parse(data)

    def _download_update(self, manifest: UpdateManifest) -> Path:
        """Download the update archive from the manifest's download URL."""
        download_url = getattr(manifest, "download_url", "")
        if not download_url:
            raise ValueError("Manifest does not contain a download_url")

        filename = download_url.rsplit("/", 1)[-1] or "envguard-update.zip"
        dest = self._cache_dir / filename

        logger.info("Downloading update from %s", download_url)

        req = urllib.request.Request(
            download_url,
            headers={"User-Agent": f"envguard/{self.current_version}"},
        )

        with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as fh:
            shutil.copyfileobj(resp, fh)

        logger.info("Downloaded update to %s", dest)
        return dest

    def _stage_update(self, download_path: Path) -> Path:
        """Extract the update archive to a staging directory.

        Returns the path to the staging directory.
        """
        staging_dir = self._cache_dir / "staging"
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
        staging_dir.mkdir(parents=True, exist_ok=True)

        if str(download_path).endswith(".zip"):
            with zipfile.ZipFile(download_path, "r") as zf:
                # Guard against zip-slip: reject members with absolute or
                # parent-traversal paths before extracting anything.
                for member in zf.namelist():
                    member_path = (staging_dir / member).resolve()
                    if not str(member_path).startswith(str(staging_dir.resolve())):
                        raise ValueError(f"Unsafe archive member rejected (zip-slip): {member}")
                zf.extractall(staging_dir)
        elif str(download_path).endswith(".tar.gz") or str(download_path).endswith(".tgz"):
            import tarfile

            with tarfile.open(download_path, "r:gz") as tf:
                # Guard against tar-slip
                for member in tf.getmembers():
                    member_path = (staging_dir / member.name).resolve()
                    if not str(member_path).startswith(str(staging_dir.resolve())):
                        raise ValueError(
                            f"Unsafe archive member rejected (tar-slip): {member.name}"
                        )
                tf.extractall(staging_dir)
        else:
            # Assume it's a single file to copy
            shutil.copy2(download_path, staging_dir / download_path.name)

        logger.info("Staged update in %s", staging_dir)
        return staging_dir

    def _apply_update(self, staged_path: Path) -> bool:
        """Apply the staged update by copying files to the install location.

        The install location is determined by the location of the current
        ``envguard`` package.
        """
        # Find the current package installation directory
        try:
            from importlib.util import find_spec

            spec = find_spec("envguard")
            if spec is None or spec.origin is None:
                logger.error("Cannot determine envguard installation path")
                return False
            install_dir = Path(spec.origin).resolve().parent.parent
        except (ImportError, ValueError) as exc:
            logger.error("Cannot determine installation path: %s", exc)
            return False

        logger.info("Installing update from %s to %s", staged_path, install_dir)

        try:
            # Look for the src/envguard directory inside the staging dir
            src_envguard = staged_path / "src" / "envguard"
            if not src_envguard.exists():
                src_envguard = staged_path / "envguard"
            if not src_envguard.exists():
                # Use the staging dir itself
                src_envguard = staged_path

            # Copy files - validate each destination stays within install_dir
            install_dir_resolved = install_dir.resolve()
            for item in src_envguard.iterdir():
                dest = (install_dir / item.name).resolve()
                if not str(dest).startswith(str(install_dir_resolved)):
                    raise ValueError(f"Unsafe update path rejected (traversal): {item.name}")
                if item.is_dir():
                    if dest.exists():
                        shutil.rmtree(dest)
                    shutil.copytree(item, dest)
                else:
                    shutil.copy2(item, dest)

            logger.info("Update applied successfully")
            return True

        except OSError as exc:
            logger.error("Failed to apply update: %s", exc)
            return False

    def _verify_update(
        self,
        file_path: Path,
        manifest: UpdateManifest,
    ) -> bool:
        """Verify the downloaded update against the manifest."""
        result = self.verifier.verify_integrity(file_path, manifest)

        if not result.get("checksum_ok", False):
            logger.error("Checksum verification failed")
            return False

        if not result.get("signature_ok", False):
            logger.warning("Signature verification failed (continuing)")

        if not result.get("trusted", False):
            logger.warning("Update trust check failed (continuing)")

        # Platform check
        if not self.verifier.verify_platform(manifest):
            logger.error("Platform compatibility check failed")
            return False

        return True
