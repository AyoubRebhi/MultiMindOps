"""Phase 1 — execution authorization unification tests.

The dependency under test is ``resolve_task_membership``: it loads a Task
by id, derives its owning project, and runs the project-role check against
the caller. Every legacy route (tasks/workflow/execution/corrector/
artifact_edit) is wired through this helper, so a single set of contract
tests proves the cross-tenant invariant holds across all of them.

We don't boot a real DB because ``Task.workflow_state`` is JSONB and
SQLite can't render it — the dependency only does ``session.query(...)``
calls, so a tiny fake session matching the call shape is enough to drive
every branch deterministically.
"""

from __future__ import annotations

from typing import Optional

import pytest
from fastapi import HTTPException

from backend.app.core.authorization import (
    require_task_project_approver,
    require_task_project_contributor,
    require_task_project_member,
    resolve_task_membership,
)
from backend.app.models.project import ProjectMember
from backend.app.models.task import Task
from backend.app.models.user import User


# ── Fake DB ─────────────────────────────────────────────────────────────────
#
# The dependency only ever runs:
#   db.query(Task).filter(...).first()
#   db.query(ProjectMember).filter(...).first()
# A handful of fakes is enough — we don't need the real ORM.


class _FakeUser:
    def __init__(self, user_id: str = "u1") -> None:
        self.id = user_id
        self.is_active = "true"

    @property
    def is_active_bool(self) -> bool:
        return self.is_active == "true"


class _FakeTask:
    def __init__(self, *, task_id: str = "t1", project_id: Optional[str] = "p1") -> None:
        self.id = task_id
        self.project_id = project_id


class _FakeMember:
    def __init__(self, *, project_id: str = "p1", user_id: str = "u1", role: str = "DEVELOPER") -> None:
        self.project_id = project_id
        self.user_id = user_id
        self.role = role


class _FakeQuery:
    """Mimics ``session.query(Model).filter(...).first()``.

    The fake session looks up which model is being queried and returns
    whichever fixture the test wired in. ``filter()`` is a no-op because
    Phase-1 lookups are always by primary key — the test already encoded
    the answer via the fixture.
    """

    def __init__(self, db: "_FakeSession", model) -> None:
        self.db = db
        self.model = model

    def filter(self, *_, **__):
        return self

    def first(self):
        if self.model is Task:
            return self.db.task
        if self.model is ProjectMember:
            return self.db.member
        return None


class _FakeSession:
    def __init__(self, *, task: Optional[_FakeTask] = None, member: Optional[_FakeMember] = None) -> None:
        self.task = task
        self.member = member

    def query(self, model):
        return _FakeQuery(self, model)


# ── resolve_task_membership ─────────────────────────────────────────────────


def test_404_when_task_does_not_exist():
    """The most basic cross-tenant guard: a task_id the caller invented
    must not disclose existence vs. non-existence — 404 either way."""
    db = _FakeSession(task=None)
    user = _FakeUser()
    with pytest.raises(HTTPException) as exc:
        resolve_task_membership(
            db, task_id="ghost", user=user, allowed_roles={"DEVELOPER"},
        )
    assert exc.value.status_code == 404


def test_404_when_task_has_no_project_id():
    """Defensive belt-and-braces: even if the NOT NULL migration somehow
    missed a row, a project-less task is unreachable through this gate."""
    db = _FakeSession(task=_FakeTask(project_id=None))
    with pytest.raises(HTTPException) as exc:
        resolve_task_membership(
            db, task_id="t1", user=_FakeUser(), allowed_roles={"DEVELOPER"},
        )
    assert exc.value.status_code == 404


def test_404_when_caller_has_no_membership_in_task_project():
    """The cross-tenant invariant: a user with no membership in the
    task's project must see 404 — never 403 — so even the existence of
    the task does not leak across projects."""
    db = _FakeSession(
        task=_FakeTask(project_id="p_other"),
        member=None,  # caller has no row for p_other
    )
    with pytest.raises(HTTPException) as exc:
        resolve_task_membership(
            db, task_id="t1", user=_FakeUser(), allowed_roles={"DEVELOPER"},
        )
    assert exc.value.status_code == 404


def test_403_when_member_role_is_below_required():
    """In-project but wrong role — the gate yields 403 because the caller
    already knows the resource exists; the failure is about role, not
    cross-tenant disclosure."""
    db = _FakeSession(
        task=_FakeTask(project_id="p1"),
        member=_FakeMember(role="VIEWER"),
    )
    with pytest.raises(HTTPException) as exc:
        resolve_task_membership(
            db, task_id="t1", user=_FakeUser(),
            # CLOUD_ARCHITECT is required by the approver gate, VIEWER is below it.
            allowed_roles={"CLOUD_ARCHITECT"},
        )
    assert exc.value.status_code == 403


def test_returns_task_and_member_on_success():
    """Happy path: a DEVELOPER on the task's project gets the loaded
    Task + ProjectMember back so the handler does not need to re-query."""
    task_in = _FakeTask(project_id="p1")
    member_in = _FakeMember(project_id="p1", role="DEVELOPER")
    db = _FakeSession(task=task_in, member=member_in)

    task, member = resolve_task_membership(
        db, task_id="t1", user=_FakeUser(), allowed_roles={"DEVELOPER"},
    )
    assert task is task_in
    assert member is member_in


