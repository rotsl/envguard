# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""Tests for security modules (trust and signatures)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from envguard.exceptions import VerificationError
from envguard.security.signatures import SignatureVerifier
from envguard.security.trust import TrustManager


class TestTrustManager:
    """Tests for the TrustManager class."""

    @pytest.fixture
    def manager(self, tmp_path: Path) -> TrustManager:
        return TrustManager(config_dir=tmp_path)

    def test_known_trusted_domains(self, manager: TrustManager):
        assert "pypi.org" in TrustManager.KNOWN_TRUSTED_DOMAINS
        assert "github.com" in TrustManager.KNOWN_TRUSTED_DOMAINS
        assert "files.pythonhosted.org" in TrustManager.KNOWN_TRUSTED_DOMAINS

    def test_is_domain_trusted_pypi(self, manager: TrustManager):
        assert manager.is_domain_trusted("pypi.org") is True

    def test_is_domain_trusted_github(self, manager: TrustManager):
        assert manager.is_domain_trusted("github.com") is True

    def test_is_domain_trusted_unknown(self, manager: TrustManager):
        assert manager.is_domain_trusted("evil-domain.com") is False

    def test_is_domain_trusted_subdomain(self, manager: TrustManager):
        # Subdomains of trusted domains
        result = manager.is_domain_trusted("files.pythonhosted.org")
        assert result is True

    def test_is_url_trusted(self, manager: TrustManager):
        assert manager.is_url_trusted("https://pypi.org/simple/") is True
        assert manager.is_url_trusted("https://github.com/user/repo") is True

    def test_is_url_trusted_untrusted(self, manager: TrustManager):
        assert manager.is_url_trusted("https://evil.com/package") is False

    def test_is_url_trusted_http(self, manager: TrustManager):
        # HTTP should still check domain trust
        result = manager.is_url_trusted("http://pypi.org/simple/")
        assert result is True  # domain is trusted

    def test_get_trusted_keys_empty(self, manager: TrustManager):
        keys = manager.get_trusted_keys()
        assert isinstance(keys, list)

    def test_add_and_remove_trusted_key(self, manager: TrustManager):
        manager.add_trusted_key("test-key-1", "AB:CD:EF")
        keys = manager.get_trusted_keys()
        assert len(keys) >= 1

        manager.remove_trusted_key("test-key-1")
        keys_after = manager.get_trusted_keys()
        # Key should be removed
        assert not any(k.get("key_id") == "test-key-1" for k in keys_after if isinstance(k, dict))

    def test_verify_source_trusted(self, manager: TrustManager):
        result = manager.verify_source("https://pypi.org/simple/requests/")
        assert result["trusted"] is True
        assert result["domain"] == "pypi.org"

    def test_verify_source_untrusted(self, manager: TrustManager):
        result = manager.verify_source("https://malware-site.com/package")
        assert result["trusted"] is False

    def test_trust_report(self, manager: TrustManager):
        report = manager.get_trust_report()
        assert isinstance(report, dict)
        assert "trusted_domains" in report or "domains" in report


class TestSignatureVerifier:
    """Tests for the SignatureVerifier class."""

    @pytest.fixture
    def verifier(self) -> SignatureVerifier:
        return SignatureVerifier()

    def test_compute_file_hash_sha256(self, verifier: SignatureVerifier, tmp_path: Path):
        data = b"test file content"
        expected = hashlib.sha256(data).hexdigest()
        test_file = tmp_path / "test.bin"
        test_file.write_bytes(data)

        result = verifier.compute_file_hash(test_file, "sha256")
        assert result == expected

    def test_compute_file_hash_sha512(self, verifier: SignatureVerifier, tmp_path: Path):
        data = b"test content 512"
        expected = hashlib.sha512(data).hexdigest()
        test_file = tmp_path / "test.bin"
        test_file.write_bytes(data)

        result = verifier.compute_file_hash(test_file, "sha512")
        assert result == expected

    def test_compute_file_hash_missing_file(self, verifier: SignatureVerifier):
        with pytest.raises((FileNotFoundError, OSError, ValueError)):
            verifier.compute_file_hash(Path("/nonexistent/file.bin"))

    def test_verify_hash_correct(self, verifier: SignatureVerifier, tmp_path: Path):
        data = b"verification test"
        expected = hashlib.sha256(data).hexdigest()
        test_file = tmp_path / "test.bin"
        test_file.write_bytes(data)

        assert verifier.verify_hash(test_file, expected, "sha256") is True

    def test_verify_hash_incorrect(self, verifier: SignatureVerifier, tmp_path: Path):
        test_file = tmp_path / "test.bin"
        test_file.write_bytes(b"wrong content for hash")
        with pytest.raises(VerificationError):
            verifier.verify_hash(test_file, "a" * 64, "sha256")

    def test_compute_data_hash(self, verifier: SignatureVerifier):
        data = b"raw data hash"
        expected = hashlib.sha256(data).hexdigest()
        result = verifier.compute_data_hash(data, "sha256")
        assert result == expected

    def test_verify_checksum(self, verifier: SignatureVerifier):
        data = b"checksum data"
        expected = hashlib.sha256(data).hexdigest()
        assert verifier.verify_checksum(data, expected, "sha256") is True

    def test_verify_checksum_wrong(self, verifier: SignatureVerifier):
        with pytest.raises(VerificationError):
            verifier.verify_checksum(b"wrong data", "a" * 64, "sha256")

    def test_unsupported_algorithm(self, verifier: SignatureVerifier):
        with pytest.raises((ValueError, Exception)):
            verifier.compute_data_hash(b"data", "unsupported_algo")
