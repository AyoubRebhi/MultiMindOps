import { NavLink, useNavigate } from 'react-router-dom';
import { useAuth } from '@/hooks/useAuth';
import RoleBadge from '@/components/common/RoleBadge';
import { APP_NAME, getNavForRole } from '@/utils/constants';

/**
 * Sidebar — fixed navigation rail (ported from the template's .db-sidebar).
 * The nav set is chosen by the signed-in user's role (Admin vs DevOps Engineer).
 * On <992px it becomes an off-canvas drawer toggled via the `open` prop.
 *
 * Props:
 *  - open: drawer open state (mobile)
 *  - onClose: called when a link is chosen or the close button is pressed
 */
export default function Sidebar({ open = false, onClose = () => {} }) {
  const { user, signOut } = useAuth();
  const navigate = useNavigate();
  const sections = getNavForRole(user?.role);

  const handleSignOut = async () => {
    await signOut();
    navigate('/auth/signin');
  };

  return (
    <aside className={`db-sidebar ${open ? 'mob-open' : ''}`.trim()}>
      <div className="db-logo justify-content-between">
        <div className="d-flex align-items-center gap-2">
          <div className="logo-i">
            <i className="fa-solid fa-layer-group" />
          </div>
          <span>{APP_NAME}</span>
        </div>
        <button
          className="boc db-sidebar-close align-items-center justify-content-center"
          style={{ width: 32, height: 32, padding: 0, borderRadius: 10 }}
          onClick={onClose}
          aria-label="Close navigation"
        >
          <i className="fa-solid fa-xmark" />
        </button>
      </div>

      <nav className="db-nav">
        {sections.map((section) => (
          <div key={section.title}>
            <div className="db-nav-section">{section.title}</div>
            {section.items.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                onClick={onClose}
                className={({ isActive }) => `db-nl ${isActive ? 'active' : ''}`.trim()}
              >
                <i className={`${item.brand ? 'fa-brands' : 'fa-solid'} ${item.icon}`} />
                <span>{item.label}</span>
                {item.badge && <span className="db-badge">{item.badge}</span>}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>

      <div className="db-bottom">
        {user && (
          <div
            className="d-flex align-items-center justify-content-between mb-2"
            style={{ padding: '4px 6px' }}
          >
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: '.8rem', fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {user.name}
              </div>
              <RoleBadge role={user.role} short />
            </div>
          </div>
        )}
        <button className="db-nl" style={{ color: '#f87171' }} onClick={handleSignOut}>
          <i className="fa-solid fa-right-from-bracket" />
          <span>Sign Out</span>
        </button>
      </div>
    </aside>
  );
}
