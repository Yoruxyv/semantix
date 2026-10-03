export interface ApiValidationIssue {
  code: string;
  detail: string;
  pointer: string;
  case_id?: string;
  case_index?: number;
}

export interface ApiError {
  code: string;
  detail: string | null;
  issues?: ApiValidationIssue[];
  retryAfterSeconds?: number;
  status: number | null;
}

export type ApiResult<T> = { ok: true; data: T } | { ok: false; error: ApiError };
