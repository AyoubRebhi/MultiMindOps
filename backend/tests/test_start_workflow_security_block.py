"""start_workflow security-block coherence tests.

After the analysis-resilience fix, a security-blocked repo no longer crashes —
``run_architecture_decision_phase`` returns ``status="blocked"`` with no
architecture strategies. ``start_workflow`` must represent that honestly:

* a BLOCKED analysis → workflow ``current_phase=ANALYSIS`` / ``status=blocked``
  (terminal), so the UI resolves to the analysis surface instead of fetching a
  non-existent architecture-decision (which 404'd and broke the run view);
* a NORMAL analysis → workflow ``ARCHITECTURE_DECISION`` / ``awaiting_input``
  (unchanged behaviour).

The orchestrator + all DB collaborators are mocked so the test exercises only
the branch logic in ``start_workflow``.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.app.services.core import workflow_orchestration_service as wos_mod
from backend.app.services.core.workflow_orchestration_service import (
    TERMINAL_WORKFLOW_STATUSES,
    WorkflowOrchestrationService,
)


class _FakeSession:
    def __init__(self):
        self.committed = False

    def add(self, _obj):
        pass

    def flush(self):
        pass

    def commit(self):
        self.committed = True

    def refresh(self, _obj):
        pass


def _run_start_workflow(arch_state: dict):
    """Drive start_workflow with a controlled orchestrator output."""
    db = _FakeSession()
    project = SimpleNamespace(id="proj-1", repository_url="https://example.com/r")
    user = SimpleNamespace(id="user-1")
    fake_task = SimpleNamespace(id="task-1", workflow_state=None, status=None)

    orch = MagicMock()
    orch.run_architecture_decision_phase.return_value = arch_state

    with patch.object(wos_mod, "OrchestratorAgent", return_value=orch), \
         patch.object(wos_mod.CredentialsService, "get_credential", return_value=None), \
         patch.object(wos_mod.TaskService, "create_task", return_value=fake_task), \
         patch.object(wos_mod.TaskService, "update_task_status") as upd_status, \
         patch.object(wos_mod.TaskService, "save_plan_awaiting_validation") as save_plan, \
         patch.object(wos_mod.TaskService, "save_workflow_state") as save_state, \
         patch.object(wos_mod.ProjectContextService, "capture_from_state") as capture:
        workflow, task, state = WorkflowOrchestrationService.start_workflow(
            db, project=project, user=user, prompt="go", execution_mode="full",
        )

    return {
        "workflow": workflow,
        "task": task,
        "state": state,
        "upd_status": upd_status,
        "save_plan": save_plan,
        "save_state": save_state,
        "capture": capture,
    }


def test_blocked_analysis_marks_workflow_blocked_at_analysis_phase():
    blocked_state = {
        "status": "blocked",
        "repository_security": {
            "status": "blocked",
            "blocked_reasons": ["secret detected in css/swiper-bundle.min.css"],
        },
        # no architecture_decision — the gate short-circuited
    }
    out = _run_start_workflow(blocked_state)
    wf = out["workflow"]

    assert wf.status == "blocked"
    assert wf.current_phase == "ANALYSIS"
    # phase record reflects the block + reasons
    analysis_phase = wf.phases_state["ANALYSIS"]
    assert analysis_phase["status"] == "blocked"
    assert analysis_phase["blocked_reasons"] == [
        "secret detected in css/swiper-bundle.min.css"
    ]
    # The task is marked blocked (after the initial "in_progress") and we do NOT
    # route through the plan-awaiting path.
    statuses = [c.args[-1] for c in out["upd_status"].call_args_list]
    assert statuses == ["in_progress", "blocked"]
    out["save_plan"].assert_not_called()
    out["save_state"].assert_called_once()
    # Context captured under the ANALYSIS phase, not ARCHITECTURE_DECISION.
    assert out["capture"].call_args.kwargs["phase"] == "ANALYSIS"


def test_normal_analysis_stays_awaiting_input_on_architecture_decision():
    normal_state = {
        "status": "awaiting_architecture_selection",
        "repository_security": {"status": "safe"},
        "architecture_decision": {"plans": [{"id": "balanced"}], "recommended_plan": "balanced"},
    }
    out = _run_start_workflow(normal_state)
    wf = out["workflow"]

    assert wf.status == "awaiting_input"
    assert wf.current_phase == "ARCHITECTURE_DECISION"
    assert wf.phases_state["ARCHITECTURE_DECISION"]["status"] == "awaiting_input"
    out["save_plan"].assert_called_once()
    out["save_state"].assert_not_called()
    # Only the initial "in_progress" transition — no "blocked" on the normal path.
    statuses = [c.args[-1] for c in out["upd_status"].call_args_list]
    assert statuses == ["in_progress"]
    assert out["capture"].call_args.kwargs["phase"] == "ARCHITECTURE_DECISION"


def test_blocked_is_a_terminal_status():
    # A blocked workflow must be terminal so a project can start a fresh run
    # after the repo is fixed (get_or_create_workflow won't reuse a terminal one).
    assert "blocked" in TERMINAL_WORKFLOW_STATUSES
