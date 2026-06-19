"""InfraRecommendationService — deterministic AWS recommendation rules.

Phase 6 of the Analysis phase. Builds the "Infrastructure Recommendations"
section WITHOUT any AI agent or LLM call: it maps the architecture pattern +
detected stack + detected services (all already produced by the codebase
analysis) to a small, sensible set of AWS building blocks.

Example:
    Spring Boot + PostgreSQL  →  ECS Fargate · RDS PostgreSQL · ALB

The output groups mirror the frontend panel: a headline ``aws_services`` list
plus ``compute`` / ``storage`` / ``networking`` / ``observability``. Each entry
is ``{service, reason}``. Pure function of its inputs — same inputs, same
output, every time.
"""

from __future__ import annotations

from typing import Any, Dict, List


def _rec(service: str, reason: str) -> Dict[str, str]:
    return {"service": service, "reason": reason}


# Database engine → managed AWS data store. First match wins.
_DATABASE_RULES = [
    (("postgres", "postgresql", "psql", "rds"), "RDS (PostgreSQL)", "Managed relational database for the detected PostgreSQL workload"),
    (("mysql", "mariadb"), "RDS (MySQL)", "Managed relational database for the detected MySQL/MariaDB workload"),
    (("mongo", "mongodb", "documentdb"), "DocumentDB", "MongoDB-compatible managed document store"),
    (("dynamodb",), "DynamoDB", "Serverless key-value store detected in the codebase"),
    (("cassandra", "scylla"), "Keyspaces", "Managed Cassandra-compatible wide-column store"),
]

_CACHE_TOKENS = ("redis", "memcached", "elasticache")
_QUEUE_TOKENS = ("rabbitmq", "kafka", "sqs", "celery", "amqp")
_SEARCH_TOKENS = ("elasticsearch", "opensearch", "solr")
_OBJECT_STORE_TOKENS = ("s3", "minio", "upload", "media", "bucket")

# Web frameworks → the app serves HTTP, so it needs a load balancer + DNS.
_WEB_TOKENS = (
    "fastapi", "flask", "django", "express", "nestjs", "koa", "fastify",
    "spring", "springboot", "spring_boot", "rails", "laravel", "gin", "echo",
    "react", "vue", "angular", "next", "nuxt", "svelte", "http", "rest", "api",
)


