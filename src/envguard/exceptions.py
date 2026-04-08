# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""Custom exception hierarchy for the envguard framework."""


class EnvguardError(Exception):
    """Base exception for all envguard errors."""

    def __init__(self, message: str = "", details: str = "") -> None:
        self.message = message
        self.details = details
        super().__init__(message)


class PlatformNotSupportedError(EnvguardError):
    """Raised when the current platform is not supported by the requested operation."""

    def __init__(self, platform: str = "", message: str = "") -> None:
        self.platform = platform
        msg = message or f"Platform '{platform}' is not supported for this operation."
        super().__init__(msg)


class CudaNotSupportedOnMacosError(EnvguardError):
    """Raised when a project requires CUDA but is running on macOS."""

    def __init__(self, message: str = "") -> None:
        msg = (
            message
            or "CUDA is not supported as a runtime target on macOS. Use CPU or Apple MPS instead."
        )
        super().__init__(msg)


class IncompatibleWheelError(EnvguardError):
    """Raised when an incompatible wheel would be installed."""

    def __init__(
        self,
        wheel_name: str = "",
        expected_arch: str = "",
        actual_arch: str = "",
        message: str = "",
    ) -> None:
        self.wheel_name = wheel_name
        self.expected_arch = expected_arch
        self.actual_arch = actual_arch
        msg = (
            message
            or f"Wheel '{wheel_name}' is incompatible: expected arch '{expected_arch}', got '{actual_arch}'."
        )
        super().__init__(msg)


class DependencyConflictError(EnvguardError):
    """Raised when dependency version conflicts are detected."""

    def __init__(self, packages: str = "", message: str = "") -> None:
        self.packages = packages
        msg = message or f"Dependency conflict detected involving: {packages}"
        super().__init__(msg)


class BrokenEnvironmentError(EnvguardError):
    """Raised when the target environment is in a broken or unusable state."""

    def __init__(self, env_path: str = "", reason: str = "", message: str = "") -> None:
        self.env_path = env_path
        self.reason = reason
        msg = message or f"Environment at '{env_path}' is broken: {reason}"
        super().__init__(msg)


class EnvironmentCreationError(EnvguardError):
    """Raised when environment creation fails."""

    def __init__(self, env_path: str = "", reason: str = "", message: str = "") -> None:
        self.env_path = env_path
        self.reason = reason
        msg = message or f"Failed to create environment at '{env_path}': {reason}"
        super().__init__(msg)


class RepairError(EnvguardError):
    """Raised when an automated repair operation fails."""

    def __init__(self, operation: str = "", reason: str = "", message: str = "") -> None:
        self.operation = operation
        self.reason = reason
        msg = message or f"Repair operation '{operation}' failed: {reason}"
        super().__init__(msg)


class PreflightError(EnvguardError):
    """Raised when preflight checks fail critically."""

    def __init__(self, findings_count: int = 0, message: str = "") -> None:
        self.findings_count = findings_count
        msg = message or f"Preflight failed with {findings_count} critical finding(s)."
        super().__init__(msg)


class NetworkUnavailableError(EnvguardError):
    """Raised when network access is required but unavailable."""

    def __init__(self, message: str = "") -> None:
        msg = message or "Network access is required but currently unavailable."
        super().__init__(msg)


class PackageManagerNotFoundError(EnvguardError):
    """Raised when a required package manager is not found."""

    def __init__(self, manager_name: str = "", message: str = "") -> None:
        self.manager_name = manager_name
        msg = message or f"Package manager '{manager_name}' not found on PATH."
        super().__init__(msg)


class ArchitectureError(EnvguardError):
    """Raised when there is an architecture mismatch or detection failure."""

    def __init__(self, message: str = "") -> None:
        msg = message or "Architecture detection or compatibility error."
        super().__init__(msg)


class SubprocessTimeoutError(EnvguardError):
    """Raised when a subprocess command times out."""

    def __init__(self, message: str = "") -> None:
        msg = message or "Subprocess command timed out."
        super().__init__(msg)


class VerificationError(EnvguardError):
    """Raised when signature or hash verification fails."""

    def __init__(self, message: str = "") -> None:
        msg = message or "Signature or hash verification failed."
        super().__init__(msg)


class TrustError(EnvguardError):
    """Raised when a trust check fails."""

    def __init__(self, message: str = "") -> None:
        msg = message or "Trust check failed."
        super().__init__(msg)


class InstallationError(EnvguardError):
    """Raised when installation fails."""

    def __init__(self, message: str = "") -> None:
        msg = message or "Installation failed."
        super().__init__(msg)


class HashAlgorithmError(EnvguardError):
    """Raised when an unsupported hash algorithm is requested."""

    def __init__(self, message: str = "") -> None:
        msg = message or "Unsupported hash algorithm."
        super().__init__(msg)


class XcodeError(EnvguardError):
    """Raised when Xcode/CLT detection or interaction fails."""

    def __init__(self, message: str = "") -> None:
        msg = message or "Xcode or Command Line Tools error."
        super().__init__(msg)
