import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import ContentContainer from '@/components/layout/ContentContainer';
import WorkflowTimeline from '@/components/workflow/WorkflowTimeline';
import WorkflowPhaseHeader from '@/components/workflow/WorkflowPhaseHeader';
import PhaseStatusCard from '@/components/workflow/PhaseStatusCard';
import PipelineGraph from '@/components/workflow/PipelineGraph';
import PipelineStageCard from '@/components/workflow/PipelineStageCard';
import ArtifactExplorer from '@/components/workflow/ArtifactExplorer';
import DeploymentTargetCard from '@/components/workflow/DeploymentTargetCard';
import ExecutionResultCard from '@/components/workflow/ExecutionResultCard';
import RealtimeLogViewer from '@/components/workflow/RealtimeLogViewer';
import LoadingSpinner from '@/components/common/LoadingSpinner';
import StatusBadge from '@/components/common/StatusBadge';
import { executionApi } from '@/services/api/executionApi';
import { deploymentApi } from '@/services/api/deploymentApi';
import { artifactApi } from '@/services/api/artifactApi';
import { formatDate } from '@/utils/formatters';

/**
 * ExecutionCenterPage — workflow Phase 6: the Pipeline Execution Center.
 * Simulates observing a real deployment pipeline (all mock, no backend):
 *   1. Pipeline Overview     → name, status, environment, region, strategy
 *   2. Pipeline Graph        → animated DAG (checkout → … → health checks)
 *   3. Real-Time Logs        → searchable streaming execution feed
 *   4. Pipeline Stages       → per-stage timing + artifacts (after the run)
 *   5. Artifact Explorer     → view / download / inspect produced artifacts
 *   6. Deployment Target     → where it deploys + architecture summary
 *   7. Failure Recovery      → shown only when the run fails
 *   8. Execution Result      → run summary (success) or failure detail
 *
 * Demo: the first run fails while provisioning infrastructure (Failure
 * Recovery), the retry runs the full pipeline green. Route: /workflows/execution.
 */
