from typing import Any, Dict, List, Optional, TypedDict


class OrchestratorState(TypedDict, total=False):
    prompt: str
    repo_url: Optional[str]
    repository_visibility: Optional[str]
    github_token: Optional[str]
    approved_artifacts: Optional[List[str]]
    uploaded_env_input: Optional[Dict[str, Any]]

    status: str
    logs: List[Dict[str, str]]

    repository_security: Optional[Dict[str, Any]]
    repository_analysis: Optional[Dict[str, Any]]

    repo_summary: Optional[Dict[str, Any]]
    file_tree: Optional[List[str]]
    important_files: Optional[List[str]]
    key_entrypoints: Optional[List[str]]
    categorized_files: Optional[Dict[str, Any]]
    chunks: Optional[List[Dict[str, Any]]]
    agent_context: Optional[Dict[str, Any]]
    env_security_runtime: Optional[Dict[str, Any]]

    plan: Optional[Dict[str, Any]]
    infra: Optional[Dict[str, Any]]
    cicd: Optional[Dict[str, Any]]
    security: Optional[Dict[str, Any]]
    deployment: Optional[Dict[str, Any]]
    monitoring: Optional[Dict[str, Any]]
    knowledge: Optional[Dict[str, Any]]
    validation: Optional[Dict[str, Any]]

    # Multi-phase workflow fields
    plans: Optional[List[Dict[str, Any]]]
    selected_plan: Optional[str]
    awaiting_user_input: bool
    auto_mode: bool

    # Human validation gate (Bloc 7)
    human_decision: Optional[str]   # "approved" | "rejected" | "modified"
    human_feedback: Optional[str]
    requires_user_input: bool

    cost_estimation: Optional[Dict[str, Any]]

    # Architecture Decision phase (replaces separate PLAN + COST_ESTIMATION)
    # Contains: { "plans": [...enriched strategies...], "recommended_plan": str }
    architecture_decision: Optional[Dict[str, Any]]
    # ID of the plan the user selected ("low_cost" | "balanced" | "high_performance")
    selected_plan_id: Optional[str]

    application_profile: Optional[Dict[str, Any]]

    # TerraformAgent → KubernetesAgent contract
    # Keys: cluster_endpoint, cluster_name, load_balancer_dns, ecr_repository_url
    terraform_outputs: Optional[Dict[str, Any]]

    # Phase 1 — Structured Constrained Generation trace.
    # Populated by InfrastructureAgent when the structured pipeline runs.
    # Shape mirrors ArtifactGenerationResult.model_dump():
    # {
    #   "blueprint_used": str,          # e.g. "python_fastapi_multi_stage_v1"
    #   "sections": {                   # per-section generation trace
    #     "startup": {
    #       "section_id": "startup",
    #       "variables": {"startup_command": "..."},
    #       "rendered_content": "CMD ...",
    #       "rag_sources": [...],
    #       "used_fallback": false,
    #     },
    #     ...
    #   },
    #   "validation": {                 # section-mapped validation result
    #     "valid": true,
    #     "errors": [],
    #     "warnings": [{"section_id": "user", "rule": "root_user", ...}],
    #   },
    #   "generation_metadata": {        # timing, blueprint info, fallback counts
    #     "blueprint_id": "...",
    #     "total_time_ms": 1200,
    #     "fallback_sections": 0,
    #     "rag_hits": 3,
    #   }
    # }
    infrastructure_generation: Optional[Dict[str, Any]]

    result: Optional[Dict[str, Any]]
    error_message: Optional[str]
