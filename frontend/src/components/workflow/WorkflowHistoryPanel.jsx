import StatusBadge from '@/components/common/StatusBadge';
import { formatDate, timeAgo } from '@/utils/formatters';

/**
 * WorkflowHistoryPanel — previous workflow executions (Section 6 of the
 * Infrastructure Dashboard). Columns: Execution ID, Date, Status, Duration,
 * Triggered By. The run the user just completed is flagged "current".
 *
 * Props:
 *  - executions: [{ id, date, status, duration, triggeredBy, current }]
 */
export default function WorkflowHistoryPanel({ executions = [] }) {
  return (
    <div className="hist">
      <div className="hist-row hist-header">
        <span>Execution ID</span>
        <span>Date</span>
        <span>Status</span>
        <span>Duration</span>
        <span>Triggered By</span>
      </div>
      {executions.map((e) => (
        <div className={`hist-row ${e.current ? 'is-current' : ''}`.trim()} key={e.id}>
          <span className="hist-id mono">
            <i className={`fa-solid ${e.current ? 'fa-circle-dot' : 'fa-clock-rotate-left'} me-2`} style={{ color: e.current ? '#34d399' : 'var(--tx3)' }} />
            {e.id}
            {e.current && <span className="tag ms-2">latest</span>}
          </span>
          <span className="hist-date">
            {formatDate(e.date)}
            <span className="hist-ago">{timeAgo(e.date)}</span>
          </span>
          <span><StatusBadge status={e.status} /></span>
          <span className="mono">{e.duration}</span>
          <span className="hist-by">{e.triggeredBy}</span>
        </div>
      ))}
    </div>
  );
}
