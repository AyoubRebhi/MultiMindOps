/* ============================================================================
   mockSchemaValidationLogs.js — scripted schema-validation output replayed by
   <RealtimeLogViewer /> in Section 6. Two scripts: the first run fails (missing
   runs-on / job name / invalid step), the re-run after the fix passes.
   level: cmd | info | warn | error | success.
   ========================================================================== */

export const failingValidationLogs = [
  { level: 'cmd', text: '$ actionlint .github/workflows/deploy.yml' },
  { level: 'info', text: 'Parsing workflow file...' },
  { level: 'info', text: 'Workflow: "Build & Deploy to AWS ECS"' },
  { level: 'info', text: 'Checking triggers... on.push.branches [main] ✓' },
  { level: 'info', text: 'Checking jobs... 2 jobs found' },
  { level: 'warn', text: 'job "deploy": missing required key "runs-on"' },
  { level: 'warn', text: 'job "build": missing display "name"' },
  { level: 'info', text: 'Checking steps... 11 steps found' },
  { level: 'error', text: 'Error: step #7 has neither "uses" nor "run"' },
  { level: 'error', text: '  .github/workflows/deploy.yml:58:9' },
  { level: 'error', text: '✖ Schema validation failed — 3 problem(s) found' },
];

export const successValidationLogs = [
  { level: 'cmd', text: '$ actionlint .github/workflows/deploy.yml' },
  { level: 'info', text: 'Parsing workflow file...' },
  { level: 'info', text: 'Workflow: "Build & Deploy to AWS ECS"' },
  { level: 'info', text: 'Checking triggers... on.push.branches [main] ✓' },
  { level: 'info', text: 'Checking jobs... 2 jobs found' },
  { level: 'info', text: '  job "build": runs-on ubuntu-latest ✓' },
  { level: 'info', text: '  job "deploy": runs-on ubuntu-latest ✓ · needs [build] ✓' },
  { level: 'info', text: 'Checking steps... 11 steps found · all valid' },
  { level: 'info', text: 'Checking syntax... expressions & contexts ✓' },
  { level: 'success', text: 'Success! Workflow schema is valid.' },
];

export default { failingValidationLogs, successValidationLogs };
