import ContentContainer from '@/components/layout/ContentContainer';
import PageHeader from '@/components/layout/PageHeader';
import ArchitecturePlanCard from '@/components/architecture/ArchitecturePlanCard';
import EmptyState from '@/components/common/EmptyState';
import LoadingSpinner from '@/components/common/LoadingSpinner';
import { useAsync } from '@/hooks/useAsync';
import { architectureApi } from '@/services/api/architectureApi';

/**
 * Architecture — all AI-proposed architecture plans awaiting or past approval.
 */
export default function Architecture() {
  const { data: plans, loading } = useAsync(() => architectureApi.list(), [], {
    initialData: [],
  });

  return (
    <ContentContainer>
      <PageHeader
        title="Architecture Plans"
        subtitle="Candidate cloud architectures proposed by the AI architecture agent, with cost-aware option comparisons."
        breadcrumbs={[{ label: 'Architecture' }]}
      />

      {loading && !plans?.length ? (
        <LoadingSpinner center label="Loading plans…" />
      ) : plans.length === 0 ? (
        <EmptyState icon="fa-sitemap" title="No architecture plans yet" />
      ) : (
        <div className="row g-3">
          {plans.map((plan) => (
            <div className="col-lg-6" key={plan.id}>
              <ArchitecturePlanCard plan={plan} />
            </div>
          ))}
        </div>
      )}
    </ContentContainer>
  );
}
