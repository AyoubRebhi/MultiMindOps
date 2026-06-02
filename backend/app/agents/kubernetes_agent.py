"""
KubernetesAgent — generates Kubernetes YAML manifests that consume
TerraformAgent outputs instead of hardcoded values.

Responsibilities (strictly scoped)
------------------------------------
• deployment.yaml — Deployment manifest using ECR image URL from terraform_outputs
• service.yaml    — Service manifest referencing ALB/cluster from terraform_outputs

Inputs
------
• terraform_outputs   — structured contract from TerraformAgent:
    {
        "cluster_endpoint":   "${terraform_output:cluster_endpoint}",
        "cluster_name":       "${terraform_output:cluster_name}",
        "load_balancer_dns":  "${terraform_output:load_balancer_dns}",
        "ecr_repository_url": "${terraform_output:ecr_repository_url}",
    }
• app_config          — application metadata (ports, replicas, labels, env_vars)
• plan                — optional plan dict for context

Contract enforcement
--------------------
The quality evaluator REJECTS responses that:
• Use hardcoded ECR URLs (e.g. ``12345.dkr.ecr.us-east-1``) instead of
  the terraform_output reference
• Contain Terraform HCL (``resource "aws_``) inside YAML values
• Are missing either deployment.yaml or service.yaml
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from backend.app.agents.base_agent import EnhancedBaseAgent
from backend.app.services.llm.provider_factory import ProviderFactory
from backend.app.services.rag.rag_pipeline_service import RAGPipelineService

logger = logging.getLogger(__name__)

_DEFAULT_SYSTEM_PROMPT = (
    "You are a senior DevSecOps engineer specialized in Kubernetes manifests for AWS EKS. "
    "\n\n"
    "STRICT RULES:\n"
    "- Output ONLY valid YAML manifests — no explanations, no prose\n"
    "- Use best practices (security, scalability, resource limits)\n"
    "- Do NOT return empty responses\n"
    "\n\n"
    "Your ONLY job is to generate valid Kubernetes YAML manifests. "
    "Never output Terraform HCL, Dockerfiles, or shell scripts. "
    "\n\n"
    "MANDATORY: Use the terraform_outputs values provided for all infrastructure references. "
    "Container image MUST reference ecr_repository_url from terraform_outputs. "
    "Do not hardcode AWS account IDs, region suffixes, cluster endpoints, or registry URLs. "
    "\n\n"
    "Use the notation ${terraform_output:OUTPUT_NAME} for any value that comes from Terraform. "
    "Add a comment next to each such reference: "
    "# Resolved at deploy time from: terraform output OUTPUT_NAME"
    "\n\n"
    "Always include resource requests/limits and a liveness probe. "
    "Respond with ONLY a valid JSON object — no markdown, no prose, no code fences. "
    'The JSON must have key "artifacts" (object) with: '
    '"kubernetes_deployment" (string: deployment.yaml content), '
    '"kubernetes_service" (string: service.yaml content). '
    'Also include "generated_artifacts" (array) and "summary" (string).'
)


class KubernetesAgent(EnhancedBaseAgent):
    """
    Generates Kubernetes manifests that reference TerraformAgent outputs
    via the structured terraform_outputs contract.

    Inherits from EnhancedBaseAgent — gains:
    • ``self.memory``     (AgentMemory)
    • ``self.validation`` (ValidationService)
    • ``react_loop()``    (Reasoning + Action with automatic retries)
    """

    ARTIFACT_FILE_MAP: Dict[str, str] = {
        "kubernetes_deployment": "kubernetes/deployment.yaml",
        "kubernetes_service":    "kubernetes/service.yaml",
    }

    def __init__(self, prompt_template: str = _DEFAULT_SYSTEM_PROMPT):
        super().__init__(name="KubernetesAgent", max_react_iterations=2)
        self.llm = ProviderFactory.for_agent("KubernetesAgent")
        self.prompt_template = prompt_template
        self._rag_pipeline = RAGPipelineService()

    # ── Public interface ──────────────────────────────────────────────────────

    def run(
        self,
        terraform_outputs: Dict[str, str],
        app_config: Dict[str, Any],
        plan: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Generate Kubernetes manifests that consume the given terraform_outputs.

        Parameters
        ----------
        terraform_outputs:
            Structured contract from TerraformAgent — must contain
            ``cluster_endpoint``, ``cluster_name``, ``load_balancer_dns``,
            ``ecr_repository_url``.
        app_config:
            Application metadata extracted by the orchestrator:
            ``app_name``, ``ports``, ``replicas``, ``env_vars``, ``namespace``.
        plan:
            Optional plan dict for additional context.

        Returns
        -------
        dict with:
        - ``artifacts``           — {key: yaml_content_string}
        - ``generated_artifacts`` — list of generated file paths
        - ``react_iterations``    — ReAct iterations consumed
        - ``rag``                 — RAG metadata
        - ``summary``             — brief description
        """
        logger.debug(
            "[KubernetesAgent] entering run terraform_outputs_length=%d",
            len(str(terraform_outputs)),
        )

        # ── RAG: kubernetes-filtered retrieval ────────────────────────────────
        rag_result = self._retrieve_k8s_context(app_config)

        # ── Build user prompt ─────────────────────────────────────────────────
        user_prompt = self._build_user_prompt(
            terraform_outputs=terraform_outputs,
            app_config=app_config,
            plan=plan,
            rag_result=rag_result,
        )
        logger.debug("[KubernetesAgent] user_prompt_size=%d", len(user_prompt))

        # ── ReAct loop ────────────────────────────────────────────────────────
        evaluate_fn = self._make_k8s_evaluator()
        iterations_used = [0]

        def _counted_evaluate(response: Dict[str, Any]) -> List[str]:
            iterations_used[0] += 1
            return evaluate_fn(response)

        response = self.react_loop(
            llm=self.llm,
            system_prompt=self.prompt_template,
            user_prompt=user_prompt,
            evaluate_fn=_counted_evaluate,
            temperature=0.1,
            max_tokens=2000,
        )

        # ── Compute generated_artifacts list ──────────────────────────────────
        artifacts = response.setdefault("artifacts", {})
        generated_artifacts = sorted(
            file_path
            for key, file_path in self.ARTIFACT_FILE_MAP.items()
            if str(artifacts.get(key) or "").strip()
        )

        response["generated_artifacts"] = generated_artifacts
        response["react_iterations"] = iterations_used[0]
        response["rag"] = {
            "enabled": True,
            "available": rag_result.get("available", False),
            "doc_type_filter": "k8s",
            "results_count": len(rag_result.get("results") or []),
        }

        logger.info(
            "[KubernetesAgent] Done — artifacts=%d react_iters=%d",
            len(generated_artifacts),
            iterations_used[0],
        )
        return response

    # ── Quality evaluator ─────────────────────────────────────────────────────

    def _make_k8s_evaluator(self) -> Callable[[Dict[str, Any]], List[str]]:
        """Return a closure that validates KubernetesAgent output quality."""
        def evaluate(response: Dict[str, Any]) -> List[str]:
            issues: List[str] = []
            issues.extend(self._default_evaluate(response))
            artifacts = (response or {}).get("artifacts") or {}

            # deployment.yaml — required ───────────────────────────────────────
            deployment = str(artifacts.get("kubernetes_deployment") or "").strip()
            if not deployment:
                issues.append("kubernetes_deployment (deployment.yaml) is missing")
            else:
                if "apiVersion" not in deployment:
                    issues.append("deployment.yaml is missing 'apiVersion' field")
                if "kind: Deployment" not in deployment:
                    issues.append("deployment.yaml is missing 'kind: Deployment'")
                if "containers:" not in deployment and "container:" not in deployment:
                    issues.append("deployment.yaml is missing a 'containers' spec")
                # Ensure ECR ref used, not a hardcoded URL
                if _looks_hardcoded_ecr(deployment):
                    issues.append(
                        "deployment.yaml contains a hardcoded ECR URL — "
                        "use ${terraform_output:ecr_repository_url} instead"
                    )

            # service.yaml — required ─────────────────────────────────────────
            service = str(artifacts.get("kubernetes_service") or "").strip()
            if not service:
                issues.append("kubernetes_service (service.yaml) is missing")
            else:
                if "kind: Service" not in service:
                    issues.append("service.yaml is missing 'kind: Service'")

            # DSL contamination guard — reject HCL inside YAML ────────────────
            hcl_markers = ('resource "aws_', "terraform {", 'provider "aws"')
            for key, content in artifacts.items():
                content_str = str(content or "")
                if any(marker in content_str for marker in hcl_markers):
                    issues.append(
                        f"Artifact '{key}' contains Terraform HCL — "
                        "must be pure Kubernetes YAML only"
                    )

            return issues

        return evaluate

    # ── RAG retrieval ─────────────────────────────────────────────────────────

    def _retrieve_k8s_context(self, app_config: Dict[str, Any]) -> Dict[str, Any]:
        """Query Qdrant with doc_type='k8s' filter."""
        app_name = app_config.get("app_name") or "application"
        ports = app_config.get("ports") or [8080]
        query = (
            f"Kubernetes Deployment Service manifest AWS EKS ECR "
            f"{app_name} port {ports[0] if ports else 8080}"
        )
        try:
            return self._rag_pipeline.retrieve_context(
                query=query,
                doc_type="k8s",
                top_k=3,
                use_hybrid=True,
                score_threshold=0.25,
            )
        except Exception as exc:
            logger.warning("[KubernetesAgent] RAG retrieval failed: %s", exc)
            return {"available": False, "results": [], "context": ""}

    # ── Prompt construction ───────────────────────────────────────────────────

    def _build_user_prompt(
        self,
        terraform_outputs: Dict[str, str],
        app_config: Dict[str, Any],
        plan: Optional[Dict[str, Any]],
        rag_result: Dict[str, Any],
    ) -> str:
        app_name = app_config.get("app_name") or "app"
        namespace = app_config.get("namespace") or "default"
        ports = app_config.get("ports") or [8080]
        replicas = app_config.get("replicas") or 2
        env_vars = app_config.get("env_vars") or []
        cpu_limit = app_config.get("resource_limits", {}).get("cpu") or "500m"
        mem_limit = app_config.get("resource_limits", {}).get("memory") or "512Mi"

        # Build ENV section for the prompt
        env_section = ""
        if env_vars:
            env_lines = "\n".join(f"  - {v}" for v in env_vars[:10])
            env_section = f"\nEnvironment variables (names only — no values): \n{env_lines}"

        rag_block = ""
        if rag_result.get("available") and rag_result.get("context"):
            rag_block = (
                "\n\nKubernetes best-practice templates (guidance only):\n"
                + self._truncate(rag_result["context"], 1200)
            )

        plan_context = ""
        if plan:
            plan_context = (
                f"\nPlan complexity: {plan.get('estimated_complexity', 'medium')}"
            )

        return f"""Generate Kubernetes manifests for the following application.

Application configuration:
- Name: {app_name}
- Namespace: {namespace}
- Container port(s): {ports}
- Desired replicas: {replicas}
- CPU limit: {cpu_limit}
- Memory limit: {mem_limit}
{env_section}
{plan_context}

Terraform outputs contract (use these references — do NOT hardcode values):
- ecr_repository_url: {terraform_outputs.get('ecr_repository_url', '${terraform_output:ecr_repository_url}')}
- cluster_endpoint:   {terraform_outputs.get('cluster_endpoint', '${terraform_output:cluster_endpoint}')}
- cluster_name:       {terraform_outputs.get('cluster_name', '${terraform_output:cluster_name}')}
- load_balancer_dns:  {terraform_outputs.get('load_balancer_dns', '${terraform_output:load_balancer_dns}')}

REQUIREMENTS:
1. deployment.yaml image field MUST use the ecr_repository_url reference above
2. Add comment: # Resolved at deploy time from: terraform output ecr_repository_url
3. Include liveness and readiness probes on the container port
4. Include resource requests (50% of limits) and limits as specified above
5. service.yaml type must be LoadBalancer (provisioned by the Terraform ALB)
{rag_block}""".strip()

    # ── Utility ───────────────────────────────────────────────────────────────

    def _truncate(self, text: str, limit: int) -> str:
        text = (text or "").strip()
        return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


# ── Module-level helper ───────────────────────────────────────────────────────

def _looks_hardcoded_ecr(content: str) -> bool:
    """Detect hardcoded AWS account ID patterns in ECR URLs."""
    import re
    # Pattern: 12-digit account ID in ECR URL
    return bool(re.search(r"\d{12}\.dkr\.ecr\.", content))
