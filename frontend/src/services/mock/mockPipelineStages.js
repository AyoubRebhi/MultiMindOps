/* ============================================================================
   mockPipelineStages.js — the high-level pipeline stages (Section 4) rendered
   as <PipelineStageCard /> cards. Each stage rolls up several graph nodes and
   carries timing + produced artifacts. Provided in a succeeding variant and a
   failing variant (the Infrastructure stage fails on the first attempt).
   MOCK ONLY. status: success | failed | running | pending | skipped.
   ========================================================================== */

export const mockPipelineStages = [
  {
    key: 'build',
    name: 'Build Stage',
    icon: 'fa-hammer',
    status: 'success',
    startTime: '08:04:14',
    endTime: '08:05:13',
    duration: '59s',
    artifacts: ['app.jar', 'test-report.xml'],
  },
  {
    key: 'docker',
    name: 'Docker Stage',
    icon: 'fa-docker',
    brand: true,
    status: 'success',
    startTime: '08:05:13',
    endTime: '08:05:49',
    duration: '36s',
    artifacts: ['customer-portal-api:a1b2c3d'],
  },
  {
    key: 'infrastructure',
    name: 'Infrastructure Stage',
    icon: 'fa-cubes',
    status: 'success',
    startTime: '08:05:49',
    endTime: '08:06:30',
    duration: '41s',
    artifacts: ['terraform.tfstate', 'tfplan.bin'],
  },
  {
    key: 'deployment',
    name: 'Deployment Stage',
    icon: 'fa-rocket',
    status: 'success',
    startTime: '08:06:30',
    endTime: '08:07:03',
    duration: '33s',
    artifacts: ['task-definition:24'],
  },
  {
    key: 'verification',
    name: 'Verification Stage',
    icon: 'fa-heart-pulse',
    status: 'success',
    startTime: '08:07:03',
    endTime: '08:07:12',
    duration: '9s',
    artifacts: ['health-report.json'],
  },
];

export const mockPipelineStagesFailed = [
  {
    key: 'build',
    name: 'Build Stage',
    icon: 'fa-hammer',
    status: 'success',
    startTime: '08:04:14',
    endTime: '08:05:13',
    duration: '59s',
    artifacts: ['app.jar', 'test-report.xml'],
  },
  {
    key: 'docker',
    name: 'Docker Stage',
    icon: 'fa-docker',
    brand: true,
    status: 'success',
    startTime: '08:05:13',
    endTime: '08:05:49',
    duration: '36s',
    artifacts: ['customer-portal-api:a1b2c3d'],
  },
  {
    key: 'infrastructure',
    name: 'Infrastructure Stage',
    icon: 'fa-cubes',
    status: 'failed',
    startTime: '08:05:49',
    endTime: '08:10:51',
    duration: '5m 2s',
    artifacts: [],
  },
  {
    key: 'deployment',
    name: 'Deployment Stage',
    icon: 'fa-rocket',
    status: 'skipped',
    startTime: '—',
    endTime: '—',
    duration: '—',
    artifacts: [],
  },
  {
    key: 'verification',
    name: 'Verification Stage',
    icon: 'fa-heart-pulse',
    status: 'skipped',
    startTime: '—',
    endTime: '—',
    duration: '—',
    artifacts: [],
  },
];

export default { mockPipelineStages, mockPipelineStagesFailed };
