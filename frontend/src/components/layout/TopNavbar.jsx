import { useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTheme } from '@/hooks/useTheme';
import { useAuth } from '@/hooks/useAuth';
import { useClickOutside } from '@/hooks/useClickOutside';
import { mockNotifications } from '@/services/mock/mockNotifications';
import { getRoleMeta, ROLES } from '@/utils/constants';
import { initials, timeAgo } from '@/utils/formatters';

/**
 * TopNavbar — fixed top bar (ported from .db-top). Holds the mobile menu
 * toggle, search, theme switch, notifications and the user menu. All dropdown
 * behavior is React state (no bootstrap.js / jQuery). The user identity comes
 * from the (mock) AuthContext.
 *
 * Props:
 *  - onMenuClick: open the mobile sidebar drawer
 */
export default function TopNavbar({ onMenuClick = () => {} }) {
  const { theme, toggleTheme } = useTheme();
  const { user, isAdmin, signOut, switchRole } = useAuth();
  const navigate = useNavigate();
  const [openMenu, setOpenMenu] = useState(null); // 'notif' | 'profile' | null

  const close = useCallback(() => setOpenMenu(null), []);
  const notifRef = useClickOutside(openMenu === 'notif', close);
  const profileRef = useClickOutside(openMenu === 'profile', close);

  const unread = mockNotifications.filter((n) => n.unread).length;
  const roleMeta = getRoleMeta(user?.role);

  const go = (path) => {
    close();
    navigate(path);
  };
  const handleSignOut = async () => {
    close();
    await signOut();
    navigate('/auth/signin');
  };
  const handleSwitchRole = () => {
    close();
    switchRole(isAdmin ? ROLES.DEVOPS_ENGINEER : ROLES.ADMIN);
    navigate('/');
  };

  return (
    <header className="db-top">
      <button
        className="boc d-lg-none align-items-center justify-content-center"
        style={{ width: 38, height: 38, padding: 0, borderRadius: 10 }}
        onClick={onMenuClick}
        aria-label="Open navigation"
      >
        <i className="fa-solid fa-bars" />
      </button>

      <div className="db-top-search">
        <i className="fa-solid fa-magnifying-glass" />
        <input type="text" placeholder="Search projects, workflows, artifacts…" />
      </div>

      <div className="ms-auto d-flex align-items-center gap-2 gap-md-3">
        {/* Theme toggle */}
        <button
          className="boc d-flex align-items-center justify-content-center"
          style={{ width: 38, height: 38, padding: 0, borderRadius: 12 }}
          onClick={toggleTheme}
          aria-label="Toggle theme"
        >
          <i className={`fa-solid ${theme === 'light' ? 'fa-moon' : 'fa-sun'}`} />
        </button>

        {/* Notifications */}
        <div style={{ position: 'relative' }} ref={notifRef}>
          <button
            className="boc d-flex align-items-center justify-content-center"
            style={{ width: 38, height: 38, padding: 0, borderRadius: 12 }}
            onClick={() =>
              setOpenMenu((m) => (m === 'notif' ? null : 'notif'))
            }
            aria-label="Notifications"
          >
            <i className="fa-regular fa-bell" />
          </button>
          {unread > 0 && (
            <span
              style={{
                position: 'absolute',
                top: 5,
                right: 5,
                width: 9,
                height: 9,
                borderRadius: '50%',
                background: '#f87171',
                border: '2px solid var(--bg)',
              }}
            />
          )}
          <div
            className={`db-dropdown ${openMenu === 'notif' ? 'open' : ''}`.trim()}
            style={{ right: 0, minWidth: 340 }}
          >
            <div className="dd-header">
              <div className="dd-header-title">
                <i className="fa-regular fa-bell me-2" style={{ color: 'var(--pur)' }} />
                Notifications
                {unread > 0 && (
                  <span className="badge-pill badge-danger ms-2">{unread} new</span>
                )}
              </div>
              <button className="dd-close" onClick={close} aria-label="Close">
                <i className="fa-solid fa-xmark" />
              </button>
            </div>
            <div className="dd-body">
              {mockNotifications.map((n) => (
                <div
                  key={n.id}
                  className="d-flex gap-3 mb-2"
                  style={{
                    padding: 10,
                    borderRadius: 10,
                    background: n.unread ? 'rgba(139,92,246,.06)' : 'transparent',
                  }}
                >
                  <div
                    className="icon-tile"
                    style={{
                      width: 32,
                      height: 32,
                      fontSize: '.85rem',
                      background: 'var(--bg3)',
                      color: n.color,
                    }}
                  >
                    <i className={`fa-solid ${n.icon}`} />
                  </div>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: '.84rem', fontWeight: 600 }}>{n.title}</div>
                    <div style={{ fontSize: '.78rem', color: 'var(--tx2)' }}>{n.body}</div>
                    <div style={{ fontSize: '.7rem', color: 'var(--tx3)', marginTop: 4 }}>
                      <i className="fa-regular fa-clock me-1" />
                      {timeAgo(n.at)}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* User menu */}
        <div style={{ position: 'relative' }} ref={profileRef}>
          <div
            className="db-user-pill"
            onClick={() =>
              setOpenMenu((m) => (m === 'profile' ? null : 'profile'))
            }
            role="button"
            tabIndex={0}
          >
            <div className="db-avatar" style={{ background: user?.avatarColor || undefined }}>
              {initials(user?.name)}
            </div>
            <div className="d-none d-md-block">
              <div style={{ fontSize: '.85rem', fontWeight: 600, lineHeight: 1.2 }}>
                {user?.name}
              </div>
              <div style={{ fontSize: '.72rem', color: 'var(--tx3)' }}>{roleMeta.label}</div>
            </div>
            <i
              className="fa-solid fa-chevron-down fa-xs"
              style={{ color: 'var(--tx3)' }}
            />
          </div>

          <div
            className={`db-dropdown ${openMenu === 'profile' ? 'open' : ''}`.trim()}
            style={{ right: 0, minWidth: 240 }}
          >
            <div className="dd-header">
              <div className="d-flex align-items-center gap-2">
                <div
                  className="db-avatar"
                  style={{ width: 40, height: 40, borderRadius: 12, background: user?.avatarColor || undefined }}
                >
                  {initials(user?.name)}
                </div>
                <div>
                  <div style={{ fontWeight: 700, fontSize: '.9rem' }}>{user?.name}</div>
                  <div style={{ fontSize: '.74rem', color: 'var(--tx3)' }}>{user?.email}</div>
                </div>
              </div>
            </div>
            <div style={{ padding: '8px 10px' }}>
              <MenuItem icon="fa-user" color="var(--pur)" label="My Profile" onClick={() => go('/settings')} />
              <MenuItem icon="fa-gear" color="var(--tx3)" label="Settings" onClick={() => go('/settings')} />
              <MenuItem
                icon="fa-repeat"
                color="#60a5fa"
                label={`Switch to ${isAdmin ? 'Engineer' : 'Admin'} view`}
                onClick={handleSwitchRole}
              />
              <div style={{ height: 1, background: 'var(--bd)', margin: '8px 6px' }} />
              <MenuItem icon="fa-right-from-bracket" color="#f87171" label="Sign Out" danger onClick={handleSignOut} />
            </div>
          </div>
        </div>
      </div>
    </header>
  );
}

function MenuItem({ icon, color, label, danger = false, onClick }) {
  return (
    <button
      className="db-nl"
      style={{ color: danger ? '#f87171' : 'var(--tx2)' }}
      type="button"
      onClick={onClick}
    >
      <i className={`fa-solid ${icon}`} style={{ color }} />
      <span>{label}</span>
    </button>
  );
}
