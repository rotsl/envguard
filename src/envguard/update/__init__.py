# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""Update management: checking, downloading, verifying, and rollback."""

from envguard.update.updater import UpdateManager
from envguard.update.manifest import ManifestParser
from envguard.update.verifier import UpdateVerifier
from envguard.update.rollback import RollbackManager

__all__ = [
    "UpdateManager",
    "ManifestParser",
    "UpdateVerifier",
    "RollbackManager",
]
