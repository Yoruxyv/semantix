import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router';

import { useAuth } from '@/features/auth/hooks/useAuth';
import { canDeleteCacheEntries } from '@/features/auth/permissions';
import { apiErrorFromUnknown, dataFromApiResult } from '@/shared/query/apiResult';
import { cacheEntryKeys } from '@/shared/query/queryKeys';

import { clearCache, deleteCacheEntry, listCacheEntries } from '../api/cacheApi';
import type { CacheEntryListResponse, CacheEntrySort } from '../types';
import { mutationFailure, mutationRefreshWarning } from '../mutationFeedback';

const PAGE_SIZE = 10;

export type CacheMutation = 'delete' | 'clear';

interface UseCacheInspectorOptions {
  onMutation: (mutation: CacheMutation) => void | Promise<void>;
}

export interface CacheInspectorController {
  actionError: string | null;
  actionWarning: string | null;
  canDelete: boolean;
  canClearAll: boolean;
  cancelClear: () => void;
  cancelDelete: () => void;
  confirmClear: boolean;
  confirmClearCache: () => Promise<void>;
  confirmDeleteEntry: (cacheKey: string) => Promise<void>;
  data: CacheEntryListResponse | null;
  hasNext: boolean;
  hasPrevious: boolean;
  isClearing: boolean;
  isLoading: boolean;
  isMutating: boolean;
  isRefreshing: boolean;
  loadError: string | null;
  refreshError: string | null;
  mutation: string | null;
  namespace: string;
  nextPage: () => void;
  pendingDelete: string | null;
  previousPage: () => void;
  refresh: () => void;
  requestClear: () => void;
  requestDelete: (cacheKey: string) => void;
  search: string;
  setSearch: (search: string) => void;
  setNamespace: (namespace: string) => void;
  setSort: (sort: CacheEntrySort) => void;
  sort: CacheEntrySort;
  visibleEnd: number;
  visibleStart: number;
}

function errorDetail(error: unknown, fallback: string): string {
  return apiErrorFromUnknown(error).detail ?? fallback;
}

/**
 * Own URL-backed search/namespace/sort/offset, ten-row pages and local confirmations.
 * Unknown sorts use newest; unsafe/negative offsets use zero. Trimmed filters and
 * pagination identify list queries, without becoming durable server filter state.
 * Search/sort changes reset offset and pending deletion; namespace also cancels
 * clear confirmation. Previously loaded data survives refresh errors.
 * Session changes dismiss confirmations; capability checks are UI hints only.
 */