export default function ExecutionCenterPage() {
  const navigate = useNavigate();

  const [loading, setLoading] = useState(true);
  const [overview, setOverview] = useState(null);
  const [target, setTarget] = useState(null);
  const [artifacts, setArtifacts] = useState([]);

  // Execution run state.
  const [status, setStatus] = useState('not_started'); // not_started|running|completed|failed
  const [attempt, setAttempt] = useState(0);
  const [events, setEvents] = useState([]);
  const [logPlayKey, setLogPlayKey] = useState(0);
  const [graphRunKey, setGraphRunKey] = useState(0);
  const [failIndex, setFailIndex] = useState(-1);
  const [preparing, setPreparing] = useState(false);
  const [stages, setStages] = useState([]);
  const [result, setResult] = useState(null);
  const pendingRef = useRef(null);

  const graphRef = useRef(null);
  const logsRef = useRef(null);
  const stagesRef = useRef(null);
  const recoveryRef = useRef(null);
  const resultRef = useRef(null);

  useEffect(() => {
    let active = true;
    Promise.all([
      executionApi.getOverview(),
      deploymentApi.getTarget(),
      artifactApi.listPipelineArtifacts(),
    ]).then(([ov, tg, arts]) => {
      if (!active) return;
      setOverview(ov);
      setTarget(tg);
      setArtifacts(arts);
      setLoading(false);
    });
    return () => {
      active = false;
    };
  }, []);

  const scrollTo = (ref) =>
    setTimeout(() => ref.current?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 60);

  const runPipeline = async () => {
    if (status === 'running') return;
    setPreparing(true);
    const next = attempt + 1;
    const res = await executionApi.runExecution(next);
    pendingRef.current = res;
    setAttempt(next);
    setEvents(res.logs);
    setFailIndex(res.failIndex);
    setStages([]);
    setResult(null);
    setStatus('running');
    setPreparing(false);
    setGraphRunKey((k) => k + 1);
    setLogPlayKey((k) => k + 1);
    scrollTo(graphRef);
  };

  // The graph animation is deterministic and always settles (the log stream can
  // be paused/cleared by the user), so the graph is authoritative for
  // completion — it reveals the stages, result and recovery sections.
  const onGraphDone = () => {
    const res = pendingRef.current;
    if (!res) return;
    setStatus(res.status);
    setStages(res.stages);
    setResult(res.result);
    scrollTo(res.status === 'failed' ? recoveryRef : resultRef);
  };

  if (loading || !overview || !target) {
    return (
      <ContentContainer>
        <LoadingSpinner center label="Connecting to the pipeline execution feed…" />
      </ContentContainer>
    );
  }

  const completed = status === 'completed';
  const failed = status === 'failed';
  const errorLines = events.filter((e) => e.level === 'error');
  const runLabel =
    status === 'not_started' ? 'Run Pipeline' : failed ? 'Retry Pipeline' : status === 'running' ? 'Running…' : 'Re-run Pipeline';

  return (
    <ContentContainer>
      <WorkflowTimeline
        current="execution"
        statuses={{
          analysis: 'completed',
          planning: 'completed',
          docker: 'completed',
          terraform: 'completed',
          cicd: 'completed',
          execution: status === 'not_started' ? 'running' : status,
        }}
      />

      <WorkflowPhaseHeader
        icon="fa-tower-broadcast"
        eyebrow="Phase 6 of 7"
        title="Pipeline Execution Center"
        subtitle="Observe the generated CI/CD pipeline execute end-to-end and deploy to the cloud."
        status={status === 'not_started' ? 'pending' : status}
        actions={
          <button
            type="button"
            className="bgrd btn px-3 py-2 code-action"
            disabled={status === 'running'}
            onClick={runPipeline}
          >
            {status === 'running' ? (
              <><i className="fa-solid fa-spinner fa-spin me-2" />{runLabel}</>
            ) : (
              <><i className={`fa-solid ${failed ? 'fa-rotate-right' : 'fa-play'} me-2`} />{runLabel}</>
            )}
          </button>
        }
      />

      {/* ============ SECTION 1 — Pipeline Overview ============ */}
      <div className="section-label">
        <span className="section-label-chip">1</span>
        Pipeline Overview
        <span className="section-label-by">{overview.pipelineId}</span>
      </div>
      <PhaseStatusCard
        icon="fa-diagram-project"
        title={overview.name}
        subtitle={`${overview.workflowFile} · ${overview.commit} (${overview.branch})`}
        status={status === 'not_started' ? 'pending' : status}
        className="mb-2"
      >
        <div className="summary-grid">
          <Summary icon="fa-circle-play" label="Status">
            <StatusBadge status={status === 'not_started' ? 'pending' : status} />
          </Summary>
          <Summary icon="fa-clock" label="Started At" value={formatDate(overview.startedAt)} />
          <Summary icon="fa-stopwatch" label="Duration" value={result?.totalDuration || overview.duration} />
          <Summary icon="fa-layer-group" label="Environment" value={overview.environment} />
          <Summary icon="fa-location-dot" label="Target Region" value={overview.region} />
          <Summary icon="fa-id-card-clip" label="AWS Account" value={overview.awsAccount} mono />
          <Summary icon="fa-arrows-spin" label="Deployment Strategy" value={overview.strategy} />
          <Summary icon="fa-user" label="Triggered By" value={overview.triggeredBy} />
        </div>
      </PhaseStatusCard>

      {/* ============ SECTION 2 — Pipeline Graph ============ */}
      <div ref={graphRef}>
        <div className="section-label mt-4">
          <span className="section-label-chip">2</span>
          Pipeline Graph
          <span className="section-label-by">Execution DAG</span>
        </div>
        <PhaseStatusCard
          icon="fa-sitemap"
          title="Pipeline Workflow"
          subtitle="Each stage runs in order — the current step pulses while completed steps turn green."
          status={status === 'not_started' ? 'pending' : status}
          className="mb-2"
        >
          <PipelineGraph nodes={overview.graph} runKey={graphRunKey} failIndex={failIndex} onDone={onGraphDone} />
        </PhaseStatusCard>
      </div>

      {/* ============ SECTION 3 — Real-Time Execution Logs ============ */}
      <div ref={logsRef}>
        <div className="section-label mt-4">
          <span className="section-label-chip">3</span>
          Real-Time Execution Logs
          <span className="section-label-by">live feed · pause · resume · search</span>
        </div>
        <PhaseStatusCard
          icon="fa-terminal"
          title="Execution Feed"
          subtitle="Streaming output from the running pipeline."
          status={status === 'not_started' ? 'pending' : status}
          className="mb-2"
        >
          <RealtimeLogViewer
            events={events}
            playKey={logPlayKey}
            preparing={preparing}
            onStart={runPipeline}
            searchable
            title="Pipeline Execution · live feed"
            startLabel={runLabel}
            emptyHint="Run the pipeline to stream the live execution feed here."
          />
        </PhaseStatusCard>
      </div>

      {/* ============ SECTION 4 — Pipeline Stages ============ */}
      {stages.length > 0 && (
        <div ref={stagesRef}>
          <div className="section-label mt-4">
            <span className="section-label-chip">4</span>
            Pipeline Stages
            <span className="section-label-by">{stages.length} stages</span>
          </div>
          <div className="stage-grid mb-2">
            {stages.map((s) => (
              <PipelineStageCard key={s.key} stage={s} />
            ))}
          </div>
        </div>
      )}

      {/* ============ SECTION 5 — Artifact Explorer ============ */}
      {completed && (
        <div>
          <div className="section-label mt-4">
            <span className="section-label-chip">5</span>
            Artifact Explorer
            <span className="section-label-by">{artifacts.length} artifacts</span>
          </div>
          <PhaseStatusCard
            icon="fa-box-archive"
            title="Produced Artifacts"
            subtitle="Artifacts generated during the run — view, download or inspect each."
            status="completed"
            className="mb-2"
          >
            <ArtifactExplorer artifacts={artifacts} />
          </PhaseStatusCard>
        </div>
      )}

      {/* ============ SECTION 6 — Deployment Target ============ */}
      <div>
        <div className="section-label mt-4">
          <span className="section-label-chip">6</span>
          Deployment Target
          <span className="section-label-by">{target.provider} · {target.region}</span>
        </div>
        <PhaseStatusCard
          icon="fa-bullseye"
          title="Where this pipeline deploys"
          subtitle="The target environment and the architecture being provisioned."
          status="completed"
          className="mb-2"
        >
          <DeploymentTargetCard target={target} />
        </PhaseStatusCard>
      </div>

      {/* ============ SECTION 7 — Failure Recovery ============ */}
      {failed && result && (
        <div ref={recoveryRef}>
          <div className="section-label mt-4">
            <span className="section-label-chip">7</span>
            Failure Recovery
            <span className="section-label-by">AI-assisted remediation</span>
          </div>
          <PhaseStatusCard
            icon="fa-life-ring"
            title="Pipeline Failed — Recovery Options"
            subtitle="Review what failed, then retry the stage or restart the pipeline."
            status="failed"
            className="mb-2"
          >
            <div className="tf-fail-grid">
              <div className="tf-fail-block">
                <div className="tf-error-label">Failed Stage</div>
                <p className="mb-0"><span className="tag mono">{result.failedStage}</span></p>
              </div>
              <div className="tf-fail-block">
                <div className="tf-error-label">Failure Reason</div>
                <p className="mb-0" style={{ fontSize: '.85rem', color: 'var(--tx2)' }}>{result.failureReason}</p>
              </div>
              <div className="tf-fail-block tf-error-reco">
                <div className="tf-error-label">
                  <i className="fa-solid fa-wand-magic-sparkles me-2" style={{ color: '#a78bfa' }} />
                  Recommended Fix
                </div>
                <p className="mb-0" style={{ fontSize: '.85rem', color: 'var(--tx2)' }}>{result.recommendedFix}</p>
              </div>
            </div>

            {errorLines.length > 0 && (
              <>
                <div className="reasoning-label mt-3 mb-1">
                  <i className="fa-solid fa-triangle-exclamation me-2" style={{ color: '#f87171' }} />
                  Error Logs
                </div>
                <pre className="code-block recovery-errors">
                  {errorLines.map((l) => l.text).join('\n')}
                </pre>
              </>
            )}

            <div className="tf-panel-actions mt-3">
              <button type="button" className="bgrd btn px-3 py-2 code-action" onClick={runPipeline}>
                <i className="fa-solid fa-rotate-right me-2" />Retry Stage
              </button>
              <button type="button" className="boc btn px-3 py-2 code-action" onClick={runPipeline}>
                <i className="fa-solid fa-arrows-rotate me-2" />Restart Pipeline
              </button>
              <button type="button" className="boc btn px-3 py-2 code-action" onClick={() => scrollTo(logsRef)}>
                <i className="fa-solid fa-terminal me-2" />View Detailed Logs
              </button>
            </div>
          </PhaseStatusCard>
        </div>
      )}

      {/* ============ SECTION 8 — Execution Result ============ */}
      {result && (
        <div ref={resultRef}>
          <div className="section-label mt-4">
            <span className="section-label-chip">8</span>
            Execution Result
            <span className="section-label-by">{completed ? 'Deployment Live' : 'Run Failed'}</span>
          </div>
          <ExecutionResultCard result={result} />
        </div>
      )}

      {/* ---- Proceed ---- */}
      <div className="phase-footer">
        <p className="phase-footer-note">
          {completed ? (
            <>
              <i className="fa-solid fa-circle-check me-2" style={{ color: '#34d399' }} />
              Pipeline executed &amp; deployed — open the Infrastructure Dashboard to review what was created.
            </>
          ) : (
            <>
              <i className="fa-solid fa-circle-info me-2" />
              Run the pipeline to completion to unlock the Infrastructure Dashboard.
            </>
          )}
        </p>
        <button
          type="button"
          className="bgrd btn px-4 py-2 phase-cta"
          disabled={!completed}
          onClick={() => navigate('/workflows/infrastructure-dashboard')}
        >
          Proceed to Infrastructure Dashboard
          <i className="fa-solid fa-arrow-right ms-2" />
        </button>
      </div>
    </ContentContainer>
  );
}

function Summary({ icon, label, value, mono = false, children }) {
  return (
    <div className="summary-item">
      <span className="summary-item-ico">
        <i className={`fa-solid ${icon}`} />
      </span>
      <div style={{ minWidth: 0 }}>
        <div className="summary-item-label">{label}</div>
        <div className={`summary-item-value ${mono ? 'mono' : ''}`.trim()}>
          {children || value}
        </div>
      </div>
    </div>
  );
}
