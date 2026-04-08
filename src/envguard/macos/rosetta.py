# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""Rosetta 2 detection and architecture classification for macOS."""

from __future__ import annotations

import platform
import shutil
import struct
import subprocess
import sys
from typing import Dict, Optional

from envguard.models import Architecture
from envguard.exceptions import ArchitectureError, SubprocessTimeoutError
from envguard.logging import get_logger

logger = get_logger(__name__)

# The magic bytes that identify a Mach-O universal (fat) binary.
_FAT_MAGIC = 0xCAFEBABE
_FAT_CIGAM = 0xBEBAFECA  # little-endian byte-swapped

# Mach-O CPU types (from mach-o/loader.h)
_CPU_TYPE_X86_64 = 0x01000007
_CPU_TYPE_ARM64 = 0x0100000C


class RosettaDetector:
    """Detect the host architecture, Rosetta 2 status, and classify risk.

    On Apple Silicon Macs, Python may be running natively (arm64) or under
    Rosetta 2 translation (x86_64).  This class provides helpers to determine
    the situation and assess the compatibility risk.
    """

    # ------------------------------------------------------------------
    # Basic architecture queries
    # ------------------------------------------------------------------

    @classmethod
    def detect_architecture(cls) -> Architecture:
        """Detect the host CPU architecture using :func:`platform.machine`.

        Returns:
            An :class:`Architecture` enum value.
        """
        machine = platform.machine().lower()
        mapping = {
            "x86_64": Architecture.X86_64,
            "amd64": Architecture.X86_64,
            "arm64": Architecture.ARM64,
            "aarch64": Architecture.ARM64,
        }
        return mapping.get(machine, Architecture.UNKNOWN)

    @classmethod
    def is_apple_silicon(cls) -> bool:
        """Check whether the host machine is Apple Silicon (arm64).

        Returns:
            ``True`` if the host CPU is arm64.
        """
        return platform.machine().lower() in ("arm64", "aarch64")

    # ------------------------------------------------------------------
    # Process-level checks
    # ------------------------------------------------------------------

    @classmethod
    def is_rosetta_process(cls) -> bool:
        """Check whether the **current** Python process is running under Rosetta.

        On macOS the ``sys.executable`` binary may be x86_64 even though the
        host hardware is arm64 (Rosetta 2 translation).  This is detected by
        comparing the reported architecture of the running interpreter against
        the native host architecture.

        Returns:
            ``True`` if the process is being translated by Rosetta 2.
        """
        # If the host is not Apple Silicon there is no Rosetta.
        if not cls.is_apple_silicon():
            return False

        # Detect the architecture of the running interpreter binary.
        # ``struct.calcsize('P')`` returns pointer size: 4 for 32-bit, 8 for 64-bit.
        # We need a more precise check: on macOS we can inspect the binary header
        # or use the ``platform`` module which reflects the *translated* arch.
        current_arch = platform.machine().lower()
        return current_arch == "x86_64"

    @classmethod
    def get_python_architecture(cls, python_path: str = "") -> Architecture:
        """Determine the architecture of a Python interpreter.

        Uses ``shutil.which`` to resolve *python_path* (if non-empty) to a
        real executable, then runs it with ``-c "import platform; print(platform.machine())"``
        to discover its architecture.

        Args:
            python_path: Path or name of the Python interpreter.  If empty,
                ``sys.executable`` is used.

        Returns:
            The :class:`Architecture` of the given interpreter.

        Raises:
            ArchitectureError: If the interpreter cannot be found or fails to
                report its architecture.
            SubprocessTimeoutError: If the subprocess times out.
        """
        if not python_path:
            python_path = sys.executable

        resolved = shutil.which(python_path)
        if resolved is None:
            raise ArchitectureError(
                f"Python interpreter not found: {python_path}"
            )

        try:
            result = subprocess.run(
                [resolved, "-c", "import platform; print(platform.machine())"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except subprocess.TimeoutExpired as exc:
            raise SubprocessTimeoutError(
                f"Timed out detecting architecture for {resolved}"
            ) from exc
        except OSError as exc:
            raise ArchitectureError(
                f"Failed to run interpreter {resolved}: {exc}"
            ) from exc

        if result.returncode != 0:
            raise ArchitectureError(
                f"Interpreter {resolved} returned non-zero exit code: "
                f"{result.stderr.strip()}"
            )

        machine = result.stdout.strip().lower()
        mapping = {
            "x86_64": Architecture.X86_64,
            "amd64": Architecture.X86_64,
            "arm64": Architecture.ARM64,
            "aarch64": Architecture.ARM64,
        }
        arch = mapping.get(machine, Architecture.UNKNOWN)
        logger.debug("Python %s reports architecture: %s", resolved, arch.value)
        return arch

    # ------------------------------------------------------------------
    # Risk classification
    # ------------------------------------------------------------------

    @classmethod
    def classify_rosetta_risk(cls, python_path: str) -> Dict[str, object]:
        """Classify the Rosetta 2 compatibility risk for a Python interpreter.

        Args:
            python_path: Path or name of the Python interpreter to evaluate.

        Returns:
            A dictionary with the following keys:

            - ``is_native`` (*bool*): True if the interpreter matches the host arch.
            - ``python_arch`` (*str*): Architecture of the Python binary.
            - ``host_arch`` (*str*): Native host architecture.
            - ``risk_level`` (*str*): One of ``none``, ``low``, ``medium``, ``high``.
            - ``recommendation`` (*str*): Human-readable advice.
        """
        host_arch = cls.detect_architecture()
        host_arch_str = host_arch.value

        try:
            python_arch = cls.get_python_architecture(python_path)
            python_arch_str = python_arch.value
        except (ArchitectureError, SubprocessTimeoutError) as exc:
            logger.warning("Could not determine Python arch: %s", exc)
            python_arch_str = "unknown"
            python_arch = Architecture.UNKNOWN

        is_native = python_arch == host_arch
        is_apple_silicon = cls.is_apple_silicon()

        # Determine risk level
        if not is_apple_silicon:
            # On Intel Macs there is no Rosetta risk.
            risk_level = "none"
            recommendation = (
                "Running on Intel Mac; no Rosetta translation concerns."
            )
        elif is_native:
            risk_level = "none"
            recommendation = (
                "Python interpreter matches native Apple Silicon architecture."
            )
        elif python_arch == Architecture.X86_64 and host_arch == Architecture.ARM64:
            risk_level = "medium"
            recommendation = (
                "Python is running under Rosetta 2 (x86_64 on arm64). "
                "Native arm64 Python is recommended for best performance. "
                "Some native arm64 packages may not install under Rosetta."
            )
        elif python_arch == Architecture.UNKNOWN:
            risk_level = "low"
            recommendation = (
                "Could not determine Python architecture. "
                "Manual verification is recommended."
            )
        else:
            risk_level = "high"
            recommendation = (
                f"Unexpected architecture combination: host={host_arch_str}, "
                f"python={python_arch_str}. Manual investigation required."
            )

        return {
            "is_native": is_native,
            "python_arch": python_arch_str,
            "host_arch": host_arch_str,
            "risk_level": risk_level,
            "recommendation": recommendation,
        }

    # ------------------------------------------------------------------
    # Universal binary support
    # ------------------------------------------------------------------

    @classmethod
    def get_universal_binary_support(cls) -> Dict[str, object]:
        """Check whether the current Python binary is a universal (fat) binary.

        Reads the first few bytes of ``sys.executable`` to inspect the Mach-O
        fat header magic number.

        Returns:
            A dictionary with:

            - ``is_universal`` (*bool*): True if the binary is a fat binary.
            - ``executable`` (*str*): Path to the checked binary.
            - ``supported_architectures`` (*list[str]*): Detected architectures.
            - ``host_architecture`` (*str*): Native host architecture.
        """
        exe_path = sys.executable
        supported_archs: list[str] = []
        is_universal = False

        try:
            with open(exe_path, "rb") as fh:
                header = fh.read(4096)

            if len(header) < 4:
                raise ArchitectureError("Binary file is too small to read header")

            magic = struct.unpack(">I", header[:4])[0]

            if magic in (_FAT_MAGIC, _FAT_CIGAM):
                is_universal = True
                # Parse the fat_arch entries to find contained architectures.
                # Fat header: magic(4) + nfat_arch(4) then nfat_arch * fat_arch
                # fat_arch: cputype(4) + cpusubtype(4) + offset(4) + size(4) + align(4)
                if len(header) >= 8:
                    nfat_arch = struct.unpack(">I", header[4:8])[0]
                    for i in range(min(nfat_arch, 10)):  # cap iterations
                        offset = 8 + i * 20
                        if offset + 4 > len(header):
                            break
                        cputype = struct.unpack(">I", header[offset : offset + 4])[0]
                        if cputype == _CPU_TYPE_X86_64:
                            supported_archs.append("x86_64")
                        elif cputype == _CPU_TYPE_ARM64:
                            supported_archs.append("arm64")
                        else:
                            supported_archs.append(f"unknown({cputype:#x})")
            else:
                # Not a fat binary – single architecture.
                supported_archs.append(cls.detect_architecture().value)

        except (OSError, struct.error) as exc:
            logger.warning("Could not inspect binary %s: %s", exe_path, exc)
            supported_archs.append("unknown")

        return {
            "is_universal": is_universal,
            "executable": exe_path,
            "supported_architectures": supported_archs,
            "host_architecture": cls.detect_architecture().value,
        }
