import { useMemo, useState } from 'react';
import ContentContainer from '@/components/layout/ContentContainer';
import PageHeader from '@/components/layout/PageHeader';
import WorkflowCard from '@/components/workflow/WorkflowCard';
import StatsCard from '@/components/common/StatsCard';
import EmptyState from '@/components/common/EmptyState';
import LoadingSpinner from '@/components/common/LoadingSpinner';
import { useWorkflows } from '@/hooks/useWorkflows';

const FILTERS = [
  { key: 'all', label: 'All' },
  { key: 'running', label: 'Running' },
  { key: 'completed', label: 'Completed' },
  { key: 'human_review', label: 'Needs Review' },
  { key: 'degraded', label: 'Degraded' },
];

/**
 * Workflows — overview of all pipeline runs with quick status counts.
 */
export default function Workflows() {
  const { data: workflows, loading } = useWorkflows();
  const [filter, setFilter] = useState('all');

  const counts = useMemo(() => {
    const list = workflows || [];
    return {
      total: list.length,
      running: list.filter((w) => w.status === 'running').length,
      review: list.filter((w) => w.status === 'human_review').length,
      completed: list.filter((w) => w.status === 'completed').length,
    };
  }, [workflows]);

  const filtered = (workflows || []).filter(
    (w) => filter === 'all' || w.status === filter
  );

  return (
    <ContentContainer>
      <PageHeader
        title="Workflows"
        subtitle="Every run of the AI infrastructure pipeline across your projects."
        breadcrumbs={[{ label: 'Workflows' }]}
      />

      <div className="row g-3 mb-4">
        <div className="col-6 col-xl-3">
          <StatsCard label="Total Runs" value={counts.total} icon="fa-diagram-project" accent="#a78bfa" />
        </div>
        <div className="col-6 col-xl-3">
          <StatsCard label="Running" value={counts.running} icon="fa-spinner" accent="#60a5fa" />
        </div>
        <div className="col-6 col-xl-3">
          <StatsCard label="Needs Review" value={counts.review} icon="fa-user-check" accent="#fbbf24" />
        </div>
        <div className="col-6 col-xl-3">
          <StatsCard label="Completed" value={counts.completed} icon="fa-circle-check" accent="#34d399" />
        </div>
      </div>

      <div className="d-flex flex-wrap gap-2 mb-4">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            className="boc btn px-3 py-1"
            style={{
              fontSize: '.8rem',
              borderRadius: 10,
              background: filter === f.key ? 'rgba(139,92,246,.15)' : 'var(--sf)',
              color: filter === f.key ? '#a78bfa' : 'var(--tx2)',
              borderColor: filter === f.key ? 'rgba(139,92,246,.3)' : 'var(--bd)',
            }}
            onClick={() => setFilter(f.key)}
          >
            {f.label}
          </button>
        ))}
      </div>

      {loading && !workflows?.length ? (
        <LoadingSpinner center label="Loading workflows…" />
      ) : filtered.length === 0 ? (
        <EmptyState icon="fa-diagram-project" title="No workflows" message="No runs match this filter." />
      ) : (
        <div className="row g-3">
          {filtered.map((wf) => (
            <div className="col-md-6 col-xl-4" key={wf.id}>
              <WorkflowCard workflow={wf} />
            </div>
          ))}
        </div>
      )}
    </ContentContainer>
  );
}
