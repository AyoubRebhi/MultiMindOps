import { useNavigate } from 'react-router-dom';
import ContentContainer from '@/components/layout/ContentContainer';
import WorkflowTimeline from '@/components/workflow/WorkflowTimeline';
import WorkflowPhaseHeader from '@/components/workflow/WorkflowPhaseHeader';
import PhaseStatusCard from '@/components/workflow/PhaseStatusCard';
import LoadingSpinner from '@/components/common/LoadingSpinner';
import Tag from '@/components/common/Tag';
import { useAsync } from '@/hooks/useAsync';
import { analysisApi } from '@/services/api/analysisApi';
import { formatDate } from '@/utils/formatters';

/**
 * ProjectAnalysisPage — the pre-workflow results screen. Surfaces the Code
 * Analysis Agent and Security Guard Agent output, then lets the user proceed
 * into the workflow (Planning phase). Route: /workflows/analysis.
 */
const SEV_VARIANT = { critical: 'danger', high: 'danger', medium: 'warning', low: 'info' };

export default function ProjectAnalysisPage() {
  const navigate = useNavigate();
  const { data: analysis, loading: aLoading } = useAsync(() => analysisApi.getAnalysis());
  const { data: security, loading: sLoading } = useAsync(() => analysisApi.getSecurity());

  if (aLoading || sLoading || !analysis || !security) {
    return (
      <ContentContainer>
        <LoadingSpinner center label="Running analysis agents…" />
      </ContentContainer>
    );
  }

  const p = analysis.project;

  return (
    <ContentContainer>
      <WorkflowTimeline current="analysis" statuses={{ analysis: 'completed' }} />

      <WorkflowPhaseHeader
        icon="fa-magnifying-glass-chart"
        eyebrow="Pre-workflow"
        title="Project Analysis Results"
        subtitle="Combined output of the Code Analysis Agent and the Security Guard Agent."
        status="completed"
      />

      {/* ---- Project summary card ---- */}
      <div className="surface project-summary mb-3">
        <div className="d-flex align-items-start justify-content-between flex-wrap gap-3">
          <div className="d-flex align-items-center gap-3" style={{ minWidth: 0 }}>
            <div className="project-summary-logo">
              <i className="fa-brands fa-react" />
            </div>
            <div style={{ minWidth: 0 }}>
              <h2 className="project-summary-name">{p.name}</h2>
              <a
                href={`https://${p.repoUrl}`}
                target="_blank"
                rel="noreferrer"
                className="project-summary-repo"
              >
                <i className="fa-brands fa-github me-1" />
                {p.repoUrl}
              </a>
            </div>
          </div>
          <span className="badge-pill badge-running">
            <i className="fa-solid fa-code-branch" />
            {p.branch}
          </span>
        </div>

        <div className="summary-grid">
          <SummaryItem icon="fa-code" label="Language" value={p.language} />
          <SummaryItem icon="fa-layer-group" label="Framework" value={p.framework} />
          <SummaryItem icon="fa-microchip" label="Runtime" value={p.runtime} />
          <SummaryItem icon="fa-database" label="Repository Size" value={p.repoSize} />
          <SummaryItem icon="fa-file-lines" label="Files" value={p.files} />
          <SummaryItem icon="fa-clock-rotate-left" label="Last Commit" value={formatDate(p.lastCommit)} />
        </div>
      </div>

      {/* ============ SECTION 1 — Code Analysis ============ */}
      <div className="section-label">
        <span className="section-label-chip">1</span>
        Code Analysis Results
        <span className="section-label-by">Code Analysis Agent</span>
      </div>

      <div className="row g-3 mb-2">
        {/* Detected stack */}
        <div className="col-lg-6">
          <PhaseStatusCard icon="fa-cubes-stacked" title="Detected Stack">
            <div className="d-flex flex-wrap gap-2">
              {analysis.detectedStack.map((s) => (
                <Tag key={s.name} icon={s.icon} brand={s.brand}>
                  {s.name}
                  <span className="text-muted-3 ms-1" style={{ fontSize: '.66rem' }}>
                    {s.version}
                  </span>
                </Tag>
              ))}
            </div>
          </PhaseStatusCard>
        </div>

        {/* Architecture type */}
        <div className="col-lg-6">
          <PhaseStatusCard icon="fa-sitemap" title="Architecture Type">
            <div className="d-flex align-items-center justify-content-between mb-2">
              <span style={{ fontWeight: 600 }}>{analysis.architecture.type}</span>
              <span className="badge-pill badge-info">
                <i className="fa-solid fa-wand-magic-sparkles" />
                {analysis.architecture.confidence}% match
              </span>
            </div>
            <div className="tag mb-2">{analysis.architecture.pattern}</div>
            <p className="mb-0" style={{ fontSize: '.83rem', color: 'var(--tx2)' }}>
              {analysis.architecture.summary}
            </p>
          </PhaseStatusCard>
        </div>

        {/* Services detected */}
        <div className="col-12">
          <PhaseStatusCard icon="fa-diagram-project" title="Services Detected" actions={
            <span className="text-muted-3" style={{ fontSize: '.78rem' }}>
              {analysis.services.length} services
            </span>
          }>
            <div className="row g-3">
              {analysis.services.map((svc) => (
                <div className="col-md-4" key={svc.name}>
                  <div className="service-tile">
                    <div className="service-tile-head">
                      <span className="service-tile-ico">
                        <i className={`${svc.brand ? 'fa-brands' : 'fa-solid'} ${svc.icon}`} />
                      </span>
                      <div style={{ minWidth: 0 }}>
                        <div className="service-tile-name mono">{svc.name}</div>
                        <div className="service-tile-role">{svc.role}</div>
                      </div>
                    </div>
                    <div className="service-tile-meta">
                      <span><i className="fa-solid fa-plug me-1" />:{svc.port}</span>
                      <span><i className="fa-solid fa-heart-pulse me-1" />{svc.health}</span>
                    </div>
                    <div className="service-tile-build mono">{svc.build}</div>
                  </div>
                </div>
              ))}
            </div>
          </PhaseStatusCard>
        </div>

        {/* Deployment recommendations */}
        <div className="col-lg-7">
          <PhaseStatusCard icon="fa-cloud-arrow-up" title="Deployment Recommendations">
            <div className="d-flex flex-column gap-2">
              {analysis.deploymentRecommendations.map((r, i) => (
                <div className="reco-row" key={i}>
                  <span className="reco-ico"><i className={`fa-solid ${r.icon}`} /></span>
                  <div>
                    <div style={{ fontWeight: 600, fontSize: '.88rem' }}>{r.title}</div>
                    <p className="mb-0" style={{ fontSize: '.8rem', color: 'var(--tx3)' }}>
                      {r.detail}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </PhaseStatusCard>
        </div>

        {/* Containerization recommendations */}
        <div className="col-lg-5">
          <PhaseStatusCard icon="fa-docker" brand title="Containerization">
            <ul className="check-list">
              {analysis.containerizationRecommendations.map((c, i) => (
                <li key={i}>
                  <i className="fa-solid fa-circle-check" />
                  <span>{c.text}</span>
                </li>
              ))}
            </ul>
          </PhaseStatusCard>
        </div>
      </div>

      {/* ============ SECTION 2 — Security Guard ============ */}
      <div className="section-label mt-4">
        <span className="section-label-chip">2</span>
        Security Guard Results
        <span className="section-label-by">Security Guard Agent</span>
      </div>

      <div className="row g-3">
        {/* Score */}
        <div className="col-lg-4">
          <PhaseStatusCard icon="fa-shield-halved" title="Security Score">
            <div className="d-flex align-items-center gap-3">
              <div
                className="score-ring"
                style={{ '--pct': security.score, '--ring': scoreColor(security.score) }}
              >
                <div className="score-ring-inner">
                  <span className="score-ring-num">{security.score}</span>
                  <span className="score-ring-grade">Grade {security.grade}</span>
                </div>
              </div>
              <div className="d-flex flex-column gap-1" style={{ fontSize: '.74rem' }}>
                <SevChip label="Critical" n={security.counts.critical} variant="danger" />
                <SevChip label="High" n={security.counts.high} variant="danger" />
                <SevChip label="Medium" n={security.counts.medium} variant="warning" />
                <SevChip label="Low" n={security.counts.low} variant="info" />
              </div>
            </div>
            <p className="mt-3 mb-0" style={{ fontSize: '.82rem', color: 'var(--tx2)' }}>
              {security.summary}
            </p>
          </PhaseStatusCard>
        </div>

        {/* Findings */}
        <div className="col-lg-8">
          <PhaseStatusCard icon="fa-triangle-exclamation" title="Findings" actions={
            <span className="text-muted-3" style={{ fontSize: '.78rem' }}>
              {security.findings.length} findings
            </span>
          }>
            <div className="d-flex flex-column gap-2">
              {security.findings.map((f) => (
                <div className="finding-row" key={f.id}>
                  <span className={`finding-ico badge-${SEV_VARIANT[f.severity] || 'info'}`}>
                    <i className={`fa-solid ${f.icon}`} />
                  </span>
                  <div style={{ minWidth: 0 }}>
                    <div className="d-flex align-items-center gap-2 flex-wrap">
                      <span style={{ fontWeight: 600, fontSize: '.86rem' }}>{f.title}</span>
                      <span className={`badge-pill badge-${SEV_VARIANT[f.severity] || 'info'}`}>
                        {f.severity}
                      </span>
                      <span className="tag">{f.category}</span>
                    </div>
                    <p className="mb-0" style={{ fontSize: '.8rem', color: 'var(--tx3)' }}>
                      {f.detail}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </PhaseStatusCard>
        </div>

        {/* Warnings */}
        <div className="col-lg-6">
          <PhaseStatusCard icon="fa-bell" title="Warnings">
            <ul className="check-list warn">
              {security.warnings.map((w, i) => (
                <li key={i}>
                  <i className="fa-solid fa-triangle-exclamation" />
                  <span>{w}</span>
                </li>
              ))}
            </ul>
          </PhaseStatusCard>
        </div>

        {/* Recommendations */}
        <div className="col-lg-6">
          <PhaseStatusCard icon="fa-list-check" title="Recommendations">
            <ul className="check-list">
              {security.recommendations.map((r, i) => (
                <li key={i}>
                  <i className={`fa-solid ${r.icon}`} />
                  <span>{r.text}</span>
                </li>
              ))}
            </ul>
          </PhaseStatusCard>
        </div>
      </div>

      {/* ---- Proceed ---- */}
      <div className="phase-footer">
        <p className="phase-footer-note">
          <i className="fa-solid fa-circle-info me-2" />
          Review complete — continue to plan the cloud architecture.
        </p>
        <button
          type="button"
          className="bgrd btn px-4 py-2 phase-cta"
          onClick={() => navigate('/workflows/planning')}
        >
          Proceed to Workflow
          <i className="fa-solid fa-arrow-right ms-2" />
        </button>
      </div>
    </ContentContainer>
  );
}

function SummaryItem({ icon, label, value }) {
  return (
    <div className="summary-item">
      <span className="summary-item-ico"><i className={`fa-solid ${icon}`} /></span>
      <div style={{ minWidth: 0 }}>
        <div className="summary-item-label">{label}</div>
        <div className="summary-item-value">{value}</div>
      </div>
    </div>
  );
}

function SevChip({ label, n, variant }) {
  return (
    <span className="d-inline-flex align-items-center gap-2">
      <span className={`badge-pill badge-${n > 0 ? variant : 'pending'}`} style={{ minWidth: 26, justifyContent: 'center' }}>
        {n}
      </span>
      <span style={{ color: 'var(--tx3)' }}>{label}</span>
    </span>
  );
}

function scoreColor(score) {
  if (score >= 80) return '#34d399';
  if (score >= 60) return '#fbbf24';
  return '#f87171';
}
