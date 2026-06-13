import RealtimeLogViewer from './RealtimeLogViewer';

/**
 * TerraformExecutionPanel — runs the (mock) `plan → apply` sequence through the
 * reusable log viewer (the execution console). The error panel and result card
 * are rendered separately by the page based on the outcome.
 *
 * Props:
 *  - status: 'not_started' | 'running' | 'completed' | 'failed'
 *  - events, playKey, onRun, onComplete, canRun, preparing
 */
export default function TerraformExecutionPanel({
  status = 'not_started',
  events = [],
  playKey = 0,
  onRun,
  onComplete,
  canRun = true,
  preparing = false,
}) {
  const startLabel =
    status === 'failed' ? 'Retry Execution' : status === 'completed' ? 'Re-run apply' : 'Run plan & apply';

  return (
    <RealtimeLogViewer
      events={events}
      playKey={playKey}
      canStart={canRun}
      preparing={preparing}
      onStart={onRun}
      onComplete={onComplete}
      startLabel={startLabel}
      title="terraform plan · apply"
      emptyHint={
        canRun
          ? 'Run plan & apply to provision the infrastructure on AWS.'
          : 'Validation must pass before the execution can run.'
      }
    />
  );
}
