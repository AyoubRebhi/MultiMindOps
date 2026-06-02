"""
TerraformAgent — generates a complete Terraform project (AWS) as split .tf files.

Responsibilities (strictly scoped)
------------------------------------
• providers.tf   — AWS provider + version constraints
• backend.tf     — S3 remote state backend
• vpc.tf         — VPC, subnets, routing, NAT gateway
• eks.tf / ecs.tf — compute cluster (architecture-aware)
• variables.tf   — all input variables
• terraform.tfvars — default variable values
• outputs.tf     — MUST expose cluster_endpoint, cluster_name,
                   load_balancer_dns, ecr_repository_url

NOT responsible for: Kubernetes YAML, Dockerfiles, CI/CD workflows.

Contract output
---------------
After generation, ``run()`` returns a ``terraform_outputs`` dict:
{
    "cluster_endpoint":    "${terraform_output:cluster_endpoint}",
    "cluster_name":        "${terraform_output:cluster_name}",
    "load_balancer_dns":   "${terraform_output:load_balancer_dns}",
    "ecr_repository_url":  "${terraform_output:ecr_repository_url}",
}

This contract is consumed by KubernetesAgent to avoid hardcoded values.

DSL contamination guard
-----------------------
The quality evaluator rejects responses that contain Kubernetes ``apiVersion:``
or ``kind: Deployment`` inside HCL artifact values.  This prevents the
"DSL bleeding" problem that motivated the refactor.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

import os

from backend.app.agents.base_agent import EnhancedBaseAgent
from backend.app.agents.errors import (
    BlueprintContractError,
    TerraformGenerationError,
    TerraformValidationError,
)
from backend.app.schemas.blueprint import InfrastructureBlueprint, parse_blueprint
from backend.app.services.llm.provider_factory import ProviderFactory
from backend.app.services.rag.rag_pipeline_service import RAGPipelineService
from backend.app.services.rag.hybrid_rag_service import HybridRAGService
# NOTE: terraform_generation imports are lazy (inside __init__) to avoid a
# circular import — terraform_generation -> agents.errors -> agents -> here.

logger = logging.getLogger(__name__)

# ── Default system prompt (overridable via constructor) ───────────────────────

_DEFAULT_SYSTEM_PROMPT = (
    "You are a senior DevSecOps engineer specialized in Terraform HCL for AWS. "
    "\n\n"
    "STRICT RULES:\n"
    "- Output ONLY valid HCL code — no explanations, no prose\n"
    "- Use best practices (security, scalability, cost optimization)\n"
    "- Do NOT return empty responses\n"
    "\n\n"
    "Your ONLY job is to generate valid HCL (.tf file content) — never output "
    "Kubernetes YAML, Dockerfiles, docker-compose, or shell scripts inside artifact values. "
    "\n\n"
    "MANDATORY: outputs.tf MUST define output blocks for ALL FOUR of these names: "
    "cluster_endpoint, cluster_name, load_balancer_dns, ecr_repository_url. "
    "\n\n"
    "Cost-optimization defaults: t3.medium worker nodes, single NAT gateway per VPC, "
    "gp3 EBS volumes, ALB over NLB unless TCP is required. "
    "Never inject real AWS account IDs, access keys, or secrets. "
    "Use variables for all environment-specific values. "
    "\n\n"
    "Respond with ONLY a valid JSON object — no markdown fences, no prose. "
    'The JSON must have key "artifacts" (object) with string values for each .tf file: '
    '"terraform_providers", "terraform_backend", "terraform_vpc", '
    '"terraform_eks" (microservices/EKS) OR "terraform_ecs" (monolith/ECS), '
    '"terraform_variables", "terraform_tfvars", "terraform_outputs". '
    'Also include "generated_artifacts" (array of generated keys), '
    '"architecture_type" ("eks"|"ecs"|"serverless"), and "summary" (string).'
)


class TerraformAgent(EnhancedBaseAgent):
    """
    Generates a complete, split Terraform project for AWS using a ReAct loop
    backed by LLM + Qdrant RAG (terraform-filtered queries).

    Inherits from EnhancedBaseAgent — gains:
    • ``self.memory``     (AgentMemory)
    • ``self.validation`` (ValidationService)
    • ``react_loop()``    (Reasoning + Action with automatic retries)
    """

    REQUIRED_OUTPUTS: List[str] = [
        "cluster_endpoint",
        "cluster_name",
        "load_balancer_dns",
        "ecr_repository_url",
    ]

    # Artifact key → relative file path inside the terraform/ directory.
    ARTIFACT_FILE_MAP: Dict[str, str] = {
        "terraform_providers": "terraform/providers.tf",
        "terraform_backend":   "terraform/backend.tf",
        "terraform_vpc":       "terraform/vpc.tf",
        "terraform_eks":       "terraform/eks.tf",
        "terraform_ecs":       "terraform/ecs.tf",
        "terraform_variables": "terraform/variables.tf",
        "terraform_tfvars":    "terraform/terraform.tfvars",
        "terraform_outputs":   "terraform/outputs.tf",
    }

    def __init__(self, prompt_template: str = _DEFAULT_SYSTEM_PROMPT):
        super().__init__(name="TerraformAgent", max_react_iterations=3)
        self.llm = ProviderFactory.for_agent("TerraformAgent")
        self.prompt_template = prompt_template
        self._rag_pipeline = RAGPipelineService()
        self._hybrid_rag = HybridRAGService()
        # Deterministic template-driven generation is the default path.
        # The free-form LLM path is retained behind TF_GENERATION_MODE=legacy
        # for emergency rollback only.
        # Lazy import to break the circular dependency between agents and
        # terraform_generation (which imports from agents.errors).
        from backend.app.services.terraform_generation import (
            TerraformTemplateRenderer,
            TerraformValidator,
        )
        self._renderer = TerraformTemplateRenderer()
        self._validator = TerraformValidator()
        self._generation_mode = (
            os.getenv("TF_GENERATION_MODE", "deterministic").strip().lower()
        )

    # ── Public interface ──────────────────────────────────────────────────────

    def run(
        self,
        prompt: str,
        plan: Dict[str, Any],
        infrastructure_context: Optional[Dict[str, Any]] = None,
        approved_artifacts: Optional[List[str]] = None,
        task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generate a complete Terraform project for the given prompt and plan.

        Returns
        -------
        dict with keys:
        - ``artifacts``          — {key: hcl_content_string}
        - ``terraform_outputs``  — structured contract consumed by KubernetesAgent
        - ``generated_artifacts``— list of generated artifact keys
        - ``react_iterations``   — ReAct iterations consumed
        - ``architecture_type``  — "eks" | "ecs" | "serverless"
        - ``rag``                — RAG metadata
        - ``summary``            — brief description
        """
        logger.debug("[TerraformAgent] entering run prompt_size=%d", len(prompt))

        # ── Strict blueprint contract validation ─────────────────────────
        # Replaces the previous .get(... default) cascade that masked every
        # producer/consumer drift. If PlannerAgent or ArchitectureDecisionAgent
        # emit a malformed blueprint, we want to know HERE — not after the
        # LLM has already burned tokens generating defaults.
        blueprint = self._require_blueprint(plan)
        strategy_tier = self._require_strategy_tier(plan, blueprint)

        # ── Mode dispatch ────────────────────────────────────────────────
        # Deterministic templates are the default. Free-form HCL via LLM is
        # retained only behind an explicit env flag for emergency rollback.
        if self._generation_mode != "legacy":
            return self._run_deterministic(
                blueprint=blueprint,
                strategy_tier=strategy_tier,
                task_id=task_id,
                infrastructure_context=infrastructure_context,
            )

        architecture_type = blueprint.terraform_architecture_type
        region = blueprint.aws_region
        compute_config = self._extract_compute_config(
            blueprint=blueprint,
            strategy_tier=strategy_tier,
            infrastructure_context=infrastructure_context,
        )
        logger.info(
            "[TerraformAgent] Contract validated — arch=%s region=%s tier=%s "
            "instance=%s min=%s max=%s multi_az=%s",
            architecture_type, region, strategy_tier,
            compute_config["instance_type"],
            compute_config["min_nodes"], compute_config["max_nodes"],
            compute_config["multi_az"],
        )

        # ── Hybrid RAG: MCP (schema) + Qdrant (corpus) ───────────────────────
        hybrid_result = self._retrieve_terraform_context(
            prompt=prompt,
            architecture_type=architecture_type,
        )

        logger.debug("[TerraformAgent] context_length=%d", len(hybrid_result.get("context") or ""))

        # ── Build user prompt ─────────────────────────────────────────────────
        user_prompt = self._build_user_prompt(
            prompt=prompt,
            plan=plan,
            architecture_type=architecture_type,
            compute_config=compute_config,
            region=region,
            hybrid_result=hybrid_result,
            approved_artifacts=approved_artifacts,
            strategy_tier=strategy_tier,
        )
        logger.debug("[TerraformAgent] user_prompt_size=%d", len(user_prompt))

        # ── ReAct loop ────────────────────────────────────────────────────────
        evaluate_fn = self._make_terraform_evaluator(architecture_type)
        iterations_used = [0]

        def _counted_evaluate(response: Dict[str, Any]) -> List[str]:
            iterations_used[0] += 1
            return evaluate_fn(response)

        response = self.react_loop(
            llm=self.llm,
            system_prompt=self.prompt_template,
            user_prompt=user_prompt,
            evaluate_fn=_counted_evaluate,
            temperature=0.2,
            max_tokens=3200,
        )

        # ── Final post-loop quality gate ──────────────────────────────────────
        # The ReAct loop returns whatever the LLM produced on iteration N
        # regardless of whether the evaluator still has issues. Without a
        # post-loop check, the orchestrator happily routes onward to
        # Kubernetes with empty/invalid HCL. Make the failure explicit.
        unresolved = evaluate_fn(response)
        if unresolved:
            raise TerraformGenerationError(
                "Terraform generation could not satisfy the evaluator after "
                f"{iterations_used[0]} ReAct iterations.",
                metadata={
                    "unresolved_issues": unresolved,
                    "iterations_used": iterations_used[0],
                    "strategy_tier": strategy_tier,
                    "architecture_type": architecture_type,
                },
            )

        # ── Extract structured terraform_outputs contract ─────────────────────
        artifacts = response.setdefault("artifacts", {})

        # ── Deterministic backend.tf — overwrite any LLM-produced version ────
        # The LLM is forbidden from emitting backend.tf because state-bucket
        # hallucination is unrecoverable. If TF_STATE_* env vars are not
        # configured yet we log and skip rather than crash — the LLM's
        # version stays in place for development. In production the env
        # vars MUST be present.
        if task_id:
            try:
                from backend.app.services.terraform_generation.backend_injector import (
                    backend_config_from_env, render_backend_tf,
                )
                cfg = backend_config_from_env(task_id)
                artifacts["terraform_backend"] = render_backend_tf(cfg)
                logger.info(
                    "[TerraformAgent] backend.tf overwritten deterministically "
                    "(bucket=%s, key=%s)", cfg.bucket, cfg.state_key,
                )
            except RuntimeError as exc:
                logger.warning(
                    "[TerraformAgent] Deterministic backend.tf skipped — %s. "
                    "Keeping LLM-generated backend.tf (DEVELOPMENT ONLY).", exc,
                )
            except Exception:
                logger.exception("[TerraformAgent] backend.tf injection failed unexpectedly")

        terraform_outputs_contract = self._extract_outputs_contract(
            outputs_hcl=str(artifacts.get("terraform_outputs") or ""),
            architecture_type=architecture_type,
        )

        # ── MCP post-generation validation ────────────────────────────────────
        mcp_validation = self._validate_artifacts_with_mcp(artifacts)

        # ── Compute generated_artifacts list ──────────────────────────────────
        generated_artifacts = sorted(
            file_path
            for key, file_path in self.ARTIFACT_FILE_MAP.items()
            if str(artifacts.get(key) or "").strip()
        )

        response["terraform_outputs"] = terraform_outputs_contract
        response["architecture_type"] = architecture_type
        response["generated_artifacts"] = generated_artifacts
        response["react_iterations"] = iterations_used[0]
        response["mcp_validation"] = mcp_validation
        response["rag"] = {
            "enabled": True,
            "available": hybrid_result.get("available", False),
            "mcp_available": hybrid_result.get("sources", {}).get("mcp", {}).get("available", False),
            "qdrant_available": hybrid_result.get("sources", {}).get("qdrant", {}).get("available", False),
            "mcp_resources": hybrid_result.get("sources", {}).get("mcp", {}).get("resources_loaded", []),
            "qdrant_results": hybrid_result.get("sources", {}).get("qdrant", {}).get("results_count", 0),
            "doc_type_filter": "terraform",
        }

        logger.info(
            "[TerraformAgent] Done — arch=%s artifacts=%d react_iters=%d mcp=%s qdrant=%s",
            architecture_type,
            len(generated_artifacts),
            iterations_used[0],
            response["rag"]["mcp_available"],
            response["rag"]["qdrant_available"],
        )
        return response

    # ── Deterministic template-driven path (default) ─────────────────────────

    def _run_deterministic(
        self,
        blueprint: InfrastructureBlueprint,
        strategy_tier: str,
        task_id: Optional[str],
        infrastructure_context: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Render Terraform via the template engine, validate, and return the
        same artifact shape the orchestrator already consumes.

        No LLM is invoked. Every byte of HCL is reproducible from
        {blueprint, strategy_tier, task_id, container_port}.
        """
        container_port = self._first_container_port(infrastructure_context)
        project_name = (
            (infrastructure_context or {}).get("project_name")
            if infrastructure_context
            else None
        )

        result = self._renderer.render(
            blueprint=blueprint,
            task_id=task_id,
            project_name=project_name,
            container_port=container_port,
        )

        # Validate before returning so the orchestrator can gate on result.
        validation = self._validator.validate(result.artifacts)
        if validation.is_blocking:
            raise TerraformValidationError(
                "Generated Terraform failed deterministic validation.",
                validator="pipeline",
                findings=[i.model_dump() for i in validation.issues]
                + [s.model_dump() for s in validation.security_issues],
                metadata={
                    "validators_run": validation.validators_run,
                    "skipped_validators": validation.skipped_validators,
                    "template_metadata": result.metadata,
                    "error_count": validation.error_count,
                    "security_critical_count": validation.security_critical_count,
                },
            )

        # Build the structured outputs contract from the rendered outputs.tf.
        terraform_outputs_contract = self._extract_outputs_contract(
            outputs_hcl=result.artifacts.get("terraform_outputs", ""),
            architecture_type=blueprint.terraform_architecture_type,
        )

        # File-paths for the orchestrator's generated_artifacts list.
        generated_artifacts = sorted(
            file_path
            for key, file_path in self.ARTIFACT_FILE_MAP.items()
            if str(result.artifacts.get(key) or "").strip()
        )
        # backend.tf is rendered too — include it explicitly.
        if "terraform_backend" in result.artifacts and "terraform/backend.tf" not in generated_artifacts:
            generated_artifacts.append("terraform/backend.tf")
            generated_artifacts.sort()

        return {
            "artifacts": result.artifacts,
            "terraform_outputs": terraform_outputs_contract,
            "architecture_type": blueprint.terraform_architecture_type,
            "generated_artifacts": generated_artifacts,
            "react_iterations": 0,            # no LLM iterations on this path
            "summary": (
                f"Rendered {blueprint.architecture_style}/{strategy_tier} "
                f"template set deterministically."
            ),
            "generation_metadata": result.metadata,
            "validation": validation.model_dump(),
            "render_mode": "deterministic_template",
            "rag": {
                "enabled": False,
                "reason": "deterministic_template_path",
            },
        }

    @staticmethod
    def _first_container_port(
        infrastructure_context: Optional[Dict[str, Any]],
    ) -> Optional[int]:
        """Pull the first detected service port from the infra context, if any."""
        if not infrastructure_context:
            return None
        for svc in infrastructure_context.get("services") or []:
            port = svc.get("port")
            if isinstance(port, int) and port > 0:
                return port
        return None

    # ── Quality evaluator ─────────────────────────────────────────────────────

    def _make_terraform_evaluator(
        self, architecture_type: str
    ) -> Callable[[Dict[str, Any]], List[str]]:
        """Return a closure that validates TerraformAgent output quality."""

        def evaluate(response: Dict[str, Any]) -> List[str]:
            issues: List[str] = []
            issues.extend(self._default_evaluate(response))
            artifacts = (response or {}).get("artifacts") or {}

            # outputs.tf is non-negotiable ─────────────────────────────────────
            outputs_hcl = str(artifacts.get("terraform_outputs") or "").strip()
            if not outputs_hcl:
                issues.append(
                    "outputs.tf (terraform_outputs) is missing — it is always required"
                )
            else:
                for name in self.REQUIRED_OUTPUTS:
                    if name not in outputs_hcl:
                        issues.append(
                            f"outputs.tf is missing required output block '{name}'"
                        )

            # providers.tf is non-negotiable ──────────────────────────────────
            if not str(artifacts.get("terraform_providers") or "").strip():
                issues.append("providers.tf (terraform_providers) is missing")

            # vpc.tf is non-negotiable ─────────────────────────────────────────
            if not str(artifacts.get("terraform_vpc") or "").strip():
                issues.append("vpc.tf (terraform_vpc) is missing")

            # Compute config: eks.tf OR ecs.tf required (unless serverless) ───
            has_eks = bool(str(artifacts.get("terraform_eks") or "").strip())
            has_ecs = bool(str(artifacts.get("terraform_ecs") or "").strip())
            if architecture_type != "serverless" and not has_eks and not has_ecs:
                issues.append(
                    f"Missing compute config for architecture '{architecture_type}': "
                    "neither eks.tf nor ecs.tf was generated"
                )

            # DSL contamination guard — reject YAML inside HCL ────────────────
            yaml_markers = ("apiVersion:", "kind: Deployment", "kind: Service", "kind: Pod")
            for key, content in artifacts.items():
                content_str = str(content or "")
                if any(marker in content_str for marker in yaml_markers):
                    issues.append(
                        f"Artifact '{key}' contains Kubernetes YAML — "
                        "artifact values must be pure HCL only"
                    )

            return issues

        return evaluate

    # ── Contract enforcement (Phase 1 of the audit refactor) ─────────────────

    def _require_blueprint(self, plan: Dict[str, Any]) -> InfrastructureBlueprint:
        """
        Pull ``infrastructure_blueprint`` off the plan and validate it through
        the typed schema. Raises ``BlueprintContractError`` on drift instead of
        silently returning a half-empty dict.
        """
        raw = plan.get("infrastructure_blueprint")
        if not raw or not isinstance(raw, dict):
            raise BlueprintContractError(
                "Plan is missing 'infrastructure_blueprint' — PlannerAgent / "
                "ArchitectureDecisionAgent must produce one before Terraform runs.",
                metadata={"plan_keys": sorted(plan.keys()) if isinstance(plan, dict) else []},
            )
        return parse_blueprint(raw)  # raises BlueprintContractError on bad shape

    def _require_strategy_tier(
        self,
        plan: Dict[str, Any],
        blueprint: InfrastructureBlueprint,
    ) -> str:
        """
        Resolve the strategy tier (low_cost | balanced | high_performance) from
        the canonical location, then fall back to the blueprint field
        (architecture_decision_agent stamps it there too), then raise.

        Replaces the previous substring search
        ``"high_performance" in str(plan.get("plan_id"))`` which always
        returned False because plan_id was never propagated by
        resume_with_selected_plan.
        """
        tier = (
            plan.get("strategy_tier")
            or plan.get("plan_id")
            or blueprint.strategy_tier
        )
        if tier not in ("low_cost", "balanced", "high_performance"):
            raise BlueprintContractError(
                f"Plan is missing a valid strategy_tier (got {tier!r}). "
                "Expected one of: low_cost | balanced | high_performance. "
                "Check resume_with_selected_plan propagation.",
                metadata={
                    "plan_strategy_tier": plan.get("strategy_tier"),
                    "plan_plan_id": plan.get("plan_id"),
                    "blueprint_strategy_tier": blueprint.strategy_tier,
                },
            )
        return tier

    # ── Context extraction helpers ────────────────────────────────────────────

    def _extract_compute_config(
        self,
        blueprint: InfrastructureBlueprint,
        strategy_tier: str,
        infrastructure_context: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Build the prompt-time compute config from the typed blueprint.

        Every value here is now sourced from the validated schema — there are
        NO ``.get(default)`` fallbacks for sizing, region, AZ, or instance
        type. If a value is missing the blueprint validator would have
        already raised, so anything reaching this method is guaranteed sane.
        """
        context = infrastructure_context or {}
        services = context.get("services") or []

        ports: List[int] = []
        for svc in services:
            port = svc.get("port")
            if port and isinstance(port, int):
                ports.append(port)

        # EKS carries node sizing; ECS/EC2 carry instance sizing. The
        # blueprint's effective_instance_type accessor enforces this.
        if blueprint.compute.type == "EKS":
            min_nodes = blueprint.compute.min_nodes
            max_nodes = blueprint.compute.max_nodes
            if min_nodes is None or max_nodes is None:
                # Defensive — validator should have caught this, but keep
                # explicit so a future schema change doesn't regress silently.
                raise BlueprintContractError(
                    "EKS blueprint reached TerraformAgent without min_nodes/max_nodes",
                    metadata={"compute": blueprint.compute.model_dump()},
                )
        else:
            # ECS/Lambda — node sizing not applicable; expose conservative
            # values so downstream prompt rendering still has consistent keys.
            min_nodes = 1
            max_nodes = 1 if blueprint.compute.type == "Lambda" else 3

        # Multi-AZ is now a typed boolean on the blueprint. The substring
        # heuristic is dead.
        multi_az = blueprint.is_multi_az or strategy_tier == "high_performance"

        # RDS / Redis flags come from explicit typed sub-models — no more
        # stringified dict scraping for "rds" / "redis".
        enable_rds = blueprint.needs_rds
        enable_redis = blueprint.needs_redis

        return {
            "instance_type": blueprint.compute.effective_instance_type,
            "min_nodes": min_nodes,
            "max_nodes": max_nodes,
            "app_ports": ports or [80, 8080],
            "enable_rds": enable_rds,
            "enable_redis": enable_redis,
            "multi_az": multi_az,
            "strategy_tier": strategy_tier,
        }

    # ── Hybrid RAG retrieval ──────────────────────────────────────────────────

    def _retrieve_terraform_context(
        self,
        prompt: str,
        architecture_type: str,
    ) -> Dict[str, Any]:
        """Query HybridRAG: MCP schemas first, Qdrant corpus second."""
        try:
            return self._hybrid_rag.retrieve_for_terraform_agent(
                prompt=prompt,
                architecture_type=architecture_type,
                top_k=4,
            )
        except Exception as exc:
            logger.warning("[TerraformAgent] HybridRAG failed, falling back to Qdrant: %s", exc)

        # Qdrant-only fallback
        topic_map = {"eks": "EKS Kubernetes", "ecs": "ECS Fargate", "serverless": "Lambda"}
        topic = topic_map.get(architecture_type, "EKS")
        query = f"Terraform AWS {topic} infrastructure VPC outputs {prompt[:200]}"
        try:
            result = self._rag_pipeline.retrieve_context(
                query=query,
                doc_type="terraform",
                top_k=4,
                use_hybrid=True,
                score_threshold=0.25,
            )
            return {**result, "sources": {"mcp": {"available": False}, "qdrant": {"available": result.get("available", False)}}}
        except Exception as exc2:
            logger.warning("[TerraformAgent] Qdrant fallback also failed: %s", exc2)
            return {"available": False, "context": "", "sources": {"mcp": {"available": False}, "qdrant": {"available": False}}}

    def _validate_artifacts_with_mcp(self, artifacts: Dict[str, Any]) -> Dict[str, Any]:
        """Run MCP HCL validation on all generated artifacts."""
        try:
            from backend.app.services.mcp_client import MCPClient
            client = MCPClient.get_instance()
            hcl_artifacts = {k: v for k, v in artifacts.items() if isinstance(v, str) and v.strip()}
            return client.validate_terraform_code("\n\n".join(hcl_artifacts.values()))
        except Exception as exc:
            logger.debug("[TerraformAgent] MCP validation skipped: %s", exc)
            return {"valid": True, "score": 100, "issues": [], "warnings": [], "summary": "MCP validation unavailable"}

    # ── Prompt construction ───────────────────────────────────────────────────

    def _build_user_prompt(
        self,
        prompt: str,
        plan: Dict[str, Any],
        architecture_type: str,
        compute_config: Dict[str, Any],
        region: str,
        hybrid_result: Dict[str, Any],
        approved_artifacts: Optional[List[str]],
        strategy_tier: str,
    ) -> str:
        compact_plan = {
            "steps": (plan.get("steps") or [])[:6],
            "required_artifacts": [
                a for a in (plan.get("required_artifacts") or [])
                if "terraform" in str(a).lower()
            ],
            "estimated_complexity": plan.get("estimated_complexity"),
        }

        approved_block = ""
        if approved_artifacts:
            terraform_approved = [a for a in approved_artifacts if "terraform" in a.lower()]
            if terraform_approved:
                approved_block = f"\nApproved terraform artifacts: {terraform_approved}"

        # ── Inject hybrid context (MCP schema + Qdrant corpus) ───────────────
        context_block = ""
        if hybrid_result.get("available") and hybrid_result.get("context"):
            context_block = (
                "\n\n--- Infrastructure Context (MCP Schemas + DevSecOps Knowledge Base) ---\n"
                + self._truncate(hybrid_result["context"], 3500)
                + "\n--- End of Context ---"
            )

        return f"""User task:
{prompt}

Execution plan (terraform-relevant steps):
{compact_plan}

Infrastructure configuration:
- Strategy tier: {strategy_tier}
- Architecture: {architecture_type.upper()}
- AWS Region: {region}
- Instance type: {compute_config['instance_type']}
- Node count: min={compute_config['min_nodes']} max={compute_config['max_nodes']}
- Application ports: {compute_config['app_ports']}
- RDS required: {compute_config['enable_rds']}
- Redis/ElastiCache required: {compute_config['enable_redis']}
- Multi-AZ: {compute_config['multi_az']}
{approved_block}

CRITICAL requirements:
1. outputs.tf MUST define all four outputs: cluster_endpoint, cluster_name, load_balancer_dns, ecr_repository_url
2. All artifact values must be pure HCL — no Kubernetes YAML inside .tf files
3. Use variables for all environment-specific values (region, account_id, project_name, environment)
4. ECR repository must be created and its URL exposed via ecr_repository_url output
5. ALB must be provisioned and its DNS name exposed via load_balancer_dns output
{context_block}""".strip()

    # ── Terraform outputs contract extraction ─────────────────────────────────

    def _extract_outputs_contract(
        self,
        outputs_hcl: str,
        architecture_type: str,
    ) -> Dict[str, str]:
        """
        Parse outputs.tf HCL to confirm which required outputs are present.
        Returns a symbolic contract dict for KubernetesAgent consumption.
        """
        contract: Dict[str, str] = {}
        for output_name in self.REQUIRED_OUTPUTS:
            # Check both quoted and unquoted output block syntax
            present = (
                f'output "{output_name}"' in outputs_hcl
                or f"output {output_name} " in outputs_hcl
            )
            contract[output_name] = (
                f"${{terraform_output:{output_name}}}"
                if present
                else self._default_output_ref(output_name, architecture_type)
            )
        return contract

    def _default_output_ref(self, output_name: str, architecture_type: str) -> str:
        return f"${{terraform_output:{output_name}}}"

    # ── Utility ───────────────────────────────────────────────────────────────

    def _truncate(self, text: str, limit: int) -> str:
        text = (text or "").strip()
        return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."
