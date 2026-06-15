import PhaseStatusCard from '@/components/workflow/PhaseStatusCard';
import { Subhead, TagRow } from './AnalysisPanelBits';

/**
 * CodeAnalysisPanel — technical repository analysis. Consumes
 * WorkflowAnalysis.codeAnalysis (languages, frameworks, libraries, package
 * managers, build tools, repository characteristics).
 *
 * @param {{ data: import('@/types/workflowAnalysis').CodeAnalysis }} props
 */
export default function CodeAnalysisPanel({ data }) {
  const c = data || {};
  const chars = Array.isArray(c.repositoryCharacteristics) ? c.repositoryCharacteristics : [];

  return (
    <PhaseStatusCard
      icon="fa-cubes-stacked"
      title="Code Analysis"
      subtitle="Detected stack, build tooling and repository characteristics"
    >
      <div className="row g-3">
        <div className="col-md-6">
          <Subhead>Languages</Subhead>
          <TagRow items={c.languages} empty="No languages detected" />

          <Subhead className="mt-3">Frameworks</Subhead>
          <TagRow items={c.frameworks} empty="No frameworks detected" />

          <Subhead className="mt-3">Libraries</Subhead>
          <TagRow items={c.libraries} empty="No libraries detected" />
        </div>

        <div className="col-md-6">
          <Subhead>Package Managers</Subhead>
          <TagRow items={c.packageManagers} empty="None detected" />

          <Subhead className="mt-3">Build Tools</Subhead>
          <TagRow items={c.buildTools} empty="None detected" />
        </div>
      </div>

      {!!chars.length && (
        <>
          <Subhead className="mt-3">Repository Characteristics</Subhead>
          <div className="summary-grid">
            {chars.map((ch) => (
              <div className="summary-item" key={ch.label}>
                <span className="summary-item-ico">
                  <i
                    className={`fa-solid ${characteristicIcon(ch)}`}
                    style={ch.ok === false ? { color: 'var(--tx3)' } : undefined}
                  />
                </span>
                <div style={{ minWidth: 0 }}>
                  <div className="summary-item-label">{ch.label}</div>
                  <div className="summary-item-value">{ch.value}</div>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </PhaseStatusCard>
  );
}

/** Prefer an explicit icon; otherwise reflect a boolean ok/ko signal. */
function characteristicIcon(ch) {
  if (ch.icon) return ch.icon;
  if (ch.ok === true) return 'fa-circle-check';
  if (ch.ok === false) return 'fa-circle-minus';
  return 'fa-circle-info';
}
