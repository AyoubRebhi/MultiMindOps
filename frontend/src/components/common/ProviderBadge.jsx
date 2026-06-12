import { CLOUD_PROVIDERS } from '@/utils/constants';

/**
 * ProviderBadge — cloud provider chip (AWS / Azure / GCP) with brand icon.
 *
 * Props:
 *  - provider: "aws" | "azure" | "gcp"
 *  - showLabel: render the provider name (default true)
 */
export default function ProviderBadge({ provider, showLabel = true }) {
  const meta = CLOUD_PROVIDERS[provider] || {
    label: provider,
    icon: 'fa-cloud',
    color: 'var(--tx2)',
  };
  const isBrand = ['fa-aws', 'fa-microsoft', 'fa-google'].includes(meta.icon);

  return (
    <span className="tag" title={meta.label}>
      <i
        className={`${isBrand ? 'fa-brands' : 'fa-solid'} ${meta.icon}`}
        style={{ color: meta.color }}
      />
      {showLabel && meta.label}
    </span>
  );
}
