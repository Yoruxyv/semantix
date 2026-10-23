import { ApiResultError } from '@/shared/query/apiResult';

export function mutationFailure(error: unknown, action: 'delete' | 'clear'): string {
  if (
    error instanceof ApiResultError &&
    error.status !== null &&
    error.status >= 400 &&
    error.status < 500
  ) {
    return (
      error.detail ??
      (action === 'delete'
        ? 'The cache entry was not deleted.'
        : 'The cache was not cleared.')
    );
  }
  return action === 'delete'
    ? 'Deletion could not be confirmed. Refresh the cache before trying again.'
    : 'Clearing could not be confirmed. Refresh the cache before trying again.';
}

export function mutationRefreshWarning(action: 'delete' | 'clear'): string {
  return `${action === 'delete' ? 'Cache entry deleted.' : 'Cache cleared.'} Follow-up refresh failed; refresh the page to update the readings.`;
}
