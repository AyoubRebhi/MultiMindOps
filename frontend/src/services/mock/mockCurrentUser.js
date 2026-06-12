/* ============================================================================
   mockCurrentUser.js — the signed-in user for the demo. AuthContext seeds its
   state from here. `mockEngineerUser` lets the demo switch into the DevOps
   Engineer experience without a backend.
   ========================================================================== */

export const mockCurrentUser = {
  id: 'usr-001',
  firstName: 'Ayoub',
  lastName: 'Rebhi',
  name: 'Ayoub Rebhi',
  email: 'rebhi.ayoub@esprit.tn',
  role: 'ADMIN',
  status: 'active',
  workspaceId: 'ws-001',
  workspaceName: 'CloudForge HQ',
  avatarColor: '#8b5cf6',
};

export const mockEngineerUser = {
  id: 'usr-002',
  firstName: 'Mariem',
  lastName: 'Ben Salah',
  name: 'Mariem Ben Salah',
  email: 'mariem.b@acme.io',
  role: 'DEVOPS_ENGINEER',
  status: 'active',
  workspaceId: 'ws-001',
  workspaceName: 'CloudForge HQ',
  avatarColor: '#3b82f6',
};
