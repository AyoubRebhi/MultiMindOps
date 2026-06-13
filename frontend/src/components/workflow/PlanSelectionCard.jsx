import { formatCurrency } from '@/utils/formatters';

/**
 * PlanSelectionCard — one selectable architecture plan (Low Cost / Balanced /
 * High Performance). Shows cost, scalability & availability ratings, the AWS
 * services involved and the trade-offs. Only one plan is selected at a time
 * (selection is owned by the parent).
 *
 * Props:
 *  - plan: see mockPlans shape
 *  - selected: boolean
 *  - onSelect(): select handler
 */
function Rating({ icon, label, value, level }) {
  return (
    <div className="plan-rating">
      <span className="plan-rating-ico"><i className={`fa-solid ${icon}`} /></span>
      <div className="plan-rating-body">
        <div className="plan-rating-label">{label}</div>
        <div className="plan-rating-value">{value}</div>
      </div>
      <span className="plan-level" aria-label={`level ${level} of 3`}>
        {[1, 2, 3].map((n) => (
          <span key={n} className={`plan-level-dot ${n <= level ? 'on' : ''}`.trim()} />
        ))}
      </span>
    </div>
  );
}

export default function PlanSelectionCard({ plan, selected = false, onSelect }) {
  if (!plan) return null;
  const {
    name, tagline, recommended, monthlyCost,
    scalability, availability, awsServices = [], tradeoffs = {},
  } = plan;

  return (
    <div
      className={`surface plan-card h-100 ${selected ? 'is-selected' : ''} ${
        recommended ? 'is-recommended' : ''
      }`.trim()}
      role="button"
      tabIndex={0}
      onClick={() => onSelect?.()}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
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
          <h3 className="plan-name">{name}</h3>
          <p className="plan-tagline">{tagline}</p>
        </div>
        <span className={`plan-radio ${selected ? 'on' : ''}`.trim()}>
          {selected && <i className="fa-solid fa-check" />}
        </span>
      </div>

      <div className="plan-cost">
        <span className="plan-cost-amount gt">{formatCurrency(monthlyCost)}</span>
        <span className="plan-cost-unit">/ month est.</span>
      </div>

      <div className="plan-ratings">
        <Rating icon="fa-arrow-up-right-dots" label="Scalability" value={scalability?.label} level={scalability?.level} />
        <Rating icon="fa-shield-halved" label="Availability" value={availability?.label} level={availability?.level} />
      </div>

      <div className="plan-section">
        <div className="plan-section-label">AWS Services</div>
        <div className="d-flex flex-wrap gap-2">
          {awsServices.map((s) => (
            <span className="tag" key={s.name}>
              <i className={`fa-solid ${s.icon}`} style={{ color: '#ff9900' }} />
              {s.name}
            </span>
          ))}
        </div>
      </div>

      <div className="plan-section">
        <div className="plan-section-label">Trade-offs</div>
        <ul className="plan-tradeoffs">
          {(tradeoffs.pros || []).map((p, i) => (
            <li key={`p${i}`} className="is-pro">
              <i className="fa-solid fa-check" />{p}
            </li>
          ))}
          {(tradeoffs.cons || []).map((c, i) => (
            <li key={`c${i}`} className="is-con">
              <i className="fa-solid fa-minus" />{c}
            </li>
          ))}
        </ul>
      </div>

      <button
        type="button"
        className={`btn w-100 plan-select-btn ${selected ? 'bgrd' : 'boc'}`}
        onClick={(e) => { e.stopPropagation(); onSelect?.(); }}
      >
        {selected ? (
          <><i className="fa-solid fa-circle-check me-2" />Selected</>
        ) : (
          <>Select {name}</>
        )}
      </button>
    </div>
  );
}
