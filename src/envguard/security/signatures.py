# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""Hash computation and verification for file integrity checks."""

from __future__ import annotations

import hashlib
from pathlib import Path

from envguard.exceptions import HashAlgorithmError, VerificationError
from envguard.logging import get_logger

logger = get_logger(__name__)


class SignatureVerifier:
    """Compute and verify cryptographic hashes of files and byte data.

    Supports SHA-256, SHA-384, and SHA-512 via Python's :mod:`hashlib`.
    """

    HASH_ALGORITHMS: list[str] = ["sha256", "sha384", "sha512"]  # noqa: RUF012
    DEFAULT_ALGORITHM: str = "sha256"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @classmethod
    def _validate_algorithm(cls, algorithm: str) -> str:
        """Normalise and validate a hash algorithm name.

        Args:
            algorithm: Name of the algorithm (e.g. ``"sha256"``).

        Returns:
            The lowercased algorithm name.

        Raises:
            HashAlgorithmError: If the algorithm is not supported.
        """
        algo = algorithm.lower().strip()
        if algo not in cls.HASH_ALGORITHMS:
            raise HashAlgorithmError(
                f"Unsupported hash algorithm '{algorithm}'. "
                f"Supported: {', '.join(cls.HASH_ALGORITHMS)}"
            )
        return algo

    @classmethod
    def _normalize_hash(cls, expected: str) -> str:
        """Normalise a hex-encoded hash string.

        Strips whitespace and ``0x`` prefix, and lowercases the result.

        Args:
            expected: Raw hex hash string.

        Returns:
            Normalised lowercase hex string.
        """
        h = expected.strip().lower()
        if h.startswith("0x"):
            h = h[2:]
        return h

    # ------------------------------------------------------------------
    # File hashing
    # ------------------------------------------------------------------

    @classmethod
    def compute_file_hash(
        cls,
        file_path: Path,
        algorithm: str = "sha256",
        chunk_size: int = 65536,
    ) -> str:
        """Compute the hash of a file by reading it in chunks.

        This is memory-efficient for large files.

        Args:
            file_path: Path to the file to hash.
            algorithm: Hash algorithm name (default ``sha256``).
            chunk_size: Read buffer size in bytes.

        Returns:
            Hex-encoded hash string.

        Raises:
            HashAlgorithmError: If *algorithm* is unsupported.
            FileNotFoundError: If *file_path* does not exist.
            OSError: If the file cannot be read.
        """
        algo = cls._validate_algorithm(algorithm)
        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        hasher = hashlib.new(algo)
        with open(path, "rb") as fh:
            while True:
                chunk = fh.read(chunk_size)
                if not chunk:
                    break
                hasher.update(chunk)

        digest = hasher.hexdigest()
        logger.debug(
            "Computed %s hash of %s: %s", algo, path.name, digest
        )
        return digest

    # ------------------------------------------------------------------
    # File hash verification
    # ------------------------------------------------------------------

    @classmethod
    def verify_hash(
        cls,
        file_path: Path,
        expected_hash: str,
        algorithm: str = "sha256",
    ) -> bool:
        """Verify a file's hash against an expected value.

        Args:
            file_path: Path to the file.
            expected_hash: The expected hex-encoded hash.
            algorithm: Hash algorithm to use.

        Returns:
            ``True`` if the computed hash matches *expected_hash*.

        Raises:
            HashAlgorithmError: If *algorithm* is unsupported.
            VerificationError: If the hash does not match.
        """
        algo = cls._validate_algorithm(algorithm)
        normalized_expected = cls._normalize_hash(expected_hash)

        try:
            computed = cls.compute_file_hash(file_path, algorithm=algo)
        except FileNotFoundError as exc:
            raise VerificationError(
                f"Cannot verify hash: file not found - {exc}"
            ) from exc
        except OSError as exc:
            raise VerificationError(
                f"Cannot verify hash: read error - {exc}"
            ) from exc

        if computed != normalized_expected:
            logger.warning(
                "Hash mismatch for %s (algorithm=%s): expected=%s, got=%s",
                file_path,
                algo,
                normalized_expected,
                computed,
            )
            raise VerificationError(
                f"Hash verification failed for {file_path}: "
                f"expected {normalized_expected}, got {computed}"
            )

        logger.info(
            "Hash verified OK for %s (%s)", file_path, algo
        )
        return True

    # ------------------------------------------------------------------
    # Data (bytes) hashing
    # ------------------------------------------------------------------

    @classmethod
    def compute_data_hash(cls, data: bytes, algorithm: str = "sha256") -> str:
        """Compute the hash of an in-memory byte string.

        Args:
            data: The bytes to hash.
            algorithm: Hash algorithm name.

        Returns:
            Hex-encoded hash string.

        Raises:
            HashAlgorithmError: If *algorithm* is unsupported.
        """
        algo = cls._validate_algorithm(algorithm)
        hasher = hashlib.new(algo)
        hasher.update(data)
        return hasher.hexdigest()

    # ------------------------------------------------------------------
    # Data (bytes) verification
    # ------------------------------------------------------------------

    @classmethod
    def verify_checksum(
        cls,
        data: bytes,
        expected: str,
        algorithm: str = "sha256",
    ) -> bool:
        """Verify a byte buffer's checksum against an expected value.

        Args:
            data: The byte buffer.
            expected: The expected hex-encoded checksum.
            algorithm: Hash algorithm to use.

        Returns:
            ``True`` if the checksum matches.

        Raises:
            HashAlgorithmError: If *algorithm* is unsupported.
            VerificationError: If the checksum does not match.
        """
        algo = cls._validate_algorithm(algorithm)
        normalized_expected = cls._normalize_hash(expected)

        computed = cls.compute_data_hash(data, algorithm=algo)

        if computed != normalized_expected:
            logger.warning(
                "Checksum mismatch (%s): expected=%s, got=%s",
                algo,
                normalized_expected,
                computed,
            )
            raise VerificationError(
                f"Checksum verification failed ({algo}): "
                f"expected {normalized_expected}, got {computed}"
            )

        return True
