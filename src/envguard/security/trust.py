# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""Trust management for verifying package sources and domains."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from envguard.exceptions import TrustError
from envguard.logging import get_logger

logger = get_logger(__name__)


class TrustManager:
    """Manage a trust store for Python package sources.

    The trust store is persisted as a JSON file inside the configuration
    directory.  It tracks trusted domains and PGP key identifiers.

    Args:
        config_dir: Override the configuration directory.  If ``None``, the
            default ``~/.envguard/`` directory is used.
    """

    TRUSTED_KEYS_FILE: str = "trusted_keys.json"
    KNOWN_TRUSTED_DOMAINS: list[str] = [  # noqa: RUF012
        "pypi.org",
        "files.pythonhosted.org",
        "github.com",
        "conda.anaconda.org",
    ]

    def __init__(self, config_dir: Path | None = None) -> None:
        if config_dir is not None:
            self._config_dir = Path(config_dir)
        else:
            from envguard.macos.paths import MacPaths

            self._config_dir = MacPaths.user_config_dir

        self._keys_file = self._config_dir / self.TRUSTED_KEYS_FILE
        self._keys: dict[str, dict[str, Any]] = {}
        self._load_keys()

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _load_keys(self) -> None:
        """Load the trusted-keys store from disk."""
        if self._keys_file.exists():
            try:
                text = self._keys_file.read_text(encoding="utf-8")
                data = json.loads(text)
                if isinstance(data, dict):
                    self._keys = data
                else:
                    logger.warning("Trusted keys file has unexpected format; starting fresh.")
                    self._keys = {}
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Failed to load trusted keys: %s", exc)
                self._keys = {}
        else:
            self._keys = {}

    def _save_keys(self) -> None:
        """Persist the trusted-keys store to disk."""
        try:
            self._config_dir.mkdir(parents=True, exist_ok=True)
            self._keys_file.write_text(
                json.dumps(self._keys, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.error("Failed to save trusted keys: %s", exc)

    # ------------------------------------------------------------------
    # Domain trust
    # ------------------------------------------------------------------

    def is_domain_trusted(self, domain: str) -> bool:
        """Check whether *domain* is in the known-trusted set.

        The check is case-insensitive.

        Args:
            domain: A domain name such as ``"pypi.org"``.

        Returns:
            ``True`` if the domain is trusted.
        """
        domain_lower = domain.lower().strip()
        return domain_lower in [d.lower() for d in self.KNOWN_TRUSTED_DOMAINS]

    def is_url_trusted(self, url: str) -> bool:
        """Parse *url* and check whether its hostname is trusted.

        Args:
            url: A full URL string (e.g. ``"https://pypi.org/simple/"``).

        Returns:
            ``True`` if the URL's domain is trusted.
        """
        try:
            parsed = urlparse(url)
            hostname = parsed.hostname
            if hostname is None:
                return False
            return self.is_domain_trusted(hostname)
        except Exception as exc:
            logger.debug("Failed to parse URL '%s': %s", url, exc)
            return False

    # ------------------------------------------------------------------
    # Key management
    # ------------------------------------------------------------------

    def get_trusted_keys(self) -> list[str]:
        """Return a list of trusted key IDs.

        Returns:
            List of key identifier strings.
        """
        return list(self._keys.keys())

    def add_trusted_key(self, key_id: str, fingerprint: str) -> None:
        """Add a key to the trust store.

        If the key already exists its fingerprint and timestamp are updated.

        Args:
            key_id: A unique identifier for the key (e.g. email or key ID).
            fingerprint: The PGP/GPG fingerprint of the key.
        """
        self._keys[key_id] = {
            "fingerprint": fingerprint,
            "added_at": datetime.now(timezone.utc).isoformat(),
        }
        self._save_keys()
        logger.info("Trusted key added: %s", key_id)

    def remove_trusted_key(self, key_id: str) -> None:
        """Remove a key from the trust store.

        Args:
            key_id: The key identifier to remove.

        Raises:
            TrustError: If the key is not found in the store.
        """
        if key_id not in self._keys:
            raise TrustError(f"Key '{key_id}' not found in trust store")

        del self._keys[key_id]
        self._save_keys()
        logger.info("Trusted key removed: %s", key_id)

    # ------------------------------------------------------------------
    # Source verification
    # ------------------------------------------------------------------

    def verify_source(
        self,
        url: str,
        artifact_hash: str | None = None,
    ) -> dict[str, Any]:
        """Verify that a package source URL is trustworthy.

        Args:
            url: The source URL.
            artifact_hash: Optional hash of the artifact for integrity
                verification (not validated against a remote source; simply
                recorded in the result).

        Returns:
            A dictionary with:

            - ``trusted`` (*bool*): Whether the domain is trusted.
            - ``domain`` (*str*): The extracted domain.
            - ``hash_verified`` (*bool*): Whether a hash was provided (always
              ``True`` if *artifact_hash* is non-empty).
            - ``artifact_hash`` (*str | None*): The hash that was supplied.
            - ``url`` (*str*): The original URL.
            - ``recommendation`` (*str*): Human-readable guidance.
        """
        domain: str = ""
        try:
            parsed = urlparse(url)
            domain = parsed.hostname or ""
        except Exception:
            pass

        trusted = self.is_domain_trusted(domain) if domain else False
        hash_verified = artifact_hash is not None and len(artifact_hash) > 0

        if trusted:
            recommendation = "Source domain is trusted. Package can be installed."
        elif not domain:
            recommendation = (
                "Could not parse domain from URL. Manual verification recommended."
            )
        else:
            recommendation = (
                f"Domain '{domain}' is NOT in the trusted list. "
                "Review the source carefully before installing."
            )

        return {
            "trusted": trusted,
            "domain": domain,
            "hash_verified": hash_verified,
            "artifact_hash": artifact_hash,
            "url": url,
            "recommendation": recommendation,
        }

    def validate_update_source(self, manifest_url: str) -> dict[str, Any]:
        """Validate an update manifest URL for trustworthiness.

        Args:
            manifest_url: URL of the update manifest.

        Returns:
            A dictionary with:

            - ``valid`` (*bool*): Whether the source is considered valid.
            - ``domain`` (*str*): Extracted domain.
            - ``is_trusted_domain`` (*bool*): Whether the domain is trusted.
            - ``url`` (*str*): The original URL.
            - ``scheme`` (*str*): URL scheme (should be ``https``).
            - ``issues`` (*list[str]*): Any issues detected.
        """
        issues: list[str] = []

        try:
            parsed = urlparse(manifest_url)
        except Exception as exc:
            issues.append(f"Failed to parse URL: {exc}")
            return {
                "valid": False,
                "domain": "",
                "is_trusted_domain": False,
                "url": manifest_url,
                "scheme": "",
                "issues": issues,
            }

        domain = parsed.hostname or ""
        scheme = parsed.scheme.lower()
        is_trusted = self.is_domain_trusted(domain) if domain else False

        # Enforce HTTPS
        if scheme != "https":
            issues.append(f"URL scheme is '{scheme}', expected 'https'")

        if not domain:
            issues.append("No domain could be extracted from the URL")

        if not is_trusted and domain:
            issues.append(f"Domain '{domain}' is not in the trusted list")

        valid = len(issues) == 0

        return {
            "valid": valid,
            "domain": domain,
            "is_trusted_domain": is_trusted,
            "url": manifest_url,
            "scheme": scheme,
            "issues": issues,
        }

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def get_trust_report(self) -> dict[str, Any]:
        """Return a comprehensive trust report.

        Returns:
            A dictionary summarising trust configuration:

            - ``trusted_domains`` (*list[str]*): Built-in trusted domains.
            - ``trusted_keys_count`` (*int*): Number of keys in the store.
            - ``trusted_key_ids`` (*list[str]*): IDs of all stored keys.
            - ``keys_file`` (*str*): Path to the keys file on disk.
            - ``keys_file_exists`` (*bool*): Whether the file exists.
        """
        return {
            "trusted_domains": list(self.KNOWN_TRUSTED_DOMAINS),
            "trusted_keys_count": len(self._keys),
            "trusted_key_ids": list(self._keys.keys()),
            "keys_file": str(self._keys_file),
            "keys_file_exists": self._keys_file.exists(),
        }
