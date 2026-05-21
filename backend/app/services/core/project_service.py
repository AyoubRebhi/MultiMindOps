"""Project lifecycle service.

Encapsulates DB operations for Project, ProjectMember, Workflow, and Artifact
so route handlers stay thin. Keeping these as ``@staticmethod`` mirrors the
existing ``TaskService`` style.
"""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy.orm import Session

from backend.app.models.artifact import Artifact
from backend.app.models.project import Project, ProjectMember
from backend.app.models.user import User
from backend.app.models.workflow import Workflow
from backend.app.schemas.project import ProjectCreate, ProjectUpdate


class ProjectService:
    @staticmethod
    def create_project(db: Session, owner: User, payload: ProjectCreate) -> Project:
        project = Project(
            owner_id=owner.id,
            name=payload.name,
            description=payload.description,
            repository_url=payload.repository_url,
            architecture_type=payload.architecture_type,
            application_profile=payload.application_profile,
            default_strategy_tier=payload.default_strategy_tier,
            current_status="draft",
            project_metadata={},
        )
        db.add(project)
        db.flush()  # populate project.id before adding membership

        # Owner is implicitly an OWNER-level member.
        member = ProjectMember(project_id=project.id, user_id=owner.id, role="OWNER")
        db.add(member)

        db.commit()
        db.refresh(project)
        return project

    @staticmethod
    def list_projects_for_user(db: Session, user: User) -> List[Project]:
        # Visible projects = projects where the user has any membership.
        return (
            db.query(Project)
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .filter(ProjectMember.user_id == user.id)
            .order_by(Project.updated_at.desc())
            .all()
        )

    @staticmethod
    def get_project(db: Session, project_id: str) -> Optional[Project]:
        return db.query(Project).filter(Project.id == project_id).first()

    @staticmethod
    def get_project_for_user(db: Session, project_id: str, user: User) -> Optional[Project]:
        return (
            db.query(Project)
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .filter(Project.id == project_id, ProjectMember.user_id == user.id)
            .first()
        )

    @staticmethod
    def update_project(db: Session, project: Project, payload: ProjectUpdate) -> Project:
        # ``exclude_unset`` so a PATCH that omits a field doesn't null it.
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(project, field, value)
        db.commit()
        db.refresh(project)
        return project

    @staticmethod
    def list_workflows(db: Session, project_id: str) -> List[Workflow]:
        return (
            db.query(Workflow)
            .filter(Workflow.project_id == project_id)
            .order_by(Workflow.created_at.desc())
            .all()
        )

    @staticmethod
    def list_artifacts(db: Session, project_id: str) -> List[Artifact]:
        return (
            db.query(Artifact)
            .filter(Artifact.project_id == project_id)
            .order_by(Artifact.artifact_type, Artifact.artifact_subtype)
            .all()
        )

    @staticmethod
    def list_members(db: Session, project_id: str) -> List[ProjectMember]:
        return (
            db.query(ProjectMember)
            .filter(ProjectMember.project_id == project_id)
            .order_by(ProjectMember.created_at.asc())
            .all()
        )
