# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""Environment resolution backends and dependency management tools."""

from envguard.resolver.base import BaseResolver
from envguard.resolver.pip_backend import PipBackend
from envguard.resolver.conda_backend import CondaBackend
from envguard.resolver.wheelcheck import WheelChecker
from envguard.resolver.markers import MarkerEvaluator
from envguard.resolver.inference import InferenceEngine

__all__ = [
    "BaseResolver",
    "PipBackend",
    "CondaBackend",
    "WheelChecker",
    "MarkerEvaluator",
    "InferenceEngine",
]
