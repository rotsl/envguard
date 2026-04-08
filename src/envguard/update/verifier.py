# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""Update verification - checksums, signatures, platform compatibility."""

from __future__ import annotations

import hashlib
import platform
import sys
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
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

logger = get_logger(__name__)


class UpdateVerifier:
    """Verify downloaded updates before installation.

    Currently supports SHA-256/384/512 checksum verification.  Signature
    verification is planned but not yet implemented.
    """

    def __init__(self) -> None:
        self._known_algorithms = {
            "sha256": hashlib.sha256,
            "sha384": hashlib.sha384,
            "sha512": hashlib.sha512,
            "md5": hashlib.md5,
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def verify_checksum(
        self,
        file_path: Path,
        expected_hash: str,
        algorithm: str = "sha256",
    ) -> bool:
        """Verify the checksum of a file.

        Args:
            file_path: Path to the file to verify.
            expected_hash: The expected hex digest.
            algorithm: Hash algorithm (``"sha256"``, ``"sha384"``, ``"sha512"``, ``"md5"``).

        Returns:
            ``True`` if the computed hash matches *expected_hash*.

        Raises:
            ValueError: If the algorithm is not supported.
        """
        if not file_path.is_file():
            logger.error("File not found for checksum verification: %s", file_path)
            return False

        hash_func = self._known_algorithms.get(algorithm.lower())
        if hash_func is None:
            raise ValueError(f"Unsupported hash algorithm: {algorithm}")

        expected = expected_hash.strip().lower()

        h = hash_func()
        with open(file_path, "rb") as fh:
            # Read in chunks to handle large files efficiently
            while True:
                chunk = fh.read(65536)  # 64 KB
                if not chunk:
                    break
                h.update(chunk)

        computed = h.hexdigest().lower()
        match = computed == expected

        if not match:
            logger.error(
                "Checksum mismatch for %s: expected %s, got %s (algorithm: %s)",
                file_path,
                expected[:16] + "…",
                computed[:16] + "…",
                algorithm,
            )
        else:
            logger.debug(
                "Checksum verified for %s (%s:%s)",
                file_path,
                algorithm,
                computed[:16] + "…",
            )

        return match

    def verify_signature(self, file_path: Path, signature: str) -> bool:
        """Verify the cryptographic signature of a file.

        .. note::

            **Signature verification is not yet implemented.** This method
            always returns ``True``.  Only checksum verification is
            currently supported.  See the security model documentation for
            details on the planned GPG / Sigstore integration.

            When signature verification is implemented, this method will:
            1. Load the trusted public key(s) from the envguard keyring.
            2. Verify the detached signature against the file contents.
            3. Check the key's trust chain and expiration.

        Args:
            file_path: Path to the file whose signature to verify.
            signature: The signature string (base64-encoded detached signature).

        Returns:
            Currently always returns ``True``.
        """
        logger.warning(
            "Signature verification is not yet implemented. "
            "Only checksum verification is currently supported. "
            "Proceeding with checksum-only trust model."
        )
        return True

    def verify_integrity(
        self,
        file_path: Path,
        manifest: UpdateManifest,
    ) -> dict:
        """Run all integrity verifications against *file_path*.

        Args:
            file_path: Path to the downloaded update file.
            manifest: The update manifest containing expected checksums, etc.

        Returns:
            A dict with keys:
            - ``checksum_ok`` (bool)
            - ``signature_ok`` (bool)
            - ``trusted`` (bool) - ``True`` when all checks pass
        """
        results: dict = {
            "checksum_ok": False,
            "signature_ok": False,
            "trusted": False,
        }

        # Checksum verification
        checksum = getattr(manifest, "checksum", "")
        algorithm = getattr(manifest, "checksum_algorithm", "sha256")

        if checksum:
            results["checksum_ok"] = self.verify_checksum(
                file_path, checksum, algorithm
            )
        else:
            logger.error("No checksum in manifest - refusing to install unverified update")
            results["checksum_ok"] = False

        # Signature verification
        signature = getattr(manifest, "signature", "")
        if signature:
            results["signature_ok"] = self.verify_signature(file_path, signature)
        else:
            logger.debug("No signature in manifest - skipping signature verification")
            results["signature_ok"] = True  # Don't block if not provided

        # Overall trust determination
        results["trusted"] = results["checksum_ok"]

        return results

    def verify_platform(self, manifest: UpdateManifest) -> bool:
        """Check whether the update supports the current platform.

        If the manifest specifies a ``platforms`` list, the current platform
        must appear in it.  If the list is empty or absent, the update is
        assumed to be platform-agnostic.

        Args:
            manifest: The update manifest.

        Returns:
            ``True`` if the platform is compatible.
        """
        platforms = getattr(manifest, "platforms", None)

        if not platforms:
            # No platform restriction
            return True

        current_system = sys.platform.lower()
        current_machine = platform.machine().lower()

        allowed = [p.lower() for p in platforms]

        # Check for broad matches
        for allowed_plat in allowed:
            # Direct match
            if allowed_plat == current_system:
                return True
            # "darwin" matches any macOS
            if allowed_plat == "darwin" and current_system == "darwin":
                return True
            # "macos" is an alias for darwin
            if allowed_plat in ("macos", "macos_arm64", "macos_x86_64"):
                if current_system == "darwin":
                    if allowed_plat == "macos":
                        return True
                    if allowed_plat == "macos_arm64" and current_machine in ("arm64", "aarch64"):
                        return True
                    if allowed_plat == "macos_x86_64" and current_machine == "x86_64":
                        return True
            # "linux" matches
            if allowed_plat == "linux" and "linux" in current_system:
                return True

        logger.warning(
            "Platform mismatch: update supports %s, current is %s/%s",
            platforms,
            current_system,
            current_machine,
        )
        return False

    def verify_python_version(self, manifest: UpdateManifest) -> bool:
        """Check whether the current Python version meets the manifest's requirement.

        Args:
            manifest: The update manifest.

        Returns:
            ``True`` if the Python version is compatible.
        """
        min_py = getattr(manifest, "min_python_version", None)
        if min_py is None:
            return True

        current = sys.version_info[:3]
        min_parts = tuple(int(p) for p in str(min_py).split(".")[:3])
        # Pad if necessary
        while len(min_parts) < 3:
            min_parts = (*min_parts, 0)

        if current >= min_parts:
            return True

        logger.warning(
            "Python version too old: need >= %s, have %s",
            min_py,
            ".".join(map(str, current)),
        )
        return False
