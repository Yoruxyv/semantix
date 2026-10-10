/**
 * Browser cache HTTP adapter: request() attaches the stored bearer token and maps
 * handled transport/HTTP/decoder failures to ApiResult; setup can still reject.
 * The server enforces roles and namespaces. Reconstructed responses discard
 * unknown fields and expose sensitive prompt/answer text, without embeddings.
 */
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

/** Validate finite nonnegative observations and a [0, 1] hit rate, not fleet-wide authority. */
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

/**
 * Validate key/namespace syntax and nonempty prompt/preview, not access rights.
 * Missing/null full responses normalize to null; supplied strings must be nonempty.
 * Date.parse guards accept more than strict ISO; expiry and remaining TTL must
 * agree only in nullability. Hits are nonnegative integers, rank starts at 1,
 * and is_expired remains a server observation rather than a local time check.
 */
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
    /** Legacy 240-character previews ending in ... only imply truncation. */
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

/**
 * Require integer pagination, limit 1-100, items <= limit, and has_more equal to
 * offset + returned items < total. Concurrent expiry/mutation can shift pages.
 */
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

/** GET /api/v1/cache/stats without a namespace filter; scope is server-resolved. */
export function getCacheStats(
  signal?: AbortSignal,
): Promise<ApiResult<CacheStatsResponse>> {
  return request(
    '/api/v1/cache/stats',
    decodeCacheStats,
    withSignal({ method: 'GET' }, signal),
  );
}

/**
 * GET /api/v1/cache/entries with offset/limit/sort and nonempty trimmed filters.
 * Omitted namespace permits global scope for wildcard principals, infers a sole
 * allowed namespace, or is rejected for multiple restricted namespaces. List
 * rows carry previews; the current server leaves their full response null.
 */
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

/**
 * GET /api/v1/cache/entries/{key} for authorized detail, without confirming reuse.
 * Missing, expired and out-of-scope entries share the server's not-found response.
 */
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

/** DELETE /api/v1/cache/entries/{key}; the server requires admin and entry scope. */
export function deleteCacheEntry(
  cacheKey: string,
): Promise<ApiResult<DeleteCacheEntryResponse>> {
  return request(
    `/api/v1/cache/entries/${encodeURIComponent(cacheKey)}`,
    decodeDeleteCacheEntry,
    { method: 'DELETE' },
  );
}

/**
 * DELETE /api/v1/cache, including namespace exactly when supplied. Omission is
 * global only for wildcard admins; a sole restricted namespace is inferred and
 * ambiguous restricted scope is rejected. Search/sort/page do not limit clearing.
 */
export function clearCache(namespace?: string): Promise<ApiResult<ClearCacheResponse>> {
  const query = new URLSearchParams();
  if (namespace !== undefined) {
    query.set('namespace', namespace);
  }
  const suffix = query.size === 0 ? '' : `?${query.toString()}`;

  return request(`/api/v1/cache${suffix}`, decodeClearCache, { method: 'DELETE' });
}

/** GET /api/v1/cache/threshold for the server's current global value. */
export function getCacheThreshold(
  signal?: AbortSignal,
): Promise<ApiResult<CacheThresholdResponse>> {
  return request(
    '/api/v1/cache/threshold',
    decodeCacheThreshold,
    withSignal({ method: 'GET' }, signal),
  );
}

/** PUT /api/v1/cache/threshold with { threshold }; the server requires wildcard admin. */
export function updateCacheThreshold(
  threshold: number,
): Promise<ApiResult<CacheThresholdResponse>> {
  return request('/api/v1/cache/threshold', decodeCacheThreshold, {
    method: 'PUT',
    body: JSON.stringify({ threshold }),
  });
}
