import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import ContentContainer from '@/components/layout/ContentContainer';
import WorkflowTimeline from '@/components/workflow/WorkflowTimeline';
import WorkflowPhaseHeader from '@/components/workflow/WorkflowPhaseHeader';
import PhaseStatusCard from '@/components/workflow/PhaseStatusCard';
import DockerfileEditor from '@/components/workflow/DockerfileEditor';
import RealtimeLogViewer from '@/components/workflow/RealtimeLogViewer';
import DockerCorrectionPanel from '@/components/workflow/DockerCorrectionPanel';
import BuildResultCard from '@/components/workflow/BuildResultCard';
import LoadingSpinner from '@/components/common/LoadingSpinner';
import { dockerApi } from '@/services/api/dockerApi';

/**
 * DockerPhasePage — workflow phase 2. The full container story:
 *   1. Dockerfile Generation  → Approve / Edit / Reject
 *   2. Docker Build Execution → simulated streaming logs (Start/Pause/Clear)
 *   3. Docker Corrector Agent → shown only when a build fails
 *   4. Build Result           → success or failure summary
 *
 * To make the demo tell a complete story the *first* build intentionally fails
 * (missing build dependency + port mismatch), the corrector proposes a fix, and
 * the rebuild succeeds. All driven by mock data — nothing is really built.
 * Route: /workflows/docker.
 */
