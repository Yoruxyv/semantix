import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { createMemoryRouter } from 'react-router';
import { RouterProvider } from 'react-router/dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useAuth } from '@/features/auth/hooks/useAuth';
import { CacheControlProvider } from '@/features/cache/context/CacheControlContext';
import { CacheInspector } from '@/features/cache/components/CacheInspector';
import { useCacheControl } from '@/features/cache/hooks/useCacheControl';
import { CacheEntryDetailPage } from '@/features/cache/pages/CacheEntryDetailPage';
import { CachePage } from '@/features/cache/pages/CachePage';
import type { CacheEntryMetadata } from '@/features/cache/types';
import { MonitorProvider } from '@/features/monitor/context/MonitorContext';
import { cacheEntryKeys } from '@/shared/query/queryKeys';
import { QueryTestProvider } from '../QueryTestProvider';
import { createTestQueryClient } from '../queryClient';
import { deferred } from '../support';

const entry: CacheEntryMetadata = {
  cache_key: 'a'.repeat(64),
  namespace: 'default',
  prompt: 'Synthetic deletion evidence',
  response_preview: 'Retained readable response.',
  response_preview_truncated: false,
  response: null,
  created_at: '2026-10-23T10:00:00Z',
  expires_at: null,
  remaining_ttl_seconds: null,
  hit_count: 0,
  last_accessed_at: null,
  recency_rank: 1,
  is_expired: false,
};
const params = {
  offset: 0,
  limit: 10,
  namespace: '',
  search: '',
  sort: 'newest' as const,
};
const unknownDelete =
  'Deletion could not be confirmed. Refresh the cache before trying again.';
const unknownClear =
  'Clearing could not be confirmed. Refresh the cache before trying again.';
const refreshWarning =
  'Cache statistics and threshold could not be refreshed. Showing the last confirmed readings.';
let client = createTestQueryClient();
let removed: boolean;
let writes: string[];
let failure: 'none' | 'deny' | 'disconnect' | 'list' | 'stats' | 'storage';
let pendingStats: ReturnType<typeof deferred<Response>> | null;
let pendingWrite: ReturnType<typeof deferred<void>> | null;
const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), { status });

function Readings() {
  const { cacheState } = useCacheControl();
  return <output aria-label="Readings state">{cacheState.status}</output>;
}

function mount(path = '/cache', onMutation?: () => Promise<void>) {
  const router = createMemoryRouter(
    [
      {
        path: '/cache',
        element:
          onMutation === undefined ? (
            <CachePage />
          ) : (
            <CacheInspector onMutation={onMutation} />
          ),
      },
      { path: '/cache/entries/:cacheKey', element: <CacheEntryDetailPage /> },
      { path: '/other', element: <p>Another page</p> },
    ],
    { initialEntries: [path] },
  );
  const view = render(
    <QueryTestProvider client={client}>
      <CacheControlProvider>
        <MonitorProvider>
          <Readings />
          <RouterProvider router={router} />
        </MonitorProvider>
      </CacheControlProvider>
    </QueryTestProvider>,
  );
  return { ...view, router };
}

const labels = {
  list: {
    request: `Delete ${entry.prompt}`,
    confirm: `Confirm delete ${entry.prompt}`,
  },
  detail: { request: 'Delete cache entry', confirm: 'Confirm delete' },
  clear: { request: 'Clear all entries', confirm: 'Confirm clear cache' },
};
async function confirm(flow: keyof typeof labels) {
  await screen.findByText(entry.prompt);
  await waitFor(() =>
    expect(screen.getByLabelText('Readings state').textContent).toBe('ready'),
  );
  fireEvent.click(screen.getByRole('button', { name: labels[flow].request }));
  fireEvent.click(screen.getByRole('button', { name: labels[flow].confirm }));
  await waitFor(() => expect(writes).toHaveLength(1));
}
function requestPath(input: string | URL | Request) {
  if (typeof input === 'string') return new URL(input).pathname;
  return new URL(input instanceof URL ? input.href : input.url).pathname;
}
async function handleWrite(path: string) {
  writes.push(path);
  if (pendingWrite !== null) await pendingWrite.promise;
  if (failure === 'deny')
    return json(
      { error: 'permission_denied', detail: 'This operation is not allowed.' },
      403,
    );
  removed = true;
  if (failure === 'disconnect') throw new TypeError('Disconnected /private/internal');
  if (failure === 'storage')
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('Private storage detail', 'SecurityError');
    });
  return json(
    path.endsWith(entry.cache_key)
      ? { deleted: true, cache_key: entry.cache_key }
      : { cleared: true },
  );
}
function readStats(): Response | Promise<Response> {
  if (removed && pendingStats !== null) return pendingStats.promise;
  if (removed && failure === 'stats')
    return json(
      { error: 'unavailable', detail: 'Stats temporarily unavailable.' },
      503,
    );
  return json({ size: removed ? 0 : 1, hits: 0, misses: 0, hit_rate: 0 });
}

