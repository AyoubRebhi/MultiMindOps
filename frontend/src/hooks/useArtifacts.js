import { useAsync } from './useAsync';
import { artifactApi } from '@/services/api/artifactApi';

/** All generated artifacts. */
export function useArtifacts() {
  return useAsync(() => artifactApi.list(), [], { initialData: [] });
}

/** Artifacts for a single project. */
export function useProjectArtifacts(projectId) {
  return useAsync(() => artifactApi.listByProject(projectId), [projectId], {
    initialData: [],
  });
}
