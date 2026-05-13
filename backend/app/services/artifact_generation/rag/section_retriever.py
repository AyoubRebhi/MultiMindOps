"""
SectionAwareRetriever — RAG retrieval scoped to individual blueprint sections.

Unlike the generic RAGPipelineService (which retrieves infrastructure knowledge in bulk),
this retriever constructs section-specific queries so that:

  section="security"    → retrieves non-root patterns, distroless recommendations
  section="dependencies" → retrieves layer-caching strategies, pip/npm best practices
  section="startup"     → retrieves CMD exec-form patterns, signal handling

Each query is enriched with the project's language, framework, and dependencies
for maximum relevance.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from backend.app.services.rag.rag_pipeline_service import RAGPipelineService

logger = logging.getLogger(__name__)


# ── Section → Qdrant doc_type ────────────────────────────────────────────────
# Maps blueprint section IDs to Qdrant document types used as filters.
_SECTION_DOC_TYPE: Dict[str, str] = {
    "builder_base": "docker",
    "runtime_base": "docker",
    "base_image": "docker",
    "build_workdir": "docker",
    "workdir": "docker",
    "build_dependencies": "docker",
    "copy_dependencies": "docker",
    "build": "docker",
    "copy_source": "docker",
    "source_code": "docker",
    "copy_jar": "docker",
    "environment": "docker",
    "expose": "docker",
    "startup": "docker",
    "entrypoint": "docker",
    "labels": "docker",
    "args": "docker",
    "healthcheck": "docker",
    "security_user": "security",
    "security": "security",
    "user": "security",
}

# ── Section → natural-language query template ─────────────────────────────────
_SECTION_QUERY: Dict[str, str] = {
    "builder_base": (
        "Docker multi-stage build base image {language} {framework} "
        "builder stage version pinning best practices"
    ),
    "runtime_base": (
        "Docker minimal runtime image {language} slim distroless production "
        "version pinning"
    ),
    "base_image": (
        "Docker base image {language} {framework} version pinning best practices"
    ),
    "build_workdir": "Docker WORKDIR builder stage best practices",
    "workdir": "Docker WORKDIR application directory best practices",
    "build_dependencies": (
        "Docker layer caching {language} dependency installation {package_manager} "
        "requirements optimization"
    ),
    "copy_dependencies": (
        "Docker multi-stage copy built artifacts dependencies {language}"
    ),
    "build": (
        "Docker RUN build command {language} {framework} compilation optimization "
        "skip tests"
    ),
    "copy_source": "Docker COPY source code context best practices exclude",
    "source_code": "Docker COPY source code application files",
    "copy_jar": "Docker COPY jar artifact multi-stage build {language}",
    "environment": (
        "Docker ENV environment variables secrets management PATH {language}"
    ),
    "expose": "Docker EXPOSE port documentation best practices",
    "security_user": (
        "Docker non-root user create group useradd adduser least privilege "
        "security hardening"
    ),
    "security": (
        "Docker security hardening non-root user filesystem permissions "
        "read-only root"
    ),
    "user": "Docker USER instruction drop privileges non-root appuser",
    "healthcheck": (
        "Docker HEALTHCHECK HTTP probe curl wget interval timeout retries "
        "container health"
    ),
    "startup": (
        "Docker CMD ENTRYPOINT exec form {language} {framework} startup command "
        "signal handling PID 1"
    ),
    "entrypoint": (
        "Docker ENTRYPOINT exec form {language} signal handling PID 1 best practices"
    ),
    "labels": "Docker LABEL OCI image metadata annotations best practices",
    "args": "Docker ARG build arguments security best practices",
}


class SectionAwareRetriever:
    """
    Retrieves RAG knowledge scoped to a specific blueprint section.

    Wraps RAGPipelineService and constructs section-targeted queries so that
    each section gets the most relevant knowledge from the corpus.
    """

    def __init__(self, rag_pipeline: Optional[RAGPipelineService] = None):
        self._rag = rag_pipeline or RAGPipelineService()

    def retrieve_for_section(
        self,
        section_id: str,
        framework: str = "",
        language: str = "",
        project_context: Optional[Dict[str, Any]] = None,
        top_k: int = 3,
    ) -> Dict[str, Any]:
        """
        Retrieve knowledge base context relevant to one blueprint section.

        Args:
            section_id:      Blueprint section ID (e.g. "security_user", "startup").
            framework:       Detected application framework (e.g. "fastapi").
            language:        Detected programming language (e.g. "python").
            project_context: Full mapped context for additional enrichment.
            top_k:           Maximum number of knowledge chunks to retrieve.

        Returns:
            {
                "available":      bool,
                "section_id":     str,
                "context_block":  str,   # formatted for LLM prompt injection
                "sources":        List[str],
                "results_count":  int,
                "query":          str,   # the query that was run (for observability)
            }
        """
        ctx = project_context or {}
        doc_type = _SECTION_DOC_TYPE.get(section_id, "docker")
        query = self._build_query(section_id, framework, language, ctx)

        logger.debug(
            "[SectionAwareRetriever] section=%s doc_type=%s query=%r",
            section_id, doc_type, query[:100],
        )

        result = self._rag.retrieve_context(
            query=query,
            doc_type=doc_type,
            top_k=top_k,
            score_threshold=0.25,
        )

        if not result.get("available"):
            logger.debug(
                "[SectionAwareRetriever] section=%s no results (reason=%s)",
                section_id, result.get("reason"),
            )
            return {
                "available": False,
                "section_id": section_id,
                "context_block": "",
                "sources": [],
                "results_count": 0,
                "query": query,
            }

        sources: List[str] = [
            r.get("source", "") for r in result.get("results", []) if r.get("source")
        ]

        logger.debug(
            "[SectionAwareRetriever] section=%s hits=%d top_score=%.3f",
            section_id,
            result.get("results_count", 0),
            (result.get("results") or [{}])[0].get("score", 0),
        )

        return {
            "available": True,
            "section_id": section_id,
            "context_block": result.get("context", ""),
            "sources": sources,
            "results_count": result.get("results_count", 0),
            "query": query,
        }

    def retrieve_for_sections(
        self,
        section_ids: List[str],
        framework: str = "",
        language: str = "",
        project_context: Optional[Dict[str, Any]] = None,
        top_k: int = 2,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Batch-retrieve knowledge for multiple sections at once.

        Returns a dict keyed by section_id with the same shape as
        retrieve_for_section().
        """
        return {
            sid: self.retrieve_for_section(
                section_id=sid,
                framework=framework,
                language=language,
                project_context=project_context,
                top_k=top_k,
            )
            for sid in section_ids
        }

    # ── Query construction ────────────────────────────────────────────────────

    @staticmethod
    def _build_query(
        section_id: str,
        framework: str,
        language: str,
        context: Dict[str, Any],
    ) -> str:
        template = _SECTION_QUERY.get(
            section_id, f"Docker {section_id} best practices {language} {framework}"
        )
        runtime = context.get("runtime") or {}
        pms: List[str] = runtime.get("package_managers") or []
        package_manager = pms[0] if pms else ""

        return template.format(
            language=language or "generic",
            framework=framework or "",
            package_manager=package_manager,
        ).strip()
