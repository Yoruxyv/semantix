import { useQuery } from '@tanstack/react-query';
import { useCallback } from 'react';

import type { ApiError } from '@/shared/api/types';
import { apiErrorFromUnknown, dataFromApiResult } from '@/shared/query/apiResult';
import { runtimeDiagnosticsKeys } from '@/shared/query/queryKeys';

import { getRuntimeDiagnostics } from '../api/metricsApi';
import type { RuntimeDiagnostics } from '../types';

export const RUNTIME_DIAGNOSTICS_STALE_TIME_MS = 30_000;

type DiagnosticsState =
  | { status: 'loading' }
  | { status: 'ready'; data: RuntimeDiagnostics }
  | { status: 'error'; error: ApiError };

interface RuntimeDiagnosticsController {
  isRefreshing: boolean;
  isStale: boolean;
  refreshError: ApiError | null;
  state: DiagnosticsState;
  refresh: () => void;
}

export function useRuntimeDiagnostics(): RuntimeDiagnosticsController {
  const query = useQuery({
    queryKey: runtimeDiagnosticsKeys.live(),
    queryFn: async ({ signal }) =>
      dataFromApiResult(await getRuntimeDiagnostics(signal)),
    gcTime: 5 * 60 * 1_000,
    staleTime: RUNTIME_DIAGNOSTICS_STALE_TIME_MS,
  });

  let state: DiagnosticsState;
  if (query.data !== undefined) {
    state = { status: 'ready', data: query.data };
  } else if (query.isError) {
    state = {
      status: 'error',
      error: apiErrorFromUnknown(query.error),
    };
  } else {
    state = { status: 'loading' };
  }

  const refresh = useCallback((): void => {
    if (!query.isFetching) {
      query.refetch({ cancelRefetch: false });
    }
  }, [query]);

  return {
    isRefreshing: query.isFetching && query.data !== undefined,
    isStale: query.isStale,
    refreshError:
      query.data !== undefined && query.isError
        ? apiErrorFromUnknown(query.error)
        : null,
    state,
    refresh,
  };
}
