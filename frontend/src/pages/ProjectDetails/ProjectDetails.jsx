import { useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import ContentContainer from '@/components/layout/ContentContainer';
import PageHeader from '@/components/layout/PageHeader';
import Card from '@/components/common/Card';
import StatusBadge from '@/components/common/StatusBadge';
import Tag from '@/components/common/Tag';
import EmptyState from '@/components/common/EmptyState';
import LoadingSpinner from '@/components/common/LoadingSpinner';
import ProjectAnalysisStatus, {
  ProjectAnalysisStatusBadge,
} from '@/components/projects/ProjectAnalysisStatus';
import { useProject, useProjectAnalysis } from '@/hooks/useProjects';
import { projectApi } from '@/services/api/projectApi';
import { useToast } from '@/hooks/useToast';
import { formatDate, timeAgo } from '@/utils/formatters';

const TABS = [
  { key: 'overview', label: 'Overview', icon: 'fa-circle-info' },
  { key: 'analysis', label: 'Analysis', icon: 'fa-magnifying-glass-chart' },
  { key: 'security', label: 'Security', icon: 'fa-shield-halved' },
];

function shortRepo(url) {
  if (!url) return null;
  return url.replace(/^https?:\/\/(www\.)?/i, '').replace(/\.git$/i, '');
}

export default function ProjectDetails() {
  const { id } = useParams();
  const toast = useToast();
  const { data: project, loading, error, refetch: refetchProject } = useProject(id);
  const { data: analysis, refetch: refetchAnalysis } = useProjectAnalysis(id);
  const [tab, setTab] = useState('overview');
  const [retrying, setRetrying] = useState(false);

  const handleRetry = async () => {
    setRetrying(true);
    try {
      await projectApi.retryBootstrap(id);
      toast.info('Analysis restarted.');
      await Promise.all([refetchProject(), refetchAnalysis()]);
    } catch (err) {
      toast.error(err.message || 'Could not restart analysis.');
    } finally {
      setRetrying(false);
    }
  };

  if (loading) {
    return (
      <ContentContainer>
        <LoadingSpinner center label="Loading project…" />
      </ContentContainer>
    );
  }

  if (error || !project) {
    return (
      <ContentContainer>
        <EmptyState
          icon="fa-triangle-exclamation"
          title="Project not found"
          message={error?.message || `No project with id "${id}".`}
          action={
            <Link to="/projects" className="boc btn px-3 py-2" style={{ fontSize: '.85rem' }}>
              Back to Projects
            </Link>
          }
        />
      </ContentContainer>
    );
  }

  // Prefer the polling analysis payload's status (fresher) over the project row.
  const bootstrapStatus = analysis?.bootstrapStatus || project.bootstrapStatus;
  const bootstrapError = analysis?.bootstrapError || project.bootstrapError;
  // A re-analysis is already running — hide the trigger so it can't be double-fired.
  const analyzing = bootstrapStatus === 'analyzing' || bootstrapStatus === 'context_building';

  return (
    <ContentContainer>
      <PageHeader
        title={project.name}
        subtitle={project.description}
        breadcrumbs={[{ label: 'Projects', to: '/projects' }, { label: project.name }]}
        actions={
          <>
            {project.repositoryUrl && (
              <button
                type="button"
                className="boc btn px-3 py-2"
                style={{ fontSize: '.85rem' }}
                disabled={retrying || analyzing}
                onClick={handleRetry}
                title="Re-run codebase analysis — re-invokes the LLM and ignores the cached result"
              >
                <i className={`fa-solid fa-arrows-rotate me-2 ${retrying ? 'fa-spin' : ''}`} />
                {retrying ? 'Re-analyzing…' : 'Re-analyze'}
              </button>
            )}
            {project.repositoryUrl && (
              <a
                href={project.repositoryUrl}
                target="_blank"
                rel="noreferrer"
                className="boc btn px-3 py-2"
                style={{ fontSize: '.85rem' }}
              >
                <i className="fa-brands fa-github me-2" />
                Repository
              </a>
            )}
            <Link
              to={`/projects/${project.id}/settings`}
              className="boc btn px-3 py-2"
              style={{ fontSize: '.85rem' }}
            >
              <i className="fa-solid fa-gear me-2" />
              Settings
            </Link>
            <Link
              to={`/workflows/${project.id}/analysis`}
              className="bgrd btn px-3 py-2"
              style={{ fontSize: '.85rem' }}
            >
              <i className="fa-solid fa-wand-magic-sparkles me-2" />
              Workflow Analysis
            </Link>
          </>
        }
      />

      {/* Meta row */}
      <div className="d-flex flex-wrap align-items-center gap-2 mb-4">
        <StatusBadge status={project.status} />
        <ProjectAnalysisStatusBadge status={bootstrapStatus} />
        <Tag icon={project.repositoryVisibility === 'private' ? 'fa-lock' : 'fa-globe'}>
          {project.repositoryVisibility}
        </Tag>
        {project.architectureType && <Tag icon="fa-sitemap">{project.architectureType}</Tag>}
        <span className="text-muted-3" style={{ fontSize: '.78rem', marginLeft: 'auto' }}>
          <i className="fa-regular fa-clock me-1" />
          Updated {timeAgo(project.updatedAt)}
        </span>
      </div>

      {/* Analysis status banner — always visible so the user sees progress */}
      <ProjectAnalysisStatus
        status={bootstrapStatus}
        error={bootstrapError}
        onRetry={bootstrapStatus === 'failed' ? handleRetry : undefined}
        retrying={retrying}
        className="mb-4"
      />

      {/* Tabs */}
      <div className="d-flex flex-wrap gap-2 mb-4" style={{ borderBottom: '1px solid var(--bd)' }}>
        {TABS.map((t) => (
          <button
            key={t.key}
            className="btn"
            style={{
              fontSize: '.85rem',
              fontWeight: 600,
              padding: '8px 14px',
              borderRadius: 0,
              color: tab === t.key ? '#a78bfa' : 'var(--tx3)',
              borderBottom: tab === t.key ? '2px solid #8b5cf6' : '2px solid transparent',
            }}
            onClick={() => setTab(t.key)}
          >
            <i className={`fa-solid ${t.icon} me-2`} />
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'overview' && <OverviewTab project={project} analysis={analysis} />}
      {tab === 'analysis' && <AnalysisTab analysis={analysis} status={bootstrapStatus} />}
      {tab === 'security' && <SecurityTab security={analysis?.security} status={bootstrapStatus} />}
    </ContentContainer>
  );
}

/* ── Overview ──────────────────────────────────────────────────────────────── */

function OverviewTab({ project, analysis }) {
  const activity = buildActivity(project, analysis);
  return (
    <div className="row g-3">
      <div className="col-lg-7">
        <Card title="Project Information" icon="fa-circle-info">
          <div className="row g-3">
            <InfoRow label="Repository" value={shortRepo(project.repositoryUrl) || '—'} mono />
            <InfoRow label="Visibility" value={project.repositoryVisibility} />
            <InfoRow label="Lifecycle Status" value={project.status} />
            <InfoRow label="Analysis Status" value={project.bootstrapStatus} />
            <InfoRow label="Architecture" value={project.architectureType || 'Inferring…'} />
            <InfoRow label="Created" value={formatDate(project.createdAt)} />
            <InfoRow label="Last Updated" value={formatDate(project.updatedAt)} />
            {typeof project.artifactCount === 'number' && (
              <InfoRow label="Artifacts" value={String(project.artifactCount)} />
            )}
          </div>
        </Card>

        {project.description && (
          <Card title="About" icon="fa-align-left" className="mt-3">
            <p style={{ fontSize: '.88rem', color: 'var(--tx2)', lineHeight: 1.6, margin: 0 }}>
              {project.description}
            </p>
          </Card>
        )}
      </div>

      <div className="col-lg-5">
        <Card title="Recent Activity" icon="fa-clock-rotate-left">
          {activity.length ? (
            <div className="d-flex flex-column gap-3">
              {activity.map((a, i) => (
                <div key={i} className="d-flex align-items-start gap-2">
                  <span className={`finding-ico badge-${a.variant}`} style={{ flexShrink: 0 }}>
                    <i className={`fa-solid ${a.icon}`} />
                  </span>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontSize: '.85rem', fontWeight: 600 }}>{a.title}</div>
                    <div className="text-muted-3" style={{ fontSize: '.74rem' }}>
                      {a.at ? timeAgo(a.at) : ''}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-muted-3" style={{ fontSize: '.85rem' }}>
              No activity yet.
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}

function buildActivity(project, analysis) {
  const items = [];
  if (project.createdAt) {
    items.push({ title: 'Project created', at: project.createdAt, icon: 'fa-folder-plus', variant: 'info' });
  }
  const status = analysis?.bootstrapStatus || project.bootstrapStatus;
  if (status === 'ready') {
    items.push({ title: 'Analysis completed', at: project.updatedAt, icon: 'fa-circle-check', variant: 'success' });
  } else if (status === 'failed') {
    items.push({ title: 'Analysis failed', at: project.updatedAt, icon: 'fa-circle-xmark', variant: 'danger' });
  } else if (status === 'analyzing' || status === 'context_building') {
    items.push({ title: 'Analysis in progress', at: project.updatedAt, icon: 'fa-spinner', variant: 'running' });
  }
  if (analysis?.security?.score != null) {
    items.push({
      title: `Security scan: ${analysis.security.score}/100 (${analysis.security.grade || '—'})`,
      at: project.updatedAt,
      icon: 'fa-shield-halved',
      variant: 'info',
    });
  }
  return items;
}

/* ── Analysis ──────────────────────────────────────────────────────────────── */

function AnalysisTab({ analysis, status }) {
  if (!analysis?.available) {
    return <PendingPanel status={status} kind="analysis" />;
  }
  const { stats } = analysis;
  return (
    <>
      {/* Summary grid */}
      <div className="surface mb-3">
        <div className="summary-grid">
          <SummaryItem icon="fa-code" label="Language" value={analysis.language || '—'} />
          <SummaryItem icon="fa-layer-group" label="Framework" value={analysis.framework || '—'} />
          <SummaryItem icon="fa-microchip" label="Runtime" value={analysis.runtime || '—'} />
          <SummaryItem icon="fa-diagram-project" label="Services" value={String(stats.serviceCount ?? analysis.services.length)} />
          <SummaryItem icon="fa-file-lines" label="Lines of Code" value={stats.linesOfCode != null ? String(stats.linesOfCode) : '—'} />
          <SummaryItem icon="fa-box" label="Project Type" value={stats.projectType || '—'} />
        </div>
      </div>

      <div className="row g-3">
        {/* Languages + frameworks */}
        <div className="col-lg-6">
          <Card title="Detected Stack" icon="fa-cubes-stacked">
            <Subhead>Languages</Subhead>
            <TagRow items={analysis.languages} empty="No languages detected" />
            <Subhead className="mt-3">Frameworks</Subhead>
            <TagRow items={analysis.frameworks} empty="No frameworks detected" />
            <Subhead className="mt-3">Build / Package Managers</Subhead>
            <TagRow items={analysis.dependencies} empty="None detected" />
          </Card>
        </div>

        {/* DevOps signals */}
        <div className="col-lg-6">
          <Card title="Repository Signals" icon="fa-gears">
            <ul className="check-list">
              <SignalItem ok={stats.hasDockerfile} label="Dockerfile present" />
              <SignalItem ok={stats.hasCompose} label="Docker Compose present" />
              <SignalItem ok={stats.hasCi} label="CI/CD configuration present" />
            </ul>
            {!!(stats.devopsTools || []).length && (
              <>
                <Subhead className="mt-3">DevOps Tools</Subhead>
                <TagRow items={stats.devopsTools} empty="None" />
              </>
            )}
            {stats.applicationProfile && (
              <>
                <Subhead className="mt-3">Application Profile</Subhead>
                <div className="d-flex flex-wrap gap-2">
                  {stats.applicationProfile.applicationType && (
                    <span className="tag">{stats.applicationProfile.applicationType}</span>
                  )}
                  {stats.applicationProfile.architecturePattern && (
                    <span className="tag">{stats.applicationProfile.architecturePattern}</span>
                  )}
                  {stats.applicationProfile.workloadProfile && (
                    <span className="tag">{stats.applicationProfile.workloadProfile}</span>
                  )}
                  {stats.applicationProfile.statefulness && (
                    <span className="tag">{stats.applicationProfile.statefulness}</span>
                  )}
                  {stats.applicationProfile.scalabilityLevel && (
                    <span className="tag">{`scalability: ${stats.applicationProfile.scalabilityLevel}`}</span>
                  )}
                </div>
                {!!(stats.applicationProfile.detectedServices || []).length && (
                  <>
                    <Subhead className="mt-3">Profile Services</Subhead>
                    <TagRow items={stats.applicationProfile.detectedServices} empty="None" />
                  </>
                )}
              </>
            )}
          </Card>
        </div>

        {/* Services */}
        {!!analysis.services.length && (
          <div className="col-12">
            <Card title="Detected Services" icon="fa-diagram-project">
              <div className="row g-3">
                {analysis.services.map((svc, i) => (
                  <div className="col-md-4" key={svc.name || i}>
                    <div className="service-tile">
                      <div className="service-tile-head">
                        <span className="service-tile-ico">
                          <i className="fa-solid fa-server" />
                        </span>
                        <div style={{ minWidth: 0 }}>
                          <div className="service-tile-name mono">{svc.name || `service-${i + 1}`}</div>
                          <div className="service-tile-role">{svc.type || svc.role || 'service'}</div>
                        </div>
                      </div>
                      {(svc.port || svc.build) && (
                        <div className="service-tile-meta">
                          {svc.port && <span><i className="fa-solid fa-plug me-1" />:{svc.port}</span>}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </Card>
          </div>
        )}
      </div>
    </>
  );
}

/* ── Security ──────────────────────────────────────────────────────────────── */

const SEV_VARIANT = { critical: 'danger', high: 'danger', medium: 'warning', low: 'info' };

function SecurityTab({ security, status }) {
  if (!security || security.score == null) {
    return <PendingPanel status={status} kind="security" />;
  }
  const c = security.counts || {};
  return (
    <div className="row g-3">
      {/* Score */}
      <div className="col-lg-4">
        <Card title="Security Score" icon="fa-shield-halved">
          <div className="d-flex align-items-center gap-3">
            <div className="score-ring" style={{ '--pct': security.score, '--ring': scoreColor(security.score) }}>
              <div className="score-ring-inner">
                <span className="score-ring-num">{security.score}</span>
                <span className="score-ring-grade">Grade {security.grade || '—'}</span>
              </div>
            </div>
            <div className="d-flex flex-column gap-1" style={{ fontSize: '.74rem' }}>
              <SevChip label="Critical" n={c.critical} variant="danger" />
              <SevChip label="High" n={c.high} variant="danger" />
              <SevChip label="Medium" n={c.medium} variant="warning" />
              <SevChip label="Low" n={c.low} variant="info" />
            </div>
          </div>
          {security.summary && (
            <p className="mt-3 mb-0" style={{ fontSize: '.82rem', color: 'var(--tx2)' }}>
              {security.summary}
            </p>
          )}
        </Card>
      </div>

      {/* Findings */}
      <div className="col-lg-8">
        <Card
          title="Findings"
          icon="fa-triangle-exclamation"
          action={
            <span className="text-muted-3" style={{ fontSize: '.78rem' }}>
              {security.findings.length} findings
            </span>
          }
        >
          {security.findings.length ? (
            <div className="d-flex flex-column gap-2">
              {security.findings.map((f) => (
                <div className="finding-row" key={f.id}>
                  <span className={`finding-ico badge-${SEV_VARIANT[f.severity] || 'info'}`}>
                    <i className="fa-solid fa-triangle-exclamation" />
                  </span>
                  <div style={{ minWidth: 0 }}>
                    <div className="d-flex align-items-center gap-2 flex-wrap">
                      <span style={{ fontWeight: 600, fontSize: '.86rem' }}>{f.title}</span>
                      <span className={`badge-pill badge-${SEV_VARIANT[f.severity] || 'info'}`}>{f.severity}</span>
                      {f.category && <span className="tag">{f.category}</span>}
                    </div>
                    {f.detail && (
                      <p className="mb-0" style={{ fontSize: '.8rem', color: 'var(--tx3)' }}>{f.detail}</p>
                    )}
                    {f.recommendation && (
                      <p className="mb-0 mt-1" style={{ fontSize: '.78rem', color: 'var(--tx2)' }}>
                        <i className="fa-solid fa-lightbulb me-1" style={{ color: '#fbbf24' }} />
                        {f.recommendation}
                      </p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="d-flex align-items-center gap-2" style={{ fontSize: '.85rem', color: '#34d399' }}>
              <i className="fa-solid fa-circle-check" />
              No security findings — repository passed all checks.
            </div>
          )}
        </Card>
      </div>

      {/* Recommendations */}
      {!!security.recommendations.length && (
        <div className="col-12">
          <Card title="Recommendations" icon="fa-list-check">
            <ul className="check-list">
              {security.recommendations.map((r, i) => (
                <li key={i}>
                  <i className="fa-solid fa-shield-halved" />
                  <span>{r}</span>
                </li>
              ))}
            </ul>
          </Card>
        </div>
      )}
    </div>
  );
}

/* ── Shared bits ───────────────────────────────────────────────────────────── */

function PendingPanel({ status, kind }) {
  const failed = status === 'failed';
  return (
    <EmptyState
      icon={failed ? 'fa-triangle-exclamation' : 'fa-hourglass-half'}
      title={failed ? `No ${kind} results` : `${kind === 'security' ? 'Security scan' : 'Analysis'} in progress`}
      message={
        failed
          ? `The analysis did not complete, so ${kind} results are unavailable. Retry from the status panel above.`
          : `Results will appear here as soon as the ${kind === 'security' ? 'security scan' : 'code analysis'} finishes.`
      }
    />
  );
}

function InfoRow({ label, value, mono = false }) {
  return (
    <div className="col-sm-6">
      <div className="form-label-sm">{label}</div>
      <div className={mono ? 'mono' : ''} style={{ fontSize: '.85rem', color: 'var(--tx)', wordBreak: 'break-word' }}>
        {value || '—'}
      </div>
    </div>
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

function Subhead({ children, className = '' }) {
  return (
    <div className={`form-label-sm ${className}`.trim()} style={{ marginBottom: 6 }}>
      {children}
    </div>
  );
}

function TagRow({ items, empty }) {
  const list = items || [];
  if (!list.length) {
    return <span className="text-muted-3" style={{ fontSize: '.8rem' }}>{empty}</span>;
  }
  return (
    <div className="d-flex flex-wrap gap-2">
      {list.map((it) => (
        <Tag key={String(it)}>{String(it)}</Tag>
      ))}
    </div>
  );
}

function SignalItem({ ok, label }) {
  return (
    <li>
      <i className={`fa-solid ${ok ? 'fa-circle-check' : 'fa-circle-minus'}`} style={{ color: ok ? '#34d399' : 'var(--tx3)' }} />
      <span style={{ color: ok ? 'var(--tx)' : 'var(--tx3)' }}>{label}</span>
    </li>
  );
}

function SevChip({ label, n = 0, variant }) {
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
