import { useAsync } from './useAsync';
import { projectApi } from '@/services/api/projectApi';

/** All projects. */
export function useProjects() {
  return useAsync(() => projectApi.list(), [], { initialData: [] });
}

/** A single project by id. */
export function useProject(id) {
  return useAsync(() => projectApi.getById(id), [id]);
}
