import { useMemo, useState } from 'react';
import StatusBadge from '@/components/common/StatusBadge';
import { formatDate } from '@/utils/formatters';

/**
 * ResourceInventoryTable — the deployed resources (Section 3 of the
 * Infrastructure Dashboard). Supports free-text search, a category filter and
 * sortable columns (name, type, status, region, created). All client-side over
 * the mock inventory.
 *
 * Props:
 *  - resources: [{ name, type, category, status, region, createdAt }]
 */
const COLUMNS = [
  { key: 'name', label: 'Resource Name' },
  { key: 'type', label: 'Type' },
  { key: 'status', label: 'Status' },
  { key: 'region', label: 'Region' },
  { key: 'createdAt', label: 'Created At' },
];

export default function ResourceInventoryTable({ resources = [] }) {
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState('all');
  const [sortKey, setSortKey] = useState('name');
  const [sortDir, setSortDir] = useState('asc');

  const categories = useMemo(
    () => ['all', ...Array.from(new Set(resources.map((r) => r.category)))],
    [resources],
  );

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = resources.filter((r) => {
      const matchesQ =
        !q ||
        r.name.toLowerCase().includes(q) ||
        r.type.toLowerCase().includes(q) ||
        r.region.toLowerCase().includes(q);
      const matchesCat = category === 'all' || r.category === category;
      return matchesQ && matchesCat;
    });
    const dir = sortDir === 'asc' ? 1 : -1;
    return [...filtered].sort((a, b) => {
      const av = String(a[sortKey] ?? '');
      const bv = String(b[sortKey] ?? '');
      return av.localeCompare(bv) * dir;
    });
  }, [resources, query, category, sortKey, sortDir]);

  const toggleSort = (key) => {
    if (key === sortKey) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir('asc');
    }
  };

  return (
    <div className="inv">
      <div className="inv-toolbar">
        <div className="inv-search">
          <i className="fa-solid fa-magnifying-glass" />
          <input
            type="text"
            placeholder="Search resources, types, regions…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          {query && (
            <button type="button" className="inv-search-clear" onClick={() => setQuery('')} aria-label="Clear search">
              <i className="fa-solid fa-xmark" />
            </button>
          )}
        </div>
        <div className="inv-filters">
          {categories.map((c) => (
            <button
              type="button"
              key={c}
              className={`inv-chip ${category === c ? 'is-active' : ''}`.trim()}
              onClick={() => setCategory(c)}
            >
              {c === 'all' ? 'All' : c}
            </button>
          ))}
        </div>
      </div>

      <div className="inv-table">
        <div className="inv-row inv-header">
          {COLUMNS.map((col) => (
            <button type="button" key={col.key} className="inv-th" onClick={() => toggleSort(col.key)}>
              {col.label}
              <i
                className={`fa-solid ms-1 ${
                  sortKey === col.key
                    ? sortDir === 'asc'
                      ? 'fa-arrow-up-short-wide'
                      : 'fa-arrow-down-wide-short'
                    : 'fa-sort'
                }`}
                style={{ opacity: sortKey === col.key ? 1 : 0.4 }}
              />
            </button>
          ))}
        </div>

        {rows.length === 0 ? (
          <div className="inv-empty">
            <i className="fa-solid fa-magnifying-glass me-2" />
            No resources match your filters.
          </div>
        ) : (
          rows.map((r) => (
            <div className="inv-row" key={r.name}>
              <span className="inv-td mono inv-name">{r.name}</span>
              <span className="inv-td"><span className="tag mono">{r.type}</span></span>
              <span className="inv-td"><StatusBadge status={r.status} /></span>
              <span className="inv-td mono">{r.region}</span>
              <span className="inv-td">{formatDate(r.createdAt)}</span>
            </div>
          ))
        )}
      </div>

      <div className="inv-foot">
        Showing {rows.length} of {resources.length} resources
      </div>
    </div>
  );
}
