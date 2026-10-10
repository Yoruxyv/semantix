import type { ApiResult } from '@/shared/api/types';
import { request, withSignal } from '@/shared/api/httpClient';

import type {
  EvaluationRunComparisonRequest,
  EvaluationRunComparisonResponse,
} from '../comparisonTypes';
import { decodeEvaluationRunComparison } from './comparisonDecoders';

/**
 * POST caller-selected baseline/candidate IDs, forwarding optional cancellation.
 * The server authorizes Viewer access to both retained aggregates, then evaluates
 * compatibility; it neither reruns providers nor applies a live cache threshold.
 */
export async function compareEvaluationRuns(
  payload: EvaluationRunComparisonRequest,
  signal?: AbortSignal,
): Promise<ApiResult<EvaluationRunComparisonResponse>> {
  return request(
    '/api/v1/evaluations/runs/compare',
    decodeEvaluationRunComparison,
    withSignal(
      {
        method: 'POST',
        body: JSON.stringify(payload),
      },
      signal,
    ),
  );
}
