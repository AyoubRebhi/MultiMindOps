import { useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import ContentContainer from '@/components/layout/ContentContainer';
import PageHeader from '@/components/layout/PageHeader';
import Card from '@/components/common/Card';
import StatusBadge from '@/components/common/StatusBadge';
import ProviderBadge from '@/components/common/ProviderBadge';
import ProgressBar from '@/components/common/ProgressBar';
import Tag from '@/components/common/Tag';
import EmptyState from '@/components/common/EmptyState';
import LoadingSpinner from '@/components/common/LoadingSpinner';
import TimelineCard from '@/components/workflow/TimelineCard';
import ArtifactCard from '@/components/artifacts/ArtifactCard';
import ArchitecturePlanCard from '@/components/architecture/ArchitecturePlanCard';
import { useProject } from '@/hooks/useProjects';
import { useProjectWorkflows } from '@/hooks/useWorkflows';
import { useProjectArtifacts } from '@/hooks/useArtifacts';
import { useAsync } from '@/hooks/useAsync';
import { architectureApi } from '@/services/api/architectureApi';
import { formatCurrency, formatDate } from '@/utils/formatters';

const TABS = [
  { key: 'overview', label: 'Overview', icon: 'fa-circle-info' },
  { key: 'pipeline', label: 'Pipeline', icon: 'fa-diagram-project' },
  { key: 'architecture', label: 'Architecture', icon: 'fa-sitemap' },
  { key: 'artifacts', label: 'Artifacts', icon: 'fa-file-code' },
];

export default function ProjectDetails() {
  const { id } = useParams();
  const { data: project, loading, error } = useProject(id);
  const { data: workflows } = useProjectWorkflows(id);
  const { data: artifacts } = useProjectArtifacts(id);
  const { data: plans } = useAsync(() => architectureApi.listByProject(id), [id], {
    initialData: [],
  });
  const [tab, setTab] = useState('overview');

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

  const latestWorkflow = (workflows || [])[0];

  return (
    <ContentContainer>
      <PageHeader
        title={project.name}
        subtitle={project.description}
        breadcrumbs={[{ label: 'Projects', to: '/projects' }, { label: project.name }]}
        actions={
          <>
            <a
              href={`https://${project.repoUrl}`}
              target="_blank"
              rel="noreferrer"
              className="boc btn px-3 py-2"
              style={{ fontSize: '.85rem' }}
            >
              <i className="fa-brands fa-github me-2" />
              Repo
            </a>
            <button className="bgrd btn px-3 py-2" style={{ fontSize: '.85rem' }}>
              <i className="fa-solid fa-play me-2" />
              Run Workflow
            </button>
          </>
        }
      />

      {/* Meta row */}
      <div className="d-flex flex-wrap align-items-center gap-2 mb-4">
        <StatusBadge status={project.status} />
        <ProviderBadge provider={project.provider} />
        <Tag icon="fa-location-dot">{project.region}</Tag>
        <Tag icon="fa-layer-group">{project.environment}</Tag>
        {project.stack.map((s) => (
          <Tag key={s}>{s}</Tag>
        ))}
      </div>

      {/* Summary stats */}
      <div className="row g-3 mb-4">
        <SummaryStat label="Pipeline Progress" value={`${project.progress}%`}>
          <ProgressBar value={project.progress} />
        </SummaryStat>
        <SummaryStat label="Services" value={project.services} icon="fa-server" />
        <SummaryStat
          label="Monthly Cost"
          value={project.monthlyCost ? formatCurrency(project.monthlyCost) : '—'}
          icon="fa-coins"
        />
        <SummaryStat label="Created" value={formatDate(project.createdAt)} icon="fa-calendar" />
      </div>

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

      {/* Tab content */}
      {tab === 'overview' && <OverviewTab project={project} workflow={latestWorkflow} />}

      {tab === 'pipeline' &&
        (latestWorkflow ? (
          <Card title={`${latestWorkflow.name} · ${latestWorkflow.status}`} icon="fa-diagram-project">
            <TimelineCard phases={latestWorkflow.phases} />
          </Card>
        ) : (
          <EmptyState icon="fa-diagram-project" title="No workflow runs yet" message="Run a workflow to see the pipeline timeline." />
        ))}

      {tab === 'architecture' &&
        (plans?.length ? (
          <div className="row g-3">
            {plans.map((plan) => (
              <div className="col-lg-6" key={plan.id}>
                <ArchitecturePlanCard plan={plan} linkToProject={false} />
              </div>
            ))}
          </div>
        ) : (
          <EmptyState icon="fa-sitemap" title="No architecture plans" message="The architecture phase hasn't produced a plan yet." />
        ))}

      {tab === 'artifacts' &&
        (artifacts?.length ? (
          <div className="row g-3">
            {artifacts.map((art) => (
              <div className="col-lg-6" key={art.id}>
                <ArtifactCard artifact={art} />
              </div>
            ))}
          </div>
        ) : (
          <EmptyState icon="fa-file-code" title="No artifacts generated" message="Artifacts appear once the Docker / Terraform phases run." />
        ))}
    </ContentContainer>
  );
}

function SummaryStat({ label, value, icon, children }) {
  return (
    <div className="col-6 col-xl-3">
      <div className="surface">
        <div className="d-flex align-items-center justify-content-between">
          <div className="db-stat-lbl" style={{ margin: 0 }}>
            {label}
          </div>
          {icon && <i className={`fa-solid ${icon}`} style={{ color: 'var(--tx3)' }} />}
        </div>
        <div style={{ fontSize: '1.4rem', fontWeight: 700, margin: '6px 0' }}>{value}</div>
        {children}
      </div>
    </div>
  );
}

function OverviewTab({ project, workflow }) {
  return (
    <div className="row g-3">
      <div className="col-lg-7">
        <Card title="About" icon="fa-circle-info">
          <p style={{ fontSize: '.88rem', color: 'var(--tx2)', lineHeight: 1.6 }}>
            {project.description}
          </p>
          <div className="row g-3 mt-1">
            <InfoRow label="Repository" value={project.repoUrl} mono />
            <InfoRow label="Owner" value={project.owner} />
            <InfoRow label="Environment" value={project.environment} />
            <InfoRow label="Region" value={project.region} mono />
          </div>
        </Card>
      </div>
      <div className="col-lg-5">
        <Card title="Latest Run" icon="fa-diagram-project">
          {workflow ? (
            <div>
              <div className="d-flex align-items-center justify-content-between mb-2">
                <span style={{ fontWeight: 600 }}>{workflow.name}</span>
                <StatusBadge status={workflow.status} />
              </div>
              <ProgressBar value={workflow.progress} showLabel />
              <div className="mt-3">
                <TimelineCard phases={(workflow.phases || []).slice(0, 4)} />
              </div>
            </div>
          ) : (
            <div className="text-muted-3" style={{ fontSize: '.85rem' }}>
              No workflow runs yet.
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}

function InfoRow({ label, value, mono = false }) {
  return (
    <div className="col-sm-6">
      <div className="form-label-sm">{label}</div>
      <div className={mono ? 'mono' : ''} style={{ fontSize: '.85rem', color: 'var(--tx)' }}>
        {value}
      </div>
    </div>
  );
}
