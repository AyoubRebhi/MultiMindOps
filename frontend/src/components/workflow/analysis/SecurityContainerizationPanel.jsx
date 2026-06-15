import PhaseStatusCard from '@/components/workflow/PhaseStatusCard';
import { Subhead, CheckList, SevChip } from './AnalysisPanelBits';
import { SEV_VARIANT, scoreColor } from './analysisHelpers';

/**
 * SecurityContainerizationPanel — combined security + containerization
 * intelligence. Consumes WorkflowAnalysis.securityAnalysis and
 * WorkflowAnalysis.containerization.
 *
 * @param {{
 *   security: import('@/types/workflowAnalysis').SecurityAnalysis,
 *   containerization: import('@/types/workflowAnalysis').Containerization,
 * }} props
 */
export default function SecurityContainerizationPanel({ security, containerization }) {
  const sec = security || {};
  const cont = containerization || {};
  const counts = countSeverities(sec.risks);

  return (
    <PhaseStatusCard
      icon="fa-shield-halved"
      title="Security & Containerization"
      subtitle="Risks, hardening guidance and the recommended image strategy"
      actions={
        sec.grade ? (
          <span className="badge-pill badge-info"><i className="fa-solid fa-award" />Grade {sec.grade}</span>
        ) : null
      }
    >
      <div className="row g-3">
        {/* Score + tallies */}
        <div className="col-lg-4">
          {sec.score != null ? (
            <div className="d-flex align-items-center gap-3">
              <div className="score-ring" style={{ '--pct': sec.score, '--ring': scoreColor(sec.score) }}>
                <div className="score-ring-inner">
                  <span className="score-ring-num">{sec.score}</span>
                  <span className="score-ring-grade">Grade {sec.grade || '—'}</span>
                </div>
              </div>
              <div className="d-flex flex-column gap-1" style={{ fontSize: '.74rem' }}>
                <SevChip label="Critical" n={counts.critical} variant="danger" />
                <SevChip label="High" n={counts.high} variant="danger" />
                <SevChip label="Medium" n={counts.medium} variant="warning" />
                <SevChip label="Low" n={counts.low} variant="info" />
              </div>
            </div>
          ) : (
            <span className="text-muted-3" style={{ fontSize: '.8rem' }}>No security score yet</span>
          )}
          {sec.summary && (
            <p className="mt-3 mb-0" style={{ fontSize: '.82rem', color: 'var(--tx2)' }}>{sec.summary}</p>
          )}
        </div>

        {/* Risks */}
        <div className="col-lg-8">
          <Subhead>Security Risks</Subhead>
          {Array.isArray(sec.risks) && sec.risks.length ? (
            <div className="d-flex flex-column gap-2">
              {sec.risks.map((f) => (
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
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="d-flex align-items-center gap-2" style={{ fontSize: '.85rem', color: '#34d399' }}>
              <i className="fa-solid fa-circle-check" />
              No security risks — repository passed all checks.
            </div>
          )}
        </div>

        {/* Security recommendations + hardening */}
        <div className="col-md-6">
          <Subhead>Security Recommendations</Subhead>
          <CheckList items={sec.recommendations} icon="fa-shield-halved" empty="No recommendations" />
        </div>
        <div className="col-md-6">
          <Subhead>Hardening Recommendations</Subhead>
          <CheckList items={sec.hardening} icon="fa-lock" empty="No hardening steps" />
        </div>
      </div>

      {/* Containerization */}
      <div className="section-label mt-4">
        <span className="section-label-chip"><i className="fa-brands fa-docker" /></span>
        Containerization
      </div>
      <div className="row g-3">
        <div className="col-md-6">
          <Subhead>Docker Suitability</Subhead>
          {cont.dockerSuitability ? (
            <span className="badge-pill badge-success">
              <i className="fa-brands fa-docker" />
              {cont.dockerSuitability}
            </span>
          ) : (
            <span className="text-muted-3" style={{ fontSize: '.8rem' }}>Not assessed</span>
          )}

          <Subhead className="mt-3">Containerization Findings</Subhead>
          <CheckList items={cont.findings} icon="fa-circle-check" empty="No findings" />
        </div>

        <div className="col-md-6">
          <Subhead>Image Strategy Recommendations</Subhead>
          <CheckList items={cont.imageStrategy} icon="fa-layer-group" empty="No image strategy yet" />
          {cont.notes && (
            <p className="mt-2 mb-0" style={{ fontSize: '.78rem', color: 'var(--tx3)' }}>
              <i className="fa-solid fa-circle-info me-1" />
              {cont.notes}
            </p>
          )}
        </div>
      </div>
    </PhaseStatusCard>
  );
}

function countSeverities(risks) {
  const counts = { critical: 0, high: 0, medium: 0, low: 0 };
  (Array.isArray(risks) ? risks : []).forEach((r) => {
    if (counts[r.severity] != null) counts[r.severity] += 1;
  });
  return counts;
}
