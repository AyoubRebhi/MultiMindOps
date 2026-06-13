import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import ContentContainer from '@/components/layout/ContentContainer';
import WorkflowTimeline from '@/components/workflow/WorkflowTimeline';
import WorkflowPhaseHeader from '@/components/workflow/WorkflowPhaseHeader';
import PhaseStatusCard from '@/components/workflow/PhaseStatusCard';
import TerraformFileViewer from '@/components/workflow/TerraformFileViewer';
import TerraformResourceSummary from '@/components/workflow/TerraformResourceSummary';
import TerraformValidationPanel from '@/components/workflow/TerraformValidationPanel';
import TerraformExecutionPanel from '@/components/workflow/TerraformExecutionPanel';
import TerraformErrorPanel from '@/components/workflow/TerraformErrorPanel';
import TerraformEditorWorkspace from '@/components/workflow/TerraformEditorWorkspace';
import TerraformDeploymentResult from '@/components/workflow/TerraformDeploymentResult';
import LoadingSpinner from '@/components/common/LoadingSpinner';
import { terraformGenerationApi } from '@/services/api/terraformGenerationApi';
import { terraformValidationApi } from '@/services/api/terraformValidationApi';
import { terraformExecutionApi } from '@/services/api/terraformExecutionApi';
import { formatDate } from '@/utils/formatters';

/**
 * TerraformPhasePage — workflow phase 3. The full infrastructure story:
 *   1. Terraform Generation   → generated .tf files + viewer
 *   2. Review & Approval      → resource summary + Approve/Edit/Reject
 *   3. Terraform Validation   → fmt/init/validate (fails → findings)
 *   4. Terraform Execution    → plan/apply (fails → error panel)
 *   5. Manual Correction      → edit/save/diff after any failure
 *   6. Final Result           → infra summary (success) or failure detail
 *
 * Like the Docker phase, the demo intentionally fails the first validation
 * (undeclared variable) and the first apply (subnet conflict) so the findings,
 * error panel and correction workspace all get exercised; re-running each after
 * the fix succeeds. All mock — no Terraform, no AWS, no sockets.
 * Route: /workflows/terraform.
 */
const lineCount = (s) => s.replace(/\n$/, '').split('\n').length;

