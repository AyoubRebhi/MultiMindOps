import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import Modal from '@/components/common/Modal';
import { useToast } from '@/hooks/useToast';
import { workflowApi } from '@/services/api/workflowApi';
import {
  CANONICAL_PHASE_ORDER,
  CANCELLABLE_PHASES,
  WORKFLOW_PHASE_VIEW,
  getWorkflowPhaseMeta,
  getStatusMeta,
  canRegeneratePhase,
  downstreamPhases,
  INVALIDATED_STATUS,
} from '@/utils/constants';

/**
 * WorkflowPhaseNav — the revision-aware phase navigator shown above every
 * workflow phase surface. It delivers the three revision-feature UI affordances:
 *
 *   1. Navigate to ANY previous phase — every recorded phase is a clickable chip
 *      that opens its surface (deep-links the :view segment).
 *   2. Regenerate a completed phase — a Regenerate action on each completed/stale
 *      regeneratable phase (Docker / Terraform / GitHub Actions).
 *   3. Dependency warning — before regenerating, a modal lists the downstream
 *      phases that will be marked stale (invalidated) and must be re-run.
 *
 * It also shows per-phase revision badges (v2, v3…), an "invalidated" marker on
 * stale phases, and a collapsible revision history. All execution is owned by the
 * backend (POST .../phases/:phase/regenerate); this component only reads
 * phases_state + triggers the call, then asks the parent to refetch.
 *
 * @param {{
 *   projectId: string,
 *   workflowId: string,
 *   phasesState: Record<string, any>,
 *   currentPhase: string|null,
 *   activeView: string,
 *   status?: string,
 *   revisions?: Array<object>,
 *   onRegenerated?: () => void,
 * }} props
 */
