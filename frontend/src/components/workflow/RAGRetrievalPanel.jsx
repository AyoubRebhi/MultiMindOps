/**
 * RAGRetrievalPanel — visualizes the Knowledge Base Retrieval step (Section 4):
 * the retrieved workflow examples with similarity scores, the lower-level
 * retrieved chunks, and the knowledge sources they were drawn from. Purely
 * presentational.
 *
 * Props:
 *  - data: see mockRagResults (query, collection, embeddingModel, vectorDims,
 *    retrievalMs, topScore, chunksRetrieved, examples[], chunks[], sources[])
 */
function scoreTone(score) {
  if (score >= 0.9) return '#34d399';
  if (score >= 0.8) return '#60a5fa';
  return '#fbbf24';
}

export default function RAGRetrievalPanel({ data }) {
  if (!data) return null;
  const {
    query,
    collection,
    embeddingModel,
    vectorDims,
    retrievalMs,
    topScore = 0,
    chunksRetrieved = 0,
    examples = [],
    chunks = [],
    sources = [],
  } = data;

  return (
    <div className="rag-panel">
      {/* Query + retrieval stats */}
      <div className="rag-query">
        <span className="rag-query-ico">
          <i className="fa-solid fa-magnifying-glass" />
        </span>
        <div style={{ minWidth: 0 }}>
          <div className="reasoning-label mb-0">Semantic Query</div>
          <p className="rag-query-text mono">{query}</p>
        </div>
      </div>

      <div className="rag-stats">
        <RagStat icon="fa-database" label="Collection" value={collection} mono />
        <RagStat icon="fa-vector-square" label="Embedding" value={embeddingModel} mono />
        <RagStat icon="fa-ruler-combined" label="Vector Dims" value={vectorDims} />
        <RagStat icon="fa-bullseye" label="Top Score" value={topScore.toFixed(2)} />
        <RagStat icon="fa-layer-group" label="Chunks" value={chunksRetrieved} />
        <RagStat icon="fa-stopwatch" label="Latency" value={`${retrievalMs} ms`} />
      </div>

      {/* Retrieved workflow examples */}
      <div className="rag-section-label">
        <i className="fa-solid fa-star me-2" style={{ color: '#fbbf24' }} />
        Retrieved Workflow Examples
      </div>
      <div className="row g-3">
        {examples.map((ex) => {
          const pct = Math.round(ex.similarity * 100);
          const tone = scoreTone(ex.similarity);
          return (
            <div className="col-lg-4" key={ex.id}>
              <div className="rag-example">
                <div className="rag-example-head">
                  <span className="rag-rank">#{ex.rank}</span>
                  <span className="rag-sim" style={{ color: tone }}>
                    {pct}% match
                  </span>
                </div>
                <div className="rag-example-title">{ex.title}</div>
                <a
                  className="rag-example-source mono"
                  href={`https://github.com/${ex.source}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  <i className="fa-solid fa-link me-1" />{ex.source}
                </a>
                <div className="rag-sim-bar">
                  <span style={{ width: `${pct}%`, background: tone }} />
                </div>
                <pre className="rag-snippet mono">{ex.snippet}</pre>
                <div className="rag-tags">
                  {ex.tags.map((t) => (
                    <span className="tag" key={t}>{t}</span>
                  ))}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <div className="row g-3 mt-1">
        {/* Retrieved chunks */}
        <div className="col-lg-7">
          <div className="rag-section-label">
            <i className="fa-solid fa-puzzle-piece me-2" style={{ color: '#a78bfa' }} />
            Retrieved Chunks
          </div>
          <div className="rag-chunks">
            {chunks.map((c) => {
              const pct = Math.round(c.score * 100);
              return (
                <div className="rag-chunk" key={c.id}>
                  <span className="rag-chunk-id mono">{c.id}</span>
                  <span className="rag-chunk-src mono">{c.source}</span>
                  <span className="rag-chunk-tokens">{c.tokens} tok</span>
                  <span className="rag-chunk-score" style={{ color: scoreTone(c.score) }}>
                    {pct}%
                  </span>
                </div>
              );
            })}
          </div>
        </div>

        {/* Knowledge sources */}
        <div className="col-lg-5">
          <div className="rag-section-label">
            <i className="fa-solid fa-book-open me-2" style={{ color: '#60a5fa' }} />
            Knowledge Sources
          </div>
          <div className="rag-sources">
            {sources.map((s) => (
              <div className="rag-source" key={s.name}>
                <span className="rag-source-ico">
                  <i className={`${s.brand ? 'fa-brands' : 'fa-solid'} ${s.icon}`} />
                </span>
                <span className="rag-source-name">{s.name}</span>
                <span className="rag-source-count">{s.documents} docs</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function RagStat({ icon, label, value, mono = false }) {
  return (
    <div className="rag-stat">
      <span className="rag-stat-ico"><i className={`fa-solid ${icon}`} /></span>
      <div style={{ minWidth: 0 }}>
        <div className="rag-stat-label">{label}</div>
        <div className={`rag-stat-value ${mono ? 'mono' : ''}`.trim()}>{value}</div>
      </div>
    </div>
  );
}
