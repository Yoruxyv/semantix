/**
 * Evaluations HTTP boundary: serialize caller payloads and decode responses.
 * Shared request() adds browser credentials and maps handled fetch/JSON/decoder
 * failures; serialization and header/credential setup can still reject. It adds
 * no retry, total timeout, body-size cap or universal error sanitization.
 * Workflows own state/query caching; server routes enforce roles and namespaces.
 * Catalog/history list omission is global only for wildcard principals; a sole
 * restricted scope is inferred, while multiple restricted scopes need a choice.
 * Saves/deletes require concrete scope, with sole restricted-scope inference.
 * All operations forward optional signals; abort does not certify remote rollback.
 */
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

/**
 * POST an evaluation-run request; the legacy exported name does not use /benchmarks.
 * The server requires Operator access and executes against an isolated cache.
 * Successful execution and best-effort history retention have separate outcomes.
 */
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

/** POST a provider-free import preview (Operator); neither saves nor runs it. */
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

/** List configured storage evidence with trimmed scope and explicit offset/limit (0/20). */
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

/** Fetch authorized dataset detail by encoded ID; cases can contain raw prompts. */
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

/** Explicit Operator save; serialize caller scope/retention, subject to enabled storage. */
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

/** Admin deletion; blank/absent namespace is omitted and resolved by the server. */
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

/** List retained aggregates with trimmed scope and offset/limit (0/20); storage may be disabled. */
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

/** Fetch authorized aggregate/threshold evidence by encoded ID, without raw cases. */
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

/** Admin deletion; required namespace still passes through the helper's blank omission. */
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
