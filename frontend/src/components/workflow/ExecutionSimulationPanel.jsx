import RealtimeLogViewer from './RealtimeLogViewer';

/**
 * ExecutionSimulationPanel — runs the compiled workflow locally with (mock)
 * nektos/act through the reusable log viewer (Section 9). The first run fails
 * (registry auth), the retry runs the full pipeline to a green deploy. The
 * pipeline result card is rendered separately by the page based on the outcome.
 *
 * Props:
 *  - status: 'not_started' | 'running' | 'completed' | 'failed'
 *  - events, playKey, onRun, onComplete, canRun, preparing
 */
export default function ExecutionSimulationPanel({
  status = 'not_started',
  events = [],
  playKey = 0,
  onRun,
  onComplete,
  canRun = true,
  preparing = false,
}) {
  const startLabel =
    status === 'failed' ? 'Retry Execution' : status === 'completed' ? 'Re-run simulation' : 'Run Simulation';

  return (
    <RealtimeLogViewer
      events={events}
      playKey={playKey}
      canStart={canRun}
      preparing={preparing}
      onStart={onRun}
      onComplete={onComplete}
      startLabel={startLabel}
      title="nektos/act · workflow run"
      emptyHint={
        canRun
          ? 'Run the simulation to execute the compiled workflow locally with nektos/act.'
          : 'Compile the workflow before running the execution simulation.'
      }
    />
  );
}
