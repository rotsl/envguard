# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""Tests for envguard custom exceptions."""

from __future__ import annotations

from envguard.exceptions import (
    ArchitectureError,
    BrokenEnvironmentError,
    CudaNotSupportedOnMacosError,
    DependencyConflictError,
    EnvguardError,
    EnvironmentCreationError,
    HashAlgorithmError,
    IncompatibleWheelError,
    InstallationError,
    NetworkUnavailableError,
    PackageManagerNotFoundError,
    PlatformNotSupportedError,
    PreflightError,
    RepairError,
    SubprocessTimeoutError,
    TrustError,
    VerificationError,
    XcodeError,
)


class TestEnvguardError:
    """Base exception tests."""

    def test_default_message(self):
        err = EnvguardError()
        assert str(err) == ""

    def test_custom_message(self):
        err = EnvguardError("something went wrong")
        assert str(err) == "something went wrong"

    def test_details_attribute(self):
        err = EnvguardError("msg", "extra details")
        assert err.message == "msg"
        assert err.details == "extra details"

    def test_inheritance(self):
        assert issubclass(EnvguardError, Exception)


class TestPlatformNotSupportedError:

    def test_default_message(self):
        err = PlatformNotSupportedError(platform="Linux")
        assert "Linux" in str(err)
        assert "not supported" in str(err)

    def test_custom_message(self):
        err = PlatformNotSupportedError(message="Custom platform error")
        assert str(err) == "Custom platform error"

    def test_platform_attribute(self):
        err = PlatformNotSupportedError(platform="Windows")
        assert err.platform == "Windows"


class TestCudaNotSupportedOnMacosError:

    def test_default_message(self):
        err = CudaNotSupportedOnMacosError()
        assert "CUDA" in str(err)
        assert "macOS" in str(err)
        assert "MPS" in str(err)

    def test_custom_message(self):
        err = CudaNotSupportedOnMacosError("Custom CUDA error")
        assert str(err) == "Custom CUDA error"


class TestIncompatibleWheelError:

    def test_default_message(self):
        err = IncompatibleWheelError(
            wheel_name="numpy-1.24.0-cp311-cp311-macosx_10_9_x86_64.whl",
            expected_arch="arm64",
            actual_arch="x86_64",
        )
        assert "numpy" in str(err)
        assert "arm64" in str(err)
        assert "x86_64" in str(err)

    def test_attributes(self):
        err = IncompatibleWheelError(wheel_name="test.whl", expected_arch="a", actual_arch="b")
        assert err.wheel_name == "test.whl"
        assert err.expected_arch == "a"
        assert err.actual_arch == "b"


class TestDependencyConflictError:

    def test_default_message(self):
        err = DependencyConflictError(packages="numpy>=1.24 vs numpy<1.23")
        assert "numpy" in str(err)
        assert "conflict" in str(err)

    def test_packages_attribute(self):
        err = DependencyConflictError(packages="pkg-a vs pkg-b")
        assert err.packages == "pkg-a vs pkg-b"


class TestBrokenEnvironmentError:

    def test_default_message(self):
        err = BrokenEnvironmentError(env_path="/tmp/.venv", reason="missing pip")
        assert "/tmp/.venv" in str(err)
        assert "missing pip" in str(err)

    def test_attributes(self):
        err = BrokenEnvironmentError(env_path="/path", reason="corrupt")
        assert err.env_path == "/path"
        assert err.reason == "corrupt"


class TestRepairError:

    def test_default_message(self):
        err = RepairError(operation="recreate_environment", reason="disk full")
        assert "recreate_environment" in str(err)
        assert "disk full" in str(err)

    def test_attributes(self):
        err = RepairError(operation="fix", reason="fail")
        assert err.operation == "fix"
        assert err.reason == "fail"


class TestPreflightError:

    def test_default_message(self):
        err = PreflightError(findings_count=3)
        assert "3" in str(err)
        assert "critical" in str(err)

    def test_custom_message(self):
        err = PreflightError(message="Custom preflight error")
        assert str(err) == "Custom preflight error"


class TestNetworkUnavailableError:

    def test_default_message(self):
        err = NetworkUnavailableError()
        assert "Network" in str(err)

    def test_custom_message(self):
        err = NetworkUnavailableError("No internet")
        assert str(err) == "No internet"


class TestVerificationError:

    def test_default_message(self):
        err = VerificationError()
        assert "verification" in str(err).lower()


class TestPackageManagerNotFoundError:

    def test_default_message(self):
        err = PackageManagerNotFoundError(manager_name="conda")
        assert "conda" in str(err)
        assert "not found" in str(err)

    def test_attribute(self):
        err = PackageManagerNotFoundError(manager_name="mamba")
        assert err.manager_name == "mamba"


class TestOtherExceptions:

    def test_architecture_error(self):
        err = ArchitectureError("arch mismatch")
        assert str(err) == "arch mismatch"

    def test_subprocess_timeout(self):
        err = SubprocessTimeoutError("pip timed out")
        assert str(err) == "pip timed out"

    def test_trust_error(self):
        err = TrustError("domain not trusted")
        assert str(err) == "domain not trusted"

    def test_installation_error(self):
        err = InstallationError("install failed")
        assert str(err) == "install failed"

    def test_hash_algorithm_error(self):
        err = HashAlgorithmError("md5 not supported")
        assert str(err) == "md5 not supported"

    def test_xcode_error(self):
        err = XcodeError("clt missing")
        assert str(err) == "clt missing"

    def test_environment_creation_error(self):
        err = EnvironmentCreationError(env_path="/path", reason="no space")
        assert "/path" in str(err)
        assert err.env_path == "/path"

    def test_all_are_envguard_errors(self):
        """Every custom exception must be a subclass of EnvguardError."""
        exceptions = [
            PlatformNotSupportedError(),
            CudaNotSupportedOnMacosError(),
            IncompatibleWheelError(),
            DependencyConflictError(),
            BrokenEnvironmentError(),
            EnvironmentCreationError(),
            RepairError(),
            PreflightError(),
            NetworkUnavailableError(),
            PackageManagerNotFoundError(),
            ArchitectureError(),
            SubprocessTimeoutError(),
            VerificationError(),
            TrustError(),
            InstallationError(),
            HashAlgorithmError(),
            XcodeError(),
        ]
        for exc in exceptions:
            assert isinstance(exc, EnvguardError), f"{type(exc).__name__} is not an EnvguardError"
