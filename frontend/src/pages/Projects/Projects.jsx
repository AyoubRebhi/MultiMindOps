import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import ContentContainer from '@/components/layout/ContentContainer';
import PageHeader from '@/components/layout/PageHeader';
import ProjectCard from '@/components/projects/ProjectCard';
import CreateProjectModal from '@/components/projects/CreateProjectModal';
import EmptyState from '@/components/common/EmptyState';
import LoadingSpinner from '@/components/common/LoadingSpinner';
import { useProjects, useCreateProject } from '@/hooks/useProjects';
import { useToast } from '@/hooks/useToast';

// Filters map to the backend project lifecycle (current_status).
const FILTERS = [
  { key: 'all', label: 'All' },
  { key: 'active', label: 'Active' },
  { key: 'draft', label: 'Draft' },
  { key: 'failed', label: 'Failed' },
  { key: 'archived', label: 'Archived' },
];

/**
 * Projects — searchable, filterable grid of all real projects, with a
 * Create-Project modal that kicks off backend analysis on submit.
 */
export default function Projects() {
  const navigate = useNavigate();
  const toast = useToast();
  const { data: projects, loading, error, refetch } = useProjects();
  const { create, creating, error: createError } = useCreateProject();

  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('all');
  const [modalOpen, setModalOpen] = useState(false);

  const filtered = useMemo(() => {
    const list = projects || [];
    const q = query.trim().toLowerCase();
    return list.filter((p) => {
      const matchesFilter = filter === 'all' || p.status === filter;
      const matchesQuery =
        !q ||
        (p.name || '').toLowerCase().includes(q) ||
        (p.description || '').toLowerCase().includes(q) ||
        (p.repositoryUrl || '').toLowerCase().includes(q);
      return matchesFilter && matchesQuery;
    });
  }, [projects, filter, query]);

  const handleCreate = async (form) => {
    const project = await create(form);
    toast.success(`Project “${project.name}” created — analysis started.`);
    setModalOpen(false);
    await refetch();
    navigate(`/projects/${project.id}`);
    return project;
  };

  return (
    <ContentContainer>
      <PageHeader
        title="Projects"
        subtitle="Repositories onboarded to the platform. Each project runs through the AI infrastructure pipeline."
        breadcrumbs={[{ label: 'Projects' }]}
        actions={
          <button
            className="bgrd btn px-3 py-2"
            style={{ fontSize: '.85rem' }}
            onClick={() => setModalOpen(true)}
          >
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
        <EmptyState
          icon="fa-triangle-exclamation"
          title="Couldn't load projects"
          message={error.message}
          action={
            <button className="boc btn px-3 py-2" style={{ fontSize: '.85rem' }} onClick={refetch}>
              <i className="fa-solid fa-rotate-right me-2" />
              Retry
            </button>
          }
        />
      ) : !projects?.length ? (
        <EmptyState
          icon="fa-folder-open"
          title="No projects yet"
          message="Create your first project to onboard a repository and run analysis."
          action={
            <button className="bgrd btn px-3 py-2" style={{ fontSize: '.85rem' }} onClick={() => setModalOpen(true)}>
              <i className="fa-solid fa-plus me-2" />
              New Project
            </button>
          }
        />
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

      <CreateProjectModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onCreate={handleCreate}
        creating={creating}
        serverError={createError}
      />
    </ContentContainer>
  );
}
