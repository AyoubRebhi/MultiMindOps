import io
import sys

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from backend.app.api.router import api_router
from backend.app.core.config import settings
from backend.app.database.base import Base
from backend.app.database.session import engine


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


def create_app() -> FastAPI:
    Base.metadata.create_all(bind=engine)

    app = FastAPI(title=settings.APP_NAME)

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