def test_owner_always_allowed_even_when_role_not_in_allowed_set():
    """OWNER and ADMIN bypass the role list — that's the existing
    ``ALWAYS_ALLOWED`` semantic of the project-scoped gate, re-asserted
    here so the task-scoped variant matches."""
    db = _FakeSession(
        task=_FakeTask(project_id="p1"),
        member=_FakeMember(role="OWNER"),
    )
    task, member = resolve_task_membership(
        db, task_id="t1", user=_FakeUser(),
        # Allowed set explicitly excludes OWNER — must still pass.
        allowed_roles={"CLOUD_ARCHITECT"},
    )
    assert member.role == "OWNER"


def test_admin_always_allowed():
    """Symmetric ADMIN check — same intent as the OWNER test."""
    db = _FakeSession(
        task=_FakeTask(project_id="p1"),
        member=_FakeMember(role="ADMIN"),
    )
    task, member = resolve_task_membership(
        db, task_id="t1", user=_FakeUser(),
        allowed_roles={"DEVELOPER"},  # ADMIN > DEVELOPER, still passes
    )
    assert member.role == "ADMIN"


# ── Convenience alias factories ─────────────────────────────────────────────
#
# These tests prove that the high-level aliases (used at route-declaration
# time) accept the expected role tiers. They are dependency *factories* so we
# invoke them and then call the inner ``_checker`` with mocked DB+user to
# verify the role set wired in.


def _invoke_dependency(dep, *, task, member, user=None):
    """Call a FastAPI dependency factory's inner ``_checker`` manually.

    The factory returns a closure that, in production, has its arguments
    filled in by FastAPI's dependency injection. We bypass FastAPI by
    calling the closure directly with our fakes.
    """
    db = _FakeSession(task=task, member=member)
    return dep(task_id=task.id, db=db, current_user=user or _FakeUser())


def test_require_task_project_member_accepts_viewer():
    """Read endpoints (``GET ...``) gate on member, which includes VIEWER."""
    task, member = _invoke_dependency(
        require_task_project_member,
        task=_FakeTask(project_id="p1"),
        member=_FakeMember(role="VIEWER"),
    )
    assert task.project_id == "p1"


def test_require_task_project_contributor_rejects_viewer():
    """Write endpoints (run-phase, retry-build, patch artifacts) require
    DEVELOPER+ — a VIEWER must be rejected even when in the project."""
    with pytest.raises(HTTPException) as exc:
        _invoke_dependency(
            require_task_project_contributor,
            task=_FakeTask(project_id="p1"),
            member=_FakeMember(role="VIEWER"),
        )
    assert exc.value.status_code == 403


def test_require_task_project_contributor_accepts_developer():
    task, member = _invoke_dependency(
        require_task_project_contributor,
        task=_FakeTask(project_id="p1"),
        member=_FakeMember(role="DEVELOPER"),
    )
    assert member.role == "DEVELOPER"


def test_require_task_project_approver_rejects_developer():
    """Approver-tier endpoints reject DEVELOPER — only CLOUD_ARCHITECT,
    OWNER, ADMIN can govern. Phase 1 has no routes mounted on this gate
    yet, but the alias is exported so Phase 2 can use it without a
    follow-up authz change."""
    with pytest.raises(HTTPException) as exc:
        _invoke_dependency(
            require_task_project_approver,
            task=_FakeTask(project_id="p1"),
            member=_FakeMember(role="DEVELOPER"),
        )
    assert exc.value.status_code == 403


def test_require_task_project_approver_accepts_cloud_architect():
    task, member = _invoke_dependency(
        require_task_project_approver,
        task=_FakeTask(project_id="p1"),
        member=_FakeMember(role="CLOUD_ARCHITECT"),
    )
    assert member.role == "CLOUD_ARCHITECT"


# ── Schema invariant (model-level) ───────────────────────────────────────────
#
# Catches the regression of "someone made Task.project_id nullable again" —
# nullable=False is the security invariant Phase 1 relies on.


def test_task_project_id_column_is_not_nullable():
    """The migration + model contract: Task.project_id MUST be NOT NULL.

    A regression to nullable=True would re-open the cross-tenant hole this
    phase was built to close, so it gets an explicit test."""
    col = Task.__table__.c.project_id
    assert col.nullable is False, (
        "Task.project_id reverted to nullable. Cross-tenant access is "
        "re-introduced — restore the NOT NULL constraint."
    )


def test_schema_guard_lists_task_project_id_as_not_null_invariant():
    """The schema guard must explicitly fail-fast on tasks.project_id
    being nullable, not silently let the app boot with a broken invariant."""
    from backend.app.core.schema_guard import describe_not_null_requirements

    reqs = list(describe_not_null_requirements())
    assert any(
        r.table == "tasks" and r.column == "project_id" for r in reqs
    ), "tasks.project_id missing from schema_guard NOT NULL list"
