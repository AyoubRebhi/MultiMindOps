/* ============================================================================
   mockNotifications.js — sample notifications for the top-bar bell dropdown.
   ========================================================================== */

export const mockNotifications = [
  {
    id: 'ntf-1',
    icon: 'fa-triangle-exclamation',
    color: '#f87171',
    title: 'Auth Service needs review',
    body: 'Container build failed — AI corrector proposed a remediation.',
    at: '2026-06-12T07:55:00Z',
    unread: true,
  },
  {
    id: 'ntf-2',
    icon: 'fa-circle-check',
    color: '#34d399',
    title: 'Payments API deployed',
    body: 'Production rollout to eu-west-1 completed successfully.',
    at: '2026-06-11T14:05:00Z',
    unread: true,
  },
  {
    id: 'ntf-3',
    icon: 'fa-cubes',
    color: '#a78bfa',
    title: 'Terraform plan ready',
    body: 'Customer Portal staging plan generated — 6 resources to add.',
    at: '2026-06-12T08:42:00Z',
    unread: true,
  },
  {
    id: 'ntf-4',
    icon: 'fa-coins',
    color: '#fbbf24',
    title: 'Cost estimate updated',
    body: 'Data Pipeline monthly estimate rose to $936 (+9%).',
    at: '2026-06-10T19:18:00Z',
    unread: false,
  },
];

// The signed-in user now lives in @/services/mock/mockCurrentUser (consumed via
// AuthContext / useAuth) — this file only owns notifications.
