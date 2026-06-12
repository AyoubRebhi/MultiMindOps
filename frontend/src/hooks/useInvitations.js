import { useAsync } from './useAsync';
import { invitationApi } from '@/services/api/invitationApi';

/** All workspace invitations. */
export function useInvitations() {
  return useAsync(() => invitationApi.list(), [], { initialData: [] });
}