export default function WorkflowPhaseNav({
  projectId,
  workflowId,
  phasesState = {},
  currentPhase,
  activeView,
  status,
  revisions = [],
  onRegenerated,
}) {
  const toast = useToast();
  const navigate = useNavigate();
  const [pendingPhase, setPendingPhase] = useState(null); // phase awaiting confirm
  const [busyPhase, setBusyPhase] = useState(null);
  const [showHistory, setShowHistory] = useState(false);
  const [cancelOpen, setCancelOpen] = useState(false);
  const [cancelling, setCancelling] = useState(false);

  // Cancellation is offered while the run is at a deployment/observation phase
  // and has not already been cancelled.
  const canCancel =
    CANCELLABLE_PHASES.has((currentPhase || '').toUpperCase()) && status !== 'cancelled';

  // Recorded phases in canonical lifecycle order (unknown phases appended).
  const phases = useMemo(() => {
    const recorded = Object.entries(phasesState || {}).filter(
      ([, e]) => e && typeof e === 'object'
    );
    return recorded
      .map(([name, entry]) => ({ name, entry }))
      .sort((a, b) => orderIndex(a.name) - orderIndex(b.name));
  }, [phasesState]);

  // The downstream phases that a regeneration of `pendingPhase` would actually
  // invalidate (recorded + not already stale) — what the warning enumerates.
  const impacted = useMemo(() => {
    if (!pendingPhase) return [];
    return downstreamPhases(pendingPhase).filter((p) => {
      const e = phasesState?.[p];
      return e && typeof e === 'object' && e.status !== INVALIDATED_STATUS;
    });
  }, [pendingPhase, phasesState]);

  if (!projectId || phases.length === 0) return null;

  async function confirmRegenerate() {
    const phase = pendingPhase;
    if (!phase) return;
    setPendingPhase(null);
    setBusyPhase(phase);
    try {
      const res = await workflowApi.regeneratePhase(projectId, workflowId, phase);
      if (res.revised) {
        const n = res.invalidatedPhases?.length || 0;
        toast.success(
          n > 0
            ? `${phaseLabel(phase)} regenerated (v${res.revision}). ${n} downstream phase${n > 1 ? 's' : ''} marked stale.`
            : `${phaseLabel(phase)} regenerated (v${res.revision}).`
        );
      } else {
        toast.error(
          `${phaseLabel(phase)} re-ran but did not complete — nothing downstream was changed.`
        );
      }
      // Land on the regenerated phase's surface so the new output is visible.
      const view = WORKFLOW_PHASE_VIEW[phase];
      if (view && view !== activeView) {
        navigate(`/workflows/run/${workflowId}/${view}`);
      }
      onRegenerated?.();
    } catch (e) {
      toast.error(e?.message || `Could not regenerate ${phaseLabel(phase)}.`);
    } finally {
      setBusyPhase(null);
    }
  }

  async function confirmCancel() {
    if (cancelling) return;
    setCancelling(true);
    try {
      const res = await workflowApi.cancelWorkflow(projectId, workflowId);
      toast.success(res.message || 'Workflow cancelled.');
      setCancelOpen(false);
      onRegenerated?.(); // reuse the parent's refetch to refresh status + phases
    } catch (e) {
      toast.error(e?.message || 'Could not cancel the workflow.');
    } finally {
      setCancelling(false);
    }
  }

  return (
    <div className="surface mb-3" style={{ padding: '12px 14px' }}>
      <div className="d-flex align-items-center justify-content-between flex-wrap gap-2 mb-2">
        <div className="d-flex align-items-center gap-2 text-muted" style={{ fontSize: '.74rem' }}>
          <i className="fa-solid fa-diagram-project" />
          <span>Workflow phases — click to revisit, regenerate to revise</span>
        </div>
        <div className="d-flex align-items-center gap-2">
          {revisions.length > 0 && (
            <button
              type="button"
              className="boc btn px-2 py-1"
              style={{ fontSize: '.72rem' }}
              onClick={() => setShowHistory((v) => !v)}
            >
              <i className="fa-solid fa-clock-rotate-left me-1" />
              Revision history ({revisions.length})
            </button>
          )}
          {canCancel && (
            <button
              type="button"
              className="btn px-2 py-1"
              style={{ fontSize: '.72rem', border: '1px solid #ef4444', color: '#ef4444' }}
              onClick={() => setCancelOpen(true)}
              title="Cancel this workflow"
            >
              <i className="fa-solid fa-ban me-1" />
              Cancel Workflow
            </button>
          )}
          {status === 'cancelled' && (
            <span className="badge-pill badge-pending" style={{ fontSize: '.72rem' }}>
              <i className="fa-solid fa-ban" /> Cancelled · re-run a phase to resume
            </span>
          )}
        </div>
      </div>

      {/* Phase chips */}
      <div className="d-flex align-items-stretch gap-2" style={{ overflowX: 'auto', paddingBottom: 4 }}>
        {phases.map(({ name, entry }, i) => (
          <PhaseChip
            key={name}
            name={name}
            entry={entry}
            isActive={WORKFLOW_PHASE_VIEW[name] === activeView}
            isCurrent={name === currentPhase}
            showArrow={i < phases.length - 1}
            busy={busyPhase === name}
            onOpen={() => openPhase(navigate, workflowId, name)}
            onRegenerate={() => setPendingPhase(name)}
          />
        ))}
      </div>

      {showHistory && <RevisionHistory revisions={revisions} />}

      {/* Dependency warning before regenerating */}
      <Modal
        open={!!pendingPhase}
        onClose={() => setPendingPhase(null)}
        title={`Regenerate ${phaseLabel(pendingPhase)}?`}
        icon="fa-rotate-right"
        footer={
          <>
            <button type="button" className="boc btn px-3 py-2" style={{ fontSize: '.82rem' }} onClick={() => setPendingPhase(null)}>
              Cancel
            </button>
            <button type="button" className="bgrd btn px-3 py-2" style={{ fontSize: '.82rem' }} onClick={confirmRegenerate}>
              <i className="fa-solid fa-rotate-right me-2" />
              Regenerate
            </button>
          </>
        }
      >
        <p style={{ fontSize: '.86rem' }}>
          This re-runs the <strong>{phaseLabel(pendingPhase)}</strong> phase and creates a new
          version of its artifacts. The previous version is preserved in history — nothing is
          deleted.
        </p>
        {impacted.length > 0 ? (
          <div className="surface" style={{ borderLeft: '3px solid #eab308' }}>
            <div className="d-flex align-items-center gap-2 mb-2" style={{ fontSize: '.82rem' }}>
              <i className="fa-solid fa-triangle-exclamation" style={{ color: '#eab308' }} />
              <strong>These downstream phases will be marked stale</strong>
            </div>
            <ul className="mb-1" style={{ fontSize: '.82rem' }}>
              {impacted.map((p) => (
                <li key={p}>{phaseLabel(p)}</li>
              ))}
            </ul>
            <div className="text-muted" style={{ fontSize: '.76rem' }}>
              They were produced from the current output and must be re-run so they reflect the new
              version.
            </div>
          </div>
        ) : (
          <div className="text-muted" style={{ fontSize: '.8rem' }}>
            No downstream phases have run yet, so nothing else is affected.
          </div>
        )}
      </Modal>

      {/* Cancel-workflow confirmation */}
      <Modal
        open={cancelOpen}
        onClose={() => setCancelOpen(false)}
        title="Cancel this workflow?"
        icon="fa-ban"
        footer={
          <>
            <button type="button" className="boc btn px-3 py-2" style={{ fontSize: '.82rem' }} onClick={() => setCancelOpen(false)}>
              Keep running
            </button>
            <button
              type="button"
              className="btn px-3 py-2"
              style={{ fontSize: '.82rem', background: '#ef4444', color: '#fff', opacity: cancelling ? 0.6 : 1 }}
              disabled={cancelling}
              onClick={confirmCancel}
            >
              {cancelling ? <span className="spinner me-2" /> : <i className="fa-solid fa-ban me-2" />}
              Cancel workflow
            </button>
          </>
        }
      >
        <p style={{ fontSize: '.86rem' }}>
          Cancelling stops this workflow and any GitHub Actions run still in progress
          (the cancel is sent to GitHub Actions). The workflow is marked{' '}
          <strong>cancelled</strong>.
        </p>
        <div className="surface" style={{ borderLeft: '3px solid #22c55e' }}>
          <div style={{ fontSize: '.82rem' }}>
            <i className="fa-solid fa-box-archive me-2" style={{ color: '#22c55e' }} />
            All generated artifacts are <strong>preserved</strong>. You can resume later by
            re-running any previous phase from this navigator.
          </div>
        </div>
      </Modal>
    </div>
  );
}

