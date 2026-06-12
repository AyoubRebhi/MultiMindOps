import { Outlet } from 'react-router-dom';
import { useTheme } from '@/hooks/useTheme';
import { APP_NAME } from '@/utils/constants';

/**
 * OnboardingLayout — centered, single-column shell with a brand header. Used by
 * the workspace setup wizard and the invitation acceptance flow. Pages own
 * their own stepper / card; the layout just frames them.
 */
export default function OnboardingLayout() {
  const { theme, toggleTheme } = useTheme();

  return (
    <div className="onb-shell">
      <div
        className="onb-wrap d-flex align-items-center justify-content-between"
        style={{ marginBottom: 24 }}
      >
        <div className="d-flex align-items-center gap-2" style={{ fontWeight: 700, fontSize: '1.15rem' }}>
          <div className="logo-i">
            <i className="fa-solid fa-layer-group" />
          </div>
          <span>{APP_NAME}</span>
        </div>
        <button
          className="boc d-flex align-items-center justify-content-center"
          style={{ width: 38, height: 38, padding: 0, borderRadius: 12 }}
          onClick={toggleTheme}
          aria-label="Toggle theme"
        >
          <i className={`fa-solid ${theme === 'light' ? 'fa-moon' : 'fa-sun'}`} />
        </button>
      </div>

      <div className="onb-wrap">
        <Outlet />
      </div>
    </div>
  );
}