function handleRead(path: string): Response | Promise<Response> {
  if (path.endsWith('/stats')) return readStats();
  if (path.endsWith('/threshold')) return json({ threshold: 0.92 });
  if (path.endsWith('/entries')) {
    if (removed && failure === 'list')
      return json(
        { error: 'unavailable', detail: 'Listing temporarily unavailable.' },
        503,
      );
    return json({
      items: removed ? [] : [entry],
      total: removed ? 0 : 1,
      offset: 0,
      limit: 10,
      has_more: false,
    });
  }
  if (path.endsWith(entry.cache_key)) return json(entry);
  throw new Error(`Unexpected fixture request: ${path}`);
}

beforeEach(() => {
  client = createTestQueryClient();
  removed = false;
  writes = [];
  failure = 'none';
  pendingStats = null;
  pendingWrite = null;
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const path = requestPath(input);
      return init?.method === 'DELETE' ? handleWrite(path) : handleRead(path);
    }),
  );
});

afterEach(() => {
  cleanup();
  client.clear();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('confirmed and unconfirmed cache mutation outcomes', () => {
  it.each(['list', 'detail', 'clear'] as const)(
    'invalidates confirmed %s even if its page unmounts before the response',
    async (flow) => {
      pendingWrite = deferred<void>();
      const stale = cacheEntryKeys.list({ ...params, namespace: 'another' });
      client.setQueryData(stale, { items: [entry] });
      client.setQueryData(cacheEntryKeys.detail(entry.cache_key), entry);
      const { unmount } = mount(
        flow === 'detail' ? `/cache/entries/${entry.cache_key}` : '/cache',
      );
      await confirm(flow);
      unmount();
      await act(async () => {
        pendingWrite?.resolve();
      });
      await waitFor(() =>
        expect(client.getQueryState(stale)?.isInvalidated).toBe(true),
      );
      expect(
        client.getQueryData(cacheEntryKeys.detail(entry.cache_key)),
      ).toBeUndefined();
      expect(writes).toHaveLength(1);
    },
  );
  it.each(['list', 'detail', 'clear'] as const)(
    'keeps %s success and invalidates only cache data',
    async (flow) => {
      const stale = cacheEntryKeys.list({ ...params, namespace: 'another' });
      client.setQueryData(stale, { items: [entry] });
      client.setQueryData(cacheEntryKeys.detail(entry.cache_key), entry);
      mount(flow === 'detail' ? `/cache/entries/${entry.cache_key}` : '/cache');
      await confirm(flow);
      await screen.findByText('The cache is empty.');
      if (flow === 'detail')
        expect(screen.getByText('Cache entry deleted.')).toBeTruthy();
      expect(client.getQueryState(stale)?.isInvalidated).toBe(true);
      expect(
        client.getQueryData(cacheEntryKeys.detail(entry.cache_key)),
      ).toBeUndefined();
      expect(screen.queryByText(/was not deleted|was not cleared/)).toBeNull();
      expect(writes).toHaveLength(1);
    },
  );

  it.each(['list', 'detail', 'clear'] as const)(
    'retains %s confirmation and readable data on explicit rejection',
    async (flow) => {
      failure = 'deny';
      mount(flow === 'detail' ? `/cache/entries/${entry.cache_key}` : '/cache');
      await confirm(flow);
      expect(await screen.findByRole('alert')).toBeTruthy();
      expect(screen.getByText(entry.prompt)).toBeTruthy();
      expect(
        screen.getByRole('button', {
          name: labels[flow].confirm,
        }),
      ).toBeTruthy();
      expect(removed).toBe(false);
      expect(writes).toHaveLength(1);
    },
  );

  it.each(['list', 'detail', 'clear'] as const)(
    'reports %s lost confirmation as unknown without retry',
    async (flow) => {
      failure = 'disconnect';
      mount(flow === 'detail' ? `/cache/entries/${entry.cache_key}` : '/cache');
      await confirm(flow);
      expect((await screen.findByRole('alert')).textContent).toBe(
        flow === 'clear' ? unknownClear : unknownDelete,
      );
      expect(screen.queryByText(/private\/internal/)).toBeNull();
      expect(screen.getByText(entry.prompt)).toBeTruthy();
      expect(writes).toHaveLength(1);
    },
  );

  it.each(['list', 'clear'] as const)(
    'does not turn %s list-refetch failure into mutation failure',
    async (flow) => {
      failure = 'list';
      mount();
      await confirm(flow);
      expect(
        await screen.findByText(
          /Listing temporarily unavailable.*Cached entries remain visible/,
        ),
      ).toBeTruthy();
      expect(screen.getByText(entry.prompt)).toBeTruthy();
      expect(screen.queryByRole('alert')).toBeNull();
      expect(writes).toHaveLength(1);
    },
  );

  it.each(['list', 'detail', 'clear'] as const)(
    'keeps %s success and exposes handled statistics-refresh failure separately',
    async (flow) => {
      failure = 'stats';
      mount(flow === 'detail' ? `/cache/entries/${entry.cache_key}` : '/cache');
      await confirm(flow);
      expect(await screen.findByText(refreshWarning)).toBeTruthy();
      expect(await screen.findByText('The cache is empty.')).toBeTruthy();
      if (flow === 'detail')
        expect(screen.getByText('Cache entry deleted.')).toBeTruthy();
      expect(screen.queryByText(/was not deleted|was not cleared/)).toBeNull();
      expect(writes).toHaveLength(1);
    },
  );

  it.each(['list', 'clear'] as const)(
    'keeps confirmed %s when its supplied callback rejects',
    async (flow) => {
      const onMutation = vi.fn(async () => {
        throw new Error('Private callback detail');
      });
      mount('/cache', onMutation);
      await confirm(flow);
      expect(
        await screen.findByText(
          flow === 'clear'
            ? 'Cache cleared. Follow-up refresh failed; refresh the page to update the readings.'
            : 'Cache entry deleted. Follow-up refresh failed; refresh the page to update the readings.',
        ),
      ).toBeTruthy();
      expect(screen.getByText('The cache is empty.')).toBeTruthy();
      expect(
        screen.queryByText(/Private callback detail|was not deleted|was not cleared/),
      ).toBeNull();
      expect(onMutation).toHaveBeenCalledOnce();
      expect(writes).toHaveLength(1);
    },
  );

  it('navigates with confirmed success and a warning when real refresh setup rejects', async () => {
    failure = 'storage';
    mount(`/cache/entries/${entry.cache_key}`);
    await confirm('detail');
    expect(
      await screen.findByText(
        'Cache entry deleted. Follow-up refresh failed; refresh the page to update the readings.',
      ),
    ).toBeTruthy();
    expect(screen.queryByText('The cache entry was not deleted.')).toBeNull();
    expect(screen.queryByText(/Private storage detail/)).toBeNull();
    expect(writes).toHaveLength(1);
  });

  it('does not navigate back after leaving detail while the follow-up is pending', async () => {
    pendingStats = deferred<Response>();
    const { router } = mount(`/cache/entries/${entry.cache_key}`);
    await confirm('detail');
    await act(() => router.navigate('/other'));
    await act(async () => {
      pendingStats?.resolve(json({ size: 0, hits: 0, misses: 0, hit_rate: 0 }));
    });
    expect(router.state.location.pathname).toBe('/other');
    expect(screen.getByText('Another page')).toBeTruthy();
    expect(writes).toHaveLength(1);
  });
  it.each(['list', 'clear'] as const)(
    'waits for one %s callback without accepting a duplicate confirmation',
    async (flow) => {
      const followUp = deferred<void>();
      const callback = vi.fn(async () => {
        await followUp.promise;
        throw new Error('Late private failure');
      });
      const { unmount } = mount('/cache', callback);
      await confirm(flow);
      await waitFor(() => expect(callback).toHaveBeenCalledOnce());
      expect(writes).toHaveLength(1);
      expect(screen.queryByRole('button', { name: labels[flow].confirm })).toBeNull();
      unmount();
      await act(async () => {
        followUp.resolve();
      });
      expect(callback).toHaveBeenCalledOnce();
      expect(writes).toHaveLength(1);
    },
  );

  it.each(['list', 'detail', 'clear'] as const)(
    'discards %s follow-up UI after the principal changes',
    async (flow) => {
      pendingStats = deferred<Response>();
      const path = flow === 'detail' ? `/cache/entries/${entry.cache_key}` : '/cache';
      const { router } = mount(path);
      await confirm(flow);
      await waitFor(() =>
        expect(
          vi
            .mocked(fetch)
            .mock.calls.filter(([input]) => requestPath(input).endsWith('/stats')),
        ).toHaveLength(2),
      );
      vi.mocked(useAuth).mockReturnValue({
        ...vi.mocked(useAuth)(),
        status: 'authenticated',
        session: { name: 'viewer', role: 'viewer', namespaces: ['default'] },
      });
      await act(() => router.navigate(path + '?principal=changed'));
      await act(async () => {
        pendingStats?.resolve(json({ size: 0, hits: 0, misses: 0, hit_rate: 0 }));
      });
      expect(router.state.location.pathname).toBe(path);
      expect(screen.queryByRole('button', { name: labels[flow].request })).toBeNull();
      expect(screen.queryByRole('button', { name: labels[flow].confirm })).toBeNull();
      expect(writes).toHaveLength(1);
    },
  );
});
