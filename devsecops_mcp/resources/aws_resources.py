"""
AWS best practices data loader — reads from mcp/data/aws/*.json
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent.parent / "data" / "aws"
_cache: dict[str, dict[str, Any]] = {}


def load_aws_best_practices(category: str = "best_practices") -> dict[str, Any] | None:
    if category in _cache:
        return _cache[category]

    path = _DATA_DIR / f"{category}.json"
    if not path.exists():
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        _cache[category] = data
        return data
    except Exception as exc:
        logger.error("Failed to load AWS best practices %s: %s", category, exc)
        return None
