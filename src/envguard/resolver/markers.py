# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""PEP 508 environment marker evaluation."""

from __future__ import annotations

import operator
import platform
import re
import sys

try:
    from envguard.logging import get_logger
except ImportError:
    import logging

    def get_logger(name: str) -> logging.Logger:  # type: ignore[misc]
        return logging.getLogger(name)


logger = get_logger(__name__)


def _looks_like_version(s: str) -> bool:
    """Return True if *s* looks like a version string (e.g. '3.11.2')."""
    return bool(s) and all(part.isdigit() for part in s.split(".") if part)


def _version_tuple(s: str) -> tuple[int, ...]:
    """Convert a version string like '3.11.2' to a comparable tuple."""
    parts = []
    for part in s.split("."):
        try:
            parts.append(int(part))
        except ValueError:
            break
    return tuple(parts) if parts else (0,)


# Supported comparison operators (PEP 508)
_OPS: dict[str, type] = {
    "==": operator.eq,
    "!=": operator.ne,
    ">=": operator.ge,
    "<=": operator.le,
    ">": operator.gt,
    "<": operator.lt,
    "~=": lambda a, b: _compatible_release(a, b),  # PEP 440 compatible release
    "===": lambda a, b: str(a).strip("\"'") == str(b).strip("\"'"),  # PEP 440 arbitrary equality
}

# Regex for a simple marker expression:  <left> <op> <right>
_SIMPLE_MARKER_RE = re.compile(
    r"""^\s*"""
    r"""(?P<left>\w[\w.]*)\s*"""
    r"""(?P<op>===|~=|==|!=|>=|<=|>|<)\s*"""
    r"""(?P<quote>['"]?)(?P<right>[^'"]+)(?P=quote)\s*"""
    r"""$""",
)

# Regex for ``and`` / ``or`` compound markers
_COMPOUND_RE = re.compile(r"\s+(?:and|or)\s+", re.IGNORECASE)


