from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from backend.app.database.session import SessionLocal
from backend.app.models.repository_analysis import RepositoryAnalysis


class RepositoryRegistryService:
    def __init__(self, session_factory: sessionmaker = SessionLocal):
        self.session_factory = session_factory

    def get_latest_analysis(
        self,
        normalized_url: str,
        branch: str = "HEAD",
    ) -> dict[str, Any] | None:
        with self.session_factory() as db:
            record = self._query_latest(db, normalized_url, branch)
            if not record:
                return None
            return self._serialize(record)

    def determine_repository_state(
        self,
        normalized_url: str,
        branch: str,
        current_commit_sha: str | None,
        current_analysis_version: str | None = None,
    ) -> dict[str, Any]:
        latest = self.get_latest_analysis(normalized_url, branch)

        if not latest:
            return {
                "status": "new",
                "reason": "no_previous_analysis",
                "latest_analysis": None,
            }

        latest_analysis_version = (latest.get("analysis_metadata") or {}).get("analysis_version")
        if current_analysis_version and latest_analysis_version != current_analysis_version:
            return {
                "status": "changed",
                "reason": "analysis_version_changed",
                "latest_analysis": latest,
            }

        previous_commit_sha = latest.get("commit_sha")
        if current_commit_sha and previous_commit_sha == current_commit_sha:
            return {
                "status": "unchanged",
                "reason": "same_commit_sha",
                "latest_analysis": latest,
            }

        return {
            "status": "changed",
            "reason": "commit_sha_changed" if current_commit_sha else "current_commit_unknown",
            "latest_analysis": latest,
        }

    def save_analysis(
        self,
        *,
        normalized_url: str,
        branch: str,
        commit_sha: str | None,
        content_fingerprint: str | None,
        analysis_status: str,
        project_summary: dict[str, Any] | None,
        analysis_output: dict[str, Any],
        analysis_metadata: dict[str, Any],
        execution_trace: list[dict[str, Any]],
        execution_stats: dict[str, Any] | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        with self.session_factory() as db:
            record = RepositoryAnalysis(
                normalized_url=normalized_url,
                branch=branch,
                commit_sha=commit_sha,
                content_fingerprint=content_fingerprint,
                analysis_status=analysis_status,
                project_summary=self._sanitize_json_payload(project_summary),
                analysis_output=self._sanitize_json_payload(analysis_output) or {},
                analysis_metadata=self._sanitize_json_payload(analysis_metadata) or {},
                execution_trace=self._sanitize_json_payload(execution_trace) or [],
                execution_stats=self._sanitize_json_payload(execution_stats or {}) or {},
                notes=self._sanitize_text(notes),
            )
            db.add(record)
            db.commit()
            db.refresh(record)
            return self._serialize(record)

    def mark_reused(
        self,
        analysis_id: str,
        trace_entry: dict[str, Any],
    ) -> dict[str, Any] | None:
        with self.session_factory() as db:
            record = db.query(RepositoryAnalysis).filter(RepositoryAnalysis.id == analysis_id).first()
            if not record:
                return None

            trace = list(record.execution_trace or [])
            trace.append(trace_entry)
            record.execution_trace = trace
            record.reuse_count = (record.reuse_count or 0) + 1
            record.last_used_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(record)
            return self._serialize(record)

    def _query_latest(
        self,
        db: Session,
        normalized_url: str,
        branch: str,
    ) -> RepositoryAnalysis | None:
        return (
            db.query(RepositoryAnalysis)
            .filter(
                RepositoryAnalysis.normalized_url == normalized_url,
                RepositoryAnalysis.branch == branch,
            )
            .order_by(RepositoryAnalysis.created_at.desc())
            .first()
        )

    def _serialize(self, record: RepositoryAnalysis) -> dict[str, Any]:
        return {
            "id": record.id,
            "normalized_url": record.normalized_url,
            "branch": record.branch,
            "commit_sha": record.commit_sha,
            "content_fingerprint": record.content_fingerprint,
            "analysis_status": record.analysis_status,
            "project_summary": record.project_summary,
            "analysis_output": record.analysis_output,
            "analysis_metadata": record.analysis_metadata,
            "execution_trace": record.execution_trace,
            "execution_stats": record.execution_stats,
            "reuse_count": record.reuse_count,
            "last_used_at": record.last_used_at.isoformat() if record.last_used_at else None,
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "updated_at": record.updated_at.isoformat() if record.updated_at else None,
            "notes": record.notes,
        }

    def _sanitize_json_payload(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                self._sanitize_text(str(key)): self._sanitize_json_payload(nested_value)
                for key, nested_value in value.items()
            }
        if isinstance(value, list):
            return [self._sanitize_json_payload(item) for item in value]
        if isinstance(value, tuple):
            return [self._sanitize_json_payload(item) for item in value]
        if isinstance(value, str):
            return self._sanitize_text(value)
        return value

    @staticmethod
    def _sanitize_text(value: str | None) -> str | None:
        if value is None:
            return None
        return value.replace("\x00", "")
