import PhaseStatusCard from '@/components/workflow/PhaseStatusCard';
import Tag from '@/components/common/Tag';
import { Subhead } from './AnalysisPanelBits';

/**
 * CustomerPortalPanel — business-readable summary for non-technical
 * stakeholders. Consumes WorkflowAnalysis.customerPortal.
 *
 * @param {{ data: import('@/types/workflowAnalysis').CustomerPortal }} props
 */
export default function CustomerPortalPanel({ data }) {
  const cp = data || {};
  return (
    <PhaseStatusCard
      icon="fa-people-roof"
      title="Customer Portal"
      subtitle="Business-readable summary for non-technical stakeholders"
    >
      {cp.overview && (
        <p style={{ fontSize: '.9rem', color: 'var(--tx)', lineHeight: 1.6, marginBottom: 16 }}>
          {cp.overview}
        </p>
      )}

      <div className="row g-3">
        <div className="col-md-6">
          <Subhead>System Purpose</Subhead>
          <p style={{ fontSize: '.83rem', color: 'var(--tx2)', margin: 0 }}>
            {cp.systemPurpose || '—'}
          </p>
        </div>
        <div className="col-md-6">
          <Subhead>Inferred Domain</Subhead>
          {cp.inferredDomain ? (
            <Tag icon="fa-compass">{cp.inferredDomain}</Tag>
          ) : (
            <span className="text-muted-3" style={{ fontSize: '.8rem' }}>—</span>
          )}
        </div>
      </div>

      <Subhead className="mt-3">Identified Actors / Users</Subhead>
      {Array.isArray(cp.actors) && cp.actors.length ? (
        <div className="d-flex flex-wrap gap-2">
          {cp.actors.map((a) => (
            <Tag key={a} icon="fa-user">{a}</Tag>
          ))}
        </div>
      ) : (
        <span className="text-muted-3" style={{ fontSize: '.8rem' }}>No actors identified</span>
      )}

      {cp.description && (
        <>
          <Subhead className="mt-3">High-Level Description</Subhead>
          <p style={{ fontSize: '.83rem', color: 'var(--tx2)', lineHeight: 1.6, margin: 0 }}>
            {cp.description}
          </p>
        </>
      )}
    </PhaseStatusCard>
  );
}
