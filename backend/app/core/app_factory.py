import io
import logging
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from backend.app.api.router import api_router
from backend.app.core.config import settings
from backend.app.core.log_redaction import install_secret_redactor
from backend.app.core.schema_guard import run_schema_guard
from backend.app.database.base import Base
from backend.app.database.session import engine
from backend.app.services.repository.github_service import resolve_workspace_dir

logger = logging.getLogger(__name__)


def validate_runtime_workspace() -> None:
    """
    Validate that the runtime workspace directory exists and is writable BEFORE
    serving any request. Failure to mkdir/write here is the production bug class
    that surfaces as `PermissionError: [Errno 13] Permission denied: 'workspace'`
    on the first repository clone — we want it logged at startup with full
    UID/GID/path diagnostics, not at 02:00 in a user-facing trace.
    """
    target = resolve_workspace_dir()
    logger.info("[RuntimeInit] WORKSPACE_DIR=%s", target)
    logger.info("[RuntimeInit] Ensuring runtime repository workspace exists")
    try:
        target.mkdir(parents=True, exist_ok=True)
        probe = target / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except PermissionError as exc:
        try:
            uid = os.getuid()    # type: ignore[attr-defined]
            gid = os.getgid()    # type: ignore[attr-defined]
        except AttributeError:
            uid = gid = -1
        existing = target
        while not existing.exists() and existing.parent != existing:
            existing = existing.parent
        try:
            st = existing.stat()
            ancestor_uid = getattr(st, "st_uid", -1)
            ancestor_gid = getattr(st, "st_gid", -1)
            ancestor_mode = oct(getattr(st, "st_mode", 0) & 0o777)
        except OSError:
            ancestor_uid = ancestor_gid = -1
            ancestor_mode = "unknown"
        logger.error(
            "[RuntimeInit] Workspace permissions FAILED: %s\n"
            "  resolved_path:    %s\n"
            "  process_uid/gid:  %s/%s\n"
            "  first_existing:   %s\n"
            "  ancestor_uid/gid: %s/%s\n"
            "  ancestor_mode:    %s\n"
            "  fix: the Dockerfile must run `mkdir -p %s && chown -R "
            "appuser:appgroup /app` BEFORE the USER appuser directive.",
            exc, target, uid, gid, existing,
            ancestor_uid, ancestor_gid, ancestor_mode, target,
        )
        raise
    logger.info("[RuntimeInit] Workspace permissions OK")


def setup_utf8_encoding() -> None:
    """Force stdout/stderr/logging to UTF-8 on Windows.

    On Windows the default locale encoding is often cp1252 or ASCII, which
    causes UnicodeEncodeError when the LLM returns characters like em-dash
    (U+2014) and the logger tries to write them to the console.

    We reconfigure unconditionally because some Windows environments report
    UTF-8 in the Python layer while the underlying console handle is still
    ASCII — the reported encoding cannot be trusted.
    """
    import os
    # Force-set for subprocesses (override any inherited value).
    os.environ["PYTHONIOENCODING"] = "utf-8"

    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        try:
            # reconfigure() is the preferred path (Python 3.7+).
            stream.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            # Fallback for streams without reconfigure() (e.g. wrapped streams).
            try:
                buffer = getattr(stream, "buffer", None)
                if buffer is not None:
                    setattr(sys, stream_name,
                            io.TextIOWrapper(buffer, encoding="utf-8", errors="replace"))
            except Exception:
                pass  # Best-effort; don't crash startup over logging setup.


# Apply at import time so any module-level logging is also covered.
setup_utf8_encoding()
# Phase 4 — install the secret redactor before any of the application
# modules below have a chance to log. The filter is idempotent so it's
# safe to call again later if a worker process re-imports this file.
install_secret_redactor()


def create_app() -> FastAPI:
    Base.metadata.create_all(bind=engine)
    # create_all() only CREATES missing tables; it never ADDs columns to
    # existing ones. Run the schema guard right after so additive drift
    # (e.g. tasks.project_id) is detected and self-healed at boot — see
    # backend/app/core/schema_guard.py.
    run_schema_guard(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Validate runtime filesystem before serving requests so PermissionError
        # surfaces with structured diagnostics at startup, not on first request.
        validate_runtime_workspace()

        rows = []
        for route in app.routes:
            methods = ",".join(sorted(getattr(route, "methods", None) or []))
            rows.append(f"  {methods or 'ANY':10s}  {route.path}")
        route_list = "\n".join(sorted(rows))
        logger.info("Registered routes:\n%s", route_list)
        print(f"[startup] Registered routes:\n{route_list}", flush=True)

        # Phase 3 — start the in-process durable-job worker (unless an
        # operator runs a dedicated worker process and disables this). The
        # worker drains the execution_jobs queue: Docker builds + corrector
        # reanalysis run here instead of as fire-and-forget asyncio tasks,
        # so they survive a restart (the job row is reaped + re-run).
        worker = None
        if settings.EXECUTION_WORKER_ENABLED:
            from backend.app.workers.execution_worker import start_in_process_worker
            # Importing the handlers module registers the phase handlers.
            from backend.app.workers import handlers as _handlers  # noqa: F401
            worker = start_in_process_worker(
                poll_interval_seconds=settings.EXECUTION_JOB_POLL_INTERVAL_SECONDS,
                heartbeat_interval_seconds=settings.EXECUTION_JOB_HEARTBEAT_INTERVAL_SECONDS,
                heartbeat_timeout_seconds=settings.EXECUTION_JOB_HEARTBEAT_TIMEOUT_SECONDS,
                max_concurrency=settings.EXECUTION_WORKER_CONCURRENCY,
            )
            logger.info("[startup] in-process execution worker started: %s", worker.worker_id)
        else:
            logger.info(
                "[startup] EXECUTION_WORKER_ENABLED=false — no in-process worker; "
                "run `python -m backend.app.workers.execution_worker` separately."
            )

        try:
            yield
        finally:
            if worker is not None:
                from backend.app.workers.execution_worker import stop_in_process_worker
                logger.info("[shutdown] stopping in-process execution worker")
                await stop_in_process_worker()

    app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

    # Allow the React dev server (port 3000) and any production origin
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Ensure all JSON responses advertise UTF-8 charset so clients decode correctly.
    @app.middleware("http")
    async def set_utf8_content_type(request: Request, call_next) -> Response:
        response = await call_next(request)
        ct = response.headers.get("content-type", "")
        if "application/json" in ct and "charset" not in ct:
            response.headers["content-type"] = "application/json; charset=utf-8"
        return response

    app.include_router(api_router)

    @app.get("/")
    def root():
        return {
            "message": "DevSecOps AI Platform API is running",
            "environment": settings.APP_ENV,
        }

    @app.get("/debug/encoding", tags=["Debug"])
    def debug_encoding():
        import locale
        return {
            "stdout_encoding": getattr(sys.stdout, "encoding", "unknown"),
            "stderr_encoding": getattr(sys.stderr, "encoding", "unknown"),
            "default_encoding": sys.getdefaultencoding(),
            "locale": locale.getpreferredencoding(),
            "test_emdash": "\u2014".encode("utf-8").decode("utf-8"),
        }

    return app