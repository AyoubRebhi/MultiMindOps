"""ArtifactApprovalService.

Append-only approval workflow. Every decision (approve / reject /
request_changes) becomes an ``ArtifactApproval`` row and updates the
denormalized ``Artifact.approval_state`` so the UI does not have to walk
history to render a badge.

Authorization is enforced at the route layer via ``require_project_role``.
This service trusts that the caller is allowed to act.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from backend.app.models.artifact import Artifact, ArtifactApproval

logger = logging.getLogger(__name__)


# action → resulting approval_state
_ACTION_TO_STATE = {
    "approve":         "approved",
    "reject":          "rejected",
    "request_changes": "requires_changes",
}


class ArtifactApprovalService:
    @staticmethod
    def record(
        db: Session,
        *,
        artifact: Artifact,
        user_id: str,
        action: str,
        comment: Optional[str] = None,
    ) -> Tuple[Artifact, ArtifactApproval]:
        if action not in _ACTION_TO_STATE:
            raise ValueError(
                f"Unknown approval action '{action}'. "
                f"Expected one of: {sorted(_ACTION_TO_STATE)}"
            )

        # Phase 2 — bind the approval to the EXACT content + version the
        # reviewer saw. Any subsequent edit changes content_hash and the
        # enforcement gate refuses execution; the approval row itself
        # stays in the audit trail as the historical decision.
        snapshot_hash = artifact.content_hash
        snapshot_version = artifact.version
        approval = ArtifactApproval(
            artifact_id=artifact.id,
            approved_by=user_id,
            action=action,
            comment=comment,
            approved_content_hash=snapshot_hash,
            approved_version=snapshot_version,
        )
        db.add(approval)

        new_state = _ACTION_TO_STATE[action]
        artifact.approval_state = new_state
        now = datetime.now(timezone.utc)
        # Keep the convenience ``approved_by`` pointer aligned with the latest
        # approval so existing reads don't need to join the history table.
        if action == "approve":
            artifact.approved_by = user_id
            artifact.approved_at = now
            artifact.approved_content_hash = snapshot_hash
        elif action == "reject":
            # Clear ``approved_by`` on rejection so stale approvals don't leak through.
            artifact.approved_by = None
            artifact.approved_at = None
            artifact.approved_content_hash = None
        # 'request_changes' — leave the prior approval pointers as they
        # are. The artifact moves to 'requires_changes', the gate refuses
        # execution, and the next edit will invalidate any approval too.

        db.commit()
        db.refresh(artifact)
        db.refresh(approval)
        logger.info(
            "[ArtifactApproval] artifact=%s action=%s state=%s by=%s hash=%s v=%s",
            artifact.id, action, new_state, user_id,
            (snapshot_hash or "")[:12], snapshot_version,
        )
        return artifact, approval

    @staticmethod
    def list_for_artifact(db: Session, artifact_id: str) -> List[ArtifactApproval]:
        return (
            db.query(ArtifactApproval)
            .filter(ArtifactApproval.artifact_id == artifact_id)
            .order_by(ArtifactApproval.created_at.desc())
            .all()
        )
