import { Link } from 'react-router-dom';
import ContentContainer from '@/components/layout/ContentContainer';

/** NotFound — 404 fallback for unmatched routes. */
export default function NotFound() {
  return (
    <ContentContainer>
      <div className="empty-state" style={{ padding: '80px 24px' }}>
        <div className="gt" style={{ fontSize: '3.5rem', fontWeight: 700 }}>
          404
        </div>
        <div style={{ fontWeight: 600, color: 'var(--tx2)', margin: '8px 0 6px' }}>
          Page not found
        </div>
        <div style={{ fontSize: '.9rem', maxWidth: 380, margin: '0 auto 20px' }}>
          The page you&apos;re looking for doesn&apos;t exist or has moved.
        </div>
        <Link to="/" className="bgrd btn px-4 py-2" style={{ fontSize: '.9rem' }}>
          <i className="fa-solid fa-house me-2" />
          Back to Dashboard
        </Link>
      </div>
    </ContentContainer>
  );
}
