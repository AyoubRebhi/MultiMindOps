import { useAsync } from './useAsync';
import { userApi } from '@/services/api/userApi';

/** All workspace members. */
export function useUsers() {
  return useAsync(() => userApi.list(), [], { initialData: [] });
}
