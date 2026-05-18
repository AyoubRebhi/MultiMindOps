"""
Real-time log streaming for execution phases.

Uses asyncio.Condition so multiple subscribers (reconnects) always see
the full log history without missing or duplicating lines.
"""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncGenerator

from .execution_models import ExecutionEvent, ExecutionLogEntry, LogLevel

logger = logging.getLogger(__name__)


def classify_log_line(line: str) -> LogLevel:
    """Map a raw docker output line to a display level."""
    lower = line.lower()
    if any(kw in lower for kw in ("error:", "failed", "fatal", "err:", "no such file", "not found", "permission denied", "cannot find", "unable to find", "denied: ")):
        return LogLevel.ERROR
    if any(kw in lower for kw in ("warning", "warn:", "deprecated", "1 warning")):
        return LogLevel.WARNING
    if any(kw in lower for kw in ("successfully built", "successfully tagged", "successfully", "pushed", " 200 ", "digest:", "writing image", "naming to ", "done ")):
        return LogLevel.SUCCESS
    if any(kw in lower for kw in ("step ", "from ", "run ", "copy ", "add ", "cmd ", "entrypoint", "expose", "workdir", "arg ", "env ", "label ", "maintainer", "volume ", "user ", "healthcheck", "onbuild", "stopsignal", "shell")):
        return LogLevel.INFO
    return LogLevel.DEFAULT


class TaskLogStream:
    """Holds log history + a Condition for broadcasting to concurrent subscribers."""

    def __init__(self) -> None:
        self._logs: list[ExecutionLogEntry] = []
        self._events: list[ExecutionEvent] = []
        self._condition: asyncio.Condition = asyncio.Condition()
        self._done: bool = False
        # Retry-session metadata stamped onto every emitted log / event so
        # subscribers can route output per retry attempt.
        self._retry_iteration: int | None = None
        self._execution_session_id: str | None = None

    def set_session(self, retry_iteration: int, execution_session_id: str) -> None:
        """Stamp every subsequent log/event with this session metadata."""
        self._retry_iteration = retry_iteration
        self._execution_session_id = execution_session_id
        logger.info(
            "[LogStream] Session set: retry=%d session=%s",
            retry_iteration, execution_session_id,
        )

    @property
    def retry_iteration(self) -> int | None:
        return self._retry_iteration

    @property
    def execution_session_id(self) -> str | None:
        return self._execution_session_id

    async def publish(self, entry: ExecutionLogEntry) -> None:
        # Stamp session metadata if not already present
        if entry.retry_iteration is None and self._retry_iteration is not None:
            entry.retry_iteration = self._retry_iteration
        if entry.execution_session_id is None and self._execution_session_id is not None:
            entry.execution_session_id = self._execution_session_id

        event = ExecutionEvent(
            type="build_log",
            timestamp=entry.timestamp,
            level=entry.level,
            message=entry.message,
            phase="building",
            retry_iteration=entry.retry_iteration,
            execution_session_id=entry.execution_session_id,
            is_replay=entry.is_replay,
        )
        async with self._condition:
            self._logs.append(entry)
            self._events.append(event)
            self._condition.notify_all()
        logger.debug("[LogStream] Appended log entry: level=%s session=%s msg=%.60s total=%d",
                     entry.level.value, self._execution_session_id, entry.message, len(self._logs))

    async def publish_event(self, event: ExecutionEvent) -> None:
        # Stamp session metadata if not already set on the event
        if event.retry_iteration is None and self._retry_iteration is not None:
            event.retry_iteration = self._retry_iteration
        if event.execution_session_id is None and self._execution_session_id is not None:
            event.execution_session_id = self._execution_session_id
        async with self._condition:
            self._events.append(event)
            self._condition.notify_all()
        logger.debug(
            "[LogStream] Appended event: type=%s msg=%.60s total=%d",
            event.type,
            event.message or "",
            len(self._events),
        )

    async def finish(self) -> None:
        async with self._condition:
            self._done = True
            self._condition.notify_all()
        logger.info("[LogStream] Stream finished: total_logs=%d", len(self._logs))

    async def subscribe(self) -> AsyncGenerator[ExecutionLogEntry, None]:
        """
        Yield every log entry from the start.
        New subscribers immediately receive the full history then continue live.
        """
        idx = 0
        logger.debug("[LogStream] New subscriber attached")
        while True:
            async with self._condition:
                while idx >= len(self._logs) and not self._done:
                    await self._condition.wait()
                batch = self._logs[idx:]
                idx += len(batch)
                done = self._done and idx >= len(self._logs)

            for entry in batch:
                yield entry

            if done:
                logger.debug("[LogStream] Subscriber reached end of stream")
                break

    async def subscribe_events(self) -> AsyncGenerator[ExecutionEvent, None]:
        """Yield typed execution events from the start, then continue live."""
        idx = 0
        logger.debug("[LogStream] New event subscriber attached")
        while True:
            async with self._condition:
                while idx >= len(self._events) and not self._done:
                    await self._condition.wait()
                batch = self._events[idx:]
                idx += len(batch)
                done = self._done and idx >= len(self._events)

            for event in batch:
                yield event

            if done:
                logger.debug("[LogStream] Event subscriber reached end of stream")
                break

    @property
    def logs(self) -> list[ExecutionLogEntry]:
        return list(self._logs)

    @property
    def events(self) -> list[ExecutionEvent]:
        return list(self._events)

    @property
    def is_done(self) -> bool:
        return self._done


class LogStreamManager:
    """
    Global registry of per-task log streams.
    Intended as a module-level singleton.
    """

    def __init__(self) -> None:
        self._streams: dict[str, TaskLogStream] = {}

    def create(self, task_id: str) -> TaskLogStream:
        stream = TaskLogStream()
        self._streams[task_id] = stream
        logger.info("[LogStreamManager] Created stream: task=%s", task_id)
        return stream

    def get(self, task_id: str) -> TaskLogStream | None:
        return self._streams.get(task_id)

    def get_or_create(self, task_id: str) -> TaskLogStream:
        if task_id not in self._streams:
            return self.create(task_id)
        return self._streams[task_id]

    def remove(self, task_id: str) -> None:
        self._streams.pop(task_id, None)
        logger.info("[LogStreamManager] Removed stream: task=%s", task_id)

    async def publish(self, task_id: str, line: str) -> ExecutionLogEntry:
        entry = ExecutionLogEntry(level=classify_log_line(line), message=line.rstrip())
        stream = self.get_or_create(task_id)
        await stream.publish(entry)
        return entry

    async def publish_event(self, task_id: str, event: ExecutionEvent) -> ExecutionEvent:
        stream = self.get_or_create(task_id)
        await stream.publish_event(event)
        return event

    async def finish(self, task_id: str) -> None:
        stream = self.get(task_id)
        if stream:
            await stream.finish()
            total = len(stream.logs)
            logger.info("[LogStreamManager] Stream complete: task=%s total_logs=%d", task_id, total)


# Module-level singleton — imported by the executor and the WebSocket route
log_stream_manager = LogStreamManager()
