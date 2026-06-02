"""
PlannerAgent — produces a DevSecOps execution plan AND an Infrastructure Blueprint.

Sprint 3 note: multi-plan generation is deferred. This agent issues one
LLM call with a compressed context to stay within the Groq free-tier
12 k TPM limit (~5-7k tokens per request vs the previous ~15.6k).

Public API (unchanged)
-----------------------
``PlannerAgent.run(prompt, planner_context) → dict``
Returns the same dict shape as before PLUS ``infrastructure_blueprint`` so the
orchestrator needs no changes.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, ValidationError

from backend.app.agents.base_agent import BaseAgent
from backend.app.agents.errors import BlueprintContractError
from backend.app.agents.memory import AgentMemory
from backend.app.schemas.blueprint import parse_blueprint
from backend.app.services.core.llm_service import LLMService

logger = logging.getLogger(__name__)

# Maximum characters of planner_context forwarded to the LLM
_MAX_CONTEXT_CHARS = 500


# ── Pydantic schema ───────────────────────────────────────────────────────────


class PlannerResponseSchema(BaseModel):
    agent: str
    input_prompt: str
    steps: list[str]
    required_artifacts: list[str]
    estimated_complexity: Literal["low", "medium", "high"]
    reasoning_summary: str


# ── Agent ─────────────────────────────────────────────────────────────────────


class PlannerAgent(BaseAgent):
    """
    Generates a single standard DevSecOps execution plan per user task.

    Memory
    ------
    ``self.memory`` caches the plan per prompt hash so repeated calls with
    the same input skip the LLM entirely.
    """

    def __init__(self, prompt_template: str):
        super().__init__(name="PlannerAgent")
        self.llm = LLMService()
        self.prompt_template = prompt_template
        self.memory = AgentMemory(agent_name="PlannerAgent")

    # ── Public interface ──────────────────────────────────────────────────────

    def run(
        self,
        prompt: str,
        planner_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Generate and return a standard execution plan.

        1. Validate that application_profile is present (infrastructure-first requirement).
        2. Check memory cache.
        3. Build a compressed user prompt (~5-7k tokens total).
        4. Call LLM once (single plan, standard variant).
        5. Validate, normalise, cache, and return.
        """
        ctx = planner_context or {}
        application_profile = ctx.get("application_profile")
        logger.debug("[PlannerAgent] application_profile=%s", application_profile)
        if not application_profile:
            raise Exception(
                "Application profile missing — cannot plan infrastructure. "
                "Run CodebaseAnalysisAgent first to produce an application_profile."
            )

        compressed = self._compress_context(planner_context)
        user_prompt = f"User task:\n{prompt}\n\nRepository context:\n{compressed}"

        # ── Memory cache check ────────────────────────────────────────────────
        cached = self.memory.recall(user_prompt)
        if cached and cached.confidence >= 0.7:
            logger.info("[PlannerAgent] Cache hit — returning memorised plan")
            return cached.output

        plan = self._single_plan(prompt, user_prompt)
        normalised = self._normalize_plan(plan, prompt=prompt, planner_context=planner_context)

        blueprint, arch_note = self._build_infrastructure_blueprint(planner_context)
        normalised["infrastructure_blueprint"] = blueprint
        existing_summary = normalised.get("reasoning_summary") or ""
        normalised["reasoning_summary"] = (
            f"{existing_summary}  {arch_note}".strip() if existing_summary else arch_note
        )

        self.memory.remember(user_prompt, normalised, confidence=0.9)
        return normalised

    # ── Single-plan generation ────────────────────────────────────────────────

    def _single_plan(self, prompt: str, user_prompt: str) -> Dict[str, Any]:
        """Issue one LLM call and return the validated plan dict."""
        response = self.llm.chat_json(
            system_prompt=self.prompt_template,
            user_prompt=user_prompt,
            temperature=0.1,
            max_tokens=900,
        )

        if "ERROR" in response or "error" in response:
            raise ValueError(f"Planner provider returned an error payload: {response}")

        try:
            validated = PlannerResponseSchema.model_validate(response)
        except ValidationError as exc:
            raise ValueError(
                f"Planner returned an invalid JSON structure: {exc}"
            ) from exc

        return validated.model_dump()

    # ── Context compression ───────────────────────────────────────────────────

    @staticmethod
    def _compress_context(planner_context: Optional[Dict[str, Any]]) -> str:
        """
        Extract the most useful fields from the planner context and
        truncate the result to _MAX_CONTEXT_CHARS characters.

        Keeps: project_type, language, security_findings, application_profile.
        Drops: verbose logs, full file trees, chunk lists, etc.
        """
        if not planner_context:
            return "{}"

        compressed: Dict[str, Any] = {}

        for key in ("project_type", "language", "framework", "runtime"):
            if planner_context.get(key):
                compressed[key] = planner_context[key]

        sec = planner_context.get("security_findings") or planner_context.get("security")
        if sec:
            sec_str = str(sec)[:200]
            compressed["security"] = sec_str
        else:
            compressed["security"] = "No issues"

        # Include application_profile for infrastructure-first planning
        profile = planner_context.get("application_profile")
        if profile:
            compressed["application_profile"] = {
                k: profile[k]
                for k in ("application_type", "scalability_level", "statefulness", "workload_profile")
                if k in profile
            }

        summary = str(compressed)
        if len(summary) > _MAX_CONTEXT_CHARS:
            summary = summary[:_MAX_CONTEXT_CHARS] + "…"
        return summary

    # ── Normalisation ─────────────────────────────────────────────────────────

    # Mandatory infrastructure-first execution steps
    _INFRA_FIRST_STEPS: List[str] = [
        "Define infrastructure using Terraform (VPC, compute, networking, storage)",
        "Create Dockerfile for application packaging",
        "Build and tag container image",
        "Define Kubernetes deployment manifests (Deployment, Service, ConfigMap)",
        "Configure GitHub Actions CI/CD pipeline for automated deployment",
        "Deploy infrastructure with terraform apply and roll out application",
    ]

    def _normalize_plan(
        self,
        plan: Dict[str, Any],
        *,
        prompt: str,
        planner_context: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        normalized = dict(plan)
        required_artifacts = [
            self._normalize_artifact_path(item)
            for item in normalized.get("required_artifacts", [])
            if str(item or "").strip()
        ]

        github_actions_only: List[str] = []
        cicd_requested = self._cicd_is_requested(prompt=prompt, planner_context=planner_context)

        for path in required_artifacts:
            if self._is_disallowed_cicd_artifact(path.lower()):
                cicd_requested = True
                continue
            github_actions_only.append(path)

        if cicd_requested and not any(
            self._is_supported_github_actions_artifact(p) for p in github_actions_only
        ):
            github_actions_only.append(".github/workflows/ci-cd.yml")

        # Enforce mandatory infrastructure-first artifacts
        github_actions_only = self._enforce_infra_artifacts(
            github_actions_only, planner_context=planner_context
        )

        normalized["required_artifacts"] = self._dedupe_preserve_order(github_actions_only)

        # Enforce infrastructure-first step ordering
        normalized["steps"] = self._enforce_infra_steps(normalized.get("steps") or [])

        return normalized

    def _enforce_infra_artifacts(
        self,
        artifacts: List[str],
        *,
        planner_context: Optional[Dict[str, Any]],
    ) -> List[str]:
        """Always include Terraform, Dockerfile, GitHub Actions. Add Kubernetes for microservices."""
        result = list(artifacts)
        profile = (planner_context or {}).get("application_profile") or {}
        app_type = profile.get("application_type") or "monolith"

        # Map profile → mandatory artifacts
        if app_type == "serverless":
            mandatory = ["terraform/main.tf", "Dockerfile", ".github/workflows/ci-cd.yml"]
        elif app_type == "microservices":
            mandatory = [
                "terraform/main.tf",
                "Dockerfile",
                "kubernetes/deployment.yaml",
                ".github/workflows/ci-cd.yml",
            ]
        else:
            # monolith / library / cli / unknown → ECS + Terraform
            mandatory = ["terraform/main.tf", "Dockerfile", ".github/workflows/ci-cd.yml"]

        existing_lower = {a.lower() for a in result}
        for artifact in mandatory:
            if artifact.lower() not in existing_lower:
                result.append(artifact)
                existing_lower.add(artifact.lower())

        return result

    def _enforce_infra_steps(self, steps: List[str]) -> List[str]:
        """Prepend mandatory infrastructure-first steps; keep any unique LLM-generated steps after."""
        # Filter out LLM steps that overlap with mandatory ones (loose match on first 25 chars)
        mandatory_prefixes = {s[:25].lower() for s in self._INFRA_FIRST_STEPS}
        extra = [
            s for s in steps
            if not any(s.lower()[:25].startswith(p[:20]) for p in mandatory_prefixes)
        ]
        return self._INFRA_FIRST_STEPS + extra

    # ── Path helpers ──────────────────────────────────────────────────────────

    def _cicd_is_requested(
        self,
        *,
        prompt: str,
        planner_context: Optional[Dict[str, Any]],
    ) -> bool:
        text = f"{prompt}\n{planner_context or {}}".lower()
        return any(
            marker in text
            for marker in (
                "ci/cd", "cicd", "pipeline", "github actions", "workflow",
                "jenkins", "gitlab ci", "azure pipelines", "circleci",
            )
        )

    def _normalize_artifact_path(self, path: str) -> str:
        lowered = str(path).replace("\\", "/").strip()
        if self._is_supported_github_actions_artifact(lowered):
            return ".github/workflows/ci-cd.yml"
        return lowered

    def _is_supported_github_actions_artifact(self, path: str) -> bool:
        lowered = str(path).lower()
        return lowered.startswith(".github/workflows/") and lowered.endswith((".yml", ".yaml"))

    def _is_disallowed_cicd_artifact(self, path: str) -> bool:
        return any(
            token in path
            for token in (
                "jenkinsfile", ".gitlab-ci", "azure-pipelines",
                ".circleci/", "scripts/build.sh", "scripts/deploy.sh",
            )
        )

    # ── Infrastructure Blueprint ──────────────────────────────────────────────

    def _build_infrastructure_blueprint(
        self,
        planner_context: Optional[Dict[str, Any]],
    ) -> Tuple[Dict[str, Any], str]:
        """
        Build a deterministic AWS infrastructure blueprint from the application
        profile embedded in planner_context.  Raises if the profile is absent.

        Returns (blueprint_dict, reasoning_note).
        """
        ctx = planner_context or {}
        profile: Dict[str, Any] = ctx.get("application_profile") or {}

        if not profile:
            raise Exception(
                "Application profile missing — cannot build infrastructure blueprint. "
                "Run CodebaseAnalysisAgent first to produce an application_profile."
            )

        # ── Extract profile fields ────────────────────────────────────────
        app_type = profile.get("application_type") or "monolith"
        scalability = profile.get("scalability_level") or "medium"
        statefulness = profile.get("statefulness") or "stateless"
        workload = profile.get("workload_profile") or "io_bound"
        detected_services: List[str] = profile.get("detected_services") or []

        logger.info(
            "[PlannerAgent] Blueprint — architecture_type=%s scalability=%s statefulness=%s",
            app_type, scalability, statefulness,
        )

        # ── Deterministic mapping ─────────────────────────────────────────
        blueprint = self._map_to_blueprint(
            app_type=app_type,
            scalability=scalability,
            statefulness=statefulness,
            workload=workload,
            detected_services=detected_services,
        )
        compute_type = blueprint.get("compute", {}).get("type", "unknown")
        logger.info(
            "[PlannerAgent] Blueprint — compute=%s scaling_strategy=%s",
            compute_type,
            blueprint.get("scaling", {}).get("strategy"),
        )

        # ── Optional LLM refinement ───────────────────────────────────────
        blueprint = self._refine_blueprint_with_llm(blueprint, profile)

        # ── Inject aws_region so the contract is complete ────────────────
        # Previously TerraformAgent silently defaulted this to "us-east-1"
        # via .get(). Now it is part of the blueprint itself.
        blueprint.setdefault("aws_region", "us-east-1")

        # ── Strict contract validation (typed Pydantic) ──────────────────
        # parse_blueprint raises BlueprintContractError on any drift —
        # catches the historical "PlannerAgent emits compute.type but
        # TerraformAgent reads compute_type" class of bug at the source.
        try:
            validated = parse_blueprint(blueprint)
        except BlueprintContractError:
            logger.exception(
                "[PlannerAgent] Blueprint failed contract validation — "
                "raising to caller (no silent fallback)."
            )
            raise
        # Re-emit the dict so downstream legacy consumers keep working.
        blueprint = validated.model_dump(mode="json", exclude_none=True)

        # ── Reasoning note explaining Terraform and Kubernetes choices ────
        terraform_reason = (
            "Terraform is used for reproducible, version-controlled infrastructure provisioning "
            f"of a {app_type} application on AWS."
        )
        if compute_type == "EKS":
            k8s_reason = (
                " Kubernetes (EKS) is selected because the microservices architecture requires "
                "container orchestration, horizontal pod autoscaling, and service mesh isolation."
            )
        elif compute_type == "Lambda":
            k8s_reason = (
                " Kubernetes is not used — serverless Lambda removes container orchestration overhead "
                "and provides fully managed scaling via API Gateway."
            )
        else:
            k8s_reason = (
                " ECS is used instead of full Kubernetes because the monolith architecture "
                "does not require the additional complexity of cluster management."
            )

        note = (
            f"Infrastructure blueprint: {blueprint['architecture_style']} architecture "
            f"with {compute_type} compute and {blueprint['scaling']['strategy']} scaling. "
            f"{terraform_reason}{k8s_reason}"
        )
        return blueprint, note

    def _map_to_blueprint(
        self,
        app_type: str,
        scalability: str,
        statefulness: str,
        workload: str,
        detected_services: List[str],
    ) -> Dict[str, Any]:
        has_relational_db = any(
            s in detected_services
            for s in ("postgresql", "mysql", "mariadb", "mssql", "sqlite")
        )
        has_nosql = any(s in detected_services for s in ("mongodb", "dynamodb", "firestore"))
        has_cache = any(s in detected_services for s in ("redis", "memcached", "valkey"))

        if app_type == "serverless":
            return self._serverless_blueprint(has_relational_db, has_nosql)
        if app_type == "microservices":
            return self._microservices_blueprint(scalability, has_cache, has_relational_db)
        # monolith / library / cli / unknown
        return self._monolith_blueprint(scalability, statefulness)

    @staticmethod
    def _monolith_blueprint(scalability: str, statefulness: str) -> Dict[str, Any]:
        multi_az = scalability != "low"
        return {
            "compute": {
                "type": "ECS",
                "instance_type": "t3.small" if scalability == "low" else "t3.medium",
            },
            "database": {
                "engine": "PostgreSQL",
                "deployment": "RDS Multi-AZ" if multi_az else "RDS Single-AZ",
            },
            "networking": {
                "vpc": True,
                "multi_az": multi_az,
                "load_balancer": "ALB",
            },
            "storage": {
                "object_storage": "S3",
                "block_storage": "EBS",
            },
            "scaling": {
                "strategy": "vertical" if scalability == "low" else "vertical+horizontal",
                "auto_scaling": scalability != "low",
            },
            "architecture_style": "monolith",
        }

    @staticmethod
    def _microservices_blueprint(
        scalability: str,
        has_cache: bool,
        has_relational_db: bool,
    ) -> Dict[str, Any]:
        high = scalability == "high"
        blueprint: Dict[str, Any] = {
            "compute": {
                "type": "EKS",
                "node_type": "t3.medium",
                "min_nodes": 3 if high else 2,
                "max_nodes": 10 if high else 5,
            },
            "database": {
                "engine": "PostgreSQL" if has_relational_db else "Aurora",
                "deployment": "RDS Multi-AZ",
                "read_replicas": high,
            },
            "networking": {
                "vpc": True,
                "multi_az": True,
                "load_balancer": "ALB",
            },
            "storage": {
                "object_storage": "S3",
                "block_storage": "EBS",
            },
            "scaling": {
                "strategy": "horizontal",
                "auto_scaling": True,
            },
            "architecture_style": "microservices",
        }
        if has_cache:
            blueprint["cache"] = {"engine": "Redis", "deployment": "ElastiCache"}
        return blueprint

    @staticmethod
    def _serverless_blueprint(has_relational_db: bool, has_nosql: bool) -> Dict[str, Any]:
        db_engine = "Aurora Serverless" if has_relational_db else "DynamoDB"
        return {
            "compute": {
                "type": "Lambda",
                "runtime": "managed",
            },
            "database": {
                "engine": db_engine,
                "deployment": "serverless",
            },
            "networking": {
                "vpc": False,
                "multi_az": True,
                "load_balancer": "API Gateway",
            },
            "storage": {
                "object_storage": "S3",
            },
            "scaling": {
                "strategy": "fully_managed",
                "auto_scaling": True,
            },
            "architecture_style": "serverless",
        }

    def _refine_blueprint_with_llm(
        self,
        blueprint: Dict[str, Any],
        application_profile: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Optionally call the LLM to refine instance types and add improvements.
        Falls back to the deterministic blueprint on any error.
        """
        if not application_profile:
            return blueprint

        # Pin the deterministic architectural choices — the LLM gets to suggest
        # instance sizes and deployment flavors, but it must NOT relabel the
        # architecture style or compute type. Past incidents: Groq rewriting
        # `architecture_style` to free-form strings like 'layered' /
        # 'event-driven' that the strict Literal validator then rejects.
        pinned_arch_style = blueprint.get("architecture_style")
        pinned_compute_type = (blueprint.get("compute") or {}).get("type")

        try:
            refined = self.llm.chat_json(
                system_prompt=(
                    "You are an AWS cloud architect. "
                    "Refine the given infrastructure blueprint JSON based on the application profile. "
                    "You may improve instance types, node sizes, deployment options, and scaling parameters. "
                    "You MUST NOT change `architecture_style` or `compute.type` — those are fixed. "
                    "`architecture_style` must remain exactly one of: 'monolith', 'microservices', 'serverless'. "
                    "Return ONLY the updated JSON object with the same keys. No prose or markdown."
                ),
                user_prompt=(
                    f"Application profile:\n{json.dumps(application_profile, ensure_ascii=False)}\n\n"
                    f"Current blueprint:\n{json.dumps(blueprint, ensure_ascii=False)}\n\n"
                    "Return the refined blueprint JSON."
                ),
                temperature=0.2,
                max_tokens=600,
            )
            # Accept only if it preserves required top-level keys
            required = {"compute", "database", "networking", "scaling", "architecture_style"}
            if isinstance(refined, dict) and required.issubset(refined.keys()):
                # Force the pinned values back, regardless of what the LLM did.
                if pinned_arch_style is not None:
                    refined["architecture_style"] = pinned_arch_style
                if pinned_compute_type is not None:
                    refined.setdefault("compute", {})["type"] = pinned_compute_type
                logger.debug("[PlannerAgent] LLM blueprint refinement accepted (arch_style/compute.type pinned).")
                return refined
            logger.warning("[PlannerAgent] LLM blueprint refinement returned unexpected shape — ignoring.")
        except Exception as exc:
            logger.warning(
                "[PlannerAgent] LLM blueprint refinement failed (%s) — using deterministic blueprint.", exc
            )
        return blueprint

    # ── Deduplication ─────────────────────────────────────────────────────────

    def _dedupe_preserve_order(self, items: List[str]) -> List[str]:
        seen: set[str] = set()
        result: List[str] = []
        for item in items:
            if item in seen:
                continue
            seen.add(item)
            result.append(item)
        return result
