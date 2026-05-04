"""
Terraform resource data loader — reads from mcp/data/terraform/*.json
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent.parent / "data" / "terraform"

# In-process cache: populated on first access, lives for the process lifetime
_cache: dict[str, dict[str, Any]] = {}


def load_terraform_resource(resource_name: str) -> dict[str, Any] | None:
    """Load structured Terraform resource data from the local JSON store."""
    if resource_name in _cache:
        return _cache[resource_name]

    path = _DATA_DIR / f"{resource_name}.json"
    if not path.exists():
        logger.debug("Terraform resource not found: %s (path=%s)", resource_name, path)
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        _cache[resource_name] = data
        return data
    except Exception as exc:
        logger.error("Failed to load terraform resource %s: %s", resource_name, exc)
        return None


def list_terraform_resources() -> list[str]:
    """Return all available Terraform resource names."""
    if not _DATA_DIR.exists():
        return []
    return sorted(p.stem for p in _DATA_DIR.glob("*.json"))


def get_all_terraform_resources() -> dict[str, dict[str, Any]]:
    """Load and return all terraform resources as a dict."""
    return {name: load_terraform_resource(name) for name in list_terraform_resources()
            if load_terraform_resource(name) is not None}
