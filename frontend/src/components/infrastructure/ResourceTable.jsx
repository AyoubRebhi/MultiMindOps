import StatusBadge from '@/components/common/StatusBadge';
import ProviderBadge from '@/components/common/ProviderBadge';
import EmptyState from '@/components/common/EmptyState';
import { formatCurrency } from '@/utils/formatters';

/**
 * ResourceTable — provisioned infrastructure resources (uses the ported
 * .db-table styling). Horizontally scrollable on small screens.
 *
 * Props:
 *  - resources: [{ id, name, type, provider, region, project, status, monthlyCost }]
 */
export default function ResourceTable({ resources = [] }) {
  if (!resources.length) {
    return (
      <EmptyState
        icon="fa-server"
        title="No resources provisioned"
        message="Run a workflow through to the Terraform phase to provision infrastructure."
      />
    );
  }

  return (
    <div style={{ overflowX: 'auto' }}>
      <table className="db-table" style={{ width: '100%', minWidth: 720 }}>
        <thead>
          <tr>
            <th>Resource</th>
            <th>Type</th>
            <th>Provider</th>
            <th>Region</th>
            <th>Project</th>
            <th>Status</th>
            <th style={{ textAlign: 'right' }}>Cost / mo</th>
          </tr>
        </thead>
        <tbody>
          {resources.map((r) => (
            <tr key={r.id}>
              <td className="mono" style={{ fontWeight: 600 }}>
                {r.name}
              </td>
              <td>{r.type}</td>
              <td>
                <ProviderBadge provider={r.provider} />
              </td>
              <td className="mono" style={{ fontSize: '.78rem' }}>
                {r.region}
              </td>
              <td>{r.project}</td>
              <td>
                <StatusBadge status={r.status} />
              </td>
              <td style={{ textAlign: 'right' }}>{formatCurrency(r.monthlyCost)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
