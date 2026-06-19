"""Regression tests for the Windows SelectorEventLoop subprocess fix.

Root cause guarded here: uvicorn ``--reload`` / ``--workers>1`` runs the in-process
execution worker on a :class:`asyncio.SelectorEventLoop`, where
``asyncio.create_subprocess_exec`` raises ``NotImplementedError`` on Windows
("asyncio subprocesses are not supported by the current event loop policy").

The fix keeps the async subprocess path on every loop that supports it and adds a
synchronous-subprocess fallback (drained on a worker thread, lines bridged back to
the running loop) when it does not. These tests:

  1. assert the loop-capability detector is correct;
  2. (Windows) reproduce the raw ``NotImplementedError`` on a SelectorEventLoop and
     prove the executor's ``_run_cmd`` still streams lines through the fallback;
  3. (any OS) prove the sync fallback streams output + reports the exit code by
     forcing the fallback on regardless of the actual loop.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile

import pytest

from backend.app.services.execution import docker_executor as de_mod
from backend.app.services.execution.docker_connectivity import loop_supports_subprocess
from backend.app.services.execution.docker_executor import DockerExecutor
from backend.app.services.execution.docker_streamer import log_stream_manager

IS_WIN = sys.platform.startswith("win")


def _echo_cmd(text: str) -> list[str]:
    return ["cmd", "/c", f"echo {text}"] if IS_WIN else ["sh", "-c", f"echo {text}"]


def _new_executor() -> DockerExecutor:
    ex = DockerExecutor(
        task_id="test-" + os.urandom(4).hex(),
        artifacts={"dockerfile": "FROM scratch"},
        image_tag="subproc-test:latest",
    )
    ex._workspace = tempfile.mkdtemp(prefix="subproc_test_")
    log_stream_manager.create(ex.task_id)
    return ex


async def _detector_on_running_loop() -> bool:
    return loop_supports_subprocess()


def test_detector_matches_loop_capability() -> None:
    """SelectorEventLoop → False on Windows (the broken case), True on POSIX."""
    loop = asyncio.SelectorEventLoop()
    try:
        result = loop.run_until_complete(_detector_on_running_loop())
    finally:
        loop.close()
    assert result is (not IS_WIN)


@pytest.mark.skipif(
    not IS_WIN, reason="SelectorEventLoop subprocess limitation is Windows-only"
)
def test_selector_loop_reproduces_bug_and_fix_streams() -> None:
    """On a Windows SelectorEventLoop: raw async subprocess fails, but the
    executor's _run_cmd streams output through the synchronous fallback."""
    loop = asyncio.SelectorEventLoop()
    asyncio.set_event_loop(loop)
    try:
        # 1. Reproduce the exact failure mode the user reported.
        async def _raw():
            await asyncio.create_subprocess_exec(
                "cmd", "/c", "echo hi",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

        with pytest.raises(NotImplementedError):
            loop.run_until_complete(_raw())

        # 2. The fix: the executor streams lines without touching the broken path.
        async def _run():
            ex = _new_executor()
            code = await ex._run_cmd(
                _echo_cmd("STREAMED_LINE_OK"), timeout=30, phase_label="test",
            )
            logs = [e.message for e in log_stream_manager.get(ex.task_id).logs]
            return code, logs

        exit_code, logs = loop.run_until_complete(_run())
        assert exit_code == 0
        assert any("STREAMED_LINE_OK" in m for m in logs)
    finally:
        loop.close()
        asyncio.set_event_loop(None)


def test_sync_fallback_streams_and_reports_exit_code(monkeypatch) -> None:
    """Force the fallback on (as if on a broken loop) and prove it streams output
    and returns the real exit code — validates the bridge on any platform."""
    monkeypatch.setattr(de_mod, "loop_supports_subprocess", lambda *a, **k: False)

    async def _go():
        ex = _new_executor()
        code = await ex._run_cmd(
            _echo_cmd("HELLO_SYNC_FALLBACK"), timeout=30, phase_label="test",
        )
        logs = [e.message for e in log_stream_manager.get(ex.task_id).logs]
        return code, logs

    exit_code, logs = asyncio.run(_go())
    assert exit_code == 0
    assert any("HELLO_SYNC_FALLBACK" in m for m in logs)
