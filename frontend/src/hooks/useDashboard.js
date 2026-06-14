import { useEffect, useRef } from 'react';
import { useAsync } from './useAsync';
import { useToast } from './useToast';
import { dashboardApi } from '@/services/api/dashboardApi';

/**
 * Dashboard data hooks — one per widget so each loads / errors / retries
 * independently. Thin wrappers over useAsync, which already exposes
 * { data, loading, error, refetch }.
 */

export function useDashboardMetrics() {
  return useAsync(() => dashboardApi.getMetrics(), [], { initialData: null });
}

export function useDashboardUsage() {
  return useAsync(() => dashboardApi.getUsage(14), [], { initialData: null });
}

export function useRecentProjects() {
  return useAsync(() => dashboardApi.getRecentProjects(6), [], { initialData: [] });
}

export function useLiveActivity() {
  return useAsync(() => dashboardApi.getActivity(8), [], { initialData: [] });
}

/**
 * useErrorToast — raise a single toast when a widget's fetch fails, and reset
 * once it recovers, so a re-render storm doesn't spam duplicate toasts.
 */
export function useErrorToast(error, label) {
  const toast = useToast();
  const lastShown = useRef(null);

  useEffect(() => {
    if (error && lastShown.current !== error) {
      lastShown.current = error;
      const detail = error?.message || 'Request failed';
      toast.error(`${label}: ${detail}`);
    }
    if (!error) lastShown.current = null;
  }, [error, label, toast]);
}
