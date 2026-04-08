# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""Update management: checking, downloading, verifying, and rollback."""

from envguard.update.manifest import ManifestParser
from envguard.update.rollback import RollbackManager
from envguard.update.updater import UpdateManager
from envguard.update.verifier import UpdateVerifier

__all__ = [
    "ManifestParser",
    "RollbackManager",
    "UpdateManager",
    "UpdateVerifier",
]
