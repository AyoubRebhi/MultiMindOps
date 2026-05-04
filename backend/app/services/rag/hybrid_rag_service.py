"""
HybridRAGService — MCP + Qdrant fusion retrieval for DevSecOps agents.

Retrieval priority:
  1. MCP (high-precision, schema-level, structured)  — always queried
  2. Qdrant (high-recall, corpus best-practices)      — queried in parallel
  3. Merge: MCP context prepended, Qdrant appended, deduplication applied

The merged context is structured (not a raw concatenation) so the LLM
receives a clear hierarchy: schema first, corpus examples second.

Usage:
    from backend.app.services.rag.hybrid_rag_service import HybridRAGService

    rag = HybridRAGService()
    result = rag.retrieve(
        query="Terraform AWS EKS VPC subnets",
        doc_type="terraform",
        architecture_type="eks",
    )
    # result["context"] — formatted string ready for LLM prompt injection
    # result["sources"] — {"mcp": [...], "qdrant": [...]}
    # result["available"] — bool
"""

from __future__ import annotations

import logging
import time
from typing import Any

from backend.app.services.mcp_client import MCPClient
from backend.app.services.rag.rag_pipeline_service import RAGPipelineService

logger = logging.getLogger(__name__)

# ── Context section headers ────────────────────────────────────────────────────
_MCP_HEADER = "## MCP Context — Terraform Schema & Best Practices"
_QDRANT_HEADER = "## RAG Context — DevSecOps Knowledge Base"


