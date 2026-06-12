import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * useAsync — run an async function and track {data, loading, error}.
 *
 * The domain hooks (useProjects, useWorkflows, ...) are thin wrappers around
 * this. Because every data source flows through here, swapping mock services
 * for the real Axios client later requires no changes to components.
 *
 * @param {Function} asyncFn   async function returning the data
 * @param {Array}    deps      dependency list that re-triggers the call
 * @param {Object}   options   { immediate = true, initialData = null }
 */
export function useAsync(asyncFn, deps = [], options = {}) {
  const { immediate = true, initialData = null } = options;
  const [data, setData] = useState(initialData);
  const [loading, setLoading] = useState(immediate);
  const [error, setError] = useState(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const run = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await asyncFn();
      if (mountedRef.current) setData(result);
      return result;
    } catch (err) {
      if (mountedRef.current) setError(err);
      return undefined;
    } finally {
      if (mountedRef.current) setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    if (immediate) run();
  }, [run, immediate]);

  return { data, loading, error, refetch: run, setData };
}
