"""Regression tests for the Terraform Windows SelectorEventLoop subprocess fix.

Mirrors ``test_windows_subprocess_loop.py`` (Docker), but for the Terraform
pipeline. Root cause guarded here: uvicorn ``--reload`` / ``--workers>1`` runs the
in-process execution worker on a :class:`asyncio.SelectorEventLoop`, where
``asyncio.create_subprocess_exec`` raises ``NotImplementedError`` on Windows. The
Terraform validate/plan streaming layer (``terraform_pipeline/streaming.py``) and
the plan-summary helper (``plan_summary.py``) reuse the SAME capability detector
(:func:`loop_supports_subprocess`) and fall back to a synchronous subprocess
drained on a worker thread when the loop cannot spawn asyncio subprocesses.

These tests:
  1. assert the shared loop-capability detector is correct (the same one Docker uses);
  2. (Windows) reproduce the raw ``NotImplementedError`` on a SelectorEventLoop and
     prove ``stream_terraform_steps`` still streams lines through the fallback;
  3. (any OS) prove the sync fallback streams output by forcing the fallback on;
  4. (any OS) prove exit codes propagate correctly through the fallback;
  5. (any OS) prove the ``plan_summary`` (``terraform show -json``) fallback works.

No real ``terraform`` binary is required: ``shutil.which`` is monkeypatched to a
controlled interpreter/script so the SAME code path runs a deterministic command.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile

import pytest

from backend.app.services.execution.docker_connectivity import loop_supports_subprocess
from backend.app.services.terraform_pipeline import plan_summary as ps_mod
from backend.app.services.terraform_pipeline import streaming as tf_mod
from backend.app.services.terraform_pipeline.pipeline_service import PLAN_OUTPUT_FILE

IS_WIN = sys.platform.startswith("win")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fake_validate_steps(line: str, exit_code: int):
    """Return (fake_binary, steps) so ``[binary, *args]`` runs a real, controlled
    command that echoes ``line`` and exits ``exit_code`` — same shape as
    VALIDATE_STEPS, but OS-portable and terraform-free."""
    if IS_WIN:
        binary = "cmd"
        if exit_code == 0:
            cmdline = f"echo {line}"
        else:
            cmdline = f"echo {line}& exit /b {exit_code}"
        return binary, [("validate", ["/c", cmdline])]
    binary = "/bin/sh"
    return binary, [("validate", ["-c", f"echo {line}; exit {exit_code}"])]


def _write_fake_terraform(dirpath: str, json_text: str = '{"resource_changes": []}') -> str:
    """Write a tiny real executable that ignores its args and prints ``json_text``
    — stands in for ``terraform show -json`` (whose args are fixed, so a generic
    interpreter can't be used)."""
    if IS_WIN:
        p = os.path.join(dirpath, "faketf.cmd")
        with open(p, "w", encoding="utf-8", newline="") as f:
            f.write(f"@echo off\r\necho {json_text}\r\n")
        return p
    p = os.path.join(dirpath, "faketf.sh")
    with open(p, "w", encoding="utf-8") as f:
        f.write(f"#!/bin/sh\necho '{json_text}'\n")
    os.chmod(p, 0o755)
    return p


async def _detector_on_running_loop() -> bool:
    return loop_supports_subprocess()


# ── 1. Detector ───────────────────────────────────────────────────────────────

def test_detector_matches_loop_capability() -> None:
    """SelectorEventLoop → False on Windows (the broken case), True on POSIX.
    This is the SAME detector both Docker and Terraform pipelines consume."""
    loop = asyncio.SelectorEventLoop()
    try:
        result = loop.run_until_complete(_detector_on_running_loop())
    finally:
        loop.close()
    assert result is (not IS_WIN)


# ── 2. Windows: reproduce the bug + prove the validate fallback streams ────────

@pytest.mark.skipif(
    not IS_WIN, reason="SelectorEventLoop subprocess limitation is Windows-only"
)
def test_selector_loop_reproduces_bug_and_validate_streams(monkeypatch) -> None:
    """On a real Windows SelectorEventLoop: raw async subprocess fails, but
    stream_terraform_steps streams output through the synchronous fallback."""
    loop = asyncio.SelectorEventLoop()
    asyncio.set_event_loop(loop)
    try:
        # 1. Reproduce the exact failure mode reported for terraform init.
        async def _raw():
            await asyncio.create_subprocess_exec(
                "cmd", "/c", "echo hi",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )

        with pytest.raises(NotImplementedError):
            loop.run_until_complete(_raw())

        # 2. The fix: on this SAME broken loop, stream_terraform_steps detects the
        #    SelectorEventLoop and streams via the sync fallback (no monkeypatch of
        #    the detector — the real loop drives the real fallback).
        binary, steps = _fake_validate_steps("STREAMED_LINE_OK", 0)
        monkeypatch.setattr(tf_mod.shutil, "which", lambda *_a, **_k: binary)
        artifact_dir = tempfile.mkdtemp(prefix="tf_subproc_")

        async def _run():
            lines: list[str] = []

            async def _pub(line: str) -> None:
                lines.append(line)

            ok, results = await tf_mod.stream_terraform_steps(artifact_dir, steps, _pub)
            return ok, results, lines

        ok, results, lines = loop.run_until_complete(_run())
        assert ok is True
        assert results[0]["returncode"] == 0
        assert any("STREAMED_LINE_OK" in m for m in lines)
        # The "$ terraform validate ..." banner is always published too.
        assert any(m.startswith("$ terraform") for m in lines)
    finally:
        loop.close()
        asyncio.set_event_loop(None)


# ── 3. Any OS: force the fallback on → streams output ─────────────────────────

def test_validate_sync_fallback_streams(monkeypatch) -> None:
    """Force the fallback (as if on a broken loop) and prove it streams output —
    validates the Popen-on-thread → loop bridge on any platform."""
    monkeypatch.setattr(tf_mod, "loop_supports_subprocess", lambda *a, **k: False)
    binary, steps = _fake_validate_steps("HELLO_SYNC_FALLBACK", 0)
    monkeypatch.setattr(tf_mod.shutil, "which", lambda *_a, **_k: binary)
    artifact_dir = tempfile.mkdtemp(prefix="tf_subproc_")

    async def _go():
        lines: list[str] = []

        async def _pub(line: str) -> None:
            lines.append(line)

        ok, results = await tf_mod.stream_terraform_steps(artifact_dir, steps, _pub)
        return ok, results, lines

    ok, results, lines = asyncio.run(_go())
    assert ok is True
    assert results[0]["ok"] is True
    assert results[0]["returncode"] == 0
    assert any("HELLO_SYNC_FALLBACK" in m for m in lines)
    # Captured output is reconstructed for the validation_report artifact.
    assert "HELLO_SYNC_FALLBACK" in results[0]["output"]


# ── 4. Any OS: exit codes propagate through the fallback ──────────────────────

def test_validate_sync_fallback_propagates_nonzero_exit(monkeypatch) -> None:
    """A non-zero terraform exit must surface as ok=False with the real code, and
    short-circuit the remaining steps."""
    monkeypatch.setattr(tf_mod, "loop_supports_subprocess", lambda *a, **k: False)
    binary, steps = _fake_validate_steps("BOOM", 3)
    monkeypatch.setattr(tf_mod.shutil, "which", lambda *_a, **_k: binary)
    artifact_dir = tempfile.mkdtemp(prefix="tf_subproc_")

    async def _go():
        lines: list[str] = []

        async def _pub(line: str) -> None:
            lines.append(line)

        return await tf_mod.stream_terraform_steps(artifact_dir, steps, _pub)

    ok, results = asyncio.run(_go())
    assert ok is False
    assert results[0]["ok"] is False
    assert results[0]["returncode"] == 3


# ── 5. Any OS: plan_summary (terraform show -json) fallback works ─────────────

def test_plan_summary_sync_fallback(monkeypatch, tmp_path) -> None:
    """generate_plan_json must run terraform show through the sync fallback on a
    SelectorEventLoop and return parseable JSON the summary builder consumes."""
    monkeypatch.setattr(ps_mod, "loop_supports_subprocess", lambda *a, **k: False)
    fake = _write_fake_terraform(str(tmp_path))
    monkeypatch.setattr(ps_mod.shutil, "which", lambda *_a, **_k: fake)
    # generate_plan_json requires the plan file to exist before it runs `show`.
    (tmp_path / PLAN_OUTPUT_FILE).write_bytes(b"binary-plan-stub")

    result = asyncio.run(ps_mod.generate_plan_json(tmp_path))
    assert result is not None
    summary = ps_mod.build_infrastructure_summary(result)
    assert summary is not None
    assert summary["total_resources"] == 0