export default function TerraformPhasePage() {
  const navigate = useNavigate();

  // ---- Generation ----
  const [loading, setLoading] = useState(true);
  const [files, setFiles] = useState([]);
  const [resources, setResources] = useState([]);
  const [activeFile, setActiveFile] = useState(null);
  const originalsRef = useRef({}); // name → original generated content

  // ---- Review ----
  const [reviewDecision, setReviewDecision] = useState(null); // approved|rejected|null

  // ---- Validation ----
  const [valStatus, setValStatus] = useState('not_started');
  const [valAttempt, setValAttempt] = useState(0);
  const [valEvents, setValEvents] = useState([]);
  const [valPlayKey, setValPlayKey] = useState(0);
  const [valPreparing, setValPreparing] = useState(false);
  const [findings, setFindings] = useState([]);
  const valPendingRef = useRef(null);

  // ---- Execution ----
  const [execStatus, setExecStatus] = useState('not_started');
  const [execAttempt, setExecAttempt] = useState(0);
  const [execEvents, setExecEvents] = useState([]);
  const [execPlayKey, setExecPlayKey] = useState(0);
  const [execPreparing, setExecPreparing] = useState(false);
  const [execError, setExecError] = useState(null);
  const execPendingRef = useRef(null);

  // ---- Result + workspace ----
  const [result, setResult] = useState(null);
  const [workspace, setWorkspace] = useState(null); // { context, fileName, original, suggestion, note }

  const validationRef = useRef(null);
  const executionRef = useRef(null);
  const workspaceRef = useRef(null);
  const viewerRef = useRef(null);

  // Load the generated files + resources once.
  useEffect(() => {
    let active = true;
    Promise.all([
      terraformGenerationApi.getFiles(),
      terraformGenerationApi.getResources(),
    ]).then(([f, r]) => {
      if (!active) return;
      setFiles(f);
      setResources(r);
      setActiveFile(f[0]?.name || null);
      originalsRef.current = Object.fromEntries(f.map((file) => [file.name, file.content]));
      setLoading(false);
    });
    return () => {
      active = false;
    };
  }, []);

  const scrollTo = (ref) =>
    setTimeout(() => ref.current?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 60);

  /* ---- Section 1: file actions ---- */
  const viewFile = (name) => {
    setActiveFile(name);
    scrollTo(viewerRef);
  };
  const downloadFile = (file) => {
    const blob = new Blob([file.content], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = file.name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };
  const openWorkspace = (context, { file, original, suggestion, note }) => {
    setWorkspace({
      context,
      fileName: file,
      original: original ?? originalsRef.current[file] ?? '',
      suggestion: suggestion ?? null,
      note: note ?? null,
    });
    scrollTo(workspaceRef);
  };
  const editFile = (name) =>
    openWorkspace('review', { file: name, original: originalsRef.current[name], note: 'Edit the file and save your changes.' });

  const saveWorkspaceFile = (next) => {
    if (!workspace) return;
    setFiles((prev) =>
      prev.map((f) =>
        f.name === workspace.fileName
          ? { ...f, content: next, lines: lineCount(next), lastGenerated: new Date().toISOString(), status: 'modified' }
          : f
      )
    );
    setActiveFile(workspace.fileName);
  };

  /* ---- Section 2: review ---- */
  const approveReview = () => {
    setReviewDecision('approved');
    scrollTo(validationRef);
  };
  const rejectReview = () => setReviewDecision('rejected');

  /* ---- Section 3: validation ---- */
  const runValidation = async () => {
    if (reviewDecision !== 'approved' || valStatus === 'running') return;
    setValPreparing(true);
    const nextAttempt = valAttempt + 1;
    const res = await terraformValidationApi.runValidation(nextAttempt);
    valPendingRef.current = res;
    setValAttempt(nextAttempt);
    setValEvents(res.logs);
    setFindings([]);
    setValStatus('running');
    setValPreparing(false);
    setValPlayKey((k) => k + 1);
  };
  const onValidationComplete = () => {
    const res = valPendingRef.current;
    if (!res) return;
    setValStatus(res.status);
    if (res.status === 'failed') {
      setFindings(res.findings);
      if (res.fix) openWorkspace('validation', res.fix);
    } else {
      setFindings([]);
      setWorkspace((w) => (w?.context === 'validation' ? null : w));
      scrollTo(executionRef);
    }
  };

  /* ---- Section 4: execution ---- */
  const runExecution = async () => {
    if (valStatus !== 'completed' || execStatus === 'running') return;
    setExecPreparing(true);
    const nextAttempt = execAttempt + 1;
    const res = await terraformExecutionApi.runExecution(nextAttempt);
    execPendingRef.current = res;
    setExecAttempt(nextAttempt);
    setExecEvents(res.logs);
    setExecError(null);
    setResult(null);
    setExecStatus('running');
    setExecPreparing(false);
    setExecPlayKey((k) => k + 1);
  };
  const onExecutionComplete = () => {
    const res = execPendingRef.current;
    if (!res) return;
    setExecStatus(res.status);
    setResult(res.result);
    if (res.status === 'failed') {
      setExecError(res.error);
      if (res.fix) openWorkspace('execution', res.fix);
    } else {
      setExecError(null);
      setWorkspace((w) => (w?.context === 'execution' ? null : w));
    }
  };

  if (loading) {
    return (
      <ContentContainer>
        <LoadingSpinner center label="Terraform Generation Agent is writing the configuration…" />
      </ContentContainer>
    );
  }

  const tfState =
    execStatus === 'completed'
      ? 'completed'
      : execStatus === 'failed' || valStatus === 'failed'
        ? 'failed'
        : 'running';
  const showValidation = reviewDecision === 'approved';
  const showExecution = valStatus === 'completed';
  const showResult = execStatus === 'completed' || execStatus === 'failed';
  const completed = execStatus === 'completed';

  const workspaceValue =
    workspace ? files.find((f) => f.name === workspace.fileName)?.content ?? '' : '';

  return (
    <ContentContainer>
      <WorkflowTimeline
        current="terraform"
        statuses={{
          analysis: 'completed',
          planning: 'completed',
          docker: 'completed',
          terraform: tfState,
        }}
      />

      <WorkflowPhaseHeader
        icon="fa-cubes"
        eyebrow="Phase 4 of 7"
        title="Terraform"
        subtitle="Generate, review, validate and provision the cloud infrastructure."
        status={tfState}
      />

      {/* ============ SECTION 1 — Terraform Generation ============ */}
      <div className="section-label">
        <span className="section-label-chip">1</span>
        Terraform Generation
        <span className="section-label-by">Terraform Generation Agent</span>
      </div>
      <PhaseStatusCard
        icon="fa-file-code"
        title="Generated Files"
        subtitle="The agent produced a complete, multi-file Terraform configuration."
        status="completed"
        className="mb-2"
      >
        <div className="row g-3 mb-3">
          {files.map((file) => (
            <div className="col-sm-6 col-xl-3" key={file.name}>
              <div className="tf-file-card">
                <div className="tf-file-card-head">
                  <span className="tf-file-ico"><i className="fa-solid fa-file-code" /></span>
                  <span className="tf-file-name mono">{file.name}</span>
                </div>
                <div className="tf-file-meta">
                  <span><i className="fa-solid fa-align-left me-1" />{file.lines} lines</span>
                  <span
                    className={`badge-pill ${file.status === 'modified' ? 'badge-running' : 'badge-success'}`}
                  >
                    <i className="fa-solid fa-circle-check" />
                    {file.status}
                  </span>
                </div>
                <div className="tf-file-gen">
                  <i className="fa-solid fa-clock-rotate-left me-1" />
                  {formatDate(file.lastGenerated)}
                </div>
                <div className="tf-file-actions">
                  <button type="button" className="tf-file-btn" onClick={() => viewFile(file.name)}>
                    <i className="fa-solid fa-eye me-1" />View
                  </button>
                  <button type="button" className="tf-file-btn" onClick={() => downloadFile(file)}>
                    <i className="fa-solid fa-download me-1" />Download
                  </button>
                  <button type="button" className="tf-file-btn" onClick={() => editFile(file.name)}>
                    <i className="fa-solid fa-pen me-1" />Edit
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>

        <div ref={viewerRef}>
          <TerraformFileViewer files={files} active={activeFile} onSelect={setActiveFile} />
        </div>
      </PhaseStatusCard>

      {/* ============ SECTION 2 — Review & Approval ============ */}
      <div className="section-label mt-4">
        <span className="section-label-chip">2</span>
        Review &amp; Approval
        <span className="section-label-by">Terraform Review Panel</span>
      </div>
      <PhaseStatusCard
        icon="fa-clipboard-check"
        title="Generated Resources Summary"
        subtitle="Review what will be provisioned, then approve to unlock validation."
        status={reviewDecision === 'approved' ? 'approved' : reviewDecision === 'rejected' ? 'rejected' : 'draft'}
        className="mb-2"
      >
        <TerraformResourceSummary resources={resources} />

        <div className="tf-panel-actions mt-3">
          <button
            type="button"
            className="boc btn px-3 py-2 code-action code-action-danger"
            onClick={rejectReview}
          >
            <i className="fa-solid fa-xmark me-2" />Reject Terraform
          </button>
          <button
            type="button"
            className="boc btn px-3 py-2 code-action"
            onClick={() => editFile('main.tf')}
          >
            <i className="fa-solid fa-pen me-2" />Edit Terraform
          </button>
          <button
            type="button"
            className="bgrd btn px-3 py-2 code-action"
            disabled={reviewDecision === 'approved'}
            onClick={approveReview}
          >
            <i className="fa-solid fa-check me-2" />
            {reviewDecision === 'approved' ? 'Approved' : 'Approve Terraform'}
          </button>
        </div>
      </PhaseStatusCard>

      {/* ============ SECTION 3 — Terraform Validation ============ */}
      {showValidation && (
        <div ref={validationRef}>
          <div className="section-label mt-4">
            <span className="section-label-chip">3</span>
            Terraform Validation
            <span className="section-label-by">fmt · init · validate</span>
          </div>
          <PhaseStatusCard
            icon="fa-clipboard-check"
            title="Validation Execution"
            subtitle="Format, initialize and validate the configuration."
            status={valStatus}
            className="mb-2"
          >
            <TerraformValidationPanel
              status={valStatus}
              events={valEvents}
              playKey={valPlayKey}
              canRun={reviewDecision === 'approved'}
              preparing={valPreparing}
              onRun={runValidation}
              onComplete={onValidationComplete}
              findings={findings}
              onFixManually={() =>
                workspace
                  ? scrollTo(workspaceRef)
                  : openWorkspace('validation', {
                      file: 'variables.tf',
                      original: originalsRef.current['variables.tf'],
                    })
              }
            />
          </PhaseStatusCard>
        </div>
      )}

      {/* ============ SECTION 4 — Terraform Execution ============ */}
      {showExecution && (
        <div ref={executionRef}>
          <div className="section-label mt-4">
            <span className="section-label-chip">4</span>
            Terraform Execution
            <span className="section-label-by">plan · apply</span>
          </div>
          <PhaseStatusCard
            icon="fa-rocket"
            title="Execution Console"
            subtitle="Provision the infrastructure on AWS."
            status={execStatus}
            className="mb-2"
          >
            <TerraformExecutionPanel
              status={execStatus}
              events={execEvents}
              playKey={execPlayKey}
              canRun={valStatus === 'completed'}
              preparing={execPreparing}
              onRun={runExecution}
              onComplete={onExecutionComplete}
            />
          </PhaseStatusCard>

          {execStatus === 'failed' && execError && (
            <TerraformErrorPanel
              error={execError}
              onModify={() =>
                workspace ? scrollTo(workspaceRef) : openWorkspace('execution', { file: 'main.tf' })
              }
              onRetry={runExecution}
            />
          )}
        </div>
      )}

      {/* ============ SECTION 5 — Manual Correction Workspace ============ */}
      {workspace && (
        <div ref={workspaceRef}>
          <div className="section-label mt-4">
            <span className="section-label-chip">5</span>
            Manual Correction
            <span className="section-label-by">TerraformEditorWorkspace</span>
          </div>
          <TerraformEditorWorkspace
            fileName={workspace.fileName}
            original={workspace.original}
            value={workspaceValue}
            suggestion={workspace.suggestion}
            context={workspace.context}
            note={workspace.note}
            onSave={saveWorkspaceFile}
            onRevalidate={runValidation}
            onRetry={runExecution}
            onClose={() => setWorkspace(null)}
          />
        </div>
      )}

      {/* ============ SECTION 6 — Final Result ============ */}
      {showResult && (
        <>
          <div className="section-label mt-4">
            <span className="section-label-chip">6</span>
            Final Result
            <span className="section-label-by">{completed ? 'Deployment Successful' : 'Deployment Failed'}</span>
          </div>
          <TerraformDeploymentResult result={result} resources={resources} />
        </>
      )}

      {/* ---- Proceed ---- */}
      <div className="phase-footer">
        <p className="phase-footer-note">
          {completed ? (
            <>
              <i className="fa-solid fa-circle-check me-2" style={{ color: '#34d399' }} />
              Infrastructure provisioned — continue to generate the CI/CD pipeline.
            </>
          ) : (
            <>
              <i className="fa-solid fa-circle-info me-2" />
              Complete the Terraform phase (generate → approve → validate → apply) to continue.
            </>
          )}
        </p>
        <button
          type="button"
          className="bgrd btn px-4 py-2 phase-cta"
          disabled={!completed}
          onClick={() => navigate('/workflows/cicd')}
        >
          Proceed to GitHub Actions Phase
          <i className="fa-solid fa-arrow-right ms-2" />
        </button>
      </div>
    </ContentContainer>
  );
}
