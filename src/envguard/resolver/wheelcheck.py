# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""Wheel filename parsing and platform-tag compatibility checks."""

from __future__ import annotations

import re

try:
    from envguard.logging import get_logger
except ImportError:
    import logging

    def get_logger(name: str) -> logging.Logger:  # type: ignore[misc]
        return logging.getLogger(name)


try:
    from envguard.models import Architecture
except ImportError:

    class Architecture:  # type: ignore[no-redef]
        ARM64 = "arm64"
        X86_64 = "x86_64"


logger = get_logger(__name__)

# Regular expression for wheel filenames per PEP 427:
#   {distribution}-{version}(-{build tag})?-{python tag}-{abi tag}-{platform tag}.whl
# Per PEP 427, distribution names use only [A-Za-z0-9._] (no hyphens).
# The build tag, if present, is a numeric-only segment.
_WHEEL_RE = re.compile(
    r"^(?P<dist>[A-Za-z0-9]([A-Za-z0-9._]*[A-Za-z0-9])?)"
    r"-(?P<ver>[A-Za-z0-9._]+)"
    r"(?:-(?P<build>\d+))?"
    r"-(?P<pytag>[A-Za-z0-9._]+)"
    r"-(?P<abi>[A-Za-z0-9._]+)"
    r"-(?P<plat>[A-Za-z0-9._-]+)"
    r"\.whl$",
)

# ------------------------------------------------------------------
# macOS platform-tag mappings
# ------------------------------------------------------------------

# ARM64 (Apple Silicon)
_ARM64_PLATFORMS: set[str] = {
    "macosx_arm64",
    "macosx_11_0_arm64",
    "macosx_12_0_arm64",
    "macosx_13_0_arm64",
    "macosx_14_0_arm64",
    "macosx_15_0_arm64",
}

# x86_64 (Intel)
_X86_64_PLATFORMS: set[str] = {
    "macosx_10_6_x86_64",
    "macosx_10_7_x86_64",
    "macosx_10_8_x86_64",
    "macosx_10_9_x86_64",
    "macosx_10_10_x86_64",
    "macosx_10_11_x86_64",
    "macosx_10_12_x86_64",
    "macosx_10_13_x86_64",
    "macosx_10_14_x86_64",
    "macosx_10_15_x86_64",
    "macosx_11_0_x86_64",
    "macosx_12_0_x86_64",
    "macosx_13_0_x86_64",
    "macosx_14_0_x86_64",
    "macosx_15_0_x86_64",
}

# Universal2 binaries work on both architectures
_UNIVERSAL_PLATFORMS: set[str] = {
    "macosx_10_9_universal2",
    "macosx_10_10_universal2",
    "macosx_11_0_universal2",
    "macosx_12_0_universal2",
    "macosx_13_0_universal2",
    "macosx_14_0_universal2",
    "macosx_15_0_universal2",
}

# Intel (i386 / older 32-bit)
_I386_PLATFORMS: set[str] = {
    "macosx_10_6_intel",
    "macosx_10_9_intel",
    "macosx_10_10_intel",
    "macosx_10_11_intel",
}


