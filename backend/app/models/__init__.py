"""Data models for the backend.

Import every ORM model class here so ``Base.metadata.create_all()`` at
startup sees them all. Adding a model without importing it here means
SQLAlchemy will not create its table on a fresh database.
"""

from backend.app.models.credentials import ProjectCredential
from backend.app.models.execution_job import ExecutionJob
from backend.app.models.invitation import Invitation
from backend.app.models.lifecycle_event import InfrastructureLifecycleEvent
from backend.app.models.release import ReleaseArtifactSnapshot, ReleaseCandidate
from backend.app.models.repository_analysis import RepositoryAnalysis
from backend.app.models.session import UserSession
from backend.app.models.task import Task
from backend.app.models.user import User
from backend.app.models.workflow_event import WorkflowPhaseEvent
from backend.app.models.workflow_execution_trace import WorkflowExecutionTrace
from backend.app.models.workspace import Workspace

__all__ = [
    "ExecutionJob",
    "InfrastructureLifecycleEvent",
    "Invitation",
    "ProjectCredential",
    "ReleaseArtifactSnapshot",
    "ReleaseCandidate",
    "RepositoryAnalysis",
    "Task",
    "User",
    "UserSession",
    "WorkflowPhaseEvent",
    "WorkflowExecutionTrace",
    "Workspace",
]
