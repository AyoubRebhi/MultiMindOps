import DockerfileDiffView from './DockerfileDiffView';

/**
 * DockerFixApprovalPanel — the human-in-control gate for the corrector's
 * suggested fix. The corrector NEVER auto-applies: it stores a patched
 * Dockerfile preview (`ai_patched_content`) which this panel shows as a
 * Current → Suggested diff. The engineer then EXPLICITLY chooses to
 *   • Apply Suggested Fix  → POST /tasks/:id/artifacts/apply-ai-patch
 *   • Edit Manually        → open the editor and PATCH their own version
 * Either path persists through the backend and the artifact is reloaded.
 *
 * Props:
 *  - current         the live (editable) Dockerfile content
 *  - suggested       the corrector's proposed Dockerfile (ai_patched_content)
 *  - applying        true while Apply is in flight
 *  - onApplyFix()    promote the suggested patch into current content
 *  - onEditManually()open the editor in edit mode for a manual fix
 */
export default function DockerFixApprovalPanel({
  current = '',
  suggested = '',
  applying = false,
  onApplyFix,
  onEditManually,
}) {
  if (!suggested) return null;
  const hasDiff = suggested.trim() !== current.trim();

  return (
    <div className="d-flex flex-column gap-3">
      <div className="surface" style={{ borderLeft: '3px solid #60a5fa' }}>
        <div className="d-flex align-items-center gap-2 flex-wrap mb-2">
          <i className="fa-solid fa-code-pull-request" style={{ color: '#60a5fa' }} />
          <span style={{ fontWeight: 600 }}>Suggested fix</span>
          <span className="badge-pill badge-info" style={{ fontSize: '.7rem' }}>
            Awaiting your approval
          </span>
        </div>
        <p style={{ fontSize: '.84rem', color: 'var(--tx2)', margin: 0 }}>
          The Docker corrector prepared a patched Dockerfile for this build failure.
          Nothing is applied automatically — review the change below, then either
          apply it as-is or edit it yourself. Your choice is persisted through the
          backend and used for the next build.
        </p>
        <div className="d-flex gap-2 flex-wrap mt-3">
          <button
            type="button"
            className="bgrd btn px-3 py-2"
            style={{ fontSize: '.82rem' }}
            disabled={!hasDiff || applying}
            onClick={() => onApplyFix?.()}
          >
            {applying ? (
              <><span className="spinner me-2" />Applying…</>
            ) : (
              <><i className="fa-solid fa-check me-2" />Apply Suggested Fix</>
            )}
          </button>
          <button
            type="button"
            className="boc btn px-3 py-2"
            style={{ fontSize: '.82rem' }}
            disabled={applying}
            onClick={() => onEditManually?.()}
          >
            <i className="fa-solid fa-pen me-2" />Edit Manually
          </button>
        </div>
      </div>

      {hasDiff ? (
        <DockerfileDiffView
          original={current}
          corrected={suggested}
          leftLabel="Current Dockerfile"
          rightLabel="Suggested Dockerfile"
        />
      ) : (
        <div className="surface d-flex align-items-center gap-2" style={{ fontSize: '.82rem', color: 'var(--tx2)' }}>
          <i className="fa-solid fa-circle-check" style={{ color: '#34d399' }} />
          The suggested fix already matches the current Dockerfile — nothing to apply.
        </div>
      )}
    </div>
  );
}
