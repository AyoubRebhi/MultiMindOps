"""
Async, line-streaming Terraform runner.

The blocking :class:`TerraformPipelineService` methods (``validate`` / ``plan``)
capture all subprocess output at once — fine for the synchronous ``/terraform/*``
API, but no good for live log streaming. This module runs the *same* terraform
command-step sequences (imported from ``pipeline_service`` so flags never drift)
under :mod:`asyncio`, emitting every stdout/stderr line to a callback as it is
produced. The workflow job handlers wire that callback to the existing
``log_stream_manager`` so Terraform validation / plan logs flow over the same
WebSocket infrastructure as Docker builds — no second streaming system.

Windows event-loop note
------------------------
uvicorn ``--reload`` / ``--workers>1`` runs the server (and the in-process
execution worker that shares its loop) on a :class:`asyncio.SelectorEventLoop`,
where ``asyncio.create_subprocess_exec`` raises ``NotImplementedError``. This is
the SAME limitation already handled for Docker. We reuse the SAME capability
detector (:func:`loop_supports_subprocess`) and, when the loop cannot spawn
asyncio subprocesses, fall back to a synchronous ``subprocess.Popen`` drained on
a worker thread whose lines are bridged back to the running loop — so live log
streaming, stdout/stderr capture and exit codes are preserved. The async path is
unchanged on every loop that supports subprocesses (Linux, or Windows Proactor).
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Awaitable, Callable, List, Tuple

# Reuse the SAME subprocess-capability detector implemented for the Docker
# pipeline — do not duplicate the loop-introspection logic.
from backend.app.services.execution.docker_connectivity import loop_supports_subprocess

PublishFn = Callable[[str], Awaitable[None]]


async def stream_terraform_steps(
    artifact_dir: Path,
    steps: List[Tuple[str, List[str]]],
    publish: PublishFn,
    *,
    per_step_timeout: int = 300,
) -> Tuple[bool, List[dict]]:
    """Run a sequence of terraform steps, streaming output line-by-line.

    Parameters
    ----------
    artifact_dir :
        Directory holding the generated ``.tf`` files (terraform ``cwd``).
    steps :
        Ordered ``[(label, args), ...]`` — e.g. ``VALIDATE_STEPS`` / ``PLAN_STEPS``
        from :mod:`pipeline_service`.
    publish :
        Async callback invoked once per output line. Wire this to
        ``log_stream_manager.publish``.
    per_step_timeout :
        Hard timeout per terraform invocation, in seconds.

    Returns
    -------
    ``(overall_ok, results)`` where ``results`` is a list of per-step dicts
    ``{"step", "ok", "returncode", "output"}``. A failed step short-circuits
    the remaining steps (no point running ``validate``/``plan`` if ``init``
    failed). Raises :class:`RuntimeError` if the terraform binary is missing.
    """
    binary = shutil.which("terraform")
    if not binary:
        raise RuntimeError(
            "The 'terraform' binary was not found on PATH. "
            "Install Terraform to run this phase."
        )

    # AWS credentials (.env / ~/.aws) overlaid onto the inherited environment so
    # `terraform plan` can authenticate against AWS.
    from backend.app.services.terraform_pipeline.pipeline_service import (
        terraform_subprocess_env,
    )

    tf_env = terraform_subprocess_env()

    # One capability check per phase: the async path on loops that support
    # subprocesses, the synchronous-thread fallback when they do not (Windows
    # SelectorEventLoop under uvicorn --reload).
    use_async = loop_supports_subprocess()

    results: List[dict] = []
    overall_ok = True

    for label, args in steps:
        await publish(f"$ terraform {' '.join(args)}")
        captured: List[str] = []

        try:
            if use_async:
                returncode = await _run_step_async(
                    binary, args, artifact_dir, tf_env, publish, captured,
                    per_step_timeout,
                )
            else:
                returncode = await _run_step_sync(
                    binary, args, artifact_dir, tf_env, publish, captured,
                    per_step_timeout,
                )
        except asyncio.TimeoutError:
            await publish(f"ERROR: terraform {label} timed out after {per_step_timeout}s")
            results.append(
                {"step": label, "ok": False, "returncode": -1, "output": "\n".join(captured)}
            )
            overall_ok = False
            break

        ok = returncode == 0
        results.append(
            {"step": label, "ok": ok, "returncode": returncode, "output": "\n".join(captured)}
        )
        if not ok:
            await publish(f"ERROR: terraform {label} exited with code {returncode}")
            overall_ok = False
            break

    return overall_ok, results


async def _run_step_async(
    binary: str,
    args: List[str],
    artifact_dir: Path,
    tf_env: dict,
    publish: PublishFn,
    captured: List[str],
    timeout: int,
) -> int:
    """Run ONE terraform step via asyncio subprocess, streaming each line.

    The original (and only) path on loops that support asyncio subprocesses.
    Appends every decoded line to ``captured`` and publishes it. Raises
    :class:`asyncio.TimeoutError` (after killing the process) on timeout.
    """
    proc = await asyncio.create_subprocess_exec(
        binary,
        *args,
        cwd=str(artifact_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,  # interleave stderr into stdout
        env=tf_env,
    )

    async def _pump() -> None:
        assert proc.stdout is not None
        async for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            captured.append(line)
            await publish(line)

    try:
        await asyncio.wait_for(_pump(), timeout=timeout)
        returncode = await asyncio.wait_for(proc.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise

    return returncode


async def _run_step_sync(
    binary: str,
    args: List[str],
    artifact_dir: Path,
    tf_env: dict,
    publish: PublishFn,
    captured: List[str],
    timeout: int,
) -> int:
    """SelectorEventLoop fallback for :func:`_run_step_async`.

    Spawns a synchronous ``subprocess.Popen`` on a worker thread, drains the
    (merged stdout+stderr) pipe in a reader thread, and bridges every decoded
    line back to THIS event loop via ``run_coroutine_threadsafe`` so ``publish``
    runs on the loop that owns the stream's ``asyncio.Condition`` (the same loop
    the WebSocket subscribes on). The main thread enforces the timeout with
    ``proc.wait(timeout=...)``. Behaviour — per-line streaming, output capture,
    exit code, timeout — matches the async path; only the spawn mechanism differs.
    Mirrors ``DockerExecutor._run_cmd_sync``.
    """
    import subprocess
    import threading

    loop = asyncio.get_running_loop()

    def _publish_threadsafe(line: str) -> None:
        try:
            asyncio.run_coroutine_threadsafe(publish(line), loop).result()
        except Exception:  # noqa: BLE001 — a publish hiccup must not kill the drain
            pass

    def _pump() -> int:
        proc = subprocess.Popen(
            [binary, *args],
            cwd=str(artifact_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # interleave — matches the async path
            env=tf_env,
        )

        def _drain() -> None:
            assert proc.stdout is not None
            for raw in iter(proc.stdout.readline, b""):
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                captured.append(line)
                _publish_threadsafe(line)
            try:
                proc.stdout.close()
            except Exception:
                pass

        reader = threading.Thread(target=_drain, daemon=True)
        reader.start()
        try:
            returncode = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            reader.join(timeout=5)
            raise asyncio.TimeoutError()
        # Let the reader finish draining whatever is buffered after exit.
        reader.join(timeout=5)
        return returncode

    return await asyncio.to_thread(_pump)
