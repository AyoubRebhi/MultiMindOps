from typing import Any, Dict, List, Optional, TypedDict


class OrchestratorState(TypedDict, total=False):
    prompt: str
    status: str
    logs: List[Dict[str, str]]
    plan: Optional[Dict[str, Any]]
    infra: Optional[Dict[str, Any]]
    result: Optional[Dict[str, Any]]
    error_message: Optional[str]