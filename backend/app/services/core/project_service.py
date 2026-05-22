"""Project lifecycle service.

Encapsulates DB operations for Project, ProjectMember, Workflow, and Artifact
so route handlers stay thin. Keeping these as ``@staticmethod`` mirrors the
existing ``TaskService`` style.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from sqlalchemy.orm import Session

from backend.app.models.artifact import Artifact
from backend.app.models.project import Project, ProjectMember
from backend.app.models.user import User
from backend.app.models.workflow import Workflow
from backend.app.schemas.project import ProjectCreate, ProjectUpdate

logger = logging.getLogger(__name__)


class ProjectService:
    @staticmethod
    def create_project(db: Session, owner: User, payload: ProjectCreate) -> Project:
        project = Project(
            owner_id=owner.id,
            name=payload.name,
            description=payload.description,
            repository_url=payload.repository_url,
            repository_visibility=payload.repository_visibility,
            architecture_type=payload.architecture_type,
            application_profile=payload.application_profile,
            # ``default_strategy_tier`` is left null when the caller omits it
            # — the bootstrap pipeline will set it from architecture inference.
            default_strategy_tier=payload.default_strategy_tier,
            current_status="draft",
            # New projects start in ``pending`` and transition through
            # analyzing → context_building → ready in the bootstrap service.
            bootstrap_status="pending",
            project_metadata={},
        )
        db.add(project)
        db.flush()  # populate project.id before adding membership

        # Owner is implicitly an OWNER-level member.
        member = ProjectMember(project_id=project.id, user_id=owner.id, role="OWNER")
        db.add(member)

        db.commit()
        db.refresh(project)
        logger.info(
            "[PROJECT_MEMBERSHIP] Added owner membership for project=%s user=%s",
            project.id, owner.id,
        )
        return project

    @staticmethod
    def ensure_owner_membership(db: Session, project: Project) -> Optional[ProjectMember]:
        """Guarantee the project owner has an OWNER ProjectMember row.

        Self-healing path for pre-existing projects (or dev-seeded users)
        whose initial OWNER membership got skipped. Idempotent: if the row
        already exists this is a single SELECT and a no-op.

        Returns the existing or newly-created membership row, or None when
        the project has no owner_id (shouldn't happen, but guard anyway).
        """
        if not project.owner_id:
            return None
        member = (
            db.query(ProjectMember)
            .filter(
                ProjectMember.project_id == project.id,
                ProjectMember.user_id == project.owner_id,
            )
            .first()
        )
        if member is not None:
            return member
        member = ProjectMember(
            project_id=project.id, user_id=project.owner_id, role="OWNER",
        )
        db.add(member)
        db.commit()
        db.refresh(member)
        logger.warning(
            "[PROJECT_MEMBERSHIP] Self-healed missing OWNER membership for "
            "project=%s owner=%s",
            project.id, project.owner_id,
        )
        return member

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
        """Return the project iff the caller has any membership on it.

        Owner self-healing: if the caller is the project's ``owner_id`` but no
        ProjectMember row exists (e.g. dev-seeded user, or an upgrade path
        where the auto-insert in ``create_project`` was skipped), the missing
        OWNER row is created in the same call so the route does not 404.
        Non-owners with no membership still get None.
        """
        project = db.query(Project).filter(Project.id == project_id).first()
        if project is None:
            return None

        member = (
            db.query(ProjectMember)
            .filter(
                ProjectMember.project_id == project.id,
                ProjectMember.user_id == user.id,
            )
            .first()
        )
        if member is not None:
            return project

        if project.owner_id == user.id:
            # Defensive self-heal — owner must always be a member.
            ProjectService.ensure_owner_membership(db, project)
            return project

        return None

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
