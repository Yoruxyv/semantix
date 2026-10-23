import type { QueryClient } from '@tanstack/react-query';
import {
  act,
  cleanup,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
} from '@testing-library/react';
import type { ReactNode } from 'react';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { QueryTestProvider } from '../QueryTestProvider';
import { createTestQueryClient } from '../queryClient';
import {
  AuthContext,
  type AuthContextValue,
  type AuthStatus,
} from '@/features/auth/context/AuthContext';
import { useAuth } from '@/features/auth/hooks/useAuth';
import type { AuthRole } from '@/features/auth/types';
import {
  clearCache,
  deleteCacheEntry,
  getCacheEntry,
  listCacheEntries,
} from '@/features/cache/api/cacheApi';
import { CacheInspector } from '@/features/cache/components/CacheInspector';
import { useCacheInspector } from '@/features/cache/hooks/useCacheInspector';
import type { CacheEntryMetadata } from '@/features/cache/types';

vi.mock('../../../src/features/cache/api/cacheApi');

const actualAuth = await vi.importActual<{ useAuth: typeof useAuth }>(
  '@/features/auth/hooks/useAuth',
);
const entry: CacheEntryMetadata = {
  cache_key: 'a'.repeat(64),
  namespace: 'tenant-alpha',
  prompt: 'Synthetic Inspector permission entry',
  response_preview: 'Synthetic response preview',
  response_preview_truncated: false,
  response: null,
  created_at: '2026-10-23T00:00:00Z',
  expires_at: null,
  remaining_ttl_seconds: null,
  hit_count: 2,
  last_accessed_at: null,
  recency_rank: 1,
  is_expired: false,
};
let client: QueryClient;
const onMutation = vi.fn();

function access(
  status: AuthStatus = 'authenticated',
  role: AuthRole = 'admin',
  namespaces = ['*'],
): AuthContextValue {
  return {
    status,
    session:
      status === 'disabled' ? null : { name: 'synthetic-user', role, namespaces },
    error: null,
    lockedUntil: null,
    authenticate: vi.fn(async () => false),
    logout: vi.fn(),
    retryAccessPolicy: vi.fn(),
  };
}

function inspector(auth: AuthContextValue, initialEntry = '/cache') {
  return (
    <AuthContext.Provider value={auth}>
      <QueryTestProvider client={client}>
        <MemoryRouter initialEntries={[initialEntry]}>
          <CacheInspector onMutation={onMutation} />
        </MemoryRouter>
      </QueryTestProvider>
    </AuthContext.Provider>
  );
}

function expectReadOnly(): void {
  expect(screen.queryAllByRole('button', { name: /^(Delete|Clear)/ })).toHaveLength(0);
  expect(screen.queryByRole('group', { name: /^Confirm/ })).toBeNull();
  expect(deleteCacheEntry).not.toHaveBeenCalled();
  expect(clearCache).not.toHaveBeenCalled();
}

beforeEach(() => {
  client = createTestQueryClient();
  // The shared setup mocks useAuth; delegate to its real context-reading hook here.
  vi.mocked(useAuth).mockImplementation(actualAuth.useAuth);
  vi.mocked(listCacheEntries).mockImplementation(async (params) => ({
    ok: true,
    data: {
      items: [{ ...entry, namespace: params.namespace || entry.namespace }],
      total: 21,
      offset: params.offset,
      limit: params.limit,
      has_more: params.offset < 20,
    },
  }));
  vi.mocked(getCacheEntry).mockResolvedValue({
    ok: true,
    data: { ...entry, response: 'Synthetic complete response' },
  });
  vi.mocked(deleteCacheEntry).mockResolvedValue({
    ok: true,
    data: { deleted: true, cache_key: entry.cache_key },
  });
  vi.mocked(clearCache).mockResolvedValue({ ok: true, data: { cleared: true } });
});

afterEach(() => {
  cleanup();
  client.clear();
  vi.clearAllMocks();
});

