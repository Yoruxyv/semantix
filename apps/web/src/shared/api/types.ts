export interface ApiValidationIssue {
  code: string;
  detail: string;
  pointer: string;
  case_id?: string;
  case_index?: number;
}

/**
 * Handled API failure. Null status means no HTTP response is attached; malformed
 * HTTP responses retain their status. Valid envelopes may add issues and positive
 * Retry-After delta seconds; that metadata does not schedule a retry.
 */
export interface ApiError {
  code: string;
  detail: string | null;
  issues?: ApiValidationIssue[];
  retryAfterSeconds?: number;
  status: number | null;
}

/** A handled request outcome; setup exceptions can still reject the promise. */
export type ApiResult<T> = { ok: true; data: T } | { ok: false; error: ApiError };
