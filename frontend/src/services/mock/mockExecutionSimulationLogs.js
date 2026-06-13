/* ============================================================================
   mockExecutionSimulationLogs.js — scripted `nektos/act` execution output
   replayed by <RealtimeLogViewer /> in Section 9. The first run fails (registry
   authentication failed), the retry runs the full pipeline to a green deploy.
   level: cmd | info | warn | error | success.
   ========================================================================== */

export const failingExecutionLogs = [
  { level: 'cmd', text: '$ act push --workflows .github/workflows/deploy.yml' },
  { level: 'info', text: '[Build & Deploy/build] 🚀 Start image=catthehacker/ubuntu:act-latest' },
  { level: 'info', text: '[Build & Deploy/build] ⭐ Run Checkout repository' },
  { level: 'info', text: '[Build & Deploy/build] ✅ Checkout repository' },
  { level: 'info', text: '[Build & Deploy/build] ⭐ Run Set up JDK 21' },
  { level: 'info', text: '[Build & Deploy/build] ⭐ Run Build with Maven' },
  { level: 'info', text: 'BUILD SUCCESS — total time: 38.4 s' },
  { level: 'info', text: '[Build & Deploy/deploy] ⭐ Run Build & push Docker image' },
  { level: 'info', text: 'Successfully built image customer-portal-api: a1b2c3d' },
  { level: 'error', text: 'denied: authentication required to push to ECR' },
  { level: 'error', text: 'Error: failed to push image — exit code 1' },
  { level: 'error', text: '✖ Job "deploy" failed at step "Build & push Docker image"' },
];

export const successExecutionLogs = [
  { level: 'cmd', text: '$ act push --workflows .github/workflows/deploy.yml' },
  { level: 'info', text: '[Build & Deploy/build] 🚀 Start image=catthehacker/ubuntu:act-latest' },
  { level: 'info', text: '[Build & Deploy/build] ⭐ Run Checkout repository' },
  { level: 'info', text: '[Build & Deploy/build] ⭐ Run Set up JDK 21' },
  { level: 'info', text: '[Build & Deploy/build] ⭐ Run Build with Maven' },
  { level: 'info', text: 'BUILD SUCCESS — total time: 37.9 s' },
  { level: 'info', text: '[Build & Deploy/build] ⭐ Run Upload JAR artifact' },
  { level: 'info', text: '[Build & Deploy/deploy] ⭐ Run Configure AWS credentials' },
  { level: 'info', text: '[Build & Deploy/deploy] ⭐ Run Login to Amazon ECR' },
  { level: 'info', text: 'Login Succeeded' },
  { level: 'info', text: '[Build & Deploy/deploy] ⭐ Run Build & push Docker image' },
  { level: 'info', text: 'Pushed customer-portal-api:a1b2c3d → 123456789012.dkr.ecr.eu-west-1.amazonaws.com' },
  { level: 'info', text: '[Build & Deploy/deploy] ⭐ Run Deploy to Amazon ECS' },
  { level: 'info', text: 'Registering new task definition revision 24...' },
  { level: 'info', text: 'Updating service customer-portal-service...' },
  { level: 'info', text: 'Waiting for service to reach a steady state...' },
  { level: 'success', text: 'Service is stable — 2/2 tasks running.' },
  { level: 'success', text: '✔ Workflow run completed successfully.' },
];

export default { failingExecutionLogs, successExecutionLogs };
