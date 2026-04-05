from datetime import datetime, timezone
from typing import Any


class ExecutionTraceService:
    def build_trace_entry(
        self,
        step: str,
        status: str,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "step": step,
            "status": status,
            "details": details or {},
        }
