import { Outlet } from 'react-router-dom';
import { useTheme } from '@/hooks/useTheme';
import { APP_NAME, APP_TAGLINE } from '@/utils/constants';

/**
 * AuthLayout — modern SaaS split-screen shell for the auth pages.
 *   - Left:  branding panel (gradient + aurora glow, feature highlights).
 *   - Right: the routed form (<Outlet />).
 * The brand panel is hidden under 992px; the form goes full-width. A small
 * theme toggle sits in the top-right so dark/light works on auth pages too.
 */
const FEATURES = [
  {
    icon: 'fa-robot',
    title: 'AI infrastructure agents',
    body: 'Generate Dockerfiles, Terraform and K8s manifests from your repo.',
  },
  {
    icon: 'fa-shield-halved',
    title: 'Secure by default',
    body: 'Scoped AWS credentials, role-based access and audited changes.',
  },
  {
    icon: 'fa-gauge-high',
    title: 'Ship faster',
    body: 'From repository analysis to deployment in a single guided workflow.',
  },
];

export default function AuthLayout() {
  const { theme, toggleTheme } = useTheme();

  return (
    <div className="auth-shell">
      {/* Branding */}
      <div className="auth-brand">
        <div className="aur aur-a" style={{ top: -120, left: -120 }} />
        <div className="aur aur-b" style={{ bottom: -100, right: -120 }} />

        <div className="position-relative" style={{ zIndex: 2 }}>
          <div className="d-flex align-items-center gap-2" style={{ fontWeight: 700, fontSize: '1.25rem' }}>
            <div className="logo-i">
              <i className="fa-solid fa-layer-group" />
            </div>
            <span>{APP_NAME}</span>
          </div>
        </div>

        <div className="position-relative" style={{ zIndex: 2 }}>
          <span className="slbl">{APP_TAGLINE}</span>
          <h2 style={{ fontSize: '2rem', fontWeight: 700, lineHeight: 1.15, marginBottom: 28 }}>
            Build and ship cloud
            <br />
            infrastructure with <span className="gt">AI</span>.
          </h2>
          {FEATURES.map((f) => (
            <div className="auth-feature" key={f.title}>
              <div className="auth-feature-ico">
                <i className={`fa-solid ${f.icon}`} />
              </div>
              <div>
                <div style={{ fontWeight: 600, fontSize: '.92rem' }}>{f.title}</div>
                <div style={{ fontSize: '.82rem', color: 'var(--tx2)' }}>{f.body}</div>
              </div>
            </div>
          ))}
        </div>

        <div className="position-relative text-muted-3" style={{ zIndex: 2, fontSize: '.78rem' }}>
          © {new Date().getFullYear()} {APP_NAME}. All rights reserved.
        </div>
      </div>

      {/* Form side */}
      <div className="auth-form-side position-relative">
        <button
          className="boc d-flex align-items-center justify-content-center"
          style={{ position: 'absolute', top: 20, right: 20, width: 38, height: 38, padding: 0, borderRadius: 12 }}
          onClick={toggleTheme}
          aria-label="Toggle theme"
        >
          <i className={`fa-solid ${theme === 'light' ? 'fa-moon' : 'fa-sun'}`} />
        </button>
        <div className="auth-form-wrap">
          <Outlet />
        </div>
      </div>
    </div>
  );
}
