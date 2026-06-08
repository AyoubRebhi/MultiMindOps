"""
Unit tests for the Docker connectivity layer.

These are hermetic: the docker subprocess is fully mocked, so they assert the
probe LOGIC (client/server detection, the never-deadlock communicate() path,
the optional DOCKER_HOST fallback, and remediation) without needing a real
Docker daemon. They use ``asyncio.run`` from sync test functions so they run
regardless of whether pytest-asyncio is configured.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from backend.app.services.execution import docker_connectivity as dc
from backend.app.services.execution.docker_connectivity import (
    DockerHealth,
    default_daemon_endpoint,
    docker_health_check,
    ensure_docker_daemon,
    get_docker_env_info,
)

_MOD = "backend.app.services.execution.docker_connectivity"


def _fake_proc(stdout: str = "", stderr: str = "", returncode: int = 0):
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout.encode(), stderr.encode()))
    proc.kill = MagicMock()
    return proc


def _cse_factory(*, server_ok: bool, fallback_endpoint: str | None = None):
    """Build a create_subprocess_exec stand-in that answers client/server probes."""

    async def _cse(_cli, *args, **kwargs):
        if "{{.Client.Version}}" in args:
            return _fake_proc(stdout="27.1.0")
        if "{{.Server.Version}}" in args:
            env = kwargs.get("env") or {}
            host = env.get("DOCKER_HOST") if env else None
            if fallback_endpoint and host == fallback_endpoint:
                return _fake_proc(stdout="27.1.0")  # fallback daemon answers
            if server_ok:
                return _fake_proc(stdout="27.1.0")
            return _fake_proc(
                stderr="Cannot connect to the Docker daemon. Is the docker daemon running?",
                returncode=1,
            )
        return _fake_proc()

    return _cse


# ── Pure helpers ────────────────────────────────────────────────────────────

def test_default_endpoint_is_os_specific():
    ep = default_daemon_endpoint()
    assert ep.startswith("npipe://") or ep.startswith("unix://")


def test_env_info_reports_transport(monkeypatch):
    monkeypatch.setenv("DOCKER_HOST", "tcp://localhost:2375")
    info = get_docker_env_info()
    assert info["docker_host"] == "tcp://localhost:2375"
    assert info["transport"] == "tcp"
    assert info["effective_endpoint"] == "tcp://localhost:2375"


# ── Health check ────────────────────────────────────────────────────────────

def test_health_check_reachable():
    with patch(f"{_MOD}.asyncio.create_subprocess_exec", new=_cse_factory(server_ok=True)):
        health = asyncio.run(docker_health_check(timeout=5))
    assert isinstance(health, DockerHealth)
    assert health.reachable is True
    assert health.client_version == "27.1.0"
    assert health.server_version == "27.1.0"
    assert health.error is None


def test_health_check_daemon_down_has_remediation():
    with patch(f"{_MOD}.asyncio.create_subprocess_exec", new=_cse_factory(server_ok=False)):
        health = asyncio.run(docker_health_check(timeout=5, probe_fallback=False))
    assert health.reachable is False
    assert health.client_version == "27.1.0"  # CLI works…
    assert health.server_version is None       # …daemon does not answer
    assert "Cannot connect" in (health.error or "")
    assert health.remediation and "docker" in health.remediation.lower()


def test_health_check_uses_fallback(monkeypatch):
    monkeypatch.setattr(dc.settings, "DOCKER_HOST_FALLBACK", "tcp://localhost:2375", raising=False)
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    cse = _cse_factory(server_ok=False, fallback_endpoint="tcp://localhost:2375")
    with patch(f"{_MOD}.asyncio.create_subprocess_exec", new=cse):
        health = asyncio.run(docker_health_check(timeout=5))
    assert health.reachable is True
    assert health.via_fallback is True
    assert health.docker_host == "tcp://localhost:2375"
    assert health.transport == "tcp"


def test_health_check_binary_missing():
    async def _boom(*_a, **_k):
        raise FileNotFoundError("docker")

    with patch(f"{_MOD}.asyncio.create_subprocess_exec", new=_boom):
        health = asyncio.run(docker_health_check(timeout=5))
    assert health.reachable is False
    assert health.client_version is None
    assert health.remediation and "PATH" in health.remediation


def test_health_check_timeout_no_deadlock():
    """A hung daemon must surface as a timeout, never block forever."""

    async def _hang(_cli, *args, **kwargs):
        proc = MagicMock()
        proc.returncode = None

        async def _never():
            await asyncio.sleep(3600)
            return (b"", b"")

        proc.communicate = _never
        proc.kill = MagicMock()
        return proc

    with patch(f"{_MOD}.asyncio.create_subprocess_exec", new=_hang):
        health = asyncio.run(docker_health_check(timeout=0.05, probe_fallback=False))
    assert health.reachable is False
    assert "timed out" in (health.error or "")


# ── ensure_docker_daemon gate ────────────────────────────────────────────────

def test_ensure_daemon_applies_fallback_to_env(monkeypatch):
    monkeypatch.setattr(dc.settings, "DOCKER_HOST_FALLBACK", "tcp://localhost:2375", raising=False)
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    cse = _cse_factory(server_ok=False, fallback_endpoint="tcp://localhost:2375")
    with patch(f"{_MOD}.asyncio.create_subprocess_exec", new=cse):
        ok, err = asyncio.run(ensure_docker_daemon())
    assert ok is True
    assert err is None
    # The working fallback is applied so the real `docker build` inherits it.
    assert dc.os.environ.get("DOCKER_HOST") == "tcp://localhost:2375"


def test_ensure_daemon_returns_error_when_unreachable(monkeypatch):
    monkeypatch.setattr(dc.settings, "DOCKER_HOST_FALLBACK", "", raising=False)
    with patch(f"{_MOD}.asyncio.create_subprocess_exec", new=_cse_factory(server_ok=False)):
        ok, err = asyncio.run(ensure_docker_daemon())
    assert ok is False
    assert err and "Cannot connect" in err
