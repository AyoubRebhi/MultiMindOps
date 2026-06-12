import { useAsync } from './useAsync';
import { workspaceApi } from '@/services/api/workspaceApi';

/** The current workspace. */
export function useWorkspace() {
  return useAsync(() => workspaceApi.get(), []);
}

/** Workspace recent-activity stream. */
export function useWorkspaceActivity() {
  return useAsync(() => workspaceApi.getActivity(), [], { initialData: [] });
}
