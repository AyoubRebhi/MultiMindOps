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
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Awaitable, Callable, List, Tuple

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

    results: List[dict] = []
    overall_ok = True

    for label, args in steps:
        await publish(f"$ terraform {' '.join(args)}")
        captured: List[str] = []

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
            await asyncio.wait_for(_pump(), timeout=per_step_timeout)
            returncode = await asyncio.wait_for(proc.wait(), timeout=per_step_timeout)
        except asyncio.TimeoutError:
            proc.kill()
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
