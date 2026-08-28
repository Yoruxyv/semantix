import { QueryClient } from '@tanstack/react-query';

import { ApiResultError } from './apiResult';

export const DEFAULT_QUERY_GC_TIME_MS = 5 * 60 * 1_000;

function isDeterministicClientError(error: unknown): boolean {
  if (!(error instanceof ApiResultError)) {
    return false;
  }

  if (error.code === 'authentication_required' || error.code === 'invalid_token') {
    return true;
  }

  return error.status !== null && error.status >= 400 && error.status < 500;
}

export function createAppQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      mutations: {
        retry: false,
      },
      queries: {
        gcTime: DEFAULT_QUERY_GC_TIME_MS,
        refetchOnWindowFocus: false,
        retry: (failureCount, error) =>
          !isDeterministicClientError(error) && failureCount < 1,
      },
    },
  });
}
