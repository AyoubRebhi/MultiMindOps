import { useCallback, useEffect, useRef, useState } from 'react';
import EmptyState from '@/components/common/EmptyState';
import { useAsync } from '@/hooks/useAsync';
import { useToast } from '@/hooks/useToast';
import { useDockerBuild } from '@/hooks/useDockerBuild';
import { dockerBuildApi } from '@/services/api/dockerBuildApi';
import DockerGenerationMetadata from './DockerGenerationMetadata';
import DockerValidationPanel from './DockerValidationPanel';
import DockerCorrectorPanel from './DockerCorrectorPanel';
import DockerReviewEditor from './DockerReviewEditor';
import DockerBuildConsole from './DockerBuildConsole';
import DockerFixApprovalPanel from './DockerFixApprovalPanel';
import DockerfileViewer from './DockerfileViewer';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/**
 * DockerReviewBuildSection — the full post-generation Docker experience, wired
 * end-to-end to EXISTING backend endpoints (no new orchestration / agents):
 *
 *   Review  → edit + Save (PATCH /tasks/:id/artifacts) — backend is source of truth
 *   Approve → POST /projects/:pid/artifacts/:aid/approvals
 *   Build   → POST /execution/docker/build/:id  (durable job)
 *   Logs    → WS /ws/execution/:id  (live, reconnecting) via useDockerBuild
 *   Status  → GET /execution/docker/status/:id  (authoritative, never inferred)
 *   Failure → corrector auto-runs (GPT-5-mini → Groq); GET /corrector/:id
 *   Fix     → review diff, then Apply (apply-ai-patch) or Edit Manually
 *   Rebuild → same build endpoint
 *
 * @param {{ projectId, taskId, data, onPhaseRefetch }} props
 *   data = the mapped Docker-phase projection (mapDockerPhase).
 */
