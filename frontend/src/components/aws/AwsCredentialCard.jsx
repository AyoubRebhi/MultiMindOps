import { useState } from 'react';
import StatusBadge from '@/components/common/StatusBadge';
import { CLOUD_PROVIDERS } from '@/utils/constants';
import { formatDate, timeAgo } from '@/utils/formatters';

/** Build a masked representation — only ever reveals the last 4 chars. */
function mask(last4, revealed) {
  if (!last4) return '—';
  return revealed ? '•'.repeat(12) + last4 : '•'.repeat(16);
}

/**
 * AwsCredentialCard — read view of the stored AWS credentials. Secrets are
 * always masked; the show/hide toggle only reveals the last 4 characters.
 *
 * Props:
 *  - credentials: see mockAwsCredentials shape
 *  - onTest: () => void   (Test Connection)
 *  - testing: boolean
 *  - testResult: { status, message } | null
 */
export default function AwsCredentialCard({ credentials, onTest, testing, testResult }) {
  const [revealed, setRevealed] = useState(false);
  if (!credentials) return null;

  const {
    region,
    accountId,
    accessKeyIdLast4,
    secretAccessKeyLast4,
    sessionTokenLast4,
    hasSessionToken,
    status,
    lastUpdated,
    updatedBy,
  } = credentials;
  const aws = CLOUD_PROVIDERS.aws;

  return (
    <div className="surface">
      <div className="d-flex align-items-center justify-content-between mb-3">
        <div className="d-flex align-items-center gap-2">
          <div className="icon-tile" style={{ background: 'rgba(255,153,0,.12)', color: aws.color }}>
            <i className="fa-brands fa-aws" />
          </div>
          <div>
            <div style={{ fontWeight: 600 }}>AWS Credentials</div>
            <div style={{ fontSize: '.74rem', color: 'var(--tx3)' }}>
              Account {accountId}
            </div>
          </div>
        </div>
        <StatusBadge status={status} />
      </div>

      <div className="d-flex justify-content-end mb-2">
        <button
          className="key-reveal"
          style={{ fontSize: '.76rem' }}
          onClick={() => setRevealed((r) => !r)}
        >
          <i className={`fa-regular ${revealed ? 'fa-eye-slash' : 'fa-eye'} me-1`} />
          {revealed ? 'Hide' : 'Show'} last 4
        </button>
      </div>

      <div className="d-flex flex-column gap-2">
        <Field label="AWS Region">
          <span className="mono">{region}</span>
        </Field>
        <Field label="Access Key ID">
          <span className="mono">{mask(accessKeyIdLast4, revealed)}</span>
        </Field>
        <Field label="Secret Access Key">
          <span className="mono">{mask(secretAccessKeyLast4, revealed)}</span>
        </Field>
        <Field label="Session Token">
          <span className="mono">
            {hasSessionToken ? mask(sessionTokenLast4, revealed) : 'Not set'}
          </span>
        </Field>
      </div>

      <div
        className="d-flex align-items-center justify-content-between mt-3 pt-3 flex-wrap gap-2"
        style={{ borderTop: '1px solid var(--bd)', fontSize: '.76rem', color: 'var(--tx3)' }}
      >
        <span>
          <i className="fa-regular fa-clock me-1" />
          Updated {timeAgo(lastUpdated)} by {updatedBy} · {formatDate(lastUpdated)}
        </span>
        {onTest && (
          <button
            className="boc btn px-3 py-1"
            style={{ fontSize: '.78rem', borderRadius: 10 }}
            onClick={onTest}
            disabled={testing}
          >
            {testing ? (
              <>
                <span className="spinner me-2" style={{ width: 13, height: 13, borderWidth: 2 }} />
                Testing…
              </>
            ) : (
              <>
                <i className="fa-solid fa-plug-circle-bolt me-1" />
                Test Connection
              </>
            )}
          </button>
        )}
      </div>

      {testResult && (
        <div
          className="mt-3 d-flex align-items-center gap-2"
          style={{
            fontSize: '.8rem',
            padding: '10px 12px',
            borderRadius: 10,
            background:
              testResult.status === 'connected'
                ? 'rgba(52,211,153,.1)'
                : 'rgba(248,113,113,.1)',
            color: testResult.status === 'connected' ? '#34d399' : '#f87171',
          }}
        >
          <i
            className={`fa-solid ${
              testResult.status === 'connected' ? 'fa-circle-check' : 'fa-circle-xmark'
            }`}
          />
          {testResult.message}
        </div>
      )}
    </div>
  );
}

function Field({ label, children }) {
  return (
    <div className="masked-field">
      <div className="d-flex flex-column">
        <span style={{ fontSize: '.68rem', color: 'var(--tx3)', letterSpacing: 0 }}>
          {label}
        </span>
        {children}
      </div>
    </div>
  );
}
