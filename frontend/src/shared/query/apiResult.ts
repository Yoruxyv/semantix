import type { ApiError, ApiResult } from '../api/types';

export class ApiResultError extends Error {
  readonly code: string;
  readonly detail: string | null;
  readonly status: number | null;

  constructor(error: ApiError) {
    super(error.detail ?? error.code);
    this.name = 'ApiResultError';
    this.code = error.code;
    this.detail = error.detail;
    this.status = error.status;
  }
}

export function dataFromApiResult<T>(result: ApiResult<T>): T {
  if (!result.ok) {
    throw new ApiResultError(result.error);
  }

  return result.data;
}

export function apiErrorFromUnknown(error: unknown): ApiError {
  if (error instanceof ApiResultError) {
    return {
      code: error.code,
      detail: error.detail,
      status: error.status,
    };
  }

  return {
    code: 'unexpected_error',
    detail: error instanceof Error ? error.message : 'An unexpected error occurred.',
    status: null,
  };
}
