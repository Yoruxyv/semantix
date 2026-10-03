import type { AuthStatus } from '@/features/auth/context/AuthContext';

export const EVALUATION_DATASET_PAGE_SIZE = 12;
export const EVALUATION_DATASET_CONTROL_CLASS =
  'font-data mt-2 min-h-11 w-full border border-(--hairline) bg-(--surface) px-3 py-2 text-xs text-(--text) outline-none focus-visible:border-(--gold) focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--gold)';

export function defaultSaveNamespace(
  authStatus: AuthStatus,
  namespaces: string[],
): string {
  if (authStatus === 'disabled') {
    return 'default';
  }
  return namespaces.length === 1 ? (namespaces[0] ?? '') : '';
}

export function defaultListNamespace(
  authStatus: AuthStatus,
  namespaces: string[],
  hasGlobalNamespace: boolean,
): string {
  if (authStatus !== 'authenticated' || hasGlobalNamespace) {
    return '';
  }
  return namespaces[0] ?? '';
}
