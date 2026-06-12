import { useMemo, useState } from 'react';
import ContentContainer from '@/components/layout/ContentContainer';
import PageHeader from '@/components/layout/PageHeader';
import ProjectCard from '@/components/projects/ProjectCard';
import EmptyState from '@/components/common/EmptyState';
import LoadingSpinner from '@/components/common/LoadingSpinner';
import { useProjects } from '@/hooks/useProjects';

const FILTERS = [
  { key: 'all', label: 'All' },
  { key: 'deployed', label: 'Deployed' },
  { key: 'running', label: 'Running' },
  { key: 'human_review', label: 'Needs Review' },
  { key: 'draft', label: 'Draft' },
];

/**
 * Projects — searchable, filterable grid of all projects.
 */
export default function Projects() {
  const { data: projects, loading, error } = useProjects();
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('all');

  const filtered = useMemo(() => {
    const list = projects || [];
    return list.filter((p) => {
      const matchesFilter = filter === 'all' || p.status === filter;
      const q = query.trim().toLowerCase();
      const matchesQuery =
        !q ||
        p.name.toLowerCase().includes(q) ||
        p.description.toLowerCase().includes(q) ||
        (p.stack || []).some((s) => s.toLowerCase().includes(q));
      return matchesFilter && matchesQuery;
    });
  }, [projects, filter, query]);

  return (
    <ContentContainer>
      <PageHeader
        title="Projects"
        subtitle="Repositories onboarded to the platform. Each project runs through the AI infrastructure pipeline."
        breadcrumbs={[{ label: 'Projects' }]}
        actions={
          <button className="bgrd btn px-3 py-2" style={{ fontSize: '.85rem' }}>
            <i className="fa-solid fa-plus me-2" />
            New Project
          </button>
        }
      />

      {/* Toolbar */}
      <div className="d-flex flex-wrap align-items-center justify-content-between gap-3 mb-4">
        <div className="d-flex flex-wrap gap-2">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              className={`boc btn px-3 py-1 ${filter === f.key ? 'active' : ''}`}
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
        <div className="db-top-search" style={{ maxWidth: 280 }}>
          <i className="fa-solid fa-magnifying-glass" />
          <input
            type="text"
            placeholder="Search projects…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
      </div>

      {loading && !projects?.length ? (
        <LoadingSpinner center label="Loading projects…" />
      ) : error ? (
        <EmptyState icon="fa-triangle-exclamation" title="Couldn't load projects" message={error.message} />
      ) : filtered.length === 0 ? (
        <EmptyState
          icon="fa-folder-open"
          title="No projects match"
          message="Try a different search term or filter."
        />
      ) : (
        <div className="row g-3">
          {filtered.map((project) => (
            <div className="col-md-6 col-xl-4" key={project.id}>
              <ProjectCard project={project} />
            </div>
          ))}
        </div>
      )}
    </ContentContainer>
  );
}
