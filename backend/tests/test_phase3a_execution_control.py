"""Phase 3A — execution control (Stop + Replay) contracts.

The durable-job CANCEL lifecycle itself (pending→cancelled, running→flagged,
worker finalises) is already proven in ``test_phase3_jobs.py``. This module
covers the NEW Phase 3A behaviour layered on top:

1. Cooperative subprocess termination (terminate → grace → kill) used by BOTH
   the docker build and terraform validate/plan runners when their handler is
   cancelled — the genuinely new, riskiest code. Tested for the async-subprocess
   path and the synchronous-thread fallback.
2. ``cancelled`` terminal-state PERSISTENCE for a stopped docker build
   (``_persist_docker_cancelled``) and a stopped terraform phase
   (``record_terraform_phase_cancelled``), so the status the WebSocket reads
   becomes ``cancelled`` (not stuck ``running``, not coerced to ``failed``).
3. The terraform WS terminal-status mapping surfaces ``cancelled``.
4. Replay AFTER a cancellation re-enqueues the same durable jobs from DB
   artifacts (reuses the existing replay infrastructure; no LLM, no regen).

Everything runs against a REAL in-memory SQLite DB (StaticPool so the helpers
that open their own ``SessionLocal`` share the one in-memory database) — the
behaviour worth proving is DB + subprocess behaviour, never a mock.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.models.artifact import Artifact, ArtifactVersion
from backend.app.models.execution_job import ExecutionJob
from backend.app.models.project import Project
from backend.app.models.task import Task
from backend.app.models.workflow import Workflow
from backend.app.models.workflow_execution_trace import WorkflowExecutionTrace
from backend.app.services.execution.docker_connectivity import (
    terminate_async_process,
    terminate_sync_process,
)


# ── Shared in-memory DB (StaticPool → one DB across all SessionLocal() calls) ──

@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for model in (Project, Workflow, Task, Artifact, ArtifactVersion,
                  ExecutionJob, WorkflowExecutionTrace):
        model.__table__.create(engine)
    Session = sessionmaker(bind=engine)
    try:
        yield Session
    finally:
        engine.dispose()


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def storage(monkeypatch, tmp_path):
    """Point the terraform rehydration root at a temp dir (replay writes HCL)."""
    monkeypatch.setenv("TF_PIPELINE_STORAGE_ROOT", str(tmp_path / "generated_terraform"))


# ════════════════════════════════════════════════════════════════════════════
# 1. Cooperative subprocess termination (terminate → grace → kill)
# ════════════════════════════════════════════════════════════════════════════

class _FakeSyncProc:
    """A subprocess.Popen-shaped stub recording terminate/kill (sync path)."""

    def __init__(self, *, exits_on_terminate: bool):
        self._rc = None
        self.terminated = False
        self.killed = False
        self._exits_on_terminate = exits_on_terminate

    def poll(self):
        return self._rc

    def terminate(self):
        self.terminated = True
        if self._exits_on_terminate:
            self._rc = -15

    def wait(self, timeout=None):
        if self._rc is not None:
            return self._rc
        raise subprocess.TimeoutExpired(cmd="x", timeout=timeout)

    def kill(self):
        self.killed = True
        self._rc = -9


def test_terminate_sync_graceful_no_kill():
    """SIGTERM lands and the child exits within grace → kill() is NOT called."""
    proc = _FakeSyncProc(exits_on_terminate=True)
    terminate_sync_process(proc, grace=0.2)
    assert proc.terminated is True
    assert proc.killed is False


def test_terminate_sync_force_kill_after_grace():
    """The child ignores SIGTERM past the grace window → kill() escalates."""
    proc = _FakeSyncProc(exits_on_terminate=False)
    terminate_sync_process(proc, grace=0.05)
    assert proc.terminated is True
    assert proc.killed is True


def test_terminate_sync_noop_on_exited_process():
    """An already-exited process is never re-terminated/killed."""
    proc = _FakeSyncProc(exits_on_terminate=True)
    proc._rc = 0  # already done
    terminate_sync_process(proc, grace=0.2)
    assert proc.terminated is False
    assert proc.killed is False


def test_terminate_sync_real_subprocess():
    """End-to-end with a REAL long-lived child: it must be dead afterwards."""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    assert proc.poll() is None  # alive
    terminate_sync_process(proc, grace=5.0)
    assert proc.poll() is not None  # terminated, not left running


class _FakeAsyncProc:
    """An asyncio.subprocess.Process-shaped stub (async path)."""

    def __init__(self, *, exit_after):
        # exit_after: seconds until wait() resolves; None = never (forces kill).
        self.returncode = None
        self.terminated = False
        self.killed = False
        self._exit_after = exit_after

    def terminate(self):
        self.terminated = True

    async def wait(self):
        if self._exit_after is None:
            await asyncio.sleep(3600)
        else:
            await asyncio.sleep(self._exit_after)
        self.returncode = -15
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9


def test_terminate_async_graceful_no_kill():
    proc = _FakeAsyncProc(exit_after=0.02)
    asyncio.run(terminate_async_process(proc, grace=2.0))
    assert proc.terminated is True
    assert proc.killed is False


def test_terminate_async_force_kill_after_grace():
    proc = _FakeAsyncProc(exit_after=None)  # never exits on its own
    asyncio.run(terminate_async_process(proc, grace=0.05))
    assert proc.terminated is True
    assert proc.killed is True


def test_terminate_async_noop_on_exited_process():
    proc = _FakeAsyncProc(exit_after=0.0)
    proc.returncode = 0  # already exited
    asyncio.run(terminate_async_process(proc, grace=2.0))
    assert proc.terminated is False
    assert proc.killed is False


# ════════════════════════════════════════════════════════════════════════════
# 2. Cancelled-state persistence — Terraform validate / plan
# ════════════════════════════════════════════════════════════════════════════

def _seed_running_tf_phase(db, *, phase: str, job_id: str) -> tuple[Workflow, Task]:
    proj = Project(id="p-tf", owner_id="u1", name="tf", current_status="active")
    wf = Workflow(
        id="wf-tf", project_id="p-tf", status="running", current_phase=phase,
        phases_state={
            phase: {
                "status": "running",
                "artifact_id": "tf-art-1",
                "job_id": job_id,
                "stream_key": f"task-tf::{'terraform_validate' if phase == 'TERRAFORM_VALIDATION' else 'terraform_plan'}",
            }
        },
    )
    task = Task(id="task-tf", prompt="p", project_id="p-tf", workflow_id="wf-tf",
                workflow_state={})
    db.add_all([proj, wf, task])
    db.commit()
    return wf, task


@pytest.mark.parametrize("phase", ["TERRAFORM_VALIDATION", "TERRAFORM_PLAN"])
def test_record_terraform_phase_cancelled(db, phase):
    """A stopped TF phase becomes `cancelled` while preserving job_id/artifact_id
    (so the UI can still find the job + Replay), and the workflow stays running."""
    from backend.app.services.core.workflow_orchestration_service import (
        WorkflowOrchestrationService,
    )
    from backend.app.services.core.task_service import TaskService

    wf, task = _seed_running_tf_phase(db, phase=phase, job_id="job-xyz")

    WorkflowOrchestrationService.record_terraform_phase_cancelled(
        db, workflow_id=wf.id, task_id=task.id, phase=phase,
    )

    db.refresh(wf)
    entry = wf.phases_state[phase]
    assert entry["status"] == "cancelled"
    assert entry["cancelled"] is True
    assert entry["job_id"] == "job-xyz", "job_id must be preserved for Replay"
    assert entry["artifact_id"] == "tf-art-1"
    # Workflow is NOT terminal — a cancelled phase can be re-run / replayed.
    assert wf.status == "running"

    state = TaskService.load_workflow_state(db, task) or {}
    assert state["terraform_pipeline"][phase]["cancelled"] is True
    assert state["terraform_pipeline"][phase]["ok"] is False


# ════════════════════════════════════════════════════════════════════════════
# 3. Terraform WS surfaces `cancelled` as a terminal status
# ════════════════════════════════════════════════════════════════════════════

def test_terraform_ws_terminal_status_maps_cancelled(db, session_factory, monkeypatch):
    """`_terraform_phase_terminal_status` returns a terminal `cancelled` so the
    WS emits {type:'complete', status:'cancelled'} instead of hanging/failing."""
    import backend.app.api.routes.execution as execmod

    proj = Project(id="p-w", owner_id="u1", name="w", current_status="active")
    wf = Workflow(id="wf-w", project_id="p-w", status="running",
                  current_phase="TERRAFORM_VALIDATION",
                  phases_state={"TERRAFORM_VALIDATION": {"status": "cancelled"}})
    task = Task(id="task-w", prompt="p", project_id="p-w", workflow_id="wf-w",
                workflow_state={})
    db.add_all([proj, wf, task])
    db.commit()

    # The helper opens its own SessionLocal — point it at the shared in-memory DB.
    monkeypatch.setattr(execmod, "SessionLocal", session_factory)

    status, exit_code, terminal = execmod._terraform_phase_terminal_status(
        "task-w", "TERRAFORM_VALIDATION",
    )
    assert terminal is True
    assert status == "cancelled"
    assert exit_code is None


# ════════════════════════════════════════════════════════════════════════════
# 4. Cancelled-state persistence — Docker build
# ════════════════════════════════════════════════════════════════════════════

def _seed_running_docker(db, *, status="running") -> Task:
    proj = Project(id="p-d", owner_id="u1", name="d", current_status="active")
    task = Task(
        id="task-d", prompt="p", project_id="p-d", workflow_id=None,
        workflow_state={
            "current_phase": "docker_build_running",
            "execution": {"docker": {"status": status, "build_number": 2,
                                      "logs": [{"message": "step 1"}]}},
        },
    )
    db.add_all([proj, task])
    db.commit()
    return task


def test_persist_docker_cancelled_marks_cancelled(db, session_factory, monkeypatch):
    """A stopped docker build is persisted as `cancelled` (not stuck running),
    stamped finished_at, and routed to a re-runnable terminal phase. Streamed
    logs are preserved."""
    import backend.app.api.routes.execution as execmod

    _seed_running_docker(db, status="running")
    monkeypatch.setattr(execmod, "SessionLocal", session_factory)

    execmod._persist_docker_cancelled("task-d", build_number=2)

    fresh = session_factory()
    try:
        task = fresh.query(Task).filter(Task.id == "task-d").first()
        docker = task.workflow_state["execution"]["docker"]
        assert docker["status"] == "cancelled"
        assert docker["finished_at"] is not None
        assert docker["logs"], "already-streamed logs must be preserved"
        # Re-runnable terminal so Rebuild / Replay light up.
        assert task.workflow_state["current_phase"] == "docker_build_failed"
    finally:
        fresh.close()


def test_persist_docker_cancelled_does_not_clobber_terminal(db, session_factory, monkeypatch):
    """A racing finaliser already wrote success/failed → cancel must NOT downgrade it."""
    import backend.app.api.routes.execution as execmod

    _seed_running_docker(db, status="success")
    monkeypatch.setattr(execmod, "SessionLocal", session_factory)

    execmod._persist_docker_cancelled("task-d", build_number=2)

    fresh = session_factory()
    try:
        task = fresh.query(Task).filter(Task.id == "task-d").first()
        assert task.workflow_state["execution"]["docker"]["status"] == "success"
    finally:
        fresh.close()


# ════════════════════════════════════════════════════════════════════════════
# 5. Replay AFTER cancellation
# ════════════════════════════════════════════════════════════════════════════

def test_replay_after_cancellation_reenqueues_jobs(db, storage):
    """After a phase is cancelled, the deterministic replay re-enqueues the SAME
    durable jobs from DB artifacts (no LLM, no regeneration) — proving a stopped
    workflow can be resumed via the existing replay infrastructure."""
    from backend.app.services.core.artifact_persistence_service import (
        ArtifactPersistenceService as APS,
    )
    from backend.app.services.core.workflow_replay_service import WorkflowReplayService

    proj = Project(id="p-r", owner_id="u1", name="r", current_status="active")
    # The validation phase was CANCELLED on the prior run.
    wf = Workflow(
        id="wf-r", project_id="p-r", status="running",
        current_phase="TERRAFORM_VALIDATION",
        phases_state={"TERRAFORM_VALIDATION": {"status": "cancelled", "cancelled": True}},
    )
    task = Task(id="task-r", prompt="p", project_id="p-r", workflow_id="wf-r",
                workflow_state={"repo_url": "https://example.com/r",
                                "plan": {"project_name": "demo"}})
    db.add_all([proj, wf, task])
    db.commit()

    APS.upsert_artifact(db, project_id="p-r", workflow_id="wf-r",
                        artifact_type="terraform", artifact_subtype="main.tf",
                        content='resource "null_resource" "x" {}\n')
    APS.upsert_artifact(db, project_id="p-r", workflow_id="wf-r",
                        artifact_type="docker", artifact_subtype="dockerfile",
                        content="FROM python:3.11\n")
    db.commit()

    result = WorkflowReplayService.replay(db, project=proj, workflow=wf, task=task)

    assert result["llm_used"] is False
    assert result["replayed"] is True
    job_phases = {j.phase for j in db.query(ExecutionJob).all()}
    assert job_phases == {"terraform_validate", "terraform_plan", "docker_build"}
    # The freshly enqueued validate job is pending (claimable again) — the cancel
    # did not block re-execution.
    validate = db.query(ExecutionJob).filter(
        ExecutionJob.phase == "terraform_validate"
    ).first()
    assert validate.status == "pending"


# ════════════════════════════════════════════════════════════════════════════
# 6. Lifecycle reconciliation — terminal JOB ⇒ workflow phase
# ════════════════════════════════════════════════════════════════════════════
#
# The in-handler finaliser is NOT the only way a job goes terminal: an operator
# can cancel a still-pending job, the reaper can fail an orphaned one (a uvicorn
# --reload kills the worker that owned it), and a handler can raise before
# recording. In every such case the workflow phase must NOT stay stuck 'running'
# — JobService reconciles it from the job's terminal status.

def _seed_tf_job(db, *, phase_job: str, status: str, wf_phase: str,
                 heartbeat=None, max_retries=0):
    """A durable TF ExecutionJob wired to the seeded workflow/task/phase."""
    job = ExecutionJob(
        id=f"job-{phase_job}",
        project_id="p-tf",
        workflow_id="wf-tf",
        task_id="task-tf",
        phase=phase_job,                       # 'terraform_validate' | 'terraform_plan'
        status=status,
        cancel_requested="false",
        retry_count=0,
        max_retries=max_retries,
        heartbeat_at=heartbeat,
        execution_context={
            "artifact_id": "tf-art-1",
            "task_id": "task-tf",
            "workflow_id": "wf-tf",
            "phase": wf_phase,                 # 'TERRAFORM_PLAN' | 'TERRAFORM_VALIDATION'
            "stream_key": f"task-tf::{phase_job}",
        },
    )
    db.add(job)
    db.commit()
    return job


def test_reaped_orphan_tf_job_reconciles_phase_to_failed(db):
    """A running TF job orphaned by a dead worker → reaper fails it AND the
    workflow phase moves running→failed (no longer stuck), preserving Replay
    pointers. This is the uvicorn --reload orphan path."""
    from backend.app.services.execution.job_service import JobService

    wf, task = _seed_running_tf_phase(db, phase="TERRAFORM_PLAN", job_id="job-terraform_plan")
    _seed_tf_job(
        db, phase_job="terraform_plan", status="running", wf_phase="TERRAFORM_PLAN",
        heartbeat=None,  # null heartbeat on a running job ⇒ reaped immediately
        max_retries=0,
    )

    reaped = JobService.reap_stale_jobs(db, heartbeat_timeout_seconds=20)
    assert reaped == 1

    job = JobService.get(db, "job-terraform_plan")
    assert job.status == "failed"  # budget spent (max_retries=0)

    db.refresh(wf)
    entry = wf.phases_state["TERRAFORM_PLAN"]
    assert entry["status"] == "failed", "orphaned phase must not stay 'running'"
    assert entry["artifact_id"] == "tf-art-1", "Replay pointer preserved"
    assert entry["job_id"] == "job-terraform_plan"
    assert wf.status == "running"  # re-runnable / replayable


def test_cancel_pending_tf_job_reconciles_phase_to_cancelled(db):
    """Cancelling a still-PENDING TF job (worker never ran the handler) must
    settle the workflow phase to cancelled, not leave it running."""
    from backend.app.services.execution.job_service import JobService

    wf, task = _seed_running_tf_phase(db, phase="TERRAFORM_VALIDATION",
                                      job_id="job-terraform_validate")
    _seed_tf_job(db, phase_job="terraform_validate", status="pending",
                 wf_phase="TERRAFORM_VALIDATION")

    result = JobService.request_cancel(db, "job-terraform_validate")
    assert result == "cancelled"  # pending → straight to cancelled

    db.refresh(wf)
    assert wf.phases_state["TERRAFORM_VALIDATION"]["status"] == "cancelled"
    assert wf.phases_state["TERRAFORM_VALIDATION"]["job_id"] == "job-terraform_validate"


def test_reconcile_does_not_clobber_already_settled_phase(db):
    """If the handler already settled the phase (e.g. 'completed'), a later
    job-terminal transition must NOT overwrite that verdict (idempotency)."""
    from backend.app.services.execution.job_service import JobService

    wf, task = _seed_running_tf_phase(db, phase="TERRAFORM_PLAN", job_id="job-terraform_plan")
    # Handler already recorded a real outcome before the job row finalised.
    wf.phases_state = {"TERRAFORM_PLAN": {"status": "completed", "artifact_id": "tf-art-1"}}
    db.commit()

    _seed_tf_job(db, phase_job="terraform_plan", status="running",
                 wf_phase="TERRAFORM_PLAN", max_retries=0)

    JobService.mark_failed_or_retry(db, "job-terraform_plan", error_message="late failure")

    db.refresh(wf)
    assert wf.phases_state["TERRAFORM_PLAN"]["status"] == "completed", (
        "a settled phase must survive a later job-terminal transition"
    )
