/* ============================================================================
   mockWorkflowHistory.js — previous workflow executions for the Infrastructure
   Dashboard (Section 6), rendered by <WorkflowHistoryPanel />. The most recent
   run is the one the user just completed. MOCK ONLY.
   ========================================================================== */

export const mockWorkflowHistory = [
  { id: 'run-7F3A9C21', date: '2026-06-13T08:07:12Z', status: 'completed', duration: '3m 01s', triggeredBy: 'Ayoub Rebhi', current: true },
  { id: 'run-6B1D8E04', date: '2026-06-13T07:41:55Z', status: 'failed', duration: '5m 38s', triggeredBy: 'Ayoub Rebhi' },
  { id: 'run-5A9C2F77', date: '2026-06-12T16:22:09Z', status: 'completed', duration: '2m 54s', triggeredBy: 'CI · push to main' },
  { id: 'run-4E7B0A13', date: '2026-06-12T11:08:44Z', status: 'completed', duration: '3m 12s', triggeredBy: 'Ayoub Rebhi' },
  { id: 'run-3C5F6D88', date: '2026-06-11T09:33:20Z', status: 'completed', duration: '2m 47s', triggeredBy: 'CI · push to main' },
];

export default mockWorkflowHistory;
