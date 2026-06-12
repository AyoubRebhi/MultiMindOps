import ProviderBadge from '@/components/common/ProviderBadge';
import { formatCurrency } from '@/utils/formatters';

/**
 * InfrastructureSummaryCard — per-provider rollup (resource count, monthly
 * cost, share of total spend).
 *
 * Props:
 *  - breakdown: { provider, resources, monthlyCost, percent }
 */
export default function InfrastructureSummaryCard({ breakdown }) {
  if (!breakdown) return null;
  const { provider, resources, monthlyCost, percent } = breakdown;

  return (
    <div className="surface surface-hover h-100">
      <div className="d-flex align-items-center justify-content-between mb-3">
        <ProviderBadge provider={provider} />
        <span className="badge-pill badge-info">{percent}% of spend</span>
      </div>

      <div className="db-stat-val" style={{ fontSize: '1.6rem' }}>
        {formatCurrency(monthlyCost)}
        <span style={{ fontSize: '.8rem', color: 'var(--tx3)', fontWeight: 400 }}>
          /mo
        </span>
      </div>
      <div className="db-stat-lbl mb-3">Estimated monthly cost</div>

      <div className="progress-track mb-3" style={{ height: 6 }}>
        <div className="progress-fill" style={{ width: `${percent}%` }} />
      </div>

      <div
        className="d-flex align-items-center justify-content-between"
        style={{ fontSize: '.78rem', color: 'var(--tx3)' }}
      >
        <span>
          <i className="fa-solid fa-server me-1" />
          {resources} resources
        </span>
        <span>
          <i className="fa-solid fa-circle-check me-1" style={{ color: '#34d399' }} />
          Provisioned
        </span>
      </div>
    </div>
  );
}
