from typing import Any, Dict, List, Optional, TypedDict


class OrchestratorState(TypedDict, total=False):
    prompt: str
    repo_url: Optional[str]
    repository_visibility: Optional[str]
    github_token: Optional[str]
    
    status: str
    logs: List[Dict[str, str]]

    repository_security: Optional[Dict[str, Any]]

    repo_summary: Optional[Dict[str, Any]]
    file_tree: Optional[List[str]]
    important_files: Optional[List[str]]
    code_chunks: Optional[List[Dict[str, Any]]]
    agent_context: Optional[Dict[str, Any]]

    plan: Optional[Dict[str, Any]]
    infra: Optional[Dict[str, Any]]
    cicd: Optional[Dict[str, Any]]
    security: Optional[Dict[str, Any]]
    deployment: Optional[Dict[str, Any]]
    monitoring: Optional[Dict[str, Any]]
    knowledge: Optional[Dict[str, Any]]
    validation: Optional[Dict[str, Any]]

    result: Optional[Dict[str, Any]]
    error_message: Optional[str]