class InfraRecommendationService:
    """Rule-based AWS recommendation builder (no AI)."""

    @staticmethod
    def recommend(
        *,
        architecture_pattern: str | None,
        application_type: str | None,
        languages: List[str] | None = None,
        frameworks: List[str] | None = None,
        services: List[Any] | None = None,
        dependencies: List[str] | None = None,
    ) -> Dict[str, Any]:
        haystack = InfraRecommendationService._build_haystack(
            architecture_pattern, application_type,
            languages, frameworks, services, dependencies,
        )

        pattern = (architecture_pattern or "").lower()
        app_type = (application_type or "").lower()
        is_serverless = "serverless" in pattern or "lambda" in haystack or "serverless" in app_type
        is_microservices = (
            "microservice" in pattern or "microservices" in app_type
            or InfraRecommendationService._service_count(services) >= 3
        )
        is_static = "static" in app_type or "static_site" in app_type or (
            InfraRecommendationService._has_any(haystack, ("react", "vue", "angular", "svelte", "next", "nuxt"))
            and not InfraRecommendationService._has_any(haystack, ("fastapi", "flask", "django", "express", "spring"))
        )
        is_web = InfraRecommendationService._has_any(haystack, _WEB_TOKENS)

        compute: List[Dict[str, str]] = []
        storage: List[Dict[str, str]] = []
        networking: List[Dict[str, str]] = []
        observability: List[Dict[str, str]] = []
        deployment_notes: List[str] = []

        # ── Compute ──────────────────────────────────────────────────────────
        if is_serverless:
            compute.append(_rec("AWS Lambda", "Event-driven / serverless workload"))
            compute.append(_rec("API Gateway", "Managed HTTP entrypoint for Lambda functions"))
            deployment_notes.append("Package functions and deploy behind API Gateway (serverless).")
        elif is_static:
            compute.append(_rec("S3 (static hosting)", "Static frontend assets served from object storage"))
            deployment_notes.append("Build static assets and host on S3 fronted by CloudFront.")
        else:
            compute.append(_rec("ECS Fargate", "Run the application as containers without managing servers"))
            if is_microservices:
                deployment_notes.append("Deploy each service as its own ECS Fargate service.")
            else:
                deployment_notes.append("Deploy as a single containerized ECS Fargate service.")

        # ── Storage / data ───────────────────────────────────────────────────
        for tokens, service, reason in _DATABASE_RULES:
            if InfraRecommendationService._has_any(haystack, tokens):
                storage.append(_rec(service, reason))
                break
        if InfraRecommendationService._has_any(haystack, _CACHE_TOKENS):
            storage.append(_rec("ElastiCache (Redis)", "In-memory cache / session store detected"))
        if is_static or InfraRecommendationService._has_any(haystack, _OBJECT_STORE_TOKENS):
            storage.append(_rec("S3", "Object storage for static assets / uploads"))
        if InfraRecommendationService._has_any(haystack, _SEARCH_TOKENS):
            storage.append(_rec("OpenSearch", "Full-text search engine detected"))

        # ── Networking ─────────────────────────────────────────────────────────
        networking.append(_rec("VPC", "Isolated network boundary for all resources"))
        if is_static:
            networking.append(_rec("CloudFront", "CDN for low-latency static delivery"))
            networking.append(_rec("Route 53", "DNS for the public site"))
        elif is_web or is_microservices:
            networking.append(_rec("Application Load Balancer", "Distribute HTTP traffic across containers"))
            networking.append(_rec("Route 53", "DNS for the public endpoint"))

        # ── Messaging (extra compute-adjacent) ──────────────────────────────────
        if InfraRecommendationService._has_any(haystack, _QUEUE_TOKENS):
            compute.append(_rec("Amazon SQS", "Decouple work with a managed message queue"))

        # ── Observability ────────────────────────────────────────────────────
        observability.append(_rec("CloudWatch", "Centralized logs, metrics and alarms"))
        if is_microservices:
            observability.append(_rec("AWS X-Ray", "Distributed tracing across services"))

        # ── Headline (the marquee picks) ─────────────────────────────────────
        aws_services = list(compute[:1] + storage[:1])
        # Always surface the public entrypoint in the headline when present.
        entry = next(
            (n for n in networking if n["service"] in ("Application Load Balancer", "CloudFront", "API Gateway")),
            None,
        )
        if entry and entry not in aws_services:
            aws_services.append(entry)
        if not aws_services:
            aws_services = compute[:1] or [_rec("ECS Fargate", "Default container compute")]

        return {
            "aws_services": aws_services,
            "compute": compute,
            "storage": storage,
            "networking": networking,
            "observability": observability,
            "deployment_notes": deployment_notes,
        }

    # ── helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _build_haystack(*groups: Any) -> str:
        parts: List[str] = []
        for group in groups:
            if group is None:
                continue
            if isinstance(group, str):
                parts.append(group)
            elif isinstance(group, (list, tuple)):
                for item in group:
                    parts.append(InfraRecommendationService._stringify(item))
            else:
                parts.append(InfraRecommendationService._stringify(group))
        return " ".join(parts).lower()

    @staticmethod
    def _stringify(item: Any) -> str:
        if isinstance(item, str):
            return item
        if isinstance(item, dict):
            # service dicts look like {"name": "...", "type": "..."}
            return " ".join(
                str(v) for v in (item.get("name"), item.get("type"), item.get("technology")) if v
            )
        return str(item)

    @staticmethod
    def _has_any(haystack: str, tokens) -> bool:
        return any(tok in haystack for tok in tokens)

    @staticmethod
    def _service_count(services: List[Any] | None) -> int:
        return len(services) if isinstance(services, list) else 0
