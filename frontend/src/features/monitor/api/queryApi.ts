import type { QueryRequest, QueryResponse } from '../types';
import type { ApiResult } from '@/shared/api/types';
import { request, withSignal } from '@/shared/api/httpClient';
import {
  isNonEmptyString,
  isNonNegativeNumber,
  isNullableIsoDate,
  isNullableFiniteNumber,
  isNullableNonNegativeNumber,
  isNullableString,
  isNumberInRange,
  isRecord,
  isSha256Hex,
} from '@/shared/api/validators';
import {
  SIMILARITY_MAX,
  SIMILARITY_MIN,
  THRESHOLD_MAX,
  THRESHOLD_MIN,
} from '@/shared/domain/similarity';

function decodeQueryResponse(value: unknown): QueryResponse {
  if (
    !isRecord(value) ||
    typeof value.response !== 'string' ||
    typeof value.cache_hit !== 'boolean' ||
    !isNumberInRange(value.similarity_threshold, THRESHOLD_MIN, THRESHOLD_MAX) ||
    !isNullableString(value.matched_prompt) ||
    !isNullableString(value.matched_cache_key) ||
    !isNullableIsoDate(value.cache_entry_created_at) ||
    !isNullableNonNegativeNumber(value.cache_entry_age_seconds) ||
    typeof value.generation_skipped !== 'boolean' ||
    typeof value.provider_called !== 'boolean' ||
    !isNonNegativeNumber(value.latency_ms) ||
    !isNullableFiniteNumber(value.similarity_score)
  ) {
    throw new Error('Invalid query response');
  }

  const hasValidMatchMetadata = value.cache_hit
    ? value.similarity_score !== null &&
      value.similarity_score >= value.similarity_threshold &&
      isNonEmptyString(value.matched_prompt) &&
      isSha256Hex(value.matched_cache_key) &&
      value.cache_entry_created_at !== null &&
      value.cache_entry_age_seconds !== null &&
      value.generation_skipped &&
      !value.provider_called
    : value.matched_prompt === null &&
      value.matched_cache_key === null &&
      value.cache_entry_created_at === null &&
      value.cache_entry_age_seconds === null &&
      value.generation_skipped !== value.provider_called;

  if (
    !hasValidMatchMetadata ||
    (value.similarity_score !== null &&
      !isNumberInRange(value.similarity_score, SIMILARITY_MIN, SIMILARITY_MAX))
  ) {
    throw new Error('Invalid query explainability metadata');
  }

  return {
    response: value.response,
    cache_hit: value.cache_hit,
    similarity_score: value.similarity_score,
    similarity_threshold: value.similarity_threshold,
    matched_prompt: value.matched_prompt,
    matched_cache_key: value.matched_cache_key,
    cache_entry_created_at: value.cache_entry_created_at,
    cache_entry_age_seconds: value.cache_entry_age_seconds,
    generation_skipped: value.generation_skipped,
    provider_called: value.provider_called,
    latency_ms: value.latency_ms,
  };
}

export function submitQuery(
  payload: QueryRequest,
  signal?: AbortSignal,
): Promise<ApiResult<QueryResponse>> {
  return request(
    '/api/v1/query',
    decodeQueryResponse,
    withSignal(
      {
        method: 'POST',
        body: JSON.stringify(payload),
      },
      signal,
    ),
  );
}