class MarkerEvaluator:
    """Evaluate PEP 508 environment markers.

    This evaluator supports simple comparisons, compound markers joined
    with ``and``/``or``, and nested parentheses via :mod:`packaging.markers`
    when available.
    """

    def __init__(self) -> None:
        # Try to use packaging.markers for full PEP 508 support
        self._use_packaging = False
        try:
            from packaging import markers as _markers  # type: ignore[import-untyped]

            self._markers_module = _markers
            self._use_packaging = True
        except ImportError:
            self._markers_module = None  # type: ignore[assignment]

    def evaluate(self, marker: str, env: dict | None = None) -> bool:
        """Evaluate a PEP 508 *marker* string.

        Args:
            marker: A marker string such as ``"python_version >= '3.8'"`` or
                ``"sys_platform == 'darwin' and platform_machine == 'arm64'"``.
            env: Optional environment override dict.  When ``None``, the
                current system environment is used.

        Returns:
            ``True`` when the marker evaluates to true.
        """
        if not marker or not marker.strip():
            return True

        if env is None:
            env = self.get_default_environment()

        # Try packaging.markers first (handles full PEP 508 syntax)
        if self._use_packaging and self._markers_module is not None:
            try:
                return self._evaluate_with_packaging(marker, env)
            except Exception as exc:
                logger.debug("packaging.markers evaluation failed: %s - falling back", exc)

        # Fallback: our own implementation
        return self._evaluate_simple_marker(marker, env)

    def get_default_environment(self) -> dict:
        """Return a dict representing the current Python environment.

        Keys correspond to PEP 508 marker variables:
        ``os_name``, ``sys_platform``, ``platform_machine``,
        ``platform_python_implementation``, ``platform_release``,
        ``platform_system``, ``platform_version``, ``python_version``,
        ``python_full_version``, ``implementation_name``,
        ``implementation_version``.
        """
        return {
            "os_name": os_name(),
            "sys_platform": sys.platform,
            "platform_machine": platform.machine(),
            "platform_python_implementation": platform.python_implementation(),
            "platform_release": platform.release(),
            "platform_system": platform.system(),
            "platform_version": platform.version(),
            "python_version": ".".join(map(str, sys.version_info[:2])),
            "python_full_version": ".".join(map(str, sys.version_info[:3])),
            "implementation_name": sys.implementation.name,
            "implementation_version": ".".join(str(v) for v in sys.implementation.version[:3]),
        }

    def parse_marker(self, marker: str) -> dict:
        """Parse a marker expression and return its components.

        Returns a dict with:
        - ``raw`` (str): the original marker
        - ``type`` (str): ``"simple"`` or ``"compound"``
        - ``expressions`` (list[dict]): each sub-expression with
          ``left``, ``op``, ``right`` keys
        """
        if not marker or not marker.strip():
            return {"raw": marker, "type": "empty", "expressions": []}

        expressions: list[dict] = []
        parts = _COMPOUND_RE.split(marker)

        for part in parts:
            part = part.strip()
            if not part:
                continue

            m = _SIMPLE_MARKER_RE.match(part)
            if m:
                expressions.append(
                    {
                        "left": m.group("left"),
                        "op": m.group("op"),
                        "right": m.group("right"),
                    }
                )
            else:
                expressions.append({"raw": part, "parse_error": True})

        return {
            "raw": marker,
            "type": "compound" if len(expressions) > 1 else "simple",
            "expressions": expressions,
        }

    def evaluate_simple(self, left: str, op: str, right: str) -> bool:
        """Evaluate a single ``left op right`` comparison against the
        current environment.

        Version-like values (e.g. ``python_version``) are compared using
        numeric tuple comparison so that ``"3.12" >= "3.8"`` works correctly.

        Args:
            left: Marker variable name (e.g. ``"python_version"``).
            op: Comparison operator (e.g. ``">="``).
            right: Literal value (e.g. ``"3.8"``).

        Returns:
            Result of the comparison.
        """
        env = self.get_default_environment()
        left_val = env.get(left, left)
        right_val = right.strip("'\"")

        op_func = _OPS.get(op)
        if op_func is None:
            logger.warning("Unsupported marker operator: %s", op)
            return False

        # Use numeric comparison for version-like values
        left_str = str(left_val)
        right_str = str(right_val)

        if _looks_like_version(left_str) and _looks_like_version(right_str):
            left_cmp = _version_tuple(left_str)
            right_cmp = _version_tuple(right_str)
            return bool(op_func(left_cmp, right_cmp))

        return bool(op_func(left_str, right_str))

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _evaluate_with_packaging(self, marker: str, env: dict) -> bool:
        """Evaluate using the ``packaging.markers`` module."""
        from packaging.markers import Marker  # type: ignore[import-untyped]

        return Marker(marker).evaluate(env)

    def _evaluate_simple_marker(self, marker: str, env: dict) -> bool:
        """Evaluate marker string using our own simple parser."""
        # Handle compound markers with and/or
        # Split on top-level ``and`` / ``or`` (respecting parentheses)
        tokens = self._tokenize_compound(marker)
        if len(tokens) == 1:
            return self._eval_single(tokens[0].strip(), env)

        # Simple left-to-right evaluation (no precedence for and/or for
        # now - PEP 508 says ``and`` binds tighter than ``or``)
        # Split into or-groups first
        or_groups: list[list[str]] = [[]]
        for token in tokens:
            stripped = token.strip().lower()
            if stripped == "or":
                or_groups.append([])
            elif stripped == "and":
                # Continue current or-group, but next token is and-bonded
                continue
            else:
                or_groups[-1].append(token.strip())

        # Evaluate each or-group: all tokens must be True (and-bonded)
        return any(all(self._eval_single(t, env) for t in group) for group in or_groups)

    def _eval_single(self, expr: str, env: dict) -> bool:
        """Evaluate a single marker expression."""
        m = _SIMPLE_MARKER_RE.match(expr.strip())
        if not m:
            logger.debug("Cannot parse marker expression: %s", expr)
            return True  # If we can't parse it, don't block

        left = m.group("left")
        op = m.group("op")
        right = m.group("right")

        left_val = env.get(left, left)
        right_val = right.strip("'\"")

        op_func = _OPS.get(op)
        if op_func is None:
            return True  # Unknown operator - don't block

        try:
            return bool(op_func(str(left_val), str(right_val)))
        except Exception:
            return True

    @staticmethod
    def _tokenize_compound(marker: str) -> list[str]:
        """Split a marker on top-level ``and`` / ``or`` keywords,
        respecting parentheses."""
        tokens: list[str] = []
        depth = 0
        current: list[str] = []

        i = 0
        while i < len(marker):
            ch = marker[i]

            if ch == "(":
                depth += 1
                current.append(ch)
            elif ch == ")":
                depth -= 1
                current.append(ch)
            elif depth == 0 and marker[i : i + 4] in (" and ", " or "):
                # Check which keyword
                for kw in ("and", "or"):
                    prefix = f" {kw} "
                    if marker[i:].startswith(prefix):
                        tokens.append("".join(current).strip())
                        current = []
                        tokens.append(kw)
                        i += len(prefix) - 1
                        break
                else:
                    current.append(ch)
            else:
                current.append(ch)
            i += 1

        tail = "".join(current).strip()
        if tail:
            tokens.append(tail)

        return tokens


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def _compatible_release(version: str, spec: str) -> bool:
    """Implement PEP 440 ``~=`` (compatible release) operator.

    ``~=X.Y`` is equivalent to ``>=X.Y, ==X.*``.
    ``~=X.Y.Z`` is equivalent to ``>=X.Y.Z, ==X.Y.*``.
    """
    # Normalise: strip quotes
    version = version.strip("'\"")
    spec = spec.strip("'\"")

    spec_parts = spec.split(".")
    if len(spec_parts) < 2:
        return False

    ver_parts = version.split(".")

    # Must be >= spec
    if ver_parts < spec_parts:
        # lexicographic comparison of numeric parts
        try:
            v_nums = [int(p) for p in ver_parts]
            s_nums = [int(p) for p in spec_parts]
        except ValueError:
            return version >= spec
        if v_nums < s_nums:
            return False

    # Must match prefix up to len(spec_parts) - 1
    prefix_len = len(spec_parts) - 1
    try:
        return [int(p) for p in ver_parts[:prefix_len]] == [int(p) for p in spec_parts[:prefix_len]]
    except ValueError:
        return ver_parts[:prefix_len] == spec_parts[:prefix_len]


def os_name() -> str:
    """Return ``os.name`` - one of ``'posix'``, ``'nt'``, ``'java'``."""
    import os

    return os.name