/* ── One phase chip: identity + status + revision + regenerate ───────────────── */

function PhaseChip({ name, entry, isActive, isCurrent, showArrow, busy, onOpen, onRegenerate }) {
  const meta = getWorkflowPhaseMeta(name);
  const status = entry?.status || 'pending';
  const statusMeta = getStatusMeta(status);
  const revision = Number(entry?.revision) || 1;
  const invalidated = status === INVALIDATED_STATUS;
  const regeneratable = canRegeneratePhase(name, status);

  return (
    <div className="d-flex align-items-center" style={{ flex: '0 0 auto' }}>
      <button
        type="button"
        onClick={onOpen}
        title={`Open ${meta.label}`}
        className="surface text-start"
        style={{
          minWidth: 150,
          padding: '8px 10px',
          cursor: 'pointer',
          border: isActive ? '1px solid var(--pur)' : '1px solid transparent',
          background: isActive ? 'rgba(124,108,246,.10)' : undefined,
          borderRadius: 8,
        }}
      >
        <div className="d-flex align-items-center gap-2">
          <i
            className={`${meta.brand ? 'fa-brands' : 'fa-solid'} ${meta.icon}`}
            style={{ opacity: 0.85, fontSize: '.9rem' }}
          />
          <span style={{ fontSize: '.8rem', fontWeight: isCurrent ? 600 : 500 }}>{meta.label}</span>
          {revision > 1 && (
            <span className="badge bg-secondary" style={{ fontSize: '.64rem' }} title={`Revision ${revision}`}>
              v{revision}
            </span>
          )}
        </div>
        <div className="d-flex align-items-center gap-2 mt-1">
          <span
            className={`badge-pill badge-${statusMeta.variant}`}
            style={{ fontSize: '.64rem' }}
          >
            <i className={`fa-solid ${statusMeta.icon} ${statusMeta.variant === 'running' ? 'fa-spin' : ''}`.trim()} />
            {statusMeta.label}
          </span>
          {regeneratable && (
            <span
              role="button"
              tabIndex={0}
              title={invalidated ? 'Re-run this stale phase' : 'Regenerate this phase'}
              onClick={(e) => {
                e.stopPropagation();
                if (!busy) onRegenerate();
              }}
              onKeyDown={(e) => {
                if ((e.key === 'Enter' || e.key === ' ') && !busy) {
                  e.stopPropagation();
                  onRegenerate();
                }
              }}
              className="text-muted"
              style={{ fontSize: '.72rem', cursor: busy ? 'default' : 'pointer' }}
            >
              {busy ? <span className="spinner" /> : <i className="fa-solid fa-rotate-right" />}
            </span>
          )}
        </div>
      </button>
      {showArrow && <i className="fa-solid fa-chevron-right text-muted mx-1" style={{ fontSize: '.7rem' }} />}
    </div>
  );
}

