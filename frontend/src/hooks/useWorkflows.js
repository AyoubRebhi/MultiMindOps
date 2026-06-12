import { useAsync } from './useAsync';
import { workflowApi } from '@/services/api/workflowApi';

/** All workflow runs. */
export function useWorkflows() {
  return useAsync(() => workflowApi.list(), [], { initialData: [] });
}

/** Workflow runs for a single project. */
export function useProjectWorkflows(projectId) {
  return useAsync(() => workflowApi.listByProject(projectId), [projectId], {
    initialData: [],
  });
}
