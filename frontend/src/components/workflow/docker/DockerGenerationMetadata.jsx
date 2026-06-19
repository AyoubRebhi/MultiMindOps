/**
 * DockerGenerationMetadata — the "Generation Metadata" panel. Renders the build
 * shape the InfrastructureAgent detected, read straight from the backend
 * projection: detected runtime, base image, port, build strategy and container
 * type. Also surfaces the generation provenance (GPT-5-mini vs deterministic
 * fallback) so the engineer knows how the Dockerfile was produced.
 *
 * Props:
 *  - metadata  mapped Docker metadata (see mapDockerPhase)
 */
const MODE_META = {
  llm: { label: 'GPT-5-mini', variant: 'success', icon: 'fa-microchip' },
  llm_with_fallback: { label: 'GPT-5-mini · fallback', variant: 'warning', icon: 'fa-microchip' },
  deterministic: { label: 'Deterministic', variant: 'info', icon: 'fa-gears' },
  degraded: { label: 'Degraded fallback', variant: 'warning', icon: 'fa-triangle-exclamation' },
};

function Field({ icon, label, value, mono = false }) {
  return (
    <div className="surface" style={{ padding: '12px 14px' }}>
      <div className="d-flex align-items-center gap-2" style={{ fontSize: '.74rem', color: 'var(--tx3)', textTransform: 'uppercase', letterSpacing: '.04em' }}>
        <i className={`fa-solid ${icon}`} />
        {label}
      </div>
      <div
        style={{
          marginTop: 6,
          fontWeight: 600,
          fontSize: mono ? '.82rem' : '.9rem',
          fontFamily: mono ? 'var(--mono, monospace)' : 'inherit',
          wordBreak: 'break-word',
        }}
      >
        {value || <span style={{ color: 'var(--tx3)', fontWeight: 400 }}>—</span>}
      </div>
    </div>
  );
}

export default function DockerGenerationMetadata({ metadata = {} }) {
  const {
    detectedRuntime,
    baseImage,
    port,
    buildStrategy,
    containerType,
    generationMode = 'llm',
    fallbackUsed,
  } = metadata;

  const mode = MODE_META[generationMode] || MODE_META.llm;
  const strategyLabel = buildStrategy
    ? buildStrategy.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
    : null;

  return (
    <>
      <div className="d-flex align-items-center gap-2 mb-2 flex-wrap">
        <span className={`badge-pill badge-${mode.variant}`}>
          <i className={`fa-solid ${mode.icon} me-1`} />
          {mode.label}
        </span>
        {fallbackUsed && generationMode === 'llm' && (
          <span className="badge-pill badge-warning">
            <i className="fa-solid fa-shuffle me-1" />
            Partial fallback
          </span>
        )}
      </div>
      <div className="row g-2">
        <div className="col-6 col-lg-4"><Field icon="fa-microchip" label="Detected Runtime" value={detectedRuntime} /></div>
        <div className="col-6 col-lg-4"><Field icon="fa-layer-group" label="Base Image" value={baseImage} mono /></div>
        <div className="col-6 col-lg-4"><Field icon="fa-plug" label="Port" value={port} mono /></div>
        <div className="col-6 col-lg-4"><Field icon="fa-diagram-project" label="Build Strategy" value={strategyLabel} /></div>
        <div className="col-6 col-lg-4"><Field icon="fa-box" label="Container Type" value={containerType} /></div>
      </div>
    </>
  );
}
