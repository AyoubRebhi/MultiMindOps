import uuid

from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.sql import func

from backend.app.database.base import Base


class RepositoryAnalysis(Base):
    __tablename__ = "repository_analyses"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    normalized_url = Column(String, nullable=False, index=True)
    branch = Column(String, nullable=False, default="HEAD", index=True)
    commit_sha = Column(String, nullable=True, index=True)
    content_fingerprint = Column(String, nullable=True)
    analysis_status = Column(String, nullable=False, default="completed")

    project_summary = Column(MutableDict.as_mutable(JSONB), nullable=True)
    analysis_output = Column(MutableDict.as_mutable(JSONB), nullable=False, default=dict)
    analysis_metadata = Column(MutableDict.as_mutable(JSONB), nullable=False, default=dict)
    execution_trace = Column(MutableList.as_mutable(JSONB), nullable=False, default=list)
    execution_stats = Column(MutableDict.as_mutable(JSONB), nullable=False, default=dict)

    reuse_count = Column(Integer, nullable=False, default=0)
    last_used_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
