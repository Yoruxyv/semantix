export interface CacheStatsResponse {
  size: number;
  hits: number;
  misses: number;
  hit_rate: number;
}

export interface ClearCacheResponse {
  cleared: true;
}

export type CacheEntrySort = 'newest' | 'oldest' | 'most_hit' | 'nearest_expiry';

export interface CacheEntryMetadata {
  cache_key: string;
  namespace: string;
  prompt: string;
  response_preview: string;
  response_preview_truncated: boolean;
  response: string | null;
  created_at: string;
  expires_at: string | null;
  remaining_ttl_seconds: number | null;
  hit_count: number;
  last_accessed_at: string | null;
  recency_rank: number;
  is_expired: boolean;
}

export interface CacheEntryListResponse {
  items: CacheEntryMetadata[];
  total: number;
  offset: number;
  limit: number;
  has_more: boolean;
}

export interface CacheEntryListParams {
  offset: number;
  limit: number;
  namespace: string;
  search: string;
  sort: CacheEntrySort;
}

export interface DeleteCacheEntryResponse {
  deleted: true;
  cache_key: string;
}

export interface CacheThresholdResponse {
  threshold: number;
}
