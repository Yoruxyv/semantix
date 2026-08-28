import { useQuery } from '@tanstack/react-query';
import { useCallback } from 'react';

import type { ApiError } from '@/shared/api/types';
import { apiErrorFromUnknown, dataFromApiResult } from '@/shared/query/apiResult';
import { runtimeMetricsKeys } from '@/shared/query/queryKeys';
import { getRuntimeMetrics } from '../api/metricsApi';
import type { RuntimeMetrics } from '../types';

export const RUNTIME_METRICS_REFRESH_INTERVAL_MS = 5_000;

type MetricsState =
  | { status: 'loading' }
  | { status: 'ready'; data: RuntimeMetrics }
  | { status: 'error'; error: ApiError };

interface RuntimeMetricsController {
  isRefreshing: boolean;
  refreshError: ApiError | null;
  state: MetricsState;
  refresh: () => void;
}

export function useRuntimeMetrics(): RuntimeMetricsController {
  const query = useQuery({
    queryKey: runtimeMetricsKeys.live(),
    queryFn: async ({ signal }) => dataFromApiResult(await getRuntimeMetrics(signal)),
    gcTime: 5 * 60 * 1_000,
    staleTime: RUNTIME_METRICS_REFRESH_INTERVAL_MS,
    refetchInterval: (currentQuery) =>
      currentQuery.state.fetchStatus === 'fetching'
        ? false
        : RUNTIME_METRICS_REFRESH_INTERVAL_MS,
    refetchIntervalInBackground: false,
  });

  let state: MetricsState;
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
    isRefreshing: query.isFetching,
    refreshError:
      query.data !== undefined && query.isError
        ? apiErrorFromUnknown(query.error)
        : null,
    state,
    refresh,
  };
}