/* ── Revision history list ───────────────────────────────────────────────────── */

function RevisionHistory({ revisions }) {
  return (
    <div className="surface mt-2" style={{ padding: '10px 12px' }}>
      <div className="text-muted mb-2" style={{ fontSize: '.72rem' }}>
        <i className="fa-solid fa-clock-rotate-left me-1" />
        Revision history (newest first)
      </div>
      <ul className="mb-0" style={{ listStyle: 'none', paddingLeft: 0 }}>
        {revisions.map((r, i) => {
          const superseded = Object.keys(r.supersededArtifacts || {});
          return (
            <li
              key={`${r.phase}-${r.revision}-${i}`}
              className="d-flex flex-wrap align-items-center gap-2 py-1"
              style={{ fontSize: '.78rem', borderTop: i ? '1px solid rgba(255,255,255,.06)' : 'none' }}
            >
              <i className="fa-solid fa-rotate-right text-muted" style={{ fontSize: '.7rem' }} />
              <strong>{phaseLabel(r.phase)}</strong>
              <span className="badge bg-secondary" style={{ fontSize: '.64rem' }}>v{r.revision}</span>
              {r.invalidatedPhases?.length > 0 && (
                <span className="text-muted">
                  invalidated {r.invalidatedPhases.map(phaseLabel).join(', ')}
                </span>
              )}
              {superseded.length > 0 && (
                <span className="text-muted">· superseded {superseded.length} artifact{superseded.length > 1 ? 's' : ''}</span>
              )}
              {r.revisedAt && (
                <span className="text-muted ms-auto" style={{ fontSize: '.7rem' }}>
                  {formatWhen(r.revisedAt)}
                </span>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/* ── helpers ─────────────────────────────────────────────────────────────────── */

function orderIndex(name) {
  const i = CANONICAL_PHASE_ORDER.indexOf(name);
  return i === -1 ? CANONICAL_PHASE_ORDER.length : i;
}

function phaseLabel(name) {
  return name ? getWorkflowPhaseMeta(name).label : 'phase';
}

function openPhase(navigate, workflowId, name) {
  const view = WORKFLOW_PHASE_VIEW[name];
  if (view) navigate(`/workflows/run/${workflowId}/${view}`);
}

function formatWhen(iso) {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}