export default function DockerPhasePage() {
  const navigate = useNavigate();

  // ---- Dockerfile generation ----
  const [loading, setLoading] = useState(true);
  const [dockerfile, setDockerfile] = useState('');
  const [correctedContent, setCorrectedContent] = useState('');
  const [decision, setDecision] = useState(null); // approved | rejected | null
  const [regenerating, setRegenerating] = useState(false);
  const [editSignal, setEditSignal] = useState(0);

  // ---- Build execution ----
  const [buildStatus, setBuildStatus] = useState('not_started'); // not_started|running|completed|failed
  const [attempt, setAttempt] = useState(0);
  const [buildEvents, setBuildEvents] = useState([]);
  const [playKey, setPlayKey] = useState(0);
  const [preparing, setPreparing] = useState(false);
  const [buildResult, setBuildResult] = useState(null);
  const pendingResultRef = useRef(null);

  // ---- Corrector ----
  const [correction, setCorrection] = useState(null);
  const [correctorDecision, setCorrectorDecision] = useState(null);

  const buildSectionRef = useRef(null);

  // Load the generated Dockerfile once.
  useEffect(() => {
    let active = true;
    dockerApi.getDockerfile().then((res) => {
      if (!active) return;
      setDockerfile(res.content);
      setCorrectedContent(res.correctedContent);
      setLoading(false);
    });
    return () => {
      active = false;
    };
  }, []);

  /* ---- Section 1 handlers ---- */
  const approveDockerfile = () => setDecision('approved');

  const rejectDockerfile = () => {
    // Simulate the agent regenerating a fresh Dockerfile.
    setDecision('rejected');
    setRegenerating(true);
    setTimeout(async () => {
      const res = await dockerApi.getDockerfile();
      setDockerfile(res.content);
      setDecision(null);
      setRegenerating(false);
    }, 1100);
  };

  const saveDockerfileEdit = (next) => {
    setDockerfile(next);
    setDecision(null); // edits require re-approval before building
  };

  /* ---- Section 2 handlers ---- */
  const startBuild = async () => {
    if (decision !== 'approved' || buildStatus === 'running') return;
    setPreparing(true);
    // fresh build → clear any previous failure/corrector state
    setCorrection(null);
    setCorrectorDecision(null);
    setBuildResult(null);
    const nextAttempt = attempt + 1;
    const res = await dockerApi.startBuild('prj-002', nextAttempt);
    pendingResultRef.current = res.result;
    setAttempt(nextAttempt);
    setBuildEvents(res.logs);
    setBuildStatus('running');
    setPreparing(false);
    setPlayKey((k) => k + 1); // triggers the log viewer to stream
  };

  const onBuildComplete = async () => {
    const result = pendingResultRef.current;
    if (!result) return;
    setBuildResult(result);
    setBuildStatus(result.status); // 'failed' | 'completed'
    if (result.status === 'failed') {
      const corr = await dockerApi.getCorrection('prj-002');
      setCorrection(corr);
    }
  };

  /* ---- Section 3 (corrector) handlers ---- */
  const approveFix = () => {
    setCorrectorDecision('approved');
    setDockerfile(correctedContent); // apply corrected Dockerfile
    setDecision('approved'); // corrected file is pre-approved
    setBuildStatus('not_started'); // ready to rebuild
    setBuildResult(null);
    setCorrection(null);
    // bring the build section into view for the rebuild
    setTimeout(() => buildSectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 60);
  };

  const modifyFix = () => {
    setCorrectorDecision('approved');
    setDockerfile(correctedContent);
    setDecision(null);
    setBuildStatus('not_started');
    setBuildResult(null);
    setCorrection(null);
    setEditSignal((s) => s + 1); // open the editor with the corrected content
  };

  const rejectFix = () => setCorrectorDecision('rejected');

  if (loading) {
    return (
      <ContentContainer>
        <LoadingSpinner center label="Docker Agent is generating the Dockerfile…" />
      </ContentContainer>
    );
  }

  const dockerTimelineState =
    buildStatus === 'completed' ? 'completed' : buildStatus === 'failed' ? 'failed' : 'running';
  const showCorrector = buildStatus === 'failed';
  const showResult = buildStatus === 'completed' || buildStatus === 'failed';
  const completed = buildStatus === 'completed';

  return (
    <ContentContainer>
      <WorkflowTimeline
        current="docker"
        statuses={{ analysis: 'completed', planning: 'completed', docker: dockerTimelineState }}
      />

      <WorkflowPhaseHeader
        icon="fa-docker"
        brand
        eyebrow="Phase 2 of 6"
        title="Docker"
        subtitle="Generate the container image, run the build, and auto-correct failures."
        status={buildStatus}
      />

      {/* ============ SECTION 1 — Dockerfile Generation ============ */}
      <div className="section-label">
        <span className="section-label-chip">1</span>
        Dockerfile Generation
        <span className="section-label-by">Docker Agent</span>
      </div>
      <PhaseStatusCard
        icon="fa-file-code"
        title="Generated Dockerfile"
        subtitle="Review the AI-generated container definition, then approve, edit or reject it."
        status={decision === 'approved' ? 'approved' : decision === 'rejected' ? 'rejected' : 'draft'}
        className="mb-2"
      >
        {regenerating ? (
          <div className="py-4">
            <LoadingSpinner center label="Regenerating Dockerfile…" />
          </div>
        ) : (
          <DockerfileEditor
            value={dockerfile}
            decision={decision}
            editSignal={editSignal}
            onApprove={approveDockerfile}
            onReject={rejectDockerfile}
            onChange={saveDockerfileEdit}
          />
        )}
      </PhaseStatusCard>

      {/* ============ SECTION 2 — Docker Build Execution ============ */}
      <div className="section-label mt-4" ref={buildSectionRef}>
        <span className="section-label-chip">2</span>
        Docker Build Execution
        <span className="section-label-by">Build Engine</span>
      </div>
      <PhaseStatusCard
        icon="fa-hammer"
        title="Build Status"
        subtitle={
          decision === 'approved'
            ? 'Start the build to stream the container build output.'
            : 'Approve the Dockerfile above to enable the build.'
        }
        status={buildStatus}
        className="mb-2"
      >
        <RealtimeLogViewer
          events={buildEvents}
          playKey={playKey}
          canStart={decision === 'approved'}
          preparing={preparing}
          onStart={startBuild}
          onComplete={onBuildComplete}
          title="customer-portal · docker build"
          emptyHint={
            decision === 'approved'
              ? 'Press “Start Build” to stream the container build output.'
              : 'Approve the Dockerfile to enable the build.'
          }
        />
      </PhaseStatusCard>

      {/* ============ SECTION 3 — Docker Corrector (only when failed) ============ */}
      {showCorrector && (
        <>
          <div className="section-label mt-4">
            <span className="section-label-chip">3</span>
            Docker Corrector Agent
            <span className="section-label-by">Auto-diagnosis</span>
          </div>
          <DockerCorrectionPanel
            correction={correction}
            decision={correctorDecision}
            onApprove={approveFix}
            onModify={modifyFix}
            onReject={rejectFix}
          />
        </>
      )}

      {/* ============ SECTION 4 — Build Result ============ */}
      {showResult && (
        <>
          <div className="section-label mt-4">
            <span className="section-label-chip">{showCorrector ? 4 : 3}</span>
            Build Result
            <span className="section-label-by">{completed ? 'Success' : 'Failure'}</span>
          </div>
          <BuildResultCard result={buildResult} />
        </>
      )}

      {/* ---- Proceed ---- */}
      <div className="phase-footer">
        <p className="phase-footer-note">
          {completed ? (
            <>
              <i className="fa-solid fa-circle-check me-2" style={{ color: '#34d399' }} />
              Image built — ready to provision infrastructure with Terraform.
            </>
          ) : (
            <>
              <i className="fa-solid fa-circle-info me-2" />
              Complete the Docker phase to continue.
            </>
          )}
        </p>
        <button
          type="button"
          className="bgrd btn px-4 py-2 phase-cta"
          disabled={!completed}
          onClick={() => navigate('/workflows/terraform')}
        >
          Proceed to Next Phase
          <i className="fa-solid fa-arrow-right ms-2" />
        </button>
      </div>
    </ContentContainer>
  );
}