export default function DockerReviewBuildSection({
  projectId,
  taskId,
  data,
  onPhaseRefetch,
}) {
  const toast = useToast();
  const mountedRef = useRef(true);
  useEffect(() => () => { mountedRef.current = false; }, []);

  const {
    data: editable,
    loading: editableLoading,
    refetch: refetchEditable,
  } = useAsync(
    () => (taskId ? dockerBuildApi.getEditableDockerfile(taskId) : Promise.resolve(null)),
    [taskId],
    { immediate: !!taskId }
  );

  const [saving, setSaving] = useState(false);
  const [approving, setApproving] = useState(false);
  const [applying, setApplying] = useState(false);
  const [reanalyzing, setReanalyzing] = useState(false);
  const [editSignal, setEditSignal] = useState(0);
  const [correctorBusy, setCorrectorBusy] = useState(false);

  const refetchPhase = useCallback(async () => {
    if (onPhaseRefetch) await onPhaseRefetch();
  }, [onPhaseRefetch]);

  // Corrector analysis runs AFTER the build WS closes; poll until it settles,
  // then reload the projection (carries the analysis) + editable (carries the
  // suggested ai_patched_content).
  const pollCorrector = useCallback(async () => {
    if (!taskId) return;
    setCorrectorBusy(true);
    try {
      for (let i = 0; i < 8; i += 1) {
        await sleep(2500);
        if (!mountedRef.current) return;
        const c = await dockerBuildApi.getCorrector(taskId).catch(() => null);
        if (c && c.status && c.status !== 'running') break;
      }
      await Promise.allSettled([refetchEditable(), refetchPhase()]);
    } finally {
      if (mountedRef.current) setCorrectorBusy(false);
    }
  }, [taskId, refetchEditable, refetchPhase]);

  const handleComplete = useCallback(
    async (finalStatus) => {
      await Promise.allSettled([refetchEditable(), refetchPhase()]);
      if (finalStatus === 'failed') pollCorrector();
    },
    [refetchEditable, refetchPhase, pollCorrector]
  );

  const build = useDockerBuild(taskId, { onComplete: handleComplete });

  /* ── Derived view model ─────────────────────────────────────────────────── */
  const dockerfileContent = editable?.content || data?.dockerfile?.content || '';
  const originalContent = editable?.originalContent || data?.dockerfile?.originalContent || '';
  const approvalState = data?.dockerfile?.approvalState || null;
  const approved = approvalState === 'approved';
  const version = editable?.version ?? data?.dockerfile?.version ?? null;
  const edited =
    (data?.dockerfile?.edited ?? false) ||
    !!editable?.userModified ||
    (!!originalContent && dockerfileContent.trim() !== originalContent.trim());
  const suggested = editable?.aiPatchedContent || null;
  const corrector = data?.corrector || {};
  const validation = data?.validation || {};
  const metadata = data?.metadata || {};

  const buildFailed = build.status === 'failed';
  const buildLabel =
    build.status === 'success' || build.status === 'failed' || build.status === 'blocked'
      ? 'Rebuild'
      : 'Build Docker Image';

  /* ── Actions ────────────────────────────────────────────────────────────── */
  async function handleSave(next) {
    if (!taskId) return;
    setSaving(true);
    try {
      await dockerBuildApi.saveDockerfile(taskId, next);
      toast.success('Dockerfile saved.');
      await Promise.allSettled([refetchEditable(), refetchPhase()]);
    } catch (e) {
      toast.error(e?.message || 'Could not save the Dockerfile. Please try again.');
    } finally {
      setSaving(false);
    }
  }

  async function handleApprove() {
    if (!projectId) return;
    setApproving(true);
    try {
      const artifactId = await dockerBuildApi.findDockerfileArtifactId(projectId);
      if (!artifactId) {
        throw new Error(
          'The Dockerfile artifact is not persisted yet — run a build so the artifact is stored, then approve.'
        );
      }
      await dockerBuildApi.approveDockerfile(projectId, artifactId);
      toast.success('Dockerfile approved.');
      await refetchPhase();
    } catch (e) {
      toast.error(e?.message || 'Could not approve the Dockerfile.');
    } finally {
      setApproving(false);
    }
  }

  async function handleBuild() {
    const res = await build.start();
    if (!res?.ok && res?.error && res.error.status !== 422) {
      toast.error(res.error.message || 'Could not start the Docker build.');
    }
  }

  async function handleApplyFix() {
    if (!taskId) return;
    setApplying(true);
    try {
      await dockerBuildApi.applyAiPatch(taskId);
      toast.success('Suggested fix applied to the Dockerfile.');
      await Promise.allSettled([refetchEditable(), refetchPhase()]);
    } catch (e) {
      toast.error(e?.message || 'Could not apply the suggested fix.');
    } finally {
      setApplying(false);
    }
  }

  async function handleReanalyze() {
    if (!taskId) return;
    setReanalyzing(true);
    try {
      await dockerBuildApi.reanalyze(taskId);
      toast.success('Corrector re-analysis started.');
      await pollCorrector();
    } catch (e) {
      toast.error(e?.message || 'Could not start corrector analysis.');
    } finally {
      setReanalyzing(false);
    }
  }

  function handleEditManually() {
    setEditSignal((s) => s + 1);
  }

  if (!taskId) {
    return (
      <EmptyState
        icon="fa-circle-info"
        title="Build is unavailable for this run"
        message="This workflow has no backing task, so the Docker build pipeline can't be driven here. Regenerate the Docker phase to create one."
      />
    );
  }

  let n = 0;
  const next = () => (n += 1);

  return (
    <>
      {/* ── Docker Review ─────────────────────────────────────────────────── */}
      <div className="section-label mt-2">
        <span className="section-label-chip">{next()}</span>
        Docker Review
        <span className="section-label-by">Edit · Save · Approve</span>
      </div>
      {editableLoading && !editable ? (
        <div className="surface"><span className="spinner me-2" />Loading the Dockerfile…</div>
      ) : (
        <DockerReviewEditor
          content={dockerfileContent}
          version={version}
          approvalState={approvalState}
          edited={edited}
          saving={saving}
          approving={approving}
          onSave={handleSave}
          onApprove={handleApprove}
          editSignal={editSignal}
        />
      )}

      {/* ── Generation Metadata ───────────────────────────────────────────── */}
      <div className="section-label mt-4">
        <span className="section-label-chip">{next()}</span>
        Generation Metadata
        <span className="section-label-by">Detected build shape</span>
      </div>
      <DockerGenerationMetadata metadata={metadata} />

      {/* ── Validation ────────────────────────────────────────────────────── */}
      <div className="section-label mt-4">
        <span className="section-label-chip">{next()}</span>
        Docker Validation Results
        <span className="section-label-by">Static analysis</span>
      </div>
      <DockerValidationPanel validation={validation} />

      {/* ── Build & Logs ──────────────────────────────────────────────────── */}
      <div className="section-label mt-4">
        <span className="section-label-chip">{next()}</span>
        Docker Build
        <span className="section-label-by">Live build · WebSocket logs</span>
      </div>
      <div className="surface d-flex align-items-center gap-3 flex-wrap mb-2">
        <button
          type="button"
          className="bgrd btn px-4 py-2"
          style={{ fontSize: '.85rem' }}
          disabled={build.building || build.starting}
          onClick={handleBuild}
        >
          {build.building || build.starting ? (
            <><span className="spinner me-2" />Building…</>
          ) : (
            <><i className="fa-solid fa-hammer me-2" />{buildLabel}</>
          )}
        </button>
        <span style={{ fontSize: '.8rem', color: 'var(--tx2)' }}>
          {approved ? (
            <><i className="fa-solid fa-shield-halved me-2" style={{ color: '#34d399' }} />Approved Dockerfile — building the image.</>
          ) : (
            <><i className="fa-solid fa-circle-info me-2" style={{ color: 'var(--tx3)' }} />You can build before approving; the build uses your latest saved Dockerfile.</>
          )}
        </span>
      </div>

      {build.status === 'blocked' && build.blockReason && (
        <div className="surface d-flex align-items-start gap-2 mb-2" style={{ borderLeft: '3px solid #f87171' }}>
          <i className="fa-solid fa-ban" style={{ color: '#f87171', marginTop: 2 }} />
          <div style={{ fontSize: '.84rem' }}>
            <strong>Build blocked by pre-build validation.</strong>
            <div style={{ color: 'var(--tx2)', marginTop: 2 }}>{build.blockReason}</div>
            <div style={{ color: 'var(--tx3)', marginTop: 4 }}>
              Fix the Dockerfile above (Edit → Save), then rebuild.
            </div>
          </div>
        </div>
      )}

      <DockerBuildConsole
        logs={build.logs}
        status={build.status}
        connectionState={build.connectionState}
        exitCode={build.exitCode}
        imageTag={build.imageTag}
        onReconnect={build.reconnect}
      />

      {/* ── Build Failure Analysis (corrector) ────────────────────────────── */}
      {(buildFailed || corrector.available || correctorBusy) && (
        <>
          <div className="section-label mt-4">
            <span className="section-label-chip">{next()}</span>
            Build Failure Analysis
            <span className="section-label-by">Auto-diagnosis · GPT-5-mini → Groq</span>
          </div>
          {correctorBusy ? (
            <div className="surface d-flex align-items-center gap-2" style={{ fontSize: '.85rem' }}>
              <span className="spinner" />
              The corrector is analyzing the build failure…
            </div>
          ) : corrector.available ? (
            <DockerCorrectorPanel corrector={corrector} />
          ) : (
            <div className="surface d-flex align-items-start gap-3" style={{ borderLeft: '3px solid var(--tx3)' }}>
              <i className="fa-solid fa-wand-magic-sparkles" style={{ color: 'var(--tx3)', marginTop: 2 }} />
              <div style={{ fontSize: '.85rem' }}>
                <strong>Corrector analysis unavailable.</strong>
                <div style={{ color: 'var(--tx2)', marginTop: 2 }}>
                  The build failed but no analysis is available yet. You can re-run the
                  analysis on the stored build logs without rebuilding.
                </div>
                <button
                  type="button"
                  className="boc btn px-3 py-2 mt-2"
                  style={{ fontSize: '.8rem' }}
                  disabled={reanalyzing}
                  onClick={handleReanalyze}
                >
                  {reanalyzing ? <span className="spinner me-2" /> : <i className="fa-solid fa-rotate-right me-2" />}
                  Re-run analysis
                </button>
              </div>
            </div>
          )}
        </>
      )}

      {/* ── Suggested Fix (apply / edit manually + diff) ──────────────────── */}
      {suggested && (
        <>
          <div className="section-label mt-4">
            <span className="section-label-chip">{next()}</span>
            Suggested Fix
            <span className="section-label-by">Current ↓ Suggested</span>
          </div>
          <DockerFixApprovalPanel
            current={dockerfileContent}
            suggested={suggested}
            applying={applying}
            onApplyFix={handleApplyFix}
            onEditManually={handleEditManually}
          />
        </>
      )}

      {/* ── Approved Dockerfile ───────────────────────────────────────────── */}
      <div className="section-label mt-4">
        <span className="section-label-chip"><i className="fa-solid fa-shield-halved" /></span>
        Approved Dockerfile
        <span className="section-label-by">Used by later phases</span>
      </div>
      {approved ? (
        <DockerfileViewer
          content={dockerfileContent}
          version={version}
          approvalState="approved"
          title="Approved Dockerfile"
        />
      ) : (
        <div className="surface d-flex align-items-start gap-3" style={{ borderLeft: '3px solid var(--tx3)' }}>
          <i className="fa-solid fa-circle-info" style={{ color: 'var(--tx3)', marginTop: 2 }} />
          <div style={{ fontSize: '.86rem' }}>
            This Dockerfile is the current persisted artifact later phases will use. It is
            awaiting approval{data?.dockerfile?.validationStatus ? ` (validation: ${data.dockerfile.validationStatus})` : ''} —
            approve it from the <strong>Docker Review</strong> panel above once the build succeeds.
          </div>
        </div>
      )}
    </>
  );
}