class WheelChecker:
    """Utility for parsing wheel filenames and checking platform compatibility.

    The checker understands macOS platform tags for both Apple Silicon
    (``arm64``) and Intel (``x86_64`` / ``universal2``) wheels.
    """

    def check_wheel_filename(
        self,
        wheel_filename: str,
        arch: Architecture,
    ) -> dict:
        """Check whether *wheel_filename* is compatible with *arch*.

        Returns a dict with:
        - ``compatible`` (bool)
        - ``wheel_name`` (str)
        - ``platform_tag`` (str)
        - ``expected_arch`` (str)
        - ``reason`` (str) - human-readable explanation when incompatible
        """
        parsed = self.parse_wheel_filename(wheel_filename)

        if not parsed:
            return {
                "compatible": False,
                "wheel_name": wheel_filename,
                "platform_tag": "",
                "expected_arch": arch.value if hasattr(arch, "value") else str(arch),
                "reason": f"Cannot parse wheel filename: {wheel_filename}",
            }

        platform_tag = parsed["platform_tag"]

        # Pure Python wheels are always compatible
        if platform_tag == "any":
            return {
                "compatible": True,
                "wheel_name": wheel_filename,
                "platform_tag": platform_tag,
                "expected_arch": arch.value if hasattr(arch, "value") else str(arch),
                "reason": "",
            }

        expected_arch = arch.value if hasattr(arch, "value") else str(arch)

        # Determine the compatibility set based on requested arch
        if expected_arch == Architecture.ARM64 or expected_arch == "arm64":
            compatible_set = _ARM64_PLATFORMS | _UNIVERSAL_PLATFORMS
        elif expected_arch == Architecture.X86_64 or expected_arch == "x86_64":
            compatible_set = _X86_64_PLATFORMS | _UNIVERSAL_PLATFORMS | _I386_PLATFORMS
        else:
            # Unknown arch - accept anything non-platform-specific
            compatible_set = _ARM64_PLATFORMS | _X86_64_PLATFORMS | _UNIVERSAL_PLATFORMS

        # The platform tag in the filename may contain multiple tags
        # separated by ``.``
        tags = platform_tag.split(".")

        for tag in tags:
            if tag in compatible_set:
                return {
                    "compatible": True,
                    "wheel_name": wheel_filename,
                    "platform_tag": tag,
                    "expected_arch": expected_arch,
                    "reason": "",
                }

        # Build a helpful reason string
        reason = self.classify_incompatibility(wheel_filename, arch) or (
            f"Platform tag '{platform_tag}' is not compatible with {expected_arch}"
        )

        return {
            "compatible": False,
            "wheel_name": wheel_filename,
            "platform_tag": platform_tag,
            "expected_arch": expected_arch,
            "reason": reason,
        }

    def parse_wheel_filename(self, filename: str) -> dict | None:
        """Extract components from a wheel filename.

        Returns a dict with keys ``dist``, ``version``, ``build``,
        ``python_tag``, ``abi_tag``, ``platform_tag`` - or ``None`` if the
        filename does not match PEP 427.
        """
        match = _WHEEL_RE.match(filename)
        if not match:
            return None
        return {
            "dist": match.group("dist"),
            "version": match.group("ver"),
            "build": match.group("build") or "",
            "python_tag": match.group("pytag"),
            "abi_tag": match.group("abi"),
            "platform_tag": match.group("plat"),
        }

    def get_compatible_tags(
        self,
        arch: Architecture,
        python_version: str = "cp311",
    ) -> list[str]:
        """Return an ordered list of platform tags compatible with *arch*.

        Tags are returned from most-specific to least-specific so that a
        caller can iterate and pick the first match.
        """
        if arch == Architecture.ARM64 or arch == "arm64":
            return sorted(_ARM64_PLATFORMS | _UNIVERSAL_PLATFORMS, reverse=True)
        if arch == Architecture.X86_64 or arch == "x86_64":
            return sorted(_X86_64_PLATFORMS | _UNIVERSAL_PLATFORMS | _I386_PLATFORMS, reverse=True)

        # Fallback: return all known macOS tags
        return sorted(
            _ARM64_PLATFORMS | _X86_64_PLATFORMS | _UNIVERSAL_PLATFORMS | _I386_PLATFORMS,
            reverse=True,
        )

    def classify_incompatibility(
        self,
        wheel_filename: str,
        arch: Architecture,
    ) -> str | None:
        """Return a human-readable reason for incompatibility, or ``None`` if compatible."""
        parsed = self.parse_wheel_filename(wheel_filename)
        if not parsed:
            return f"Invalid wheel filename: {wheel_filename}"

        platform_tag = parsed["platform_tag"]
        if platform_tag == "any":
            return None

        expected_arch = arch.value if hasattr(arch, "value") else str(arch)
        tags = platform_tag.split(".")

        arm_only = _ARM64_PLATFORMS - _UNIVERSAL_PLATFORMS
        x86_only = _X86_64_PLATFORMS | _I386_PLATFORMS

        if expected_arch in (Architecture.ARM64, "arm64"):
            if any(t in x86_only for t in tags) and not any(
                t in (_ARM64_PLATFORMS | _UNIVERSAL_PLATFORMS) for t in tags
            ):
                return (
                    f"Wheel '{wheel_filename}' is built for x86_64 (Intel) but "
                    f"the target architecture is {expected_arch} (Apple Silicon). "
                    f"Install Rosetta 2 or use a universal2 / arm64 wheel."
                )
        elif expected_arch in (Architecture.X86_64, "x86_64"):
            if any(t in arm_only for t in tags) and not any(
                t in (_X86_64_PLATFORMS | _UNIVERSAL_PLATFORMS) for t in tags
            ):
                return (
                    f"Wheel '{wheel_filename}' is built for arm64 (Apple Silicon) but "
                    f"the target architecture is {expected_arch} (Intel). "
                    f"Use a universal2 or x86_64 wheel."
                )

        # Check if *any* tag matches
        if expected_arch in (Architecture.ARM64, "arm64"):
            compat_set = _ARM64_PLATFORMS | _UNIVERSAL_PLATFORMS
        else:
            compat_set = _X86_64_PLATFORMS | _UNIVERSAL_PLATFORMS | _I386_PLATFORMS

        if not any(t in compat_set for t in tags):
            return (
                f"Wheel '{wheel_filename}' has platform tag '{platform_tag}' "
                f"which is not compatible with {expected_arch}"
            )

        return None

    def is_pure_python_wheel(self, wheel_filename: str) -> bool:
        """Return ``True`` when *wheel_filename* has a platform tag of ``any``."""
        parsed = self.parse_wheel_filename(wheel_filename)
        if not parsed:
            return False
        return parsed["platform_tag"] == "any"
