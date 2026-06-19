import { formatCurrency } from '@/utils/formatters';
import { planIcon, complexityMeta, patternLabel } from './architecturePlanHelpers';

/**
 * PlanComparisonTable — side-by-side comparison of the AI-generated plans so an
 * engineer can read the differences at a glance (Phase 4). Every value comes
 * straight from the backend; nothing is hidden. Rows whose values differ across
 * plans are flagged so the trade-off is obvious.
 *
 * Props:
 *  - plans          mapped plans (see mapArchitecturePlan)
 *  - selectedId     persisted selection (column highlight)
 *  - recommendedId  recommended plan id (column marker)
 */
const ROWS = [
  { key: 'pattern', label: 'Architecture pattern', get: (p) => patternLabel(p.architecture?.style) },
  { key: 'deployment', label: 'Deployment model', get: (p) => p.architecture?.deployment || '—' },
  {
    key: 'runtime',
    label: 'Runtime / compute',
    get: (p) =>
      [p.architecture?.computeType, p.architecture?.runtime].filter(Boolean).join(' · ') || '—',
  },
  { key: 'services', label: 'AWS services', get: (p) => `${(p.awsServices || []).length} services` },
  {
    key: 'cost',
    label: 'Cost estimate (monthly)',
    get: (p) => (p.monthlyCost != null ? formatCurrency(p.monthlyCost) : '—'),
  },
  { key: 'scalability', label: 'Scalability level', get: (p) => p.scalabilityTier || '—' },
  { key: 'availability', label: 'Availability level', get: (p) => p.availabilityLevel || '—' },
  {
    key: 'complexity',
    label: 'Operational complexity',
    get: (p) => complexityMeta(p.complexity).label,
  },
];

export default function PlanComparisonTable({ plans = [], selectedId, recommendedId }) {
  if (!plans.length) return null;

  return (
    <div className="surface" style={{ overflowX: 'auto' }}>
      <table className="cmp-table" style={{ width: '100%', borderCollapse: 'collapse', minWidth: 520 }}>
        <thead>
          <tr>
            <th
              style={{
                textAlign: 'left',
                padding: '10px 12px',
                fontSize: '.72rem',
                textTransform: 'uppercase',
                letterSpacing: '.04em',
                color: 'var(--tx3)',
              }}
            >
              Attribute
            </th>
            {plans.map((p) => (
              <th
                key={p.id}
                style={{
                  textAlign: 'left',
                  padding: '10px 12px',
                  borderBottom: '1px solid var(--bd)',
                  background: p.id === selectedId ? 'var(--ac-soft, rgba(96,165,250,.08))' : 'transparent',
                }}
              >
                <div className="d-flex align-items-center gap-2" style={{ fontSize: '.86rem', fontWeight: 700 }}>
                  <i className={`fa-solid ${planIcon(p.id)}`} style={{ opacity: 0.7 }} />
                  {p.title}
                </div>
                <div className="d-flex gap-2 mt-1 flex-wrap">
                  {p.id === recommendedId && (
                    <span className="badge-pill badge-info" style={{ fontSize: '.62rem' }}>
                      <i className="fa-solid fa-star me-1" />Recommended
                    </span>
                  )}
                  {p.id === selectedId && (
                    <span className="badge-pill badge-success" style={{ fontSize: '.62rem' }}>
                      <i className="fa-solid fa-circle-check me-1" />Selected
                    </span>
                  )}
                </div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {ROWS.map((row) => {
            const values = plans.map((p) => row.get(p));
            const differs = new Set(values).size > 1;
            return (
              <tr key={row.key}>
                <td
                  style={{
                    padding: '9px 12px',
                    fontSize: '.8rem',
                    color: 'var(--tx2)',
                    borderTop: '1px solid var(--bd)',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {row.label}
                  {differs && (
                    <i
                      className="fa-solid fa-code-compare ms-2"
                      title="Differs across plans"
                      style={{ color: '#fbbf24', fontSize: '.7rem' }}
                    />
                  )}
                </td>
                {plans.map((p, i) => (
                  <td
                    key={p.id}
                    style={{
                      padding: '9px 12px',
                      fontSize: '.82rem',
                      fontWeight: differs ? 600 : 400,
                      borderTop: '1px solid var(--bd)',
                      background: p.id === selectedId ? 'var(--ac-soft, rgba(96,165,250,.06))' : 'transparent',
                    }}
                  >
                    {values[i]}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
