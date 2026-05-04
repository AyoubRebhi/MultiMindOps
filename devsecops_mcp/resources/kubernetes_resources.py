"""
Kubernetes template data loader — reads from mcp/data/kubernetes/*.json
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent.parent / "data" / "kubernetes"
_cache: dict[str, dict[str, Any]] = {}


def load_kubernetes_template(template_name: str) -> dict[str, Any] | None:
    if template_name in _cache:
        return _cache[template_name]

    path = _DATA_DIR / f"{template_name}.json"
    if not path.exists():
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        _cache[template_name] = data
        return data
    except Exception as exc:
        logger.error("Failed to load kubernetes template %s: %s", template_name, exc)
        return None


def list_kubernetes_templates() -> list[str]:
    if not _DATA_DIR.exists():
        return []
    return sorted(p.stem for p in _DATA_DIR.glob("*.json"))