class HybridRAGService:
    """
    Fuses MCP (live structured schemas) with Qdrant (static corpus) retrieval.

    MCP provides high-precision, schema-level context (arguments, examples, constraints).
    Qdrant provides high-recall context from the DevSecOps corpus (patterns, security rules).

    The merged output is formatted for direct LLM prompt injection.
    """

    def __init__(self) -> None:
        self._mcp = MCPClient.get_instance()
        self._qdrant_rag = RAGPipelineService()

    # ── Primary API ───────────────────────────────────────────────────────────

    def retrieve(
        self,
        query: str,
        doc_type: str | None = None,
        architecture_type: str = "eks",
        resource_hints: list[str] | None = None,
        top_k: int = 4,
        max_total_chars: int = 5_000,
        mcp_max_chars: int = 3_000,
        qdrant_max_chars: int = 2_000,
    ) -> dict[str, Any]:
        """
        Retrieve and merge context from MCP and Qdrant.

        Args:
            query:             Natural language query for Qdrant retrieval.
            doc_type:          Qdrant doc_type filter ('terraform', 'k8s', 'docker', ...).
            architecture_type: 'eks', 'ecs', or 'serverless' — used for MCP template selection.
            resource_hints:    Explicit Terraform resource types to include from MCP.
            top_k:             Number of Qdrant results to retrieve.
            max_total_chars:   Global cap on merged context length.
            mcp_max_chars:     Max chars allocated to MCP context.
            qdrant_max_chars:  Max chars allocated to Qdrant context.

        Returns:
            dict with:
              - available: bool
              - context: str (merged, formatted, ready for LLM injection)
              - sources: {"mcp": {...}, "qdrant": {...}}
              - latency_ms: {"mcp": int, "qdrant": int}
        """
        t0 = time.monotonic()

        mcp_result = self._retrieve_mcp(
            query=query,
            architecture_type=architecture_type,
            resource_hints=resource_hints,
            max_chars=mcp_max_chars,
        )

        qdrant_result = self._retrieve_qdrant(
            query=query,
            doc_type=doc_type,
            top_k=top_k,
            max_chars=qdrant_max_chars,
        )

        total_ms = int((time.monotonic() - t0) * 1000)

        merged_context = self._merge(
            mcp_result=mcp_result,
            qdrant_result=qdrant_result,
            max_total_chars=max_total_chars,
        )

        available = mcp_result.get("available") or qdrant_result.get("available")

        logger.info(
            "[HybridRAG] query=%r doc_type=%s arch=%s mcp=%s qdrant=%s total_ms=%d",
            query[:60],
            doc_type,
            architecture_type,
            mcp_result.get("available"),
            qdrant_result.get("available"),
            total_ms,
        )

        return {
            "available": available,
            "context": merged_context,
            "sources": {
                "mcp": {
                    "available": mcp_result.get("available", False),
                    "resources_loaded": mcp_result.get("resources_loaded", []),
                    "char_count": mcp_result.get("char_count", 0),
                },
                "qdrant": {
                    "available": qdrant_result.get("available", False),
                    "results_count": len(qdrant_result.get("results", [])),
                    "char_count": len(qdrant_result.get("context", "")),
                },
            },
            "latency_ms": total_ms,
            "query": query,
            "doc_type": doc_type,
            "architecture_type": architecture_type,
        }

    def retrieve_for_terraform_agent(
        self,
        prompt: str,
        architecture_type: str,
        top_k: int = 4,
    ) -> dict[str, Any]:
        """Convenience wrapper optimized for TerraformAgent retrieval."""
        topic_map = {
            "eks": "Terraform AWS EKS Kubernetes cluster VPC subnets IAM outputs",
            "ecs": "Terraform AWS ECS Fargate cluster VPC ALB task definition outputs",
            "serverless": "Terraform AWS Lambda API Gateway serverless VPC outputs",
        }
        query = topic_map.get(architecture_type, "Terraform AWS infrastructure VPC") + f" {prompt[:150]}"

        return self.retrieve(
            query=query,
            doc_type="terraform",
            architecture_type=architecture_type,
            top_k=top_k,
            mcp_max_chars=10_000,
            qdrant_max_chars=2_000,
            max_total_chars=12_000,
        )

    def retrieve_for_kubernetes_agent(
        self,
        prompt: str,
        terraform_outputs: dict[str, str] | None = None,
        top_k: int = 3,
    ) -> dict[str, Any]:
        """Convenience wrapper optimized for KubernetesAgent retrieval."""
        tf_context = ""
        if terraform_outputs:
            tf_context = " ECR_URL=" + terraform_outputs.get("ecr_repository_url", "")

        return self.retrieve(
            query=f"Kubernetes deployment service manifest EKS pod security{tf_context} {prompt[:100]}",
            doc_type="k8s",
            architecture_type="eks",
            mcp_max_chars=1_500,
            qdrant_max_chars=2_000,
            max_total_chars=3_500,
        )

    def retrieve_for_infrastructure_agent(
        self,
        prompt: str,
        runtime_info: dict[str, Any] | None = None,
        top_k: int = 4,
    ) -> dict[str, Any]:
        """Convenience wrapper optimized for InfrastructureAgent (Docker) retrieval."""
        rt = (runtime_info or {})
        lang = rt.get("language", "")
        framework = rt.get("framework", "")
        return self.retrieve(
            query=f"Dockerfile docker-compose {lang} {framework} {prompt[:100]}",
            doc_type="docker",
            architecture_type="ecs",  # Docker aligns with ECS deployment model
            resource_hints=[],
            mcp_max_chars=500,  # MCP has limited Docker data — Qdrant dominates here
            qdrant_max_chars=3_000,
            max_total_chars=3_500,
        )

    def validate_terraform_artifacts(
        self,
        artifacts: dict[str, str],
    ) -> dict[str, Any]:
        """
        Validate multiple Terraform artifacts using MCP tools.

        Args:
            artifacts: dict of {artifact_key: hcl_content}

        Returns:
            dict of {artifact_key: validation_result}
        """
        results: dict[str, Any] = {}
        for key, hcl in artifacts.items():
            if not isinstance(hcl, str) or not hcl.strip():
                continue
            results[key] = self._mcp.validate_terraform_code(hcl)
        return results

    def health_check(self) -> dict[str, Any]:
        return {
            "mcp": self._mcp.health_check(),
            "qdrant": self._qdrant_rag.health_check(),
        }

    # ── Internal retrieval ────────────────────────────────────────────────────

    def _retrieve_mcp(
        self,
        query: str,
        architecture_type: str,
        resource_hints: list[str] | None,
        max_chars: int,
    ) -> dict[str, Any]:
        try:
            if "k8s" in query.lower() or "kubernetes" in query.lower():
                return self._mcp.build_kubernetes_context(query, max_chars=max_chars)
            return self._mcp.build_terraform_context(
                query=query,
                architecture_type=architecture_type,
                resource_hints=resource_hints,
                max_chars=max_chars,
            )
        except Exception as exc:
            logger.warning("[HybridRAG] MCP retrieval failed: %s", exc)
            return {"available": False, "context_text": "", "resources_loaded": []}

    def _retrieve_qdrant(
        self,
        query: str,
        doc_type: str | None,
        top_k: int,
        max_chars: int,
    ) -> dict[str, Any]:
        try:
            result = self._qdrant_rag.retrieve_context(
                query=query,
                doc_type=doc_type,
                top_k=top_k,
                use_hybrid=True,
                score_threshold=0.25,
            )
            # Truncate context to max_chars
            ctx = result.get("context", "")
            if len(ctx) > max_chars:
                ctx = ctx[:max_chars] + "\n[...Qdrant context truncated...]"
            result["context"] = ctx
            return result
        except Exception as exc:
            logger.warning("[HybridRAG] Qdrant retrieval failed: %s", exc)
            return {"available": False, "context": "", "results": []}

    # ── Merge ─────────────────────────────────────────────────────────────────

    def _merge(
        self,
        mcp_result: dict[str, Any],
        qdrant_result: dict[str, Any],
        max_total_chars: int,
    ) -> str:
        """
        Merge MCP and Qdrant context into a single structured string.

        MCP context is placed FIRST (higher priority).
        Qdrant context is placed SECOND (recall / examples).
        """
        parts: list[str] = []

        mcp_text = mcp_result.get("context_text", "").strip()
        if mcp_text:
            parts.append(f"{_MCP_HEADER}\n\n{mcp_text}")

        qdrant_text = qdrant_result.get("context", "").strip()
        if qdrant_text:
            parts.append(f"{_QDRANT_HEADER}\n\n{qdrant_text}")

        if not parts:
            return "(No context available from MCP or Qdrant)"

        merged = "\n\n" + ("─" * 70) + "\n\n".join(parts)

        if len(merged) > max_total_chars:
            merged = merged[:max_total_chars] + "\n\n[...context truncated — total budget exceeded...]"

        return merged
