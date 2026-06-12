/* ============================================================================
   mockWorkspace.js — the Admin-owned workspace + headline stats and the
   recent-activity stream shown on the Admin dashboard.
   ========================================================================== */

export const mockWorkspace = {
  id: 'ws-001',
  name: 'CloudForge HQ',
  company: 'CloudForge Inc.',
  description:
    'Primary workspace for the platform engineering team — owns all production cloud infrastructure.',
  region: 'eu-west-1',
  plan: 'Team',
  owner: 'Ayoub Rebhi',
  createdAt: '2026-04-10T09:00:00Z',
  stats: {
    totalMembers: 7,
    activeProjects: 6,
    activeWorkflows: 3,
    pendingInvitations: 2,
  },
};

export const mockWorkspaceActivity = [
  {
    id: 'wa-1',
    type: 'success',
    icon: 'fa-user-plus',
    actor: 'Mariem B.',
    message: 'accepted the invitation and joined the workspace',
    at: '2026-06-12T08:10:00Z',
  },
  {
    id: 'wa-2',
    type: 'info',
    icon: 'fa-paper-plane',
    actor: 'Ayoub Rebhi',
    message: 'invited karim.devops@acme.io as DevOps Engineer',
    at: '2026-06-11T16:42:00Z',
  },
  {
    id: 'wa-3',
    type: 'success',
    icon: 'fa-aws',
    brand: true,
    actor: 'Ayoub Rebhi',
    message: 'updated AWS credentials for eu-west-1',
    at: '2026-06-11T14:05:00Z',
  },
  {
    id: 'wa-4',
    type: 'warning',
    icon: 'fa-user-lock',
    actor: 'Ayoub Rebhi',
    message: 'blocked yassine.k@acme.io',
    at: '2026-06-10T11:20:00Z',
  },
  {
    id: 'wa-5',
    type: 'info',
    icon: 'fa-rocket',
    actor: 'Sami T.',
    message: 'deployed Payments API to production',
    at: '2026-06-09T19:18:00Z',
  },
];
