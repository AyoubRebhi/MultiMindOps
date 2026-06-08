"""
Docker registry credential management and tag generation.

Supports:
- Docker Hub  (DOCKER_REGISTRY_TYPE=dockerhub)
- GHCR        (DOCKER_REGISTRY_TYPE=ghcr)
- Generic     (any registry URL in DOCKER_REGISTRY_URL)
"""

from __future__ import annotations

import asyncio
import logging
import re
import time

logger = logging.getLogger(__name__)

# Characters allowed in an image name component
_SAFE_RE = re.compile(r"[^a-z0-9._-]")


def _slugify(text: str) -> str:
    return _SAFE_RE.sub("-", text.lower().strip())[:40].strip("-") or "app"


def generate_image_tag(
    project_name: str,
    task_id: str,
    registry_url: str = "",
    registry_username: str = "",
) -> str:
    """
    Build a unique, push-ready image tag.

    Examples:
      myapp:abc123-1717000000     (no registry)
      myuser/myapp:abc123-1717000000  (Docker Hub)
      ghcr.io/myuser/myapp:abc123-1717000000  (GHCR)
    """
    slug = _slugify(project_name)
    short_id = task_id[:8] if len(task_id) >= 8 else task_id
    tag = f"{short_id}-{int(time.time())}"

    if registry_url and registry_username:
        return f"{registry_url}/{registry_username}/{slug}:{tag}"
    if registry_username:
        return f"{registry_username}/{slug}:{tag}"
    return f"{slug}:{tag}"


async def docker_login(
    registry_url: str,
    username: str,
    password: str,
) -> tuple[bool, str]:
    """
    Run `docker login` and return (success, output).
    registry_url may be empty for Docker Hub.
    """
    from .docker_connectivity import resolve_docker_cli

    cmd = [resolve_docker_cli(), "login", "--username", username, "--password-stdin"]
    if registry_url:
        cmd.append(registry_url)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout_bytes, _ = await asyncio.wait_for(
            proc.communicate(input=password.encode()),
            timeout=30,
        )
        output = stdout_bytes.decode(errors="replace").strip()
        return proc.returncode == 0, output
    except Exception as exc:
        return False, str(exc)
