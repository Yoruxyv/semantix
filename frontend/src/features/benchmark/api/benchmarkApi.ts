import type { ApiResult } from '@/shared/api/types';
import type {
  BenchmarkDatasetListResponse,
  BenchmarkRunResponse,
  EvaluationDatasetPreview,
  EvaluationDatasetValidationRequest,
  EvaluationRunRequest,
  EvaluationRunHistoryDetail,
  EvaluationRunHistoryListResponse,
  DeleteEvaluationRunHistoryResponse,
  DeletePersistedEvaluationDatasetResponse,
  PersistedEvaluationDatasetDetail,
  PersistedEvaluationDatasetListResponse,
  PersistEvaluationDatasetRequest,
} from '../types';
import {
  decodeBenchmarkDatasets,
  decodeBenchmarkRun,
  decodeDeletePersistedEvaluationDataset,
  decodeEvaluationDatasetPreview,
  decodePersistedEvaluationDatasetDetail,
  decodePersistedEvaluationDatasets,
} from './benchmarkDecoders';
import {
  decodeDeleteEvaluationRunHistory,
  decodeEvaluationRunHistoryDetail,
  decodeEvaluationRunHistoryList,
} from './historyDecoders';
import { request, withSignal } from '@/shared/api/httpClient';

export async function getBenchmarkDatasets(
  signal?: AbortSignal,
): Promise<ApiResult<BenchmarkDatasetListResponse>> {
  return request(
    '/api/v1/evaluations/datasets',
    decodeBenchmarkDatasets,
    withSignal({ method: 'GET' }, signal),
  );
}

export async function runBenchmark(
  payload: EvaluationRunRequest,
  signal?: AbortSignal,
): Promise<ApiResult<BenchmarkRunResponse>> {
  return request(
    '/api/v1/evaluations/runs',
    decodeBenchmarkRun,
    withSignal(
      {
        method: 'POST',
        body: JSON.stringify(payload),
      },
      signal,
    ),
  );
}

export async function validateEvaluationDataset(
  payload: EvaluationDatasetValidationRequest,
  signal?: AbortSignal,
): Promise<ApiResult<EvaluationDatasetPreview>> {
  return request(
    '/api/v1/evaluations/datasets/validate',
    decodeEvaluationDatasetPreview,
    withSignal(
      {
        method: 'POST',
        body: JSON.stringify(payload),
      },
      signal,
    ),
  );
}

function namespaceQuery(namespace?: string): string {
  return namespace === undefined || namespace.trim() === ''
    ? ''
    : `?namespace=${encodeURIComponent(namespace.trim())}`;
}

export async function getPersistedEvaluationDatasets(
  options: {
    namespace?: string;
    offset?: number;
    limit?: number;
  } = {},
  signal?: AbortSignal,
): Promise<ApiResult<PersistedEvaluationDatasetListResponse>> {
  const parameters = new URLSearchParams();
  if (options.namespace?.trim()) {
    parameters.set('namespace', options.namespace.trim());
  }
  parameters.set('offset', String(options.offset ?? 0));
  parameters.set('limit', String(options.limit ?? 20));

  return request(
    `/api/v1/evaluations/datasets/persisted?${parameters.toString()}`,
    decodePersistedEvaluationDatasets,
    withSignal({ method: 'GET' }, signal),
  );
}

export async function getPersistedEvaluationDataset(
  datasetId: string,
  signal?: AbortSignal,
): Promise<ApiResult<PersistedEvaluationDatasetDetail>> {
  return request(
    `/api/v1/evaluations/datasets/persisted/${encodeURIComponent(datasetId)}`,
    decodePersistedEvaluationDatasetDetail,
    withSignal({ method: 'GET' }, signal),
  );
}

export async function persistEvaluationDataset(
  payload: PersistEvaluationDatasetRequest,
  signal?: AbortSignal,
): Promise<ApiResult<PersistedEvaluationDatasetDetail>> {
  return request(
    '/api/v1/evaluations/datasets/persisted',
    decodePersistedEvaluationDatasetDetail,
    withSignal(
      {
        method: 'POST',
        body: JSON.stringify(payload),
      },
      signal,
    ),
  );
}

export async function deletePersistedEvaluationDataset(
  datasetId: string,
  namespace?: string,
  signal?: AbortSignal,
): Promise<ApiResult<DeletePersistedEvaluationDatasetResponse>> {
  return request(
    `/api/v1/evaluations/datasets/persisted/${encodeURIComponent(
      datasetId,
    )}${namespaceQuery(namespace)}`,
    decodeDeletePersistedEvaluationDataset,
    withSignal({ method: 'DELETE' }, signal),
  );
}

export async function getEvaluationRunHistory(
  options: {
    namespace?: string;
    offset?: number;
    limit?: number;
  } = {},
  signal?: AbortSignal,
): Promise<ApiResult<EvaluationRunHistoryListResponse>> {
  const parameters = new URLSearchParams();
  if (options.namespace?.trim()) {
    parameters.set('namespace', options.namespace.trim());
  }
  parameters.set('offset', String(options.offset ?? 0));
  parameters.set('limit', String(options.limit ?? 20));

  return request(
    `/api/v1/evaluations/runs?${parameters.toString()}`,
    decodeEvaluationRunHistoryList,
    withSignal({ method: 'GET' }, signal),
  );
}

export async function getEvaluationRunHistoryDetail(
  runId: string,
  signal?: AbortSignal,
): Promise<ApiResult<EvaluationRunHistoryDetail>> {
  return request(
    `/api/v1/evaluations/runs/${encodeURIComponent(runId)}`,
    decodeEvaluationRunHistoryDetail,
    withSignal({ method: 'GET' }, signal),
  );
}

export async function deleteEvaluationRunHistory(
  runId: string,
  namespace: string,
  signal?: AbortSignal,
): Promise<ApiResult<DeleteEvaluationRunHistoryResponse>> {
  return request(
    `/api/v1/evaluations/runs/${encodeURIComponent(runId)}${namespaceQuery(namespace)}`,
    decodeDeleteEvaluationRunHistory,
    withSignal({ method: 'DELETE' }, signal),
  );
}
