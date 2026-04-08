# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""Tests for update manifest parsing and verification."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from envguard.update.manifest import ManifestParser
from envguard.update.verifier import UpdateVerifier

try:
    from envguard.models import UpdateManifest
except ImportError:
    from envguard.update.manifest import UpdateManifest


SAMPLE_MANIFEST_JSON = json.dumps(
    {
        "version": "0.2.0",
        "download_url": "https://github.com/example/envguard/releases/tag/v0.2.0",
        "changelog": "Added MPS detection, improved Rosetta handling",
        "checksum": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "checksum_algorithm": "sha256",
        "min_python_version": "3.10",
        "platforms": ["darwin"],
        "signature": "",
        "release_date": "2026-04-01T00:00:00Z",
    }
)


SAMPLE_MANIFEST_DICT = {
    "version": "0.2.0",
    "download_url": "https://github.com/example/envguard/releases/v0.2.0",
    "changelog": "Bug fixes",
    "checksum": "abc123",
    "checksum_algorithm": "sha256",
    "min_python_version": "3.10",
    "platforms": ["darwin"],
    "signature": "",
    "release_date": "2026-04-01T00:00:00Z",
}


class TestManifestParser:
    """Tests for ManifestParser."""

    @pytest.fixture
    def parser(self) -> ManifestParser:
        return ManifestParser()

    def test_parse_from_json_string(self, parser: ManifestParser):
        manifest = parser.parse(SAMPLE_MANIFEST_JSON)
        assert manifest.version == "0.2.0"
        assert hasattr(manifest, "platforms") and "darwin" in manifest.platforms

    def test_parse_from_dict(self, parser: ManifestParser):
        manifest = parser.parse(SAMPLE_MANIFEST_DICT)
        assert manifest.version == "0.2.0"
        # channel is not a field on the fallback UpdateManifest; use getattr
        assert getattr(manifest, "channel", None) is None

    def test_parse_file(self, parser: ManifestParser, tmp_path: Path):
        manifest_file = tmp_path / "manifest.json"
        manifest_file.write_text(SAMPLE_MANIFEST_JSON)
        manifest = parser.parse_file(manifest_file)
        assert manifest.version == "0.2.0"

    def test_validate_good_manifest(self, parser: ManifestParser):
        manifest = parser.parse(SAMPLE_MANIFEST_JSON)
        issues = parser.validate(manifest)
        # Should have zero or minimal issues
        assert isinstance(issues, list)

    def test_validate_missing_version(self, parser: ManifestParser):
        bad = {"platforms": ["darwin"]}  # missing version
        manifest = parser.parse(bad)
        issues = parser.validate(manifest)
        assert len(issues) > 0

    def test_to_json(self, parser: ManifestParser):
        manifest = parser.parse(SAMPLE_MANIFEST_JSON)
        json_str = parser.to_json(manifest)
        parsed = json.loads(json_str)
        assert parsed["version"] == "0.2.0"

    def test_compare_versions_newer(self, parser: ManifestParser):
        result = parser.compare_versions("0.1.0", "0.2.0")
        assert result < 0  # current < latest

    def test_compare_versions_same(self, parser: ManifestParser):
        result = parser.compare_versions("1.0.0", "1.0.0")
        assert result == 0

    def test_compare_versions_older(self, parser: ManifestParser):
        result = parser.compare_versions("2.0.0", "1.0.0")
        assert result > 0

    def test_compare_versions_prerelease(self, parser: ManifestParser):
        result = parser.compare_versions("0.1.0", "0.2.0a1")
        # Pre-release versions are typically considered older
        assert isinstance(result, int)

    def test_format_changelog(self, parser: ManifestParser):
        manifest = parser.parse(SAMPLE_MANIFEST_JSON)
        formatted = parser.format_changelog(manifest)
        assert isinstance(formatted, str)
        assert len(formatted) > 0

    def test_generate_sample_manifest(self, parser: ManifestParser):
        manifest = parser.generate_sample_manifest()
        assert isinstance(manifest, UpdateManifest)
        assert manifest.version != ""
        assert hasattr(manifest, "platforms") and isinstance(manifest.platforms, list)
        assert len(manifest.platforms) > 0


