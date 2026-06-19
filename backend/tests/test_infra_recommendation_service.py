"""Unit tests for the deterministic InfraRecommendationService rule engine.

Pure function of its inputs (architecture pattern + stack + services) — no DB,
no LLM. Verifies the headline mappings the Analysis phase advertises.
"""

from __future__ import annotations

from backend.app.services.core.infra_recommendation_service import (
    InfraRecommendationService,
)


def _services(infra: dict, group: str) -> set[str]:
    return {r["service"] for r in infra[group]}


def test_spring_boot_plus_postgres_maps_to_fargate_rds_alb():
    infra = InfraRecommendationService.recommend(
        architecture_pattern="layered",
        application_type="monolith",
        languages=["Java"],
        frameworks=["Spring Boot"],
        services=[{"name": "postgres", "type": "database"}],
        dependencies=["Maven"],
    )
    assert "ECS Fargate" in _services(infra, "compute")
    assert "RDS (PostgreSQL)" in _services(infra, "storage")
    assert "Application Load Balancer" in _services(infra, "networking")
    # Headline surfaces compute + db + public entrypoint.
    headline = _services(infra, "aws_services")
    assert "ECS Fargate" in headline
    assert "RDS (PostgreSQL)" in headline
    assert "Application Load Balancer" in headline


def test_serverless_maps_to_lambda_and_api_gateway():
    infra = InfraRecommendationService.recommend(
        architecture_pattern="serverless",
        application_type="serverless",
        languages=["Python"],
        frameworks=[],
        services=[],
        dependencies=[],
    )
    compute = _services(infra, "compute")
    assert "AWS Lambda" in compute
    assert "API Gateway" in compute
    assert "ECS Fargate" not in compute


def test_static_frontend_maps_to_s3_cloudfront():
    infra = InfraRecommendationService.recommend(
        architecture_pattern="static",
        application_type="static_site",
        languages=["JavaScript"],
        frameworks=["React"],
        services=[],
        dependencies=["npm"],
    )
    assert "S3 (static hosting)" in _services(infra, "compute")
    assert "CloudFront" in _services(infra, "networking")


def test_redis_adds_elasticache():
    infra = InfraRecommendationService.recommend(
        architecture_pattern="layered",
        application_type="monolith",
        languages=["Python"],
        frameworks=["FastAPI"],
        services=[{"name": "redis"}, {"name": "postgresql"}],
        dependencies=["pip"],
    )
    storage = _services(infra, "storage")
    assert "RDS (PostgreSQL)" in storage
    assert "ElastiCache (Redis)" in storage


def test_microservices_adds_xray_tracing():
    infra = InfraRecommendationService.recommend(
        architecture_pattern="microservices",
        application_type="microservices",
        languages=["Go"],
        frameworks=["Gin"],
        services=[{"name": "svc-a"}, {"name": "svc-b"}, {"name": "svc-c"}],
        dependencies=["go.mod"],
    )
    assert "AWS X-Ray" in _services(infra, "observability")
    assert "CloudWatch" in _services(infra, "observability")


def test_always_returns_a_headline_even_with_no_signals():
    infra = InfraRecommendationService.recommend(
        architecture_pattern=None,
        application_type=None,
        languages=[],
        frameworks=[],
        services=[],
        dependencies=[],
    )
    assert infra["aws_services"], "headline must never be empty"
    assert "CloudWatch" in _services(infra, "observability")
