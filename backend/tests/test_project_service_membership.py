"""Owner-membership self-healing tests for ProjectService.

The bug class we're guarding against: a dev-seeded owner whose
ProjectMember row is missing gets a 404 on every project-scoped endpoint
because ``get_project_for_user`` does an INNER JOIN. The self-heal in
``ProjectService.ensure_owner_membership`` adds the missing OWNER row;
``get_project_for_user`` invokes it whenever the caller IS the owner.
"""

from __future__ import annotations

from typing import List, Optional
from unittest.mock import MagicMock

import pytest

from backend.app.models.project import ProjectMember
from backend.app.services.core.project_service import ProjectService


class _FakeProject:
    def __init__(self, project_id="p1", owner_id="u1"):
        self.id = project_id
        self.owner_id = owner_id


class _FakeUser:
    def __init__(self, user_id="u1"):
        self.id = user_id


class _FakeQuery:
    """Minimal SQLAlchemy query stand-in.

    Each call site of ``db.query(Model).filter(...).first()`` resolves to
    whichever object the test set up under that model. We carry a tiny
    behavior bag so we can detect membership INSERTs.
    """

    def __init__(self, db, model):
        self.db = db
        self.model = model

    def filter(self, *_, **__):
        return self

    def first(self):
        cls_name = self.model.__name__
        if cls_name == "Project":
            return self.db._project
        if cls_name == "ProjectMember":
            return self.db._member
        return None


class _FakeSession:
    def __init__(self, *, project=None, member=None):
        self._project = project
        self._member = member
        self.added: List[object] = []
        self.commits = 0

    def query(self, model):
        return _FakeQuery(self, model)

    def add(self, obj):
        self.added.append(obj)
        # Simulate INSERT — subsequent ProjectMember queries should see this.
        if isinstance(obj, ProjectMember):
            self._member = obj

    def commit(self):
        self.commits += 1

    def refresh(self, _):
        pass

    def flush(self):
        pass


def test_get_project_for_user_returns_project_when_member_exists():
    project = _FakeProject()
    user = _FakeUser()
    member = MagicMock(spec=ProjectMember)
    db = _FakeSession(project=project, member=member)

    result = ProjectService.get_project_for_user(db, project_id="p1", user=user)

    assert result is project
    assert not db.added, "should not insert when membership already exists"


def test_get_project_for_user_self_heals_when_owner_membership_missing():
    project = _FakeProject(owner_id="u1")
    user = _FakeUser(user_id="u1")  # same id as project.owner_id
    db = _FakeSession(project=project, member=None)

    result = ProjectService.get_project_for_user(db, project_id="p1", user=user)

    assert result is project
    # Self-heal must have INSERTed a fresh OWNER row
    assert len(db.added) == 1
    inserted = db.added[0]
    assert isinstance(inserted, ProjectMember)
    assert inserted.role == "OWNER"
    assert inserted.user_id == "u1"
    assert inserted.project_id == "p1"
    assert db.commits >= 1


def test_get_project_for_user_returns_none_for_non_owner_without_membership():
    project = _FakeProject(owner_id="someone-else")
    user = _FakeUser(user_id="u1")
    db = _FakeSession(project=project, member=None)

    result = ProjectService.get_project_for_user(db, project_id="p1", user=user)

    # Non-owner with no membership: caller stays locked out.
    assert result is None
    assert not db.added


def test_get_project_for_user_returns_none_when_project_missing():
    db = _FakeSession(project=None, member=None)
    user = _FakeUser()

    result = ProjectService.get_project_for_user(db, project_id="nope", user=user)
    assert result is None
    assert not db.added


def test_ensure_owner_membership_is_idempotent():
    project = _FakeProject()
    existing = MagicMock(spec=ProjectMember)
    db = _FakeSession(project=project, member=existing)

    result = ProjectService.ensure_owner_membership(db, project)

    assert result is existing
    assert not db.added, "no INSERT when an OWNER row already exists"


def test_ensure_owner_membership_returns_none_when_owner_id_missing():
    project = _FakeProject()
    project.owner_id = None  # corruption guard

    db = _FakeSession(project=project, member=None)
    result = ProjectService.ensure_owner_membership(db, project)
    assert result is None
    assert not db.added
