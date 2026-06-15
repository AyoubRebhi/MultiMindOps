import { useCallback, useEffect, useRef, useState } from 'react';
import { useAsync } from './useAsync';
import { projectApi } from '@/services/api/projectApi';
import { analysisApi } from '@/services/api/analysisApi';

/** All projects the current user can see. */
export function useProjects() {
  return useAsync(() => projectApi.list(), [], { initialData: [] });
}

/** A single project by id (ProjectDetailResponse-backed). */
export function useProject(id) {
  return useAsync(() => projectApi.getById(id), [id]);
}

/** Bootstrap/analysis statuses that are still in-flight (keep polling). */
const ACTIVE_STATUSES = new Set(['pending', 'analyzing', 'context_building']);

/**
 * useProjectAnalysis — fetch the consolidated analysis + security payload and
 * poll while the bootstrap is still running.
 *
 * Phase 9 (live status): polling is the interim mechanism ahead of WebSockets.
 * The hook stops polling once the status reaches a terminal state (ready /
 * failed). `intervalMs` is the poll cadence; pass 0 to disable polling.
 */
export function useProjectAnalysis(projectId, { intervalMs = 4000 } = {}) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
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
        const result = await analysisApi.getProjectAnalysis(projectId);
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

  // Schedule the next poll whenever data updates and the status is still active.
  useEffect(() => {
    clearTimer();
    if (!intervalMs || !data) return undefined;
    if (!ACTIVE_STATUSES.has(data.bootstrapStatus)) return undefined;
    timerRef.current = setTimeout(() => {
      fetchOnce({ silent: true });
    }, intervalMs);
    return clearTimer;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, intervalMs]);

  return { data, loading, error, refetch: () => fetchOnce() };
}

/**
 * useCreateProject — create mutation with its own loading/error state. The
 * created project's analysis is scheduled server-side immediately, so callers
 * typically navigate to the detail page where the status component takes over.
 */
export function useCreateProject() {
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState(null);

  const create = useCallback(async (form) => {
    setCreating(true);
    setError(null);
    try {
      return await projectApi.create(form);
    } catch (err) {
      setError(err);
      throw err;
    } finally {
      setCreating(false);
    }
  }, []);

  return { create, creating, error };
}