describe('Cache Inspector permissions', () => {
  it.each<AuthRole>(['viewer', 'operator'])(
    'keeps inspection, filters, pagination, refresh and full response for %s',
    async (role) => {
      vi.mocked(listCacheEntries).mockImplementation(async (params) => ({
        ok: true,
        data: {
          items: [{ ...entry, response_preview_truncated: true }],
          total: 21,
          offset: params.offset,
          limit: params.limit,
          has_more: params.offset < 20,
        },
      }));
      render(inspector(access('authenticated', role, ['tenant-alpha'])));
      await screen.findByText(entry.prompt);
      expectReadOnly();

      fireEvent.change(screen.getByLabelText('Search cached prompts'), {
        target: { value: 'Synthetic' },
      });
      fireEvent.change(screen.getByLabelText('Sort cache entries'), {
        target: { value: 'oldest' },
      });
      fireEvent.change(screen.getByLabelText('Namespace'), {
        target: { value: 'tenant-alpha' },
      });
      await screen.findByRole('button', { name: 'Next' });
      fireEvent.click(screen.getByRole('button', { name: 'Next' }));
      await waitFor(() => {
        expect(listCacheEntries).toHaveBeenCalledWith(
          {
            offset: 10,
            limit: 10,
            search: 'Synthetic',
            sort: 'oldest',
            namespace: 'tenant-alpha',
          },
          expect.any(AbortSignal),
        );
      });
      await screen.findByText('11-11 of 21 entries');
      fireEvent.click(screen.getByRole('button', { name: 'Previous' }));
      await screen.findByText('1-1 of 21 entries');
      const reads = vi.mocked(listCacheEntries).mock.calls.length;
      fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));
      await waitFor(() =>
        expect(vi.mocked(listCacheEntries).mock.calls.length).toBeGreaterThan(reads),
      );
      fireEvent.click(
        screen.getByRole('button', { name: 'Inspect complete response' }),
      );
      await screen.findByText('Synthetic complete response');
      expect(getCacheEntry).toHaveBeenCalledWith(
        entry.cache_key,
        expect.any(AbortSignal),
      );
      expectReadOnly();
    },
  );

  it.each<AuthStatus>(['loading', 'unauthenticated', 'error', 'session-error'])(
    'hides destructive actions for %s even with a stale admin session',
    async (status) => {
      render(inspector(access(status)));
      await screen.findByText(entry.prompt);
      expectReadOnly();
    },
  );

  it.each<AuthStatus>(['authenticated', 'disabled'])(
    'preserves destructive confirmations and mutations in %s admin-capable mode',
    async (status) => {
      render(inspector(access(status)));
      await screen.findByText(entry.prompt);
      fireEvent.click(screen.getByRole('button', { name: `Delete ${entry.prompt}` }));
      expect(deleteCacheEntry).not.toHaveBeenCalled();
      fireEvent.click(
        screen.getByRole('button', { name: `Confirm delete ${entry.prompt}` }),
      );
      await waitFor(() => expect(onMutation).toHaveBeenCalledWith('delete'));
      expect(deleteCacheEntry).toHaveBeenCalledExactlyOnceWith(entry.cache_key);
      fireEvent.click(screen.getByRole('button', { name: 'Clear all entries' }));
      expect(clearCache).not.toHaveBeenCalled();
      fireEvent.click(screen.getByRole('button', { name: 'Confirm clear cache' }));
      await waitFor(() => expect(onMutation).toHaveBeenCalledWith('clear'));
      expect(clearCache).toHaveBeenCalledExactlyOnceWith(undefined);
    },
  );

  it.each([
    ['viewer', 'delete'],
    ['operator', 'delete'],
    ['viewer', 'clear'],
    ['operator', 'clear'],
  ] as const)(
    'invalidates open %s/%s confirmation when admin capability is lost',
    async (role, action) => {
      const admin = access();
      const view = render(inspector(admin));
      await screen.findByText(entry.prompt);
      fireEvent.click(
        screen.getByRole('button', {
          name: action === 'delete' ? `Delete ${entry.prompt}` : 'Clear all entries',
        }),
      );
      const obsoleteConfirm = screen.getByRole('button', {
        name:
          action === 'delete'
            ? `Confirm delete ${entry.prompt}`
            : 'Confirm clear cache',
      });
      view.rerender(inspector(access('authenticated', role, ['tenant-alpha'])));
      expectReadOnly();
      fireEvent.click(obsoleteConfirm);
      expectReadOnly();
      fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));
      await screen.findByText(entry.prompt);
      view.rerender(inspector(admin));
      expect(screen.queryByRole('group', { name: /^Confirm/ })).toBeNull();
      expect(deleteCacheEntry).not.toHaveBeenCalled();
      expect(clearCache).not.toHaveBeenCalled();
    },
  );

  it.each<AuthRole>(['viewer', 'operator'])(
    'defensively blocks current controller requests and confirms after demotion to %s',
    async (role) => {
      let current = access();
      const view = renderHook(() => useCacheInspector({ onMutation }), {
        wrapper: ({ children }: Readonly<{ children: ReactNode }>) => (
          <AuthContext.Provider value={current}>
            <QueryTestProvider client={client}>
              <MemoryRouter>{children}</MemoryRouter>
            </QueryTestProvider>
          </AuthContext.Provider>
        ),
      });
      act(() => view.result.current.requestDelete(entry.cache_key));
      current = access('authenticated', role, ['tenant-alpha']);
      view.rerender();
      await act(async () => {
        view.result.current.requestDelete(entry.cache_key);
        view.result.current.requestClear();
        await view.result.current.confirmDeleteEntry(entry.cache_key);
        await view.result.current.confirmClearCache();
      });
      expect(view.result.current.pendingDelete).toBeNull();
      expect(view.result.current.confirmClear).toBe(false);
      expect(deleteCacheEntry).not.toHaveBeenCalled();
      expect(clearCache).not.toHaveBeenCalled();
    },
  );

  it('does not imply deployment-wide clearing for a sole-namespace admin', async () => {
    render(inspector(access('authenticated', 'admin', ['tenant-alpha'])));
    await screen.findByText(entry.prompt);
    expect(screen.queryByRole('button', { name: 'Clear all entries' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Clear cache' }));
    expect(
      screen.queryByText(
        'Clear every cache entry and reset all backend cache statistics?',
      ),
    ).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Confirm clear cache' }));
    await waitFor(() => expect(clearCache).toHaveBeenCalledExactlyOnceWith(undefined));
  });

  it('preserves explicit namespace selection for a multi-namespace admin', async () => {
    render(
      inspector(
        access('authenticated', 'admin', ['tenant-alpha', 'tenant-beta']),
        '/cache?namespace=tenant-beta',
      ),
    );
    await screen.findByText(entry.prompt);
    fireEvent.click(screen.getByRole('button', { name: 'Clear namespace' }));
    expect(
      screen.getByText('Clear every entry and reset statistics for tenant-beta?'),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Confirm clear cache' }));
    await waitFor(() =>
      expect(clearCache).toHaveBeenCalledExactlyOnceWith('tenant-beta'),
    );
  });

  it.each(['/cache', '/cache?namespace=foreign'])(
    'retains denied list feedback without enabling clear for restricted scope %s',
    async (path) => {
      vi.mocked(listCacheEntries).mockResolvedValue({
        ok: false,
        error: { code: 'forbidden', detail: 'Synthetic namespace denied', status: 403 },
      });
      render(
        inspector(
          access('authenticated', 'admin', ['tenant-alpha', 'tenant-beta']),
          path,
        ),
      );
      await screen.findByText('Synthetic namespace denied');
      const clear = screen.getByRole<HTMLButtonElement>('button', { name: /^Clear/ });
      expect(clear.disabled).toBe(true);
      fireEvent.click(clear);
      expect(screen.queryByRole('group', { name: /^Confirm/ })).toBeNull();
      expect(clearCache).not.toHaveBeenCalled();
      expect(deleteCacheEntry).not.toHaveBeenCalled();
    },
  );
});
