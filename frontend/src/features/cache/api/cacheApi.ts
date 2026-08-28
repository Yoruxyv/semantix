import type {
  CacheEntryListParams,
  CacheEntryListResponse,
  CacheEntryMetadata,
  CacheStatsResponse,
  CacheThresholdResponse,
  ClearCacheResponse,
  DeleteCacheEntryResponse,
} from '../types';
import type { ApiResult } from '@/shared/api/types';
import { request, withSignal } from '@/shared/api/httpClient';
import { isCacheNamespace } from '../namespace';
import {
  isIsoDate,
  isNonEmptyString,
  isNonNegativeNumber,
  isNonNegativeInteger,
  isNullableIsoDate,
  isNullableNonNegativeNumber,
  isNumberInRange,
  isRecord,
  isSha256Hex,
} from '@/shared/api/validators';

const LEGACY_RESPONSE_PREVIEW_LENGTH = 240;

function decodeCacheStats(value: unknown): CacheStatsResponse {
  if (
    !isRecord(value) ||
    !isNonNegativeNumber(value.size) ||
    !isNonNegativeNumber(value.hits) ||
    !isNonNegativeNumber(value.misses) ||
    !isNumberInRange(value.hit_rate, 0, 1)
  ) {
    throw new Error('Invalid cache stats response');
  }

  return {
    size: value.size,
    hits: value.hits,
    misses: value.misses,
    hit_rate: value.hit_rate,
  };
}

function decodeCacheEntry(value: unknown): CacheEntryMetadata {
  if (
    !isRecord(value) ||
    !isSha256Hex(value.cache_key) ||
    typeof value.namespace !== 'string' ||
    !isCacheNamespace(value.namespace) ||
    !isNonEmptyString(value.prompt) ||
    !isNonEmptyString(value.response_preview) ||
    (value.response_preview_truncated !== undefined &&
      typeof value.response_preview_truncated !== 'boolean') ||
    (value.response !== undefined &&
      value.response !== null &&
      !isNonEmptyString(value.response)) ||
    !isIsoDate(value.created_at) ||
    !isNullableIsoDate(value.expires_at) ||
    !isNullableNonNegativeNumber(value.remaining_ttl_seconds) ||
    !isNonNegativeInteger(value.hit_count) ||
    !isNullableIsoDate(value.last_accessed_at) ||
    !isNonNegativeInteger(value.recency_rank) ||
    value.recency_rank < 1 ||
    typeof value.is_expired !== 'boolean'
  ) {
    throw new Error('Invalid cache-entry metadata');
  }

  const hasValidExpiry =
    value.expires_at === null
      ? value.remaining_ttl_seconds === null
      : value.remaining_ttl_seconds !== null;

  if (!hasValidExpiry) {
    throw new Error('Invalid cache-entry timestamps');
  }

  return {
    cache_key: value.cache_key,
    namespace: value.namespace,
    prompt: value.prompt,
    response_preview: value.response_preview,
    response_preview_truncated:
      value.response_preview_truncated ??
      (value.response_preview.length === LEGACY_RESPONSE_PREVIEW_LENGTH &&
        value.response_preview.endsWith('...')),
    response: value.response ?? null,
    created_at: value.created_at,
    expires_at: value.expires_at,
    remaining_ttl_seconds: value.remaining_ttl_seconds,
    hit_count: value.hit_count,
    last_accessed_at: value.last_accessed_at,
    recency_rank: value.recency_rank,
    is_expired: value.is_expired,
  };
}

function decodeCacheEntryList(value: unknown): CacheEntryListResponse {
  if (
    !isRecord(value) ||
    !Array.isArray(value.items) ||
    !isNonNegativeInteger(value.total) ||
    !isNonNegativeInteger(value.offset) ||
    !isNonNegativeInteger(value.limit) ||
    !isNumberInRange(value.limit, 1, 100) ||
    typeof value.has_more !== 'boolean'
  ) {
    throw new Error('Invalid cache-entry list');
  }

  const items = value.items.map(decodeCacheEntry);
  const expectedHasMore = value.offset + items.length < value.total;

  if (items.length > value.limit || value.has_more !== expectedHasMore) {
    throw new Error('Invalid cache-entry page');
  }

  return {
    items,
    total: value.total,
    offset: value.offset,
    limit: value.limit,
    has_more: value.has_more,
  };
}

function decodeClearCache(value: unknown): ClearCacheResponse {
  if (!isRecord(value) || value.cleared !== true) {
    throw new Error('Invalid clear-cache response');
  }

  return { cleared: true };
}

function decodeDeleteCacheEntry(value: unknown): DeleteCacheEntryResponse {
  if (!isRecord(value) || value.deleted !== true || !isSha256Hex(value.cache_key)) {
    throw new Error('Invalid delete-cache-entry response');
  }

  return {
    deleted: true,
    cache_key: value.cache_key,
  };
}

function decodeCacheThreshold(value: unknown): CacheThresholdResponse {
  if (!isRecord(value) || !isNumberInRange(value.threshold, 0, 1)) {
    throw new Error('Invalid cache-threshold response');
  }

  return { threshold: value.threshold };
}

export function getCacheStats(
  signal?: AbortSignal,
): Promise<ApiResult<CacheStatsResponse>> {
  return request(
    '/api/v1/cache/stats',
    decodeCacheStats,
    withSignal({ method: 'GET' }, signal),
  );
}

export function listCacheEntries(
  params: CacheEntryListParams,
  signal?: AbortSignal,
): Promise<ApiResult<CacheEntryListResponse>> {
  const query = new URLSearchParams({
    offset: String(params.offset),
    limit: String(params.limit),
    sort: params.sort,
  });
  const namespace = params.namespace.trim();
  const search = params.search.trim();
  if (namespace !== '') {
    query.set('namespace', namespace);
  }
  if (search !== '') {
    query.set('search', search);
  }

  return request(
    `/api/v1/cache/entries?${query.toString()}`,
    decodeCacheEntryList,
    withSignal({ method: 'GET' }, signal),
  );
}

export function getCacheEntry(
  cacheKey: string,
  signal?: AbortSignal,
): Promise<ApiResult<CacheEntryMetadata>> {
  return request(
    `/api/v1/cache/entries/${encodeURIComponent(cacheKey)}`,
    decodeCacheEntry,
    withSignal({ method: 'GET' }, signal),
  );
}

export function deleteCacheEntry(
  cacheKey: string,
): Promise<ApiResult<DeleteCacheEntryResponse>> {
  return request(
    `/api/v1/cache/entries/${encodeURIComponent(cacheKey)}`,
    decodeDeleteCacheEntry,
    { method: 'DELETE' },
  );
}

export function clearCache(namespace?: string): Promise<ApiResult<ClearCacheResponse>> {
  const query = new URLSearchParams();
  if (namespace !== undefined) {
    query.set('namespace', namespace);
  }
  const suffix = query.size === 0 ? '' : `?${query.toString()}`;

  return request(`/api/v1/cache${suffix}`, decodeClearCache, { method: 'DELETE' });
}

export function getCacheThreshold(
  signal?: AbortSignal,
): Promise<ApiResult<CacheThresholdResponse>> {
  return request(
    '/api/v1/cache/threshold',
    decodeCacheThreshold,
    withSignal({ method: 'GET' }, signal),
  );
}

export function updateCacheThreshold(
  threshold: number,
): Promise<ApiResult<CacheThresholdResponse>> {
  return request('/api/v1/cache/threshold', decodeCacheThreshold, {
    method: 'PUT',
    body: JSON.stringify({ threshold }),
  });
}
