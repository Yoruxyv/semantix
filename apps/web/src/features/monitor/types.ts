import type { ApiError } from '@/shared/api/types';

/** Browser payload; QueryForm supplies the selected namespace and policy flags. */
export interface QueryRequest {
  prompt: string;
  namespace?: string;
  cache_enabled?: boolean;
  cache_read_enabled?: boolean;
  cache_write_enabled?: boolean;
  private?: boolean;
}

export type QueryPolicyMode = 'normal' | 'read-only' | 'refresh' | 'bypass' | 'private';

export const QUERY_POLICY_LABELS: Record<QueryPolicyMode, string> = {
  normal: 'Normal read and write',
  'read-only': 'Read only',
  refresh: 'Refresh and write',
  bypass: 'Bypass cache',
  private: 'Private request',
};

/** Pair the wire payload with its local presentation mode; only request is sent. */
export interface QuerySubmission {
  policyMode: QueryPolicyMode;
  request: QueryRequest;
}

/** Submitted namespace/mode context, separate from server-returned match evidence. */
export interface QueryEvidence {
  namespace: string;
  policyMode: QueryPolicyMode;
}

/** Decoded server evidence; nullable fields stay null and timestamps stay strings. */
export interface QueryResponse {
  response: string;
  cache_hit: boolean;
  similarity_score: number | null;
  similarity_threshold: number;
  matched_prompt: string | null;
  matched_cache_key: string | null;
  cache_entry_created_at: string | null;
  cache_entry_age_seconds: number | null;
  generation_skipped: boolean;
  provider_called: boolean;
  latency_ms: number;
}

export type QueryState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'success'; data: QueryResponse }
  | { status: 'error'; error: ApiError };

/**
 * Local presentation record, with a browser timestamp. MonitorProvider bounds
 * this in-memory list and omits private requests; it is not durable run history.
 */
export interface QueryTrace {
  id: string;
  prompt: string;
  similarity: number | null;
  latencyMs: number;
  recordedAt: Date;
  actualCacheHit: boolean;
  namespace: string;
  policyMode: QueryPolicyMode;
  providerCalled: boolean;
}