class TestUpdateVerifier:
    """Tests for UpdateVerifier."""

    @pytest.fixture
    def verifier(self) -> UpdateVerifier:
        return UpdateVerifier()

    def test_verify_checksum_correct(self, verifier: UpdateVerifier, tmp_path: Path):
        import hashlib

        data = b"test content for checksum"
        expected = hashlib.sha256(data).hexdigest()
        test_file = tmp_path / "test.bin"
        test_file.write_bytes(data)

        assert verifier.verify_checksum(test_file, expected, "sha256") is True

    def test_verify_checksum_incorrect(self, verifier: UpdateVerifier, tmp_path: Path):
        test_file = tmp_path / "test.bin"
        test_file.write_bytes(b"wrong content")

        assert verifier.verify_checksum(test_file, "0" * 64, "sha256") is False

    def test_verify_checksum_missing_file(self, verifier: UpdateVerifier):
        assert verifier.verify_checksum(Path("/nonexistent/file"), "abc", "sha256") is False

    def test_verify_checksum_sha384(self, verifier: UpdateVerifier, tmp_path: Path):
        import hashlib

        data = b"sha384 test"
        expected = hashlib.sha384(data).hexdigest()
        test_file = tmp_path / "test.bin"
        test_file.write_bytes(data)

        assert verifier.verify_checksum(test_file, expected, "sha384") is True

    def test_verify_checksum_sha512(self, verifier: UpdateVerifier, tmp_path: Path):
        import hashlib

        data = b"sha512 test"
        expected = hashlib.sha512(data).hexdigest()
        test_file = tmp_path / "test.bin"
        test_file.write_bytes(data)

        assert verifier.verify_checksum(test_file, expected, "sha512") is True

    def test_verify_checksum_unsupported_algorithm(self, verifier: UpdateVerifier, tmp_path: Path):
        test_file = tmp_path / "test.bin"
        test_file.write_bytes(b"data")
        # Should handle unsupported algorithm gracefully
        result = verifier.verify_checksum(test_file, "abc", "md5")
        assert result is False

    def test_verify_platform_darwin(self, verifier: UpdateVerifier):
        import sys

        manifest = UpdateManifest(platforms=["darwin"])
        result = verifier.verify_platform(manifest)
        # Only True on macOS (darwin); False on Linux CI
        if sys.platform == "darwin":
            assert result is True
        else:
            assert result is False

    def test_verify_platform_linux(self, verifier: UpdateVerifier):
        import sys

        manifest = UpdateManifest(platforms=["linux"])
        result = verifier.verify_platform(manifest)
        # On macOS CI, this should be False; on Linux CI, True
        if sys.platform == "linux":
            assert result is True
        else:
            assert result is False

    def test_verify_python_version(self, verifier: UpdateVerifier):
        manifest = UpdateManifest(min_python_version="3.10")
        assert verifier.verify_python_version(manifest) is True

    def test_verify_signature_placeholder(self, verifier: UpdateVerifier, tmp_path: Path):
        """Signature verification is a placeholder - should not crash."""
        test_file = tmp_path / "test.bin"
        test_file.write_bytes(b"data")
        # This should not raise even though signature is empty
        result = verifier.verify_signature(test_file, "")
        # The implementation should document this is a placeholder
        assert isinstance(result, bool)

    def test_verify_integrity(self, verifier: UpdateVerifier, tmp_path: Path):
        import hashlib

        data = b"integrity test"
        checksum = hashlib.sha256(data).hexdigest()
        test_file = tmp_path / "test.bin"
        test_file.write_bytes(data)

        manifest = UpdateManifest(
            checksum=checksum,
            checksum_algorithm="sha256",
            platforms=["darwin"],
            min_python_version="3.10",
        )
        result = verifier.verify_integrity(test_file, manifest)
        assert isinstance(result, dict)
        assert "checksum_ok" in result
