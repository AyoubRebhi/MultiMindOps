import { formatCurrency } from '@/utils/formatters';
import {
  planIcon,
  scalabilityLevel,
  availabilityLevel,
  complexityMeta,
  costProfileLabel,
  patternLabel,
} from './architecturePlanHelpers';

/**
 * ArchitecturePlanCard — ONE AI-generated architecture plan, rendered straight
 * from the backend architecture-decision payload (no mock data). Shows the
 * architecture type, AWS services, cost, scalability/availability ratings,
 * operational complexity and the trade-offs so an engineer can review a single
 * option in depth, then select it.
 *
 * Selection is owned by the parent (the backend persists it). While a request
 * is in flight the button shows a spinner and every card's button is disabled
 * to prevent duplicate selection requests.
 *
 * Props:
 *  - plan        mapped plan (see mapArchitecturePlan)
 *  - selected    this plan is the persisted selection
 *  - selecting   THIS plan's selection request is in flight
 *  - disabled    a selection request (any plan) is in flight
 *  - onSelect()  select handler
 */
function Rating({ icon, label, value, level }) {
  return (
    <div className="plan-rating">
      <span className="plan-rating-ico"><i className={`fa-solid ${icon}`} /></span>
      <div className="plan-rating-body">
        <div className="plan-rating-label">{label}</div>
        <div className="plan-rating-value">{value || '—'}</div>
      </div>
      <span className="plan-level" aria-label={`level ${level} of 3`}>
        {[1, 2, 3].map((n) => (
          <span key={n} className={`plan-level-dot ${n <= level ? 'on' : ''}`.trim()} />
        ))}
      </span>
    </div>
  );
}

function Attr({ label, value }) {
  if (!value) return null;
  return (
    <div className="d-flex justify-content-between align-items-center gap-3" style={{ fontSize: '.82rem' }}>
      <span style={{ color: 'var(--tx3)' }}>{label}</span>
      <span style={{ fontWeight: 600, textAlign: 'right' }}>{value}</span>
    </div>
  );
}

export default function ArchitecturePlanCard({
  plan,
  selected = false,
  selecting = false,
  disabled = false,
  onSelect,
}) {
  if (!plan) return null;
  const {
    id, title, description, recommended,
    monthlyCost, yearlyCost, costProfile,
    scalabilityTier, availabilityLevel: availability, complexity,
    awsServices = [], tradeoffs = [], architecture = {},
  } = plan;

  const cx = complexityMeta(complexity);
  const profile = costProfileLabel(costProfile);
  const clickable = !disabled && !selected;

  return (
    <div
      className={`surface plan-card h-100 ${selected ? 'is-selected' : ''} ${
        recommended ? 'is-recommended' : ''
      }`.trim()}
      role="button"
      tabIndex={0}
      aria-pressed={selected}
      onClick={() => clickable && onSelect?.()}
      onKeyDown={(e) => {
        if (clickable && (e.key === 'Enter' || e.key === ' ')) {
          e.preventDefault();
          onSelect?.();
        }
      }}
    >
      {recommended && (
        <span className="plan-ribbon">
          <i className="fa-solid fa-star me-1" />Recommended
        </span>
      )}

      <div className="plan-head">
        <div style={{ minWidth: 0 }}>
          <h3 className="plan-name">
            <i className={`fa-solid ${planIcon(id)} me-2`} style={{ opacity: 0.7 }} />
            {title}
          </h3>
          <p className="plan-tagline">{description}</p>
        </div>
        <span className={`plan-radio ${selected ? 'on' : ''}`.trim()}>
          {selected && <i className="fa-solid fa-check" />}
        </span>
      </div>

      {selected && (
        <span
          className="badge-pill badge-success"
          style={{ alignSelf: 'flex-start', marginBottom: 4 }}
        >
          <i className="fa-solid fa-circle-check me-1" />Selected plan
        </span>
      )}

      <div className="plan-cost">
        <span className="plan-cost-amount gt">{formatCurrency(monthlyCost)}</span>
        <span className="plan-cost-unit">/ month est.</span>
      </div>
      {(yearlyCost != null || profile) && (
        <div style={{ fontSize: '.74rem', color: 'var(--tx3)', marginTop: -6, marginBottom: 4 }}>
          {yearlyCost != null && <>~{formatCurrency(yearlyCost)} / year</>}
          {yearlyCost != null && profile && ' · '}
          {profile && <>{profile}</>}
        </div>
      )}

      <div className="plan-ratings">
        <Rating
          icon="fa-arrow-up-right-dots"
          label="Scalability"
          value={scalabilityTier}
          level={scalabilityLevel(scalabilityTier)}
        />
        <Rating
          icon="fa-shield-halved"
          label="Availability"
          value={availability}
          level={availabilityLevel(availability)}
        />
      </div>

      <div className="plan-section">
        <div className="plan-section-label">Architecture</div>
        <div className="d-flex flex-column gap-1">
          <Attr label="Pattern" value={patternLabel(architecture.style)} />
          <Attr label="Compute" value={architecture.computeType} />
          <Attr label="Runtime / size" value={architecture.runtime} />
          <Attr label="Database" value={architecture.databaseEngine} />
          <Attr label="Deployment" value={architecture.deployment} />
          <div className="d-flex justify-content-between align-items-center gap-3" style={{ fontSize: '.82rem' }}>
            <span style={{ color: 'var(--tx3)' }}>Operational complexity</span>
            <span className={`badge-pill badge-${cx.variant}`}>{cx.label}</span>
          </div>
        </div>
      </div>

      <div className="plan-section">
        <div className="plan-section-label">AWS Services</div>
        {awsServices.length ? (
          <div className="d-flex flex-wrap gap-2">
            {awsServices.map((s) => (
              <span className="tag" key={s}>
                <i className="fa-solid fa-cube" style={{ color: '#ff9900' }} />
                {s}
              </span>
            ))}
          </div>
        ) : (
          <span className="text-muted-3" style={{ fontSize: '.8rem' }}>Not specified</span>
        )}
      </div>

      <div className="plan-section">
        <div className="plan-section-label">Trade-offs</div>
        {tradeoffs.length ? (
          <ul className="plan-tradeoffs">
            {tradeoffs.map((t, i) => (
              <li key={i}>
                <i className="fa-solid fa-circle-info" style={{ color: 'var(--tx3)' }} />
                {t}
              </li>
            ))}
          </ul>
        ) : (
          <span className="text-muted-3" style={{ fontSize: '.8rem' }}>None listed</span>
        )}
      </div>

      <button
        type="button"
        className={`btn w-100 plan-select-btn ${selected ? 'bgrd' : 'boc'}`}
        disabled={disabled || selected}
        onClick={(e) => {
          e.stopPropagation();
          if (clickable) onSelect?.();
        }}
      >
        {selected ? (
          <><i className="fa-solid fa-circle-check me-2" />Selected</>
        ) : selecting ? (
          <><span className="spinner me-2" />Selecting…</>
        ) : (
          <>Select {title}</>
        )}
      </button>
    </div>
  );
}
