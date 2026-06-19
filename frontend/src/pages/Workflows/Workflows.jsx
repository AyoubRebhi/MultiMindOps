import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import ContentContainer from '@/components/layout/ContentContainer';
import PageHeader from '@/components/layout/PageHeader';
import WorkflowCard from '@/components/workflow/WorkflowCard';
import StatsCard from '@/components/common/StatsCard';
import EmptyState from '@/components/common/EmptyState';
import ErrorState from '@/components/common/ErrorState';
import LoadingSpinner from '@/components/common/LoadingSpinner';
import { useWorkflows } from '@/hooks/useWorkflows';
import { useAuth } from '@/hooks/useAuth';

const FILTERS = [
  { key: 'all', label: 'All' },
  { key: 'running', label: 'Running' },
  { key: 'awaiting_input', label: 'Awaiting Input' },
  { key: 'completed', label: 'Completed' },
  { key: 'failed', label: 'Failed' },
];

/** Collapse the backend Workflow.status into the page's filter buckets. */
function bucketOf(status) {
  const s = (status || '').toLowerCase();
  if (s === 'running' || s === 'pending') return 'running';
  if (s === 'awaiting_input') return 'awaiting_input';
  if (s === 'completed') return 'completed';
  if (s === 'failed' || s === 'cancelled') return 'failed';
  return 'other';
}

/**
 * Workflows — overview of pipeline runs with quick status counts.
 *
 * Visibility is role-aware and enforced by the backend (GET /api/workflows):
 *   • ADMIN           sees every workflow on the platform — read-only monitoring.
 *   • DEVOPS_ENGINEER sees only the workflows they launched.
 * The role gating below is UX only (the API is the source of truth).
 */
export default function Workflows() {
  const { data: workflows, loading, error, refetch } = useWorkflows();
  const { isAdmin } = useAuth();
  const [filter, setFilter] = useState('all');

  const counts = useMemo(() => {
    const list = workflows || [];
    return {
      total: list.length,
      running: list.filter((w) => bucketOf(w.status) === 'running').length,
      review: list.filter((w) => bucketOf(w.status) === 'awaiting_input').length,
      completed: list.filter((w) => bucketOf(w.status) === 'completed').length,
    };
  }, [workflows]);

  const filtered = (workflows || []).filter(
    (w) => filter === 'all' || bucketOf(w.status) === filter
  );

  return (
    <ContentContainer>
      <PageHeader
        title="Workflows"
        subtitle={
          isAdmin
            ? 'Monitoring every workflow across the platform — read-only.'
            : "Every run of the AI infrastructure pipeline you've launched."
        }
        breadcrumbs={[{ label: 'Workflows' }]}
        // Admins are read-only: no workflow execution actions.
        actions={
          isAdmin ? null : (
            <Link to="/workflows/analysis" className="bgrd btn px-3 py-2" style={{ fontSize: '.85rem' }}>
              <i className="fa-solid fa-play me-2" />
              Run Workflow
            </Link>
          )
        }
      />

      {isAdmin && (
        <div
          className="surface d-flex align-items-center gap-2 mb-4"
          style={{ borderColor: 'rgba(96,165,250,.3)', background: 'rgba(96,165,250,.08)' }}
        >
          <i className="fa-solid fa-eye" style={{ color: '#60a5fa' }} />
          <span style={{ fontSize: '.82rem', color: 'var(--tx2)' }}>
            <strong style={{ color: 'var(--tx1)' }}>Read-only monitoring.</strong>{' '}
            As an admin you can view every workflow and its progress, but you
            cannot execute phases, rerun, or modify workflow state.
          </span>
        </div>
      )}

      <div className="row g-3 mb-4">
        <div className="col-6 col-xl-3">
          <StatsCard label="Total Runs" value={counts.total} icon="fa-diagram-project" accent="#a78bfa" />
        </div>
        <div className="col-6 col-xl-3">
          <StatsCard label="Running" value={counts.running} icon="fa-spinner" accent="#60a5fa" />
        </div>
        <div className="col-6 col-xl-3">
          <StatsCard label="Awaiting Input" value={counts.review} icon="fa-hourglass-half" accent="#fbbf24" />
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
      ) : error ? (
        <ErrorState
          title="Couldn't load workflows"
          message={error.message}
          onRetry={refetch}
        />
      ) : filtered.length === 0 ? (
        <EmptyState
          icon="fa-diagram-project"
          title="No workflows"
          message={
            (workflows || []).length === 0
              ? isAdmin
                ? 'No workflows have been launched on the platform yet.'
                : "You haven't launched any workflows yet. Start one from a project."
              : 'No runs match this filter.'
          }
        />
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
