# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Rohan R. All rights reserved.

"""Structured logging utilities for the envguard framework."""

from __future__ import annotations

import logging
import sys

# Default format for envguard log messages
_LOG_FORMAT = "%(asctime)s | %(name)s | %(levelname)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"

# Module-level cache so repeated get_logger calls for the same name reuse the instance
_loggers: dict[str, logging.Logger] = {}


def get_logger(
    name: str = "envguard",
    level: int = logging.INFO,
    *,
    handler: logging.Handler | None = None,
    propagate: bool = False,
) -> logging.Logger:
    """Return a configured :class:`logging.Logger` for the given *name*.

    Parameters
    ----------
    name:
        Logger name - typically the module dotted path (e.g. ``"envguard.rules"``).
    level:
        Minimum log level.  Defaults to ``logging.INFO``.
    handler:
        Optional custom handler.  When *None* a :class:`logging.StreamHandler`
        writing to *sys.stderr* is attached automatically.
    propagate:
        Whether log messages should propagate to ancestor loggers.

    Returns
    -------
    logging.Logger
        A cached, fully-configured logger instance.
    """
    if name in _loggers:
        return _loggers[name]

    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = propagate

    # Avoid adding duplicate handlers when called more than once programmatically
    if not logger.handlers:
        if handler is None:
            stream = logging.StreamHandler(sys.stderr)
            stream.setLevel(level)
            formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)
            stream.setFormatter(formatter)
            handler = stream
        logger.addHandler(handler)

    _loggers[name] = logger
    return logger