export function useCacheInspector({
  onMutation,
}: Readonly<UseCacheInspectorOptions>): CacheInspectorController {
  const auth = useAuth();
  const canDelete = canDeleteCacheEntries(auth.status, auth.session);
  const canClearAll =
    canDelete &&
    (auth.status === 'disabled' || auth.session?.namespaces.includes('*') === true);
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const search = searchParams.get('search') ?? '';
  const namespace = searchParams.get('namespace') ?? '';
  const requestedSort = searchParams.get('sort');
  const sort: CacheEntrySort =
    requestedSort === 'oldest' ||
    requestedSort === 'most_hit' ||
    requestedSort === 'nearest_expiry'
      ? requestedSort
      : 'newest';
  const requestedOffset = Number(searchParams.get('offset') ?? 0);
  const offset =
    Number.isSafeInteger(requestedOffset) && requestedOffset >= 0 ? requestedOffset : 0;
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionWarning, setActionWarning] = useState<string | null>(null);
  const [mutation, setMutation] = useState<string | null>(null);
  const activeMutation = useRef(false);
  const generation = useRef(0);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);

  useEffect(() => {
    setPendingDelete(null);
    setConfirmClear(false);
    setActionError(null);
    setActionWarning(null);
    setMutation(null);
    activeMutation.current = false;
    return () => {
      generation.current += 1;
    };
  }, [auth.status, auth.session]);

  const params = {
    offset,
    limit: PAGE_SIZE,
    namespace: namespace.trim(),
    search: search.trim(),
    sort,
  };
  /** The 20-second freshness and five-minute inactive retention are client policy, not entry TTL. */
  const entriesQuery = useQuery({
    queryKey: cacheEntryKeys.list(params),
    queryFn: async ({ signal }) =>
      dataFromApiResult(await listCacheEntries(params, signal)),
    staleTime: 20 * 1_000,
    gcTime: 5 * 60 * 1_000,
  });
  /** Mutation settlement records only the server response; follow-up work is separate. */
  const deleteMutation = useMutation({
    mutationFn: async (cacheKey: string) =>
      dataFromApiResult(await deleteCacheEntry(cacheKey)),
  });
  const clearMutation = useMutation({
    mutationFn: async (selectedNamespace: string | undefined) =>
      dataFromApiResult(await clearCache(selectedNamespace)),
  });

  /** Pending manual refreshes are deduplicated; refetch does not cancel an active read. */
  const manualRefresh = useMutation({
    mutationFn: () => entriesQuery.refetch({ cancelRefetch: false }),
  });

  const data = entriesQuery.data ?? null;
  const loadError =
    data === null && entriesQuery.isError
      ? errorDetail(entriesQuery.error, 'Cache inspector data could not be loaded.')
      : null;
  const refreshError =
    data !== null && entriesQuery.isError
      ? errorDetail(entriesQuery.error, 'Cache inspector data could not be refreshed.')
      : null;

  function refresh(): void {
    if (!manualRefresh.isPending) {
      manualRefresh.mutate();
    }
  }

  function updateSearch(nextSearch: string): void {
    setSearchParams(
      (current) => {
        const next = new URLSearchParams(current);
        if (nextSearch === '') {
          next.delete('search');
        } else {
          next.set('search', nextSearch);
        }
        next.delete('offset');
        return next;
      },
      { replace: true },
    );
    setPendingDelete(null);
  }

  function updateNamespace(nextNamespace: string): void {
    setSearchParams(
      (current) => {
        const next = new URLSearchParams(current);
        if (nextNamespace === '') {
          next.delete('namespace');
        } else {
          next.set('namespace', nextNamespace);
        }
        next.delete('offset');
        return next;
      },
      { replace: true },
    );
    setConfirmClear(false);
    setPendingDelete(null);
  }

  function updateSort(nextSort: CacheEntrySort): void {
    setSearchParams(
      (current) => {
        const next = new URLSearchParams(current);
        if (nextSort === 'newest') {
          next.delete('sort');
        } else {
          next.set('sort', nextSort);
        }
        next.delete('offset');
        return next;
      },
      { replace: true },
    );
    setPendingDelete(null);
  }

  function updateOffset(nextOffset: number): void {
    setSearchParams(
      (current) => {
        const next = new URLSearchParams(current);
        if (nextOffset === 0) {
          next.delete('offset');
        } else {
          next.set('offset', String(nextOffset));
        }
        return next;
      },
      { replace: true },
    );
  }

  function requestClear(): void {
    if (!canDelete) return;
    setPendingDelete(null);
    setConfirmClear(true);
  }

  function cancelClear(): void {
    setConfirmClear(false);
  }

  function requestDelete(cacheKey: string): void {
    if (!canDelete) return;
    setConfirmClear(false);
    setPendingDelete(cacheKey);
  }

  function cancelDelete(): void {
    setPendingDelete(null);
  }

  /** Follow-up failures cannot change the confirmed remote outcome. */
  async function confirmDeleteEntry(cacheKey: string): Promise<void> {
    if (!canDelete || activeMutation.current) return;
    activeMutation.current = true;
    const owner = generation.current;
    setMutation(cacheKey);
    setActionError(null);
    setActionWarning(null);

    try {
      try {
        await deleteMutation.mutateAsync(cacheKey);
      } catch (error: unknown) {
        if (owner === generation.current)
          setActionError(mutationFailure(error, 'delete'));
        return;
      }
      queryClient.removeQueries({
        queryKey: cacheEntryKeys.detail(cacheKey),
        exact: true,
      });
      await queryClient.invalidateQueries({ queryKey: cacheEntryKeys.lists() });
      if (owner !== generation.current) return;
      setPendingDelete(null);
      updateOffset(0);
      await onMutation('delete');
    } catch {
      if (owner === generation.current)
        setActionWarning(mutationRefreshWarning('delete'));
    } finally {
      if (owner === generation.current) {
        activeMutation.current = false;
        setMutation(null);
      }
    }
  }

  /**
   * Blank namespace omits scope for server resolution; search/page never constrain
   * clearing. Follow-up/callback errors do not prove the remote clear was undone.
   */
  async function confirmClearCache(): Promise<void> {
    if (!canDelete || activeMutation.current) return;
    activeMutation.current = true;
    const owner = generation.current;
    setMutation('clear');
    setActionError(null);
    setActionWarning(null);

    const selectedNamespace = namespace.trim();
    try {
      try {
        await clearMutation.mutateAsync(
          selectedNamespace === '' ? undefined : selectedNamespace,
        );
      } catch (error: unknown) {
        if (owner === generation.current)
          setActionError(mutationFailure(error, 'clear'));
        return;
      }
      queryClient.removeQueries({ queryKey: cacheEntryKeys.details() });
      await queryClient.invalidateQueries({ queryKey: cacheEntryKeys.lists() });
      if (owner !== generation.current) return;
      setConfirmClear(false);
      setPendingDelete(null);
      updateOffset(0);
      await onMutation('clear');
    } catch {
      if (owner === generation.current)
        setActionWarning(mutationRefreshWarning('clear'));
    } finally {
      if (owner === generation.current) {
        activeMutation.current = false;
        setMutation(null);
      }
    }
  }

  const visibleStart = data === null || data.total === 0 ? 0 : data.offset + 1;
  const visibleEnd =
    data === null ? 0 : Math.min(data.offset + data.items.length, data.total);

  return {
    actionError,
    actionWarning,
    canDelete,
    canClearAll,
    cancelClear,
    cancelDelete,
    confirmClear,
    confirmClearCache,
    confirmDeleteEntry,
    data,
    hasNext: data?.has_more ?? false,
    hasPrevious: data !== null && data.offset > 0,
    isClearing: mutation === 'clear',
    isLoading: data === null && entriesQuery.isPending,
    isMutating: mutation !== null,
    isRefreshing: manualRefresh.isPending,
    loadError,
    refreshError,
    mutation,
    namespace,
    nextPage: () => updateOffset(offset + PAGE_SIZE),
    pendingDelete,
    previousPage: () => updateOffset(Math.max(0, offset - PAGE_SIZE)),
    refresh,
    requestClear,
    requestDelete,
    search,
    setSearch: updateSearch,
    setNamespace: updateNamespace,
    setSort: updateSort,
    sort,
    visibleEnd,
    visibleStart,
  };
}
