"""
Docker daemon connectivity layer.

This module centralises EVERYTHING about *reaching* the Docker daemon. It does
NOT build images and contains NO business logic — the rest of the codebase talks
to Docker through the ``docker`` CLI via asyncio subprocesses (``DockerExecutor``,
``docker_registry.docker_login``); this module makes that connection robust and
diagnosable.

Public surface
--------------
* :func:`resolve_docker_cli`     — locate the ``docker`` executable even when the
                                   worker process did not inherit the interactive
                                   shell PATH (Windows service / launchd / sandbox).
* :func:`get_docker_env_info`    — read ``DOCKER_HOST`` / ``DOCKER_TLS_VERIFY`` /
                                   ``DOCKER_CERT_PATH`` / ``DOCKER_CONTEXT`` and
                                   derive the effective endpoint + transport.
* :func:`default_daemon_endpoint`— OS-specific default (Windows named pipe vs the
                                   unix socket).
* :func:`docker_health_check`    — side-effect-free structured probe of the daemon.
* :func:`ensure_docker_daemon`   — the pre-build gate the executor calls; applies
                                   the optional ``DOCKER_HOST_FALLBACK`` and returns
                                   ``(ok, error_message)``.

Why a dedicated layer
---------------------
The original pre-build check ran ``docker info`` and then awaited ``proc.wait()``
while both stdout AND stderr were PIPEs that were never drained. ``docker info``
emits enough output to fill the OS pipe buffer, so the child blocked on write and
the parent's 10 s wait timed out — reporting "daemon unreachable" on a perfectly
healthy daemon. We probe with ``docker version`` (small, deterministic output)
through ``communicate()``, which drains both pipes and therefore can never
deadlock.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import sys
from dataclasses import asdict, dataclass
from typing import Optional

from backend.app.core.config import settings

logger = logging.getLogger(__name__)

_IS_WINDOWS = sys.platform.startswith("win")

# Fallback install locations probed when ``docker`` is not on PATH. The worker
# process may run without the interactive shell's PATH (Windows service, launchd,
# CI sandbox, etc.), so a missing PATH entry should not look like "Docker not
# installed".
_WINDOWS_DOCKER_CANDIDATES = [
    r"C:\Program Files\Docker\Docker\resources\bin\docker.exe",
    r"C:\Program Files\Docker\Docker\resources\docker.exe",
    r"C:\ProgramData\DockerDesktop\version-bin\docker.exe",
]
_POSIX_DOCKER_CANDIDATES = [
    "/usr/bin/docker",
    "/usr/local/bin/docker",
    "/opt/homebrew/bin/docker",
    "/snap/bin/docker",
]

# Cached resolved CLI path for the life of the process.
_resolved_cli: Optional[str] = None


def resolve_docker_cli() -> str:
    """Return a path to the ``docker`` executable.

    Resolution order: PATH (``shutil.which``) → known install locations → the bare
    name ``"docker"`` (so the subprocess raises a clear ``FileNotFoundError`` if
    nothing is found). The result is cached for the process.
    """
    global _resolved_cli
    if _resolved_cli:
        return _resolved_cli
    found = shutil.which("docker")
    if found:
        _resolved_cli = found
        return found
    candidates = _WINDOWS_DOCKER_CANDIDATES if _IS_WINDOWS else _POSIX_DOCKER_CANDIDATES
    for candidate in candidates:
        if os.path.isfile(candidate):
            logger.warning(
                "[DockerConnectivity] 'docker' not on PATH; using fallback %s",
                candidate,
            )
            _resolved_cli = candidate
            return candidate
    return "docker"


def loop_supports_subprocess(loop: Optional[asyncio.AbstractEventLoop] = None) -> bool:
    """Return ``True`` when the running event loop can spawn asyncio subprocesses.

    On Windows only the :class:`asyncio.ProactorEventLoop` supports subprocesses.
    uvicorn's ``--reload`` / ``--workers>1`` mode sets ``use_subprocess=True`` and
    therefore runs the server (and the in-process execution worker that shares its
    loop) on a :class:`asyncio.SelectorEventLoop`, where
    ``asyncio.create_subprocess_exec`` raises ``NotImplementedError``. Everywhere
    else (Linux, or Windows under the default Proactor loop) asyncio subprocesses
    work. Callers use this to fall back to a synchronous subprocess on a thread.
    """
    if not _IS_WINDOWS:
        return True
    try:
        loop = loop or asyncio.get_running_loop()
    except RuntimeError:
        return False
    # ``asyncio.ProactorEventLoop`` only exists on Windows, where this line runs.
    return isinstance(loop, asyncio.ProactorEventLoop)


def default_daemon_endpoint() -> str:
    """OS-specific default daemon endpoint when ``DOCKER_HOST`` is unset."""
    return "npipe:////./pipe/docker_engine" if _IS_WINDOWS else "unix:///var/run/docker.sock"


def _transport_of(endpoint: str) -> str:
    e = (endpoint or "").lower()
    for scheme in ("tcp", "npipe", "unix", "ssh", "fd"):
        if e.startswith(scheme + "://"):
            return scheme
    return "default"


def get_docker_env_info() -> dict:
    """Snapshot the Docker-related environment the subprocess will inherit."""
    docker_host = os.environ.get("DOCKER_HOST", "").strip()
    endpoint = docker_host or default_daemon_endpoint()
    return {
        "docker_host": docker_host or None,
        "docker_tls_verify": os.environ.get("DOCKER_TLS_VERIFY", "").strip() or None,
        "docker_cert_path": os.environ.get("DOCKER_CERT_PATH", "").strip() or None,
        "docker_context": os.environ.get("DOCKER_CONTEXT", "").strip() or None,
        "effective_endpoint": endpoint,
        "transport": _transport_of(endpoint),
        "platform": sys.platform,
    }


@dataclass
class DockerHealth:
    """Structured result of a daemon probe — JSON-serialisable for diagnostics."""

    reachable: bool
    binary: str
    client_version: Optional[str] = None
    server_version: Optional[str] = None
    endpoint: Optional[str] = None
    transport: Optional[str] = None
    docker_host: Optional[str] = None
    via_fallback: bool = False
    error: Optional[str] = None
    remediation: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


def _run_docker_sync(
    cli: str,
    args: list[str],
    timeout: float,
    env: Optional[dict],
) -> tuple[Optional[int], str, str]:
    """Synchronous ``docker <args>`` probe — the SelectorEventLoop fallback.

    Mirrors :func:`_run_docker`'s contract (``(returncode, stdout, stderr)``,
    ``returncode is None`` on spawn failure / timeout). ``subprocess.run`` drains
    both pipes via ``capture_output`` so it cannot deadlock on a full pipe buffer.
    Runs on a worker thread (see :func:`_run_docker`) so it never blocks the loop.
    """
    import subprocess

    try:
        proc = subprocess.run(
            [cli, *args],
            capture_output=True,
            timeout=timeout,
            env=env,
        )
    except FileNotFoundError:
        return None, "", f"Docker CLI not found (looked for '{cli}')."
    except subprocess.TimeoutExpired:
        return None, "", f"timed out after {timeout:.0f}s"

    return (
        proc.returncode,
        proc.stdout.decode(errors="replace").strip(),
        proc.stderr.decode(errors="replace").strip(),
    )


async def _run_docker(
    args: list[str],
    *,
    timeout: float,
    env: Optional[dict] = None,
) -> tuple[Optional[int], str, str]:
    """Run ``docker <args>`` and capture output via ``communicate()``.

    ``communicate()`` drains both pipes concurrently, so this can never deadlock
    on a full pipe buffer (the bug this module replaces). Returns
    ``(returncode, stdout, stderr)``; ``returncode`` is ``None`` when the process
    could not be spawned or timed out.

    ``env=None`` means inherit the parent environment (so ``DOCKER_HOST`` and
    friends are honoured automatically).
    """
    cli = resolve_docker_cli()

    # Windows + uvicorn --reload/--workers>1 ⇒ SelectorEventLoop, which cannot
    # spawn asyncio subprocesses. Run a synchronous probe on a worker thread
    # instead. The async path below is unchanged on every loop that supports
    # subprocesses (Linux, or Windows ProactorEventLoop).
    if not loop_supports_subprocess():
        return await asyncio.to_thread(_run_docker_sync, cli, list(args), timeout, env)

    try:
        proc = await asyncio.create_subprocess_exec(
            cli,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
    except FileNotFoundError:
        return None, "", f"Docker CLI not found (looked for '{cli}')."
    except NotImplementedError:
        # asyncio subprocess is unsupported on the current event loop (e.g. a
        # Windows SelectorEventLoop). Surfacing this is far more useful than a
        # generic timeout.
        return None, "", (
            "asyncio subprocesses are not supported by the current event loop "
            "policy (Windows requires the ProactorEventLoop)."
        )

    try:
        out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return None, "", f"timed out after {timeout:.0f}s"

    return (
        proc.returncode,
        out_b.decode(errors="replace").strip(),
        err_b.decode(errors="replace").strip(),
    )


def _remediation(health: DockerHealth, *, client_ok: bool) -> str:
    if not client_ok:
        locs = _WINDOWS_DOCKER_CANDIDATES if _IS_WINDOWS else _POSIX_DOCKER_CANDIDATES
        return (
            "The `docker` CLI could not be executed by the backend process. Ensure "
            "Docker is installed and on the PATH of the user that runs the backend/"
            f"worker (also checked: {', '.join(locs)}), or set DOCKER_HOST to a "
            "reachable daemon endpoint."
        )
    if _IS_WINDOWS:
        return (
            f"The Docker CLI works but the daemon at {health.endpoint} is unreachable "
            "from the backend process. Checklist: (1) Docker Desktop is running; "
            "(2) the account running the backend is a member of the 'docker-users' "
            "group; (3) if the backend runs as a Windows service or inside a sandbox, "
            "the named pipe \\\\.\\pipe\\docker_engine is not visible to it — enable "
            "'Expose daemon on tcp://localhost:2375 without TLS' in Docker Desktop "
            "and set DOCKER_HOST=tcp://localhost:2375 (or DOCKER_HOST_FALLBACK) so the "
            "worker connects over TCP."
        )
    return (
        f"The Docker CLI works but the daemon at {health.endpoint} is unreachable. "
        "Checklist: (1) `dockerd` is running; (2) the backend user is in the 'docker' "
        "group (sudo usermod -aG docker <user>, then re-login); (3) otherwise set "
        "DOCKER_HOST (or DOCKER_HOST_FALLBACK) to a reachable endpoint such as "
        "tcp://localhost:2375."
    )


async def docker_health_check(
    *,
    timeout: Optional[float] = None,
    probe_fallback: bool = True,
) -> DockerHealth:
    """Probe Docker connectivity. Side-effect-free.

    Strategy: read the client version first (proves the CLI runs without needing
    the daemon), then the server version (the actual daemon probe). If the daemon
    is unreachable and ``DOCKER_HOST_FALLBACK`` is configured, retry once against
    that endpoint. Returns a :class:`DockerHealth` with ``reachable`` plus rich
    diagnostics and remediation text.
    """
    timeout = (
        timeout
        if timeout is not None
        else float(getattr(settings, "DOCKER_DAEMON_PROBE_TIMEOUT_SECONDS", 20.0))
    )
    env_info = get_docker_env_info()
    health = DockerHealth(
        reachable=False,
        binary=resolve_docker_cli(),
        endpoint=env_info["effective_endpoint"],
        transport=env_info["transport"],
        docker_host=env_info["docker_host"],
    )

    # 1. Client version — confirms the CLI is executable; does not need the daemon.
    rc, out, err = await _run_docker(
        ["version", "--format", "{{.Client.Version}}"], timeout=timeout,
    )
    if rc is None and not out:
        health.error = err or "docker client probe failed"
        health.remediation = _remediation(health, client_ok=False)
        return health
    if out:
        health.client_version = out.splitlines()[0].strip()

    # 2. Server version — the actual daemon reachability probe.
    rc, out, err = await _run_docker(
        ["version", "--format", "{{.Server.Version}}"], timeout=timeout,
    )
    if rc == 0 and out:
        health.server_version = out.splitlines()[0].strip()
        health.reachable = True
        return health

    primary_err = err or out or "daemon did not respond"

    # 3. Optional explicit fallback endpoint (e.g. tcp://localhost:2375).
    fallback = (getattr(settings, "DOCKER_HOST_FALLBACK", "") or "").strip()
    if probe_fallback and fallback and fallback != (env_info["docker_host"] or ""):
        rc2, out2, err2 = await _run_docker(
            ["version", "--format", "{{.Server.Version}}"],
            timeout=timeout,
            env={**os.environ, "DOCKER_HOST": fallback},
        )
        if rc2 == 0 and out2:
            health.server_version = out2.splitlines()[0].strip()
            health.reachable = True
            health.via_fallback = True
            health.docker_host = fallback
            health.endpoint = fallback
            health.transport = _transport_of(fallback)
            return health
        primary_err = (
            f"{primary_err}; DOCKER_HOST_FALLBACK {fallback} also failed: "
            f"{err2 or out2 or 'no response'}"
        )

    health.error = primary_err
    health.remediation = _remediation(health, client_ok=bool(health.client_version))
    return health


async def ensure_docker_daemon(
    *, timeout: Optional[float] = None,
) -> tuple[bool, Optional[str]]:
    """Pre-build gate. ``(True, None)`` when the daemon is reachable, else
    ``(False, human_readable_error)``.

    When the daemon is reachable ONLY via the configured ``DOCKER_HOST_FALLBACK``,
    this applies that value to ``os.environ`` so the subsequent ``docker build``
    subprocess (which inherits the environment) connects to the working endpoint.
    """
    health = await docker_health_check(timeout=timeout)
    if health.reachable:
        if health.via_fallback and health.docker_host:
            os.environ["DOCKER_HOST"] = health.docker_host
            logger.warning(
                "[DockerConnectivity] primary endpoint unreachable; applying "
                "DOCKER_HOST fallback %s for this process.",
                health.docker_host,
            )
        logger.info(
            "[DockerConnectivity] daemon reachable: client=%s server=%s endpoint=%s%s",
            health.client_version,
            health.server_version,
            health.endpoint,
            " (via fallback)" if health.via_fallback else "",
        )
        return True, None

    msg = health.error or "Docker daemon unreachable"
    if health.remediation:
        msg = f"{msg}\n{health.remediation}"
    logger.error("[DockerConnectivity] daemon unreachable: %s", msg)
    return False, msg
