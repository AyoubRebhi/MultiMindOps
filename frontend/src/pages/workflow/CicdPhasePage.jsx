import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import ContentContainer from '@/components/layout/ContentContainer';
import WorkflowTimeline from '@/components/workflow/WorkflowTimeline';
import WorkflowPhaseHeader from '@/components/workflow/WorkflowPhaseHeader';
import PhaseStatusCard from '@/components/workflow/PhaseStatusCard';
import GitHubWorkflowViewer from '@/components/workflow/GitHubWorkflowViewer';
import AgentReasoningCard from '@/components/workflow/AgentReasoningCard';
import RAGRetrievalPanel from '@/components/workflow/RAGRetrievalPanel';
import WorkflowValidationPanel from '@/components/workflow/WorkflowValidationPanel';
import SecurityAuditPanel from '@/components/workflow/SecurityAuditPanel';
import WorkflowCompilerPanel from '@/components/workflow/WorkflowCompilerPanel';
import ExecutionSimulationPanel from '@/components/workflow/ExecutionSimulationPanel';
import PipelineResultCard from '@/components/workflow/PipelineResultCard';
import LoadingSpinner from '@/components/common/LoadingSpinner';
import Tag from '@/components/common/Tag';
import { cicdIntentApi } from '@/services/api/cicdIntentApi';
import { cicdContextApi } from '@/services/api/cicdContextApi';
import { cicdGenerationApi } from '@/services/api/cicdGenerationApi';
import { cicdValidationApi } from '@/services/api/cicdValidationApi';
import { cicdSecurityApi } from '@/services/api/cicdSecurityApi';
import { cicdCompilationApi } from '@/services/api/cicdCompilationApi';
import { cicdExecutionApi } from '@/services/api/cicdExecutionApi';

/**
 * CicdPhasePage — workflow phase 5: the GitHub Actions / CI-CD Agent. Simulates
 * the complete CI/CD generation journey end-to-end (all mock, no backend):
 *   1. Request Analysis        → the analyzed request + detected stack
 *   2. Intent Extraction       → AI reasoning card
 *   3. Context Collection      → categorized repository findings
 *   4. RAG Retrieval           → knowledge-base workflow examples
 *   5. Workflow Generation     → generated deploy.yml (approve / edit / reject)
 *   6. Schema Validation       → fails first (findings) then passes after a fix
 *   7. Security Audit          → critical findings → fix / approve-anyway / re-run
 *   8. Compilation             → pin actions, checksum, workflow.lock
 *   9. Execution Simulation    → nektos/act run (fails then succeeds on retry)
 *  10. Final Result            → pipeline summary (success) or failure detail
 *
 * Route: /workflows/cicd.
 */
const TONE_VARIANT = { ok: 'success', info: 'info', warn: 'warning' };

