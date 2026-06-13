/* ============================================================================
   mockSecurityAudit.js — output of the Security Guardrails Audit (Section 7),
   rendered as security cards by <SecurityAuditPanel />. The first audit flags
   critical findings (hardcoded key / unverified action / excessive perms); the
   re-audit after the fix passes with a high score. MOCK ONLY — nothing scanned.
   ========================================================================== */

// Five audit categories, scored per run. status: pass | warn | fail
const failingCategories = [
  {
    key: 'dangerous_commands',
    name: 'Dangerous Commands',
    icon: 'fa-skull-crossbones',
    status: 'warn',
    detail: 'curl | bash pattern detected in a run step.',
  },
  {
    key: 'secrets_exposure',
    name: 'Secrets Exposure',
    icon: 'fa-key',
    status: 'fail',
    detail: 'Hardcoded AWS access key found in an env block.',
  },
  {
    key: 'third_party_actions',
    name: 'Third Party Actions',
    icon: 'fa-puzzle-piece',
    status: 'fail',
    detail: 'Unverified action pinned to a mutable tag (not SHA).',
  },
  {
    key: 'permissions',
    name: 'Permissions',
    icon: 'fa-user-shield',
    status: 'fail',
    detail: 'Workflow grants permissions: write-all (excessive).',
  },
  {
    key: 'suspicious_urls',
    name: 'Suspicious URLs',
    icon: 'fa-link-slash',
    status: 'warn',
    detail: 'External script downloaded from an unpinned domain.',
  },
];

const passingCategories = [
  { key: 'dangerous_commands', name: 'Dangerous Commands', icon: 'fa-skull-crossbones', status: 'pass', detail: 'No dangerous shell patterns detected.' },
  { key: 'secrets_exposure', name: 'Secrets Exposure', icon: 'fa-key', status: 'pass', detail: 'All credentials use ${{ secrets.* }} references.' },
  { key: 'third_party_actions', name: 'Third Party Actions', icon: 'fa-puzzle-piece', status: 'pass', detail: 'All actions verified & pinned to immutable versions.' },
  { key: 'permissions', name: 'Permissions', icon: 'fa-user-shield', status: 'pass', detail: 'Least-privilege: contents:read, id-token:write.' },
  { key: 'suspicious_urls', name: 'Suspicious URLs', icon: 'fa-link-slash', status: 'pass', detail: 'No external script downloads detected.' },
];

export const mockSecurityAuditFailed = {
  status: 'failed',
  score: 48,
  grade: 'D',
  riskLevel: 'High',
  categories: failingCategories,
  warnings: [
    'A run step pipes a remote script directly into bash.',
    'Image is tagged with "latest" rather than an immutable SHA.',
  ],
  criticalFindings: [
    {
      id: 'SEC-001',
      title: 'Hardcoded AWS access key',
      category: 'Secrets Exposure',
      line: 54,
      icon: 'fa-key',
      detail: 'An AWS access key (AKIA…) is embedded in an env block. Move it to repository secrets.',
    },
    {
      id: 'SEC-002',
      title: 'Unverified third-party action',
      category: 'Third Party Actions',
      line: 67,
      icon: 'fa-puzzle-piece',
      detail: 'aws-actions/amazon-ecs-deploy is pinned to @v2 (mutable). Pin to a full commit SHA.',
    },
    {
      id: 'SEC-003',
      title: 'Excessive workflow permissions',
      category: 'Permissions',
      line: 9,
      icon: 'fa-user-shield',
      detail: 'permissions: write-all grants every scope. Restrict to contents:read and id-token:write.',
    },
  ],
};

export const mockSecurityAuditPassed = {
  status: 'passed',
  score: 96,
  grade: 'A',
  riskLevel: 'Low',
  categories: passingCategories,
  warnings: [],
  criticalFindings: [],
};

export default { mockSecurityAuditFailed, mockSecurityAuditPassed };
