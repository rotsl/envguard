# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""PyPI JSON API-based dependency resolver.

Resolves a set of loose requirements to a fully-pinned list by querying
the PyPI JSON API.  Uses a greedy BFS with conflict detection.
"""

from __future__ import annotations

import sys
from collections import deque
from typing import Any

import requests
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import Version

from envguard.exceptions import DependencyConflictError, NetworkUnavailableError
from envguard.logging import get_logger
from envguard.models import ResolvedPackage

logger = get_logger(__name__)

PYPI_JSON_URL = "https://pypi.org/pypi/{name}/json"
PYPI_VERSION_URL = "https://pypi.org/pypi/{name}/{version}/json"
MAX_DEPTH = 12
_REQUEST_TIMEOUT = 15


class PyPIResolver:
    """Resolve a list of PEP 508 requirements to a pinned set.

    Queries the PyPI JSON API to find the latest version of each package
    that satisfies all accumulated constraints, then recurses into
    transitive dependencies.

    Args:
        python_version: Target Python version string (e.g. ``"3.11"``).
            Defaults to the running interpreter's version.
        index_url: Override the PyPI index URL base.
        session: Optional pre-configured ``requests.Session``.
    """

    def __init__(
        self,
        python_version: str | None = None,
        index_url: str = "https://pypi.org",
        session: requests.Session | None = None,
    ) -> None:
        self._python_version = python_version or "{}.{}".format(*sys.version_info[:2])
        self._index_url = index_url.rstrip("/")
        self._session = session or requests.Session()
        self._session.headers["User-Agent"] = "envguard/0.1.0 (pip-resolver)"
        self._pypi_cache: dict[str, dict[str, Any]] = {}
        self._version_cache: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(self, requirements: list[str]) -> list[ResolvedPackage]:
        """Resolve *requirements* to a fully-pinned list.

        Args:
            requirements: PEP 508 requirement strings (e.g. ``["requests>=2.28"]``).

        Returns:
            Ordered list of :class:`~envguard.models.ResolvedPackage` objects,
            one per resolved package (including transitive dependencies).

        Raises:
            DependencyConflictError: If no version satisfies all constraints.
            NetworkUnavailableError: If the PyPI API cannot be reached.
        """
        pinned: dict[str, ResolvedPackage] = {}
        constraints: dict[str, SpecifierSet] = {}
        work_queue: deque[tuple[str, int]] = deque()

        for req_str in requirements:
            work_queue.append((req_str, 0))

        visited_pairs: set[tuple[str, str]] = set()

        while work_queue:
            req_str, depth = work_queue.popleft()

            if depth > MAX_DEPTH:
                logger.warning("Max resolution depth reached for: %s", req_str)
                continue

            try:
                req = Requirement(req_str)
            except Exception as exc:
                logger.warning("Skipping invalid requirement %r: %s", req_str, exc)
                continue

            # Evaluate environment markers
            if req.marker and not req.marker.evaluate(self._marker_env()):
                logger.debug("Skipping %s (marker not satisfied)", req_str)
                continue

            name = canonicalize_name(req.name)

            # Merge specifier into accumulated constraints
            existing = constraints.get(name, SpecifierSet())
            merged = SpecifierSet(
                str(existing) + "," + str(req.specifier) if str(existing) else str(req.specifier)
            )
            constraints[name] = merged

            # De-duplicate (name, specifier) pairs to avoid infinite loops
            key = (name, str(merged))
            if key in visited_pairs:
                continue
            visited_pairs.add(key)

            # If already pinned and pin still satisfies updated constraints, skip
            if name in pinned:
                if Version(pinned[name].version) in merged:
                    continue
                # Conflict with current pin — need to re-resolve
                logger.debug(
                    "Constraint update for %s (%s) invalidates pin %s — re-resolving",
                    name,
                    merged,
                    pinned[name].version,
                )
                del pinned[name]

            # Fetch PyPI metadata
            try:
                meta = self._fetch_package_meta(name)
            except NetworkUnavailableError:
                raise
            except Exception as exc:
                logger.warning("Could not fetch metadata for %s: %s", name, exc)
                continue

            version = self._select_version(meta, merged)
            if version is None:
                raise DependencyConflictError(
                    packages=name,
                    message=(
                        f"No version of '{name}' satisfies constraints {merged}. "
                        f"Available: {', '.join(sorted(meta.get('releases', {}).keys())[:10])}"
                    ),
                )

            # Fetch per-version metadata for requires_dist
            try:
                ver_meta = self._fetch_version_meta(name, version)
            except Exception as exc:
                logger.warning(
                    "Could not fetch version metadata for %s==%s: %s", name, version, exc
                )
                ver_meta = {}

            info = ver_meta.get("info", {})
            requires_dist: list[str] = info.get("requires_dist") or []
            requires_python: str | None = info.get("requires_python") or None

            pkg = ResolvedPackage(
                name=name,
                version=version,
                normalized_name=name,
                specifier=f"{name}=={version}",
                requires_dist=requires_dist,
                requires_python=requires_python,
                extras=sorted(req.extras),
            )
            pinned[name] = pkg
            logger.debug("Resolved %s==%s", name, version)

            # Enqueue transitive dependencies
            for dep_str in requires_dist:
                try:
                    dep = Requirement(dep_str)
                except Exception:
                    continue
                if dep.marker and not dep.marker.evaluate(self._marker_env()):
                    continue
                # Only follow extras that we requested
                if dep.extras and not (dep.extras & req.extras):
                    continue
                work_queue.append((str(dep), depth + 1))

        return list(pinned.values())

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _marker_env(self) -> dict[str, str]:
        """Build a PEP 508 marker environment dict for the current Python."""
        major, minor = self._python_version.split(".")[:2]
        return {
            "python_version": f"{major}.{minor}",
            "python_full_version": self._python_version,
            "sys_platform": sys.platform,
            "platform_system": sys.platform.capitalize(),
            "implementation_name": "cpython",
            "extra": "",
        }

    def _fetch_package_meta(self, name: str) -> dict[str, Any]:
        """Fetch and cache the PyPI /pypi/{name}/json response."""
        if name in self._pypi_cache:
            return self._pypi_cache[name]

        url = f"{self._index_url}/pypi/{name}/json"
        try:
            resp = self._session.get(url, timeout=_REQUEST_TIMEOUT)
        except requests.ConnectionError as exc:
            raise NetworkUnavailableError(f"Cannot reach PyPI ({self._index_url}): {exc}") from exc

        if resp.status_code == 404:
            raise ValueError(f"Package '{name}' not found on PyPI")
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        self._pypi_cache[name] = data
        return data

    def _fetch_version_meta(self, name: str, version: str) -> dict[str, Any]:
        """Fetch and cache per-version metadata."""
        cache_key = f"{name}=={version}"
        if cache_key in self._version_cache:
            return self._version_cache[cache_key]

        url = f"{self._index_url}/pypi/{name}/{version}/json"
        try:
            resp = self._session.get(url, timeout=_REQUEST_TIMEOUT)
        except requests.ConnectionError as exc:
            raise NetworkUnavailableError(str(exc)) from exc

        if resp.status_code == 404:
            # Fall back to top-level cached metadata
            return self._pypi_cache.get(name, {})
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        self._version_cache[cache_key] = data
        return data

    def _select_version(self, meta: dict[str, Any], specifier: SpecifierSet) -> str | None:
        """Select the best (highest non-yanked) version satisfying *specifier*."""
        releases: dict[str, list[dict[str, Any]]] = meta.get("releases", {})
        python_requires_str: str | None = meta.get("info", {}).get("requires_python")
        python_requires = SpecifierSet(python_requires_str) if python_requires_str else None
        current_python = Version(self._python_version)

        candidates: list[Version] = []
        for ver_str, files in releases.items():
            try:
                v = Version(ver_str)
            except Exception:
                continue
            # Skip pre-releases unless the specifier explicitly allows them
            if v.is_prerelease and not specifier.prereleases:
                continue
            # Skip yanked releases (all files yanked)
            if files and all(f.get("yanked") for f in files):
                continue
            # Must satisfy requested constraints
            if v not in specifier:
                continue
            # Must satisfy package's requires-python
            if python_requires and current_python not in python_requires:
                continue
            candidates.append(v)

        if not candidates:
            return None
        return str(max(candidates))
