import { useAsync } from './useAsync';
import { awsCredentialsApi } from '@/services/api/awsCredentialsApi';

/** The workspace AWS credentials (secrets masked). */
export function useAwsCredentials() {
  return useAsync(() => awsCredentialsApi.get(), []);
}
