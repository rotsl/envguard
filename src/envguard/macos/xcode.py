# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""Xcode and Command Line Tools detection for macOS."""

from __future__ import annotations

import shutil
import subprocess

from envguard.logging import get_logger

logger = get_logger(__name__)

# Default timeout for subprocess calls (seconds)
_DEFAULT_TIMEOUT = 15


class XcodeChecker:
    """Detect and query Xcode and Command Line Tools installation status.

    All methods are class-level and stateless; no instance is required.
    """

    # ------------------------------------------------------------------
    # Basic checks
    # ------------------------------------------------------------------

    @classmethod
    def is_installed(cls) -> bool:
        """Check whether the Xcode.app bundle is installed.

        Runs ``xcode-select -p`` and inspects whether the returned path points
        inside an ``Xcode.app`` bundle (as opposed to the standalone CLT).

        Returns:
            ``True`` if full Xcode is installed.
        """
        path = cls.get_path()
        if path is None:
            return False
        return "Xcode.app" in path

    @classmethod
    def get_path(cls) -> str | None:
        """Return the developer tools path reported by ``xcode-select -p``.

        Returns:
            The path string, or ``None`` if ``xcode-select`` is not available
            or returns a non-zero exit code.
        """
        xcode_select = shutil.which("xcode-select")
        if xcode_select is None:
            logger.debug("xcode-select not found on PATH")
            return None

        try:
            result = subprocess.run(
                [xcode_select, "-p"],
                capture_output=True,
                text=True,
                timeout=_DEFAULT_TIMEOUT,
            )
        except subprocess.TimeoutExpired as exc:
            logger.warning("xcode-select -p timed out: %s", exc)
            return None
        except OSError as exc:
            logger.debug("Failed to run xcode-select: %s", exc)
            return None

        if result.returncode != 0:
            # stderr often contains guidance when tools are not installed
            logger.debug(
                "xcode-select returned %d: %s",
                result.returncode,
                result.stderr.strip(),
            )
            return None

        return result.stdout.strip()

    @classmethod
    def is_command_line_tools_installed(cls) -> bool:
        """Check whether the stand-alone Command Line Tools are installed.

        CLTs are present when ``xcode-select -p`` succeeds but does **not**
        point inside ``Xcode.app``, or when ``xcodebuild`` is available but
        Xcode.app itself is absent.

        Returns:
            ``True`` if the stand-alone CLT package is installed.
        """
        path = cls.get_path()
        if path is None:
            return False
        # If xcode-select points somewhere that is NOT inside Xcode.app,
        # then we have the standalone CLT.
        if "Xcode.app" in path:
            # Full Xcode is installed, which includes CLT implicitly.
            return True
        # Path exists but is not inside Xcode.app => standalone CLT.
        return True

    @classmethod
    def get_version(cls) -> str | None:
        """Return the Xcode version string via ``xcodebuild -version``.

        Returns:
            A version string such as ``"Xcode 15.2"`` with build info, or
            ``None`` if ``xcodebuild`` is unavailable or fails.
        """
        xcodebuild = shutil.which("xcodebuild")
        if xcodebuild is None:
            logger.debug("xcodebuild not found on PATH")
            return None

        try:
            result = subprocess.run(
                [xcodebuild, "-version"],
                capture_output=True,
                text=True,
                timeout=_DEFAULT_TIMEOUT,
            )
        except subprocess.TimeoutExpired as exc:
            logger.warning("xcodebuild -version timed out: %s", exc)
            return None
        except OSError as exc:
            logger.debug("Failed to run xcodebuild: %s", exc)
            return None

        if result.returncode != 0:
            logger.debug(
                "xcodebuild returned %d: %s",
                result.returncode,
                result.stderr.strip(),
            )
            return None

        # Output looks like:
        #   Xcode 15.2\nBuild version 15C500b
        lines = result.stdout.strip().splitlines()
        if lines:
            return lines[0].strip()
        return None

    # ------------------------------------------------------------------
    # Composite checks
    # ------------------------------------------------------------------

    @classmethod
    def check_build_tools(cls) -> dict[str, object]:
        """Run all build-tool checks and return a consolidated result.

        Returns:
            A dictionary with keys:

            - ``installed`` (*bool*): Whether any developer tools are available.
            - ``path`` (*str | None*): The ``xcode-select`` path.
            - ``version`` (*str | None*): Xcode version (``None`` for CLT-only).
            - ``has_cli_tools`` (*bool*): Whether CLT are available.
            - ``is_full_xcode`` (*bool*): Whether full Xcode.app is installed.
        """
        path = cls.get_path()
        installed = path is not None
        has_cli_tools = cls.is_command_line_tools_installed()
        is_full_xcode = cls.is_installed()
        version = cls.get_version() if is_full_xcode else None

        return {
            "installed": installed,
            "path": path,
            "version": version,
            "has_cli_tools": has_cli_tools,
            "is_full_xcode": is_full_xcode,
        }

    @classmethod
    def verify_source_build_prerequisites(cls) -> list[str]:
        """Check for tools typically required to build Python from source.

        Probes for the following on ``PATH``:

        - ``make`` - build driver
        - ``gcc`` / ``cc`` - C compiler
        - ``clang`` - LLVM compiler (default on macOS)
        - ``git`` - version control (often needed for CPython checkouts)

        Returns:
            A list of missing tool names.  An empty list means all
            prerequisites are satisfied.
        """
        required_tools = ["make", "gcc", "clang", "git"]
        # cc is a common symlink; check it as a fallback for gcc
        fallback_map = {"gcc": "cc"}

        missing: list[str] = []

        for tool in required_tools:
            found = shutil.which(tool) is not None
            if not found:
                # Try a fallback name
                fallback = fallback_map.get(tool)
                if fallback:
                    found = shutil.which(fallback) is not None
                    if found:
                        logger.debug("%s not found but fallback %s is available", tool, fallback)
                        continue
            if not found:
                missing.append(tool)
                logger.debug("Prerequisite tool not found: %s", tool)

        # Additionally, verify developer directory is set
        dev_path = cls.get_path()
        if dev_path is None:
            if "xcode-cli-tools" not in missing:
                missing.append("xcode-cli-tools")
            logger.debug("No developer directory set via xcode-select")
        else:
            logger.debug("Developer directory: %s", dev_path)

        return missing
