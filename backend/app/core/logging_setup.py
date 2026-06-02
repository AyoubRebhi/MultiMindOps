"""Centralized logging configuration.

Sets the root log level from ``LOG_LEVEL`` (or sensible per-environment
defaults) and silences chatty third-party libraries. Called once at process
startup from ``app_factory.create_app`` and from the standalone
``execution_worker`` entry point.

Defaults
--------
* ``APP_ENV=development`` → ``INFO``
* ``APP_ENV=production``  → ``WARNING``
* Any value in ``LOG_LEVEL`` overrides the above (e.g. ``LOG_LEVEL=DEBUG``).

Third-party silencing
---------------------
The libraries below are forced to ``WARNING`` regardless of the app level —
they're informative at INFO and useless during normal operation.
"""

from __future__ import annotations

import logging
import os
from typing import Optional


# Third-party loggers that flood stdout at INFO/DEBUG with no actionable info.
_NOISY_LIBRARIES = (
    "sqlalchemy.engine",
    "httpx",
    "httpcore",
    "urllib3",
    "qdrant_client",
    "openai._base_client",
)


def _resolve_level(app_env: str, override: Optional[str]) -> int:
    """Resolve the effective root level from APP_ENV + optional LOG_LEVEL.

    LOG_LEVEL wins when set. Unrecognised values fall back to the env default.
    """
    if override:
        try:
            return logging._nameToLevel[override.strip().upper()]
        except KeyError:
            pass
    return logging.WARNING if (app_env or "").strip().lower() == "production" else logging.INFO


_CONFIGURED = False


def configure_logging(app_env: str = "development", level_override: Optional[str] = None) -> None:
    """Configure the root logger and silence noisy libraries. Idempotent.

    Parameters
    ----------
    app_env :
        Value of ``settings.APP_ENV`` — drives the default level.
    level_override :
        Value of ``settings.LOG_LEVEL`` (or ``os.environ["LOG_LEVEL"]``).
        When set, overrides the per-environment default.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return

    effective = _resolve_level(app_env, level_override or os.environ.get("LOG_LEVEL"))

    root = logging.getLogger()
    root.setLevel(effective)

    # basicConfig() is a no-op if handlers already exist (uvicorn attaches its
    # own). Add a minimal handler only when no other handler is wired up so we
    # never duplicate uvicorn's output.
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
                datefmt="%H:%M:%S",
            )
        )
        root.addHandler(handler)

    for noisy in _NOISY_LIBRARIES:
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _CONFIGURED = True
