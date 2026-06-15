import { useCallback, useEffect, useRef, useState } from 'react';
import { workflowAnalysisApi } from '@/services/api/workflowAnalysisApi';

/**
 * useWorkflowAnalysis — fetch the single aggregated Workflow Analysis payload
 * for a project and poll while the run is still `RUNNING`.
 *
 * Mirrors useProjectAnalysis (polling stops at a terminal status). Returns the
 * mutation helpers too so the action bar can start/rerun the workflow and have
 * the hook immediately reflect the resulting state.
 *
 * @param {string} projectId
 * @param {{ intervalMs?: number }} [opts]
 * @returns {{
 *   data: import('@/types/workflowAnalysis').WorkflowAnalysis | null,
 *   loading: boolean, error: any, working: boolean,
 *   refetch: () => Promise<any>, start: () => Promise<any>, rerun: () => Promise<any>,
 * }}
 */
export function useWorkflowAnalysis(projectId, { intervalMs = 4000 } = {}) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [working, setWorking] = useState(false); // start/rerun in flight
  const mountedRef = useRef(true);
  const timerRef = useRef(null);

  const clearTimer = () => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  };

  const fetchOnce = useCallback(
    async ({ silent = false } = {}) => {
      if (!projectId) return undefined;
      if (!silent) setLoading(true);
      try {
        const result = await workflowAnalysisApi.getAnalysis(projectId);
        if (!mountedRef.current) return result;
        setData(result);
        setError(null);
        return result;
      } catch (err) {
        if (mountedRef.current) setError(err);
        return undefined;
      } finally {
        if (mountedRef.current && !silent) setLoading(false);
      }
    },
    [projectId]
  );

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      clearTimer();
    };
  }, []);

  // Initial load + reload when the project changes.
  useEffect(() => {
    clearTimer();
    setData(null);
    setError(null);
    fetchOnce();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  // Poll while the status is still RUNNING.
  useEffect(() => {
    clearTimer();
    if (!intervalMs || !data) return undefined;
    if (data.status !== 'RUNNING') return undefined;
    timerRef.current = setTimeout(() => fetchOnce({ silent: true }), intervalMs);
    return clearTimer;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, intervalMs]);

  // Shared runner for the start/rerun mutations.
  const mutate = useCallback(
    async (fn) => {
      if (!projectId) return undefined;
      setWorking(true);
      try {
        const result = await fn(projectId);
        if (mountedRef.current && result) {
          setData(result);
          setError(null);
        }
        return result;
      } catch (err) {
        if (mountedRef.current) setError(err);
        throw err;
      } finally {
        if (mountedRef.current) setWorking(false);
      }
    },
    [projectId]
  );

  const start = useCallback(() => mutate(workflowAnalysisApi.startWorkflow), [mutate]);
  const rerun = useCallback(() => mutate(workflowAnalysisApi.rerunWorkflow), [mutate]);

  return { data, loading, error, working, refetch: () => fetchOnce(), start, rerun };
}

export default useWorkflowAnalysis;
