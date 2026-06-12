import ContentContainer from '@/components/layout/ContentContainer';
import PageHeader from '@/components/layout/PageHeader';
import StatsCard from '@/components/common/StatsCard';
import Card from '@/components/common/Card';
import LoadingSpinner from '@/components/common/LoadingSpinner';
import InfrastructureSummaryCard from '@/components/infrastructure/InfrastructureSummaryCard';
import ResourceTable from '@/components/infrastructure/ResourceTable';
import { useAsync } from '@/hooks/useAsync';
import { terraformApi } from '@/services/api/terraformApi';
import { formatCurrency } from '@/utils/formatters';

/**
 * Infrastructure — provisioned cloud footprint: spend, per-provider rollups,
 * a cost breakdown and the live resource inventory.
 */
export default function Infrastructure() {
  const { data, loading } = useAsync(
    () => terraformApi.getInfrastructureSummary(),
    []
  );

  if (loading && !data) {
    return (
      <ContentContainer>
        <LoadingSpinner center label="Loading infrastructure…" />
      </ContentContainer>
    );
  }

  const { totals, providerBreakdown, costBreakdown, resources } = data;
  const maxCost = Math.max(...costBreakdown.map((c) => c.amount));

  return (
    <ContentContainer>
      <PageHeader
        title="Infrastructure"
        subtitle="A unified view of everything provisioned by Terraform across your cloud accounts."
        breadcrumbs={[{ label: 'Infrastructure' }]}
        actions={
          <button className="boc btn px-3 py-2" style={{ fontSize: '.85rem' }}>
            <i className="fa-solid fa-arrows-rotate me-2" />
            Refresh State
          </button>
        }
      />

      {/* Totals */}
      <div className="row g-3 mb-4">
        <div className="col-6 col-xl-3">
          <StatsCard label="Monthly Spend" value={formatCurrency(totals.monthlyCost)} icon="fa-coins" accent="#fbbf24" gradientValue />
        </div>
        <div className="col-6 col-xl-3">
          <StatsCard label="Resources" value={totals.resources} icon="fa-server" accent="#a78bfa" />
        </div>
        <div className="col-6 col-xl-3">
          <StatsCard label="Regions" value={totals.regions} icon="fa-earth-americas" accent="#60a5fa" />
        </div>
        <div className="col-6 col-xl-3">
          <StatsCard label="Config Drift" value={totals.drift} icon="fa-triangle-exclamation" accent="#f87171" trend="down" delta="needs sync" />
        </div>
      </div>

      {/* Provider rollups */}
      <h2 className="card-title mb-3">By Provider</h2>
      <div className="row g-3 mb-4">
        {providerBreakdown.map((b) => (
          <div className="col-md-4" key={b.provider}>
            <InfrastructureSummaryCard breakdown={b} />
          </div>
        ))}
      </div>

      <div className="row g-3 mb-4">
        {/* Cost breakdown */}
        <div className="col-lg-5">
          <Card title="Cost Breakdown" icon="fa-chart-pie">
            <div className="d-flex flex-column gap-3">
              {costBreakdown.map((c) => (
                <div key={c.category}>
                  <div className="d-flex align-items-center justify-content-between mb-1">
                    <span style={{ fontSize: '.82rem', color: 'var(--tx2)' }}>
                      <i className={`fa-solid ${c.icon} me-2`} style={{ color: c.color }} />
                      {c.category}
                    </span>
                    <span style={{ fontSize: '.82rem', fontWeight: 600 }}>
                      {formatCurrency(c.amount)}
                    </span>
                  </div>
                  <div className="progress-track" style={{ height: 6 }}>
                    <div
                      className="progress-fill"
                      style={{
                        width: `${(c.amount / maxCost) * 100}%`,
                        background: c.color,
                      }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </Card>
        </div>

        {/* Resource inventory */}
        <div className="col-lg-7">
          <Card title="Resource Inventory" icon="fa-server">
            <ResourceTable resources={resources} />
          </Card>
        </div>
      </div>
    </ContentContainer>
  );
}