export default function CicdPhasePage() {
  const navigate = useNavigate();

  // ---- Agent outputs (sections 1–4) ----
  const [loading, setLoading] = useState(true);
  const [request, setRequest] = useState(null);
  const [intent, setIntent] = useState(null);
  const [context, setContext] = useState(null);
  const [rag, setRag] = useState(null);

  // ---- Generated workflow (section 5) ----
  const [yaml, setYaml] = useState('');
  const [yamlMeta, setYamlMeta] = useState(null);
  const [filename, setFilename] = useState('.github/workflows/deploy.yml');
  const [decision, setDecision] = useState(null); // approved | rejected | null
  const [editSignal, setEditSignal] = useState(0);

  // ---- Validation (section 6) ----
  const [valStatus, setValStatus] = useState('not_started');
  const [valAttempt, setValAttempt] = useState(0);
  const [valEvents, setValEvents] = useState([]);
  const [valPlayKey, setValPlayKey] = useState(0);
  const [valPreparing, setValPreparing] = useState(false);
  const [valFindings, setValFindings] = useState([]);
  const valPendingRef = useRef(null);

  // ---- Security audit (section 7) ----
  const [secStatus, setSecStatus] = useState('not_started'); // not_started|running|passed|failed
  const [secAttempt, setSecAttempt] = useState(0);
  const [secAudit, setSecAudit] = useState(null);
  const [secApprovedAnyway, setSecApprovedAnyway] = useState(false);

  // ---- Compilation (section 8) ----
  const [compStatus, setCompStatus] = useState('not_started'); // not_started|compiling|compiled
  const [compResult, setCompResult] = useState(null);

  // ---- Execution simulation (section 9) ----
  const [execStatus, setExecStatus] = useState('not_started');
  const [execAttempt, setExecAttempt] = useState(0);
  const [execEvents, setExecEvents] = useState([]);
  const [execPlayKey, setExecPlayKey] = useState(0);
  const [execPreparing, setExecPreparing] = useState(false);
  const [execResult, setExecResult] = useState(null);
  const execPendingRef = useRef(null);

  const viewerRef = useRef(null);
  const validationRef = useRef(null);
  const securityRef = useRef(null);
  const compilerRef = useRef(null);
  const executionRef = useRef(null);
  const resultRef = useRef(null);

  // Load the agent outputs + generated workflow once.
  useEffect(() => {
    let active = true;
    Promise.all([
      cicdIntentApi.getRequestAnalysis(),
      cicdIntentApi.getIntent(),
      cicdContextApi.getContext(),
      cicdContextApi.getRagResults(),
      cicdGenerationApi.getWorkflow(),
    ]).then(([req, intnt, ctx, ragRes, wf]) => {
      if (!active) return;
      setRequest(req);
      setIntent(intnt);
      setContext(ctx);
      setRag(ragRes);
      setYaml(wf.content);
      setYamlMeta(wf.meta);
      setFilename(wf.filename);
      setLoading(false);
    });
    return () => {
      active = false;
    };
  }, []);

  const scrollTo = (ref) =>
    setTimeout(() => ref.current?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 60);

  /* ---- Section 5: workflow decision + fix ---- */
  const approveWorkflow = () => {
    setDecision('approved');
    scrollTo(validationRef);
  };
  const rejectWorkflow = () => setDecision('rejected');
  const fixWorkflow = () => {
    setEditSignal((s) => s + 1);
    scrollTo(viewerRef);
  };

  /* ---- Section 6: validation ---- */
  const runValidation = async () => {
    if (decision !== 'approved' || valStatus === 'running') return;
    setValPreparing(true);
    const next = valAttempt + 1;
    const res = await cicdValidationApi.runValidation(next);
    valPendingRef.current = res;
    setValAttempt(next);
    setValEvents(res.logs);
    setValFindings([]);
    setValStatus('running');
    setValPreparing(false);
    setValPlayKey((k) => k + 1);
  };
  const onValidationComplete = () => {
    const res = valPendingRef.current;
    if (!res) return;
    setValStatus(res.status);
    if (res.status === 'failed') {
      setValFindings(res.findings);
    } else {
      setValFindings([]);
      scrollTo(securityRef);
    }
  };

  /* ---- Section 7: security audit ---- */
  const runAudit = async () => {
    if (valStatus !== 'completed' || secStatus === 'running') return;
    const next = secAttempt + 1;
    setSecStatus('running');
    const res = await cicdSecurityApi.runAudit(next);
    setSecAttempt(next);
    setSecAudit(res);
    setSecStatus(res.status); // passed | failed
    if (res.status === 'passed') scrollTo(compilerRef);
  };
  const approveAuditAnyway = () => setSecApprovedAnyway(true);

  /* ---- Section 8: compilation (auto-runs once security clears) ---- */
  const securityCleared =
    secStatus === 'passed' || (secStatus === 'failed' && secApprovedAnyway);

  useEffect(() => {
    if (!securityCleared || compStatus !== 'not_started') return;
    let active = true;
    setCompStatus('compiling');
    cicdCompilationApi.compile().then((res) => {
      if (!active) return;
      setCompResult(res);
      setCompStatus('compiled');
      scrollTo(executionRef);
    });
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [securityCleared]);

  /* ---- Section 9: execution simulation ---- */
  const runExecution = async () => {
    if (compStatus !== 'compiled' || execStatus === 'running') return;
    setExecPreparing(true);
    const next = execAttempt + 1;
    const res = await cicdExecutionApi.runExecution(next);
    execPendingRef.current = res;
    setExecAttempt(next);
    setExecEvents(res.logs);
    setExecResult(null);
    setExecStatus('running');
    setExecPreparing(false);
    setExecPlayKey((k) => k + 1);
  };
  const onExecutionComplete = () => {
    const res = execPendingRef.current;
    if (!res) return;
    setExecStatus(res.status);
    setExecResult(res.result);
    scrollTo(resultRef);
  };

  if (loading || !request || !intent || !context || !rag) {
    return (
      <ContentContainer>
        <LoadingSpinner center label="CI/CD Agent is analyzing the request and gathering context…" />
      </ContentContainer>
    );
  }

  // ---- Gating / derived state ----
  const showValidation = decision === 'approved';
  const validationPassed = valStatus === 'completed';
  const showSecurity = validationPassed;
  const showCompilation = securityCleared;
  const compilationDone = compStatus === 'compiled';
  const showExecution = compilationDone;
  const showResult = execStatus === 'completed' || execStatus === 'failed';
  const completed = execStatus === 'completed';

  const cicdState = completed
    ? 'completed'
    : execStatus === 'failed'
      ? 'failed'
      : 'running';

  const repo = request.repository;

  return (
    <ContentContainer>
      <WorkflowTimeline
        current="cicd"
        statuses={{
          analysis: 'completed',
          planning: 'completed',
          docker: 'completed',
          terraform: 'completed',
          cicd: cicdState,
        }}
      />

      <WorkflowPhaseHeader
        icon="fa-github"
        brand
        eyebrow="Phase 5 of 7"
        title="GitHub Actions"
        subtitle="Generate, validate, audit, compile and simulate a production CI/CD pipeline."
        status={cicdState}
      />

      {/* ============ SECTION 1 — Request Analysis ============ */}
      <div className="section-label">
        <span className="section-label-chip">1</span>
        Request Analysis
        <span className="section-label-by">CI/CD Request Analyzer</span>
      </div>

      <PhaseStatusCard
        icon="fa-comment-dots"
        title="Original User Request"
        subtitle="The natural-language request the CI/CD Agent is fulfilling."
        status="completed"
        className="mb-3"
      >
        <p className="cicd-request">{request.originalRequest}</p>

        <div className="summary-grid">
          <SummaryItem icon="fa-github" brand label="Repository" value={repo.name} />
          <SummaryItem icon="fa-code-branch" label="Branch" value={repo.branch} />
          <SummaryItem icon="fa-lock" label="Visibility" value={repo.visibility} />
          <SummaryItem icon="fa-layer-group" label="Framework" value={request.framework} />
        </div>
      </PhaseStatusCard>

      <div className="row g-3 mb-2">
        <div className="col-lg-7">
          <PhaseStatusCard icon="fa-cubes-stacked" title="Detected Technology Stack">
            <div className="d-flex flex-wrap gap-2 mb-3">
              {request.techStack.map((s) => (
                <Tag key={s.name} icon={s.icon} brand={s.brand}>
                  {s.name}
                  <span className="text-muted-3 ms-1" style={{ fontSize: '.66rem' }}>
                    {s.version}
                  </span>
                </Tag>
              ))}
            </div>
            <div className="reasoning-label mb-1">Detected Runtime Versions</div>
            <div className="d-flex flex-wrap gap-2">
              {request.runtimeVersions.map((r) => (
                <span className="tag mono" key={r}>
                  <i className="fa-solid fa-microchip" />{r}
                </span>
              ))}
            </div>
          </PhaseStatusCard>
        </div>

        <div className="col-lg-5">
          <PhaseStatusCard icon="fa-satellite-dish" title="Detected Signals">
            <div className="d-flex flex-column gap-2">
              {request.signals.map((sig) => (
                <span className={`cicd-signal badge-pill badge-${TONE_VARIANT[sig.tone] || 'info'}`} key={sig.label}>
                  <i className={`${sig.brand ? 'fa-brands' : 'fa-solid'} ${sig.icon}`} />
                  {sig.label}
                </span>
              ))}
            </div>
          </PhaseStatusCard>
        </div>
      </div>

      <div className="row g-3">
        <div className="col-md-4">
          <div className="surface assess-tile">
            <div className="d-flex align-items-center gap-3">
              <span className="assess-ico"><i className="fa-solid fa-wand-magic-sparkles" /></span>
              <div style={{ minWidth: 0 }}>
                <div className="assess-title">Agent Confidence</div>
                <div className="assess-value">{request.agentConfidence}%</div>
              </div>
            </div>
            <div className="reasoning-conf-bar mt-2">
              <span style={{ width: `${request.agentConfidence}%` }} />
            </div>
          </div>
        </div>
        <div className="col-md-4">
          <AssessTile icon="fa-tag" title="Intent Type" value={request.intentType} />
        </div>
        <div className="col-md-4">
          <AssessTile icon="fa-gauge-high" title="Pipeline Complexity" value={request.pipelineComplexity} />
        </div>
      </div>

      {/* ============ SECTION 2 — Intent Extraction ============ */}
      <div className="section-label mt-4">
        <span className="section-label-chip">2</span>
        Intent Extraction
        <span className="section-label-by">Intent Extraction Agent</span>
      </div>
      <AgentReasoningCard data={intent} />

      {/* ============ SECTION 3 — Context Collection ============ */}
      <div className="section-label mt-4">
        <span className="section-label-chip">3</span>
        Context Collection
        <span className="section-label-by">Repository Context Analyzer</span>
      </div>
      <div className="row g-3 mb-2">
        {context.categories.map((cat) => (
          <div className="col-md-6 col-xl-3" key={cat.key}>
            <PhaseStatusCard icon={cat.icon} title={cat.title}>
              <div className="d-flex flex-column gap-2">
                {cat.items.map((it) => (
                  <div className="ctx-item" key={it.name}>
                    <span className="ctx-item-ico">
                      <i className={`${it.brand ? 'fa-brands' : 'fa-solid'} ${it.icon}`} />
                    </span>
                    <div style={{ minWidth: 0 }}>
                      <div className="ctx-item-name mono">{it.name}</div>
                      <div className="ctx-item-detail">{it.detail}</div>
                    </div>
                  </div>
                ))}
              </div>
            </PhaseStatusCard>
          </div>
        ))}
      </div>
      <PhaseStatusCard
        icon="fa-docker"
        brand
        title="Containerization Status"
        subtitle={`${context.containerization.baseImage} · port ${context.containerization.exposedPort} · health ${context.containerization.healthcheck}`}
        status={context.containerization.status === 'ready' ? 'completed' : 'warning'}
      >
        <div className="ctx-checks">
          {context.containerization.checks.map((c) => (
            <span className={`ctx-check ${c.ok ? 'ok' : 'bad'}`} key={c.label}>
              <i className={`fa-solid ${c.ok ? 'fa-circle-check' : 'fa-circle-xmark'}`} />
              {c.label}
            </span>
          ))}
        </div>
      </PhaseStatusCard>

      {/* ============ SECTION 4 — RAG Retrieval ============ */}
      <div className="section-label mt-4">
        <span className="section-label-chip">4</span>
        Knowledge Base Retrieval
        <span className="section-label-by">HybridRAG · devsecops_kb</span>
      </div>
      <PhaseStatusCard
        icon="fa-database"
        title="Retrieved Workflow Knowledge"
        subtitle="Similar pipelines retrieved from the knowledge base to ground generation."
        status="completed"
        className="mb-2"
      >
        <RAGRetrievalPanel data={rag} />
      </PhaseStatusCard>

      {/* ============ SECTION 5 — Workflow Generation ============ */}
      <div className="section-label mt-4">
        <span className="section-label-chip">5</span>
        Workflow Generation
        <span className="section-label-by">Workflow Generation Agent</span>
      </div>
      <PhaseStatusCard
        icon="fa-file-code"
        title="Generated GitHub Actions Workflow"
        subtitle="Review the generated pipeline, then approve to unlock validation."
        status={decision === 'approved' ? 'approved' : decision === 'rejected' ? 'rejected' : 'draft'}
        className="mb-2"
      >
        <div ref={viewerRef}>
          <GitHubWorkflowViewer
            value={yaml}
            filename={filename}
            meta={yamlMeta}
            decision={decision}
            editSignal={editSignal}
            onApprove={approveWorkflow}
            onReject={rejectWorkflow}
            onChange={setYaml}
          />
        </div>
      </PhaseStatusCard>

      {/* ============ SECTION 6 — Schema Validation ============ */}
      {showValidation && (
        <div ref={validationRef}>
          <div className="section-label mt-4">
            <span className="section-label-chip">6</span>
            Schema Validation
            <span className="section-label-by">actionlint · jobs · steps · syntax</span>
          </div>
          <PhaseStatusCard
            icon="fa-clipboard-check"
            title="Validation Execution"
            subtitle="Parse the workflow and validate jobs, steps and syntax."
            status={valStatus}
            className="mb-2"
          >
            <WorkflowValidationPanel
              status={valStatus}
              events={valEvents}
              playKey={valPlayKey}
              canRun={decision === 'approved'}
              preparing={valPreparing}
              onRun={runValidation}
              onComplete={onValidationComplete}
              findings={valFindings}
              onFixManually={fixWorkflow}
            />
          </PhaseStatusCard>
        </div>
      )}

      {/* ============ SECTION 7 — Security Audit ============ */}
      {showSecurity && (
        <div ref={securityRef}>
          <div className="section-label mt-4">
            <span className="section-label-chip">7</span>
            Security Audit
            <span className="section-label-by">Security Guardrails Agent</span>
          </div>
          <PhaseStatusCard
            icon="fa-shield-halved"
            title="Security Guardrails Audit"
            subtitle="Scan for dangerous commands, secrets, unverified actions, permissions and URLs."
            status={secStatus === 'passed' ? 'completed' : secStatus === 'failed' ? (secApprovedAnyway ? 'warning' : 'failed') : secStatus}
            className="mb-2"
          >
            <SecurityAuditPanel
              status={secStatus}
              audit={secAudit}
              canRun={validationPassed}
              onRun={runAudit}
              approvedAnyway={secApprovedAnyway}
              onFix={fixWorkflow}
              onApproveAnyway={approveAuditAnyway}
            />
          </PhaseStatusCard>
        </div>
      )}

      {/* ============ SECTION 8 — Compilation ============ */}
      {showCompilation && (
        <div ref={compilerRef}>
          <div className="section-label mt-4">
            <span className="section-label-chip">8</span>
            Compilation
            <span className="section-label-by">Workflow Compiler</span>
          </div>
          <PhaseStatusCard
            icon="fa-microchip"
            title="Workflow Compiler"
            subtitle="Pin actions to immutable SHAs, compute a checksum and emit workflow.lock."
            status={compStatus === 'compiled' ? 'completed' : 'running'}
            className="mb-2"
          >
            <WorkflowCompilerPanel status={compStatus} result={compResult} />
          </PhaseStatusCard>
        </div>
      )}

      {/* ============ SECTION 9 — Execution Simulation ============ */}
      {showExecution && (
        <div ref={executionRef}>
          <div className="section-label mt-4">
            <span className="section-label-chip">9</span>
            Execution Simulation
            <span className="section-label-by">Execution Agent · nektos/act</span>
          </div>
          <PhaseStatusCard
            icon="fa-play"
            title="Execution Agent Simulation"
            subtitle="Run the compiled workflow locally to verify it before it ships."
            status={execStatus}
            className="mb-2"
          >
            <ExecutionSimulationPanel
              status={execStatus}
              events={execEvents}
              playKey={execPlayKey}
              canRun={compilationDone}
              preparing={execPreparing}
              onRun={runExecution}
              onComplete={onExecutionComplete}
            />
          </PhaseStatusCard>
        </div>
      )}

      {/* ============ SECTION 10 — Final Result ============ */}
      {showResult && (
        <div ref={resultRef}>
          <div className="section-label mt-4">
            <span className="section-label-chip">10</span>
            Final Result
            <span className="section-label-by">{completed ? 'Pipeline Generated' : 'Pipeline Failed'}</span>
          </div>
          <PipelineResultCard result={execResult} />
        </div>
      )}

      {/* ---- Proceed ---- */}
      <div className="phase-footer">
        <p className="phase-footer-note">
          {completed ? (
            <>
              <i className="fa-solid fa-circle-check me-2" style={{ color: '#34d399' }} />
              Pipeline generated &amp; verified — continue to the Execution Center.
            </>
          ) : (
            <>
              <i className="fa-solid fa-circle-info me-2" />
              Complete the CI/CD phase (approve → validate → audit → compile → simulate) to continue.
            </>
          )}
        </p>
        <button
          type="button"
          className="bgrd btn px-4 py-2 phase-cta"
          disabled={!completed}
          onClick={() => navigate('/workflows/execution')}
        >
          Proceed to Execution Center
          <i className="fa-solid fa-arrow-right ms-2" />
        </button>
      </div>
    </ContentContainer>
  );
}

function SummaryItem({ icon, brand = false, label, value }) {
  return (
    <div className="summary-item">
      <span className="summary-item-ico">
        <i className={`${brand ? 'fa-brands' : 'fa-solid'} ${icon}`} />
      </span>
      <div style={{ minWidth: 0 }}>
        <div className="summary-item-label">{label}</div>
        <div className="summary-item-value">{value}</div>
      </div>
    </div>
  );
}

function AssessTile({ icon, title, value }) {
  return (
    <div className="surface assess-tile">
      <div className="d-flex align-items-center gap-3">
        <span className="assess-ico"><i className={`fa-solid ${icon}`} /></span>
        <div style={{ minWidth: 0 }}>
          <div className="assess-title">{title}</div>
          <div className="assess-value">{value}</div>
        </div>
      </div>
    </div>
  );
}
