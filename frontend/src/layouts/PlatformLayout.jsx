import { useEffect, useState } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import Sidebar from '@/components/layout/Sidebar';
import TopNavbar from '@/components/layout/TopNavbar';

/**
 * PlatformLayout — the shared application shell.
 *
 * Composes the fixed Sidebar + TopNavbar around a routed <Outlet />. Owns the
 * responsive drawer state:
 *   - desktop (≥992px): sidebar always visible (CSS)
 *   - tablet/mobile (<992px): sidebar is an off-canvas drawer with a backdrop
 * The drawer auto-closes whenever the route changes.
 */
export default function PlatformLayout() {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const location = useLocation();

  // Close the mobile drawer on navigation.
  useEffect(() => {
    setDrawerOpen(false);
  }, [location.pathname]);

  // Prevent body scroll while the drawer is open on mobile.
  useEffect(() => {
    document.body.style.overflow = drawerOpen ? 'hidden' : '';
    return () => {
      document.body.style.overflow = '';
    };
  }, [drawerOpen]);

  return (
    <div className="app-shell">
      <Sidebar open={drawerOpen} onClose={() => setDrawerOpen(false)} />

      <div
        className={`db-backdrop ${drawerOpen ? 'show' : ''}`.trim()}
        onClick={() => setDrawerOpen(false)}
        aria-hidden="true"
      />

      <TopNavbar onMenuClick={() => setDrawerOpen(true)} />

      <main className="db-main">
        <Outlet />
      </main>
    </div>
  );
}
