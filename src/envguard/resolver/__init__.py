# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""Environment resolution backends and dependency management tools."""

from envguard.resolver.base import BaseResolver
from envguard.resolver.conda_backend import CondaBackend
from envguard.resolver.inference import InferenceEngine
from envguard.resolver.markers import MarkerEvaluator
from envguard.resolver.pip_backend import PipBackend
from envguard.resolver.pypi_resolver import PyPIResolver
from envguard.resolver.uv_backend import UvBackend
from envguard.resolver.wheelcheck import WheelChecker

__all__ = [
    "BaseResolver",
    "CondaBackend",
    "InferenceEngine",
    "MarkerEvaluator",
    "PipBackend",
    "PyPIResolver",
    "UvBackend",
    "WheelChecker",
]
