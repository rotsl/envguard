# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""PyPI uploader — twine-first with urllib fallback."""

from __future__ import annotations

import hashlib
import importlib.util
import mimetypes
import shutil
import uuid
from typing import TYPE_CHECKING

from envguard.exceptions import PublishError
from envguard.logging import get_logger
from envguard.models import PublishResult

if TYPE_CHECKING:
    from pathlib import Path

logger = get_logger(__name__)

PYPI_UPLOAD_URL = "https://upload.pypi.org/legacy/"
TEST_PYPI_UPLOAD_URL = "https://test.pypi.org/legacy/"


class Uploader:
    """Upload build artifacts to PyPI (or TestPyPI).

    The primary upload path uses ``twine`` when it is available on
    ``$PATH`` or importable.  If twine is absent a direct ``urllib``
    multipart POST to the PyPI legacy upload API is used instead.

    Args:
        repository_url: Upload endpoint.  Defaults to PyPI.
        token: PyPI API token (``pypi-...``).  Also read from the
            ``PYPI_TOKEN`` environment variable when not passed directly.
    """

    def __init__(
        self,
        repository_url: str = PYPI_UPLOAD_URL,
        token: str | None = None,
    ) -> None:
        self.repository_url = repository_url
        self._token = token

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def upload(self, artifacts: list[Path]) -> PublishResult:
        """Upload *artifacts* to the configured repository.

        Args:
            artifacts: Paths to ``.whl`` or ``.tar.gz`` files.

        Returns:
            :class:`~envguard.models.PublishResult` with upload details.

        Raises:
            PublishError: If the token is missing or no artifacts provided.
        """
        if not artifacts:
            raise PublishError(operation="upload", reason="No artifacts to upload")

        token = self._resolve_token()

        if shutil.which("twine") or importlib.util.find_spec("twine"):
            return self._upload_twine(artifacts, token)
        else:
            logger.info("twine not found — using urllib upload path")
            return self._upload_urllib(artifacts, token)

    # ------------------------------------------------------------------
    # Upload backends
    # ------------------------------------------------------------------

    def _upload_twine(self, artifacts: list[Path], token: str) -> PublishResult:
        """Upload via ``twine upload``."""
        import os
        import subprocess

        env = os.environ.copy()
        env["TWINE_PASSWORD"] = token
        env["TWINE_USERNAME"] = "__token__"

        cmd = [
            "twine",
            "upload",
            "--repository-url",
            self.repository_url,
            "--non-interactive",
            "--disable-progress-bar",
        ] + [str(a) for a in artifacts]

        logger.info("Uploading via twine: %s", [a.name for a in artifacts])

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            raise PublishError(operation="upload", reason="twine upload timed out") from exc
        except FileNotFoundError:
            # twine spec found but binary missing — fall through to urllib
            return self._upload_urllib(artifacts, token)

        if proc.returncode != 0:
            error = proc.stderr.strip() or proc.stdout.strip()
            raise PublishError(operation="upload", reason=error[:1000])

        return PublishResult(
            ok=True,
            artifacts=[str(a) for a in artifacts],
            uploaded=[a.name for a in artifacts],
            repository_url=self.repository_url,
            method="twine",
        )

    def _upload_urllib(self, artifacts: list[Path], token: str) -> PublishResult:
        """Upload via direct multipart POST to the PyPI legacy upload API."""

        uploaded = []
        for artifact in artifacts:
            logger.info("Uploading %s via urllib...", artifact.name)
            try:
                self._upload_single(artifact, token)
                uploaded.append(artifact.name)
            except Exception as exc:
                raise PublishError(
                    operation="upload",
                    reason=f"Failed to upload {artifact.name}: {exc}",
                ) from exc

        return PublishResult(
            ok=True,
            artifacts=[str(a) for a in artifacts],
            uploaded=uploaded,
            repository_url=self.repository_url,
            method="urllib",
        )

    def _upload_single(self, artifact: Path, token: str) -> None:
        """POST a single artifact to the PyPI legacy API."""
        import base64
        import urllib.error
        import urllib.request

        data = artifact.read_bytes()
        md5 = hashlib.md5(data).hexdigest()
        sha256 = hashlib.sha256(data).hexdigest()

        filetype = "bdist_wheel" if artifact.suffix == ".whl" else "sdist"
        boundary = uuid.uuid4().hex

        fields: dict[str, str] = {
            ":action": "file_upload",
            "protocol_version": "1",
            "filetype": filetype,
            "md5_digest": md5,
            "sha2_digest": sha256,
        }

        body = b""
        for key, value in fields.items():
            body += f"--{boundary}\r\n".encode()
            body += f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode()
            body += value.encode() + b"\r\n"

        # File field
        mime_type = mimetypes.guess_type(artifact.name)[0] or "application/octet-stream"
        body += f"--{boundary}\r\n".encode()
        body += (
            f'Content-Disposition: form-data; name="content"; filename="{artifact.name}"\r\n'
        ).encode()
        body += f"Content-Type: {mime_type}\r\n\r\n".encode()
        body += data + b"\r\n"
        body += f"--{boundary}--\r\n".encode()

        credentials = base64.b64encode(f"__token__:{token}".encode()).decode()
        headers = {
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Authorization": f"Basic {credentials}",
            "User-Agent": "envguard/0.1.0",
        }

        req = urllib.request.Request(
            self.repository_url,
            data=body,
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=120):
                pass
        except urllib.error.HTTPError as exc:
            reason = exc.read().decode("utf-8", errors="replace")[:500]
            raise PublishError(
                operation="upload",
                reason=f"HTTP {exc.code}: {reason}",
            ) from exc

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_token(self) -> str:
        """Resolve the API token from direct arg or environment."""
        import os

        token = self._token or os.environ.get("PYPI_TOKEN") or os.environ.get("TWINE_PASSWORD")
        if not token:
            raise PublishError(
                operation="upload",
                reason=(
                    "No PyPI token provided. Pass --token or set the "
                    "PYPI_TOKEN environment variable."
                ),
            )
        return token
