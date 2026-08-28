import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  within,
  waitFor,
} from '@testing-library/react';
import { createMemoryRouter, MemoryRouter } from 'react-router';
import { RouterProvider } from 'react-router/dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import App from '@/App';
import { useAuth } from '@/features/auth/hooks/useAuth';
import type { AuthRole } from '@/features/auth/types';
import { useQuery } from '@/features/monitor/hooks/useQuery';
import {
  clearCache,
  deleteCacheEntry,
  getCacheEntry,
  getCacheStats,
  getCacheThreshold,
  listCacheEntries,
  updateCacheThreshold,
} from '@/features/cache/api/cacheApi';
import { getBenchmarkDatasets } from '@/features/benchmark/api/benchmarkApi';
import {
  getRuntimeDiagnostics,
  getRuntimeMetrics,
} from '@/features/observability/api/metricsApi';
import type { CacheEntryMetadata } from '@/features/cache/types';
import type { QueryResponse } from '@/features/monitor/types';

vi.mock('../../src/features/monitor/hooks/useQuery');
vi.mock('../../src/features/cache/api/cacheApi');
vi.mock('../../src/features/benchmark/api/benchmarkApi');
vi.mock('../../src/features/observability/api/metricsApi');

const queryResponse: QueryResponse = {
  response: 'Semantic caching reuses answers for meaningfully similar prompts.',
  cache_hit: false,
  similarity_score: 0.88,
  similarity_threshold: 0.9,
  matched_prompt: null,
  matched_cache_key: null,
  cache_entry_created_at: null,
  cache_entry_age_seconds: null,
  generation_skipped: false,
  provider_called: true,
  latency_ms: 125,
};

const cacheEntry: CacheEntryMetadata = {
  cache_key: 'a'.repeat(64),
  namespace: 'default',
  prompt: 'Explain semantic caching',
  response_preview: 'A cached explanation.',
  response_preview_truncated: false,
  response: null,
  created_at: '2026-07-17T09:00:00Z',
  expires_at: '2026-07-17T10:00:00Z',
  remaining_ttl_seconds: 3600,
  hit_count: 0,
  last_accessed_at: null,
  recency_rank: 1,
  is_expired: false,
};

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

function renderWithHistory() {
  const router = createMemoryRouter([{ path: '*', element: <App /> }], {
    initialEntries: ['/', '/cache'],
    initialIndex: 1,
  });

  return {
    router,
    ...render(<RouterProvider router={router} />),
  };
}

function renderLegacyRouteWithHistory() {
  const router = createMemoryRouter([{ path: '*', element: <App /> }], {
    initialEntries: ['/', '/benchmarks?dataset=quick#results'],
    initialIndex: 1,
  });

  return {
    router,
    ...render(<RouterProvider router={router} />),
  };
}

function useAuthenticatedPrincipal(
  role: AuthRole,
  namespaces: string[],
  name = `${role}-principal`,
): void {
  vi.mocked(useAuth).mockReturnValue({
    authenticate: vi.fn(async () => true),
    error: null,
    lockedUntil: null,
    logout: vi.fn(),
    retryAccessPolicy: vi.fn(),
    session: {
      name,
      role,
      namespaces,
    },
    status: 'authenticated',
  });
}

describe('application routing', () => {
  const submit = vi.fn();
  const writeClipboardText = vi.fn(async () => undefined);

  beforeEach(() => {
    vi.stubGlobal('crypto', {
      randomUUID: vi.fn(() => 'trace-id'),
    });
    vi.stubGlobal('scrollTo', vi.fn());
    Object.defineProperty(window.navigator, 'clipboard', {
      configurable: true,
      value: { writeText: writeClipboardText },
    });
    vi.mocked(useQuery).mockReturnValue({
      state: { status: 'idle' },
      submit,
    });
    submit.mockResolvedValue(queryResponse);

    vi.mocked(getCacheStats).mockResolvedValue({
      ok: true,
      data: { size: 1, hits: 3, misses: 2, hit_rate: 0.6 },
    });
    vi.mocked(getCacheThreshold).mockResolvedValue({
      ok: true,
      data: { threshold: 0.9 },
    });
    vi.mocked(updateCacheThreshold).mockResolvedValue({
      ok: true,
      data: { threshold: 0.8 },
    });
    vi.mocked(listCacheEntries).mockResolvedValue({
      ok: true,
      data: {
        items: [cacheEntry],
        total: 1,
        offset: 0,
        limit: 10,
        has_more: false,
      },
    });
    vi.mocked(getCacheEntry).mockResolvedValue({
      ok: true,
      data: cacheEntry,
    });
    vi.mocked(deleteCacheEntry).mockResolvedValue({
      ok: true,
      data: { deleted: true, cache_key: cacheEntry.cache_key },
    });
    vi.mocked(clearCache).mockResolvedValue({
      ok: true,
      data: { cleared: true },
    });
    vi.mocked(getBenchmarkDatasets).mockResolvedValue({
      ok: true,
      data: {
        datasets: [
          {
            dataset_id: 'quick',
            dataset_source: 'builtin',
            schema_version: null,
            version: '1.0.0',
            digest: 'd'.repeat(64),
            name: 'Quick semantic safety set',
            description: 'Controlled prompts.',
            query_count: 8,
            expected_hits: 4,
            expected_misses: 4,
            categories: [
              'seed',
              'exact_duplicate',
              'paraphrase',
              'unrelated',
              'typo',
              'negation',
              'different_intent',
            ],
          },
        ],
        default_dataset_id: 'quick',
      },
    });
    vi.mocked(getRuntimeMetrics).mockResolvedValue({
      ok: true,
      data: {
        observed_at: '2026-07-19T08:00:00Z',
        uptime_seconds: 120,
        request_count: 0,
        error_count: 0,
        cache_hits: 0,
        cache_misses: 0,
        provider_calls: 0,
        in_flight_coalesced_requests: 0,
        average_latency_ms: null,
        p95_latency_ms: null,
        latency_sample_size: 0,
        cache_size: 0,
        evictions: 0,
        expirations: 0,
      },
    });
    vi.mocked(getRuntimeDiagnostics).mockResolvedValue({
      ok: true,
      data: {
        observed_at: '2026-08-21T08:00:00Z',
        process_scope: 'single_backend_process',
        application_version: '1.0.0',
        embedding_provider_category: 'mock',
        generation_provider_category: 'mock',
        embedding_dimensions: 32,
        embedding_space_fingerprint: 'a'.repeat(64),
        generation_configuration_fingerprint: 'b'.repeat(64),
        cache_backend: 'memory',
        cache_readiness: 'ready',
        normalization_mode: 'identity',
        normalization_algorithm_version: 'identity-v1',
        normalization_fingerprint: 'c'.repeat(64),
        evaluation_timeout_seconds: 300,
        evaluation_max_cases: 50,
        evaluation_max_repetitions: 5,
        evaluation_max_thresholds: 15,
        evaluation_max_request_bytes: 65_536,
        evaluation_dataset_persistence_enabled: false,
        evaluation_history_persistence_enabled: false,
      },
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it.each([
    ['/', 'Probe the cache', 'Monitor', 'Monitor | Semantix'],
    ['/cache', 'Cache inspector', 'Cache', 'Cache | Semantix'],
    ['/evaluations', 'Evaluation laboratory', 'Evaluations', 'Evaluations | Semantix'],
    ['/observability', 'Observability', 'Observability', 'Observability | Semantix'],
  ])(
    'renders %s with an active navigation link and page title',
    async (path, heading, link, title) => {
      renderAt(path);

      expect(
        screen.getByRole('navigation', {
          name: 'Primary navigation',
        }),
      ).toBeTruthy();
      expect(
        await screen.findByRole(
          'heading',
          { level: 1, name: heading },
          { timeout: 10_000 },
        ),
      ).toBeTruthy();
      expect(
        screen.getByRole('link', { name: link }).getAttribute('aria-current'),
      ).toBe('page');
      expect(document.title).toBe(title);
    },
    10_000,
  );

  it('loads a live cache entry directly with Cache active', async () => {
    renderAt(`/cache/entries/${cacheEntry.cache_key}`);

    expect(
      await screen.findByRole('heading', {
        level: 1,
        name: 'Cache entry detail',
      }),
    ).toBeTruthy();
    expect(
      screen.getByRole('link', { name: 'Cache' }).getAttribute('aria-current'),
    ).toBe('page');
    expect(document.title).toBe('Cache | Semantix');
    expect(
      await screen.findByText(cacheEntry.response_preview, {}, { timeout: 10_000 }),
    ).toBeTruthy();
    expect(getCacheEntry).toHaveBeenCalledWith(
      cacheEntry.cache_key,
      expect.any(AbortSignal),
    );
  });

  it('rejects a malformed cache key without an API request', async () => {
    renderAt('/cache/entries/not-a-cache-key');

    expect(
      await screen.findByText(
        'This cache entry could not be found or is no longer available.',
        {},
        { timeout: 10_000 },
      ),
    ).toBeTruthy();
    expect(getCacheEntry).not.toHaveBeenCalled();
  });

  it('uses the same neutral detail state for a missing entry', async () => {
    vi.mocked(getCacheEntry).mockResolvedValue({
      ok: false,
      error: {
        code: 'cache_entry_not_found',
        detail: 'Cache entry not found.',
        status: 404,
      },
    });

    renderAt(`/cache/entries/${cacheEntry.cache_key}`);

    expect(
      await screen.findByText(
        'This cache entry could not be found or is no longer available.',
        {},
        { timeout: 10_000 },
      ),
    ).toBeTruthy();
    expect(screen.queryByText('Cache entry not found.')).toBeNull();
  }, 10_000);

  it('copies the cache key with accessible feedback', async () => {
    renderAt(`/cache/entries/${cacheEntry.cache_key}`);
    await screen.findByRole('heading', { name: cacheEntry.prompt });

    fireEvent.click(screen.getByRole('button', { name: 'Copy cache key' }));

    await waitFor(() =>
      expect(writeClipboardText).toHaveBeenCalledWith(cacheEntry.cache_key),
    );
    expect(await screen.findByText('Cache key copied.')).toBeTruthy();
  });

  it('hides detail deletion from a Viewer', async () => {
    useAuthenticatedPrincipal('viewer', ['default']);
    renderAt(`/cache/entries/${cacheEntry.cache_key}`);

    await screen.findByRole('heading', { name: cacheEntry.prompt });
    expect(screen.queryByRole('button', { name: 'Delete cache entry' })).toBeNull();
  });

  it('deletes as an Admin-capable principal and returns to Cache', async () => {
    renderAt(`/cache/entries/${cacheEntry.cache_key}`);
    await screen.findByRole('heading', { name: cacheEntry.prompt });
    const statsCallsBeforeDelete = vi.mocked(getCacheStats).mock.calls.length;

    fireEvent.click(screen.getByRole('button', { name: 'Delete cache entry' }));
    expect(
      screen.getByRole('group', {
        name: /Confirm deletion of cache entry/,
      }),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Confirm delete' }));

    expect(
      await screen.findByRole('heading', {
        level: 1,
        name: 'Cache inspector',
      }),
    ).toBeTruthy();
    expect(await screen.findByText('Cache entry deleted.')).toBeTruthy();
    expect(deleteCacheEntry).toHaveBeenCalledWith(cacheEntry.cache_key);
    expect(vi.mocked(getCacheStats).mock.calls.length).toBeGreaterThan(
      statsCallsBeforeDelete,
    );
  });

  it('restores Cache filters after opening and closing entry detail', async () => {
    renderAt('/cache?namespace=default&search=semantic&sort=oldest&offset=10');
    await screen.findByText(cacheEntry.prompt);

    fireEvent.click(screen.getByRole('link', { name: 'View entry details' }));
    await screen.findByRole('heading', { name: 'Cache entry detail' });
    fireEvent.click(screen.getByRole('link', { name: 'Back to Cache' }));

    expect(await screen.findByDisplayValue('semantic')).toBeTruthy();
    expect((screen.getByLabelText('Namespace') as HTMLInputElement).value).toBe(
      'default',
    );
    expect(
      (screen.getByLabelText('Sort cache entries') as HTMLSelectElement).value,
    ).toBe('oldest');
  });

  it('renders a useful not-found route', async () => {
    renderAt('/missing');

    expect(
      await screen.findByRole('heading', {
        level: 1,
        name: 'Signal not found',
      }),
    ).toBeTruthy();
    expect(
      screen.getByRole('link', { name: 'Return to Monitor' }).getAttribute('href'),
    ).toBe('/');
    expect(document.title).toBe('Page not found | Semantix');
  });

  it('uses one stable authentication gate instead of an empty workspace', () => {
    vi.mocked(useAuth).mockReturnValue({
      authenticate: vi.fn(async () => false),
      error: null,
      lockedUntil: null,
      logout: vi.fn(),
      retryAccessPolicy: vi.fn(),
      session: null,
      status: 'unauthenticated',
    });

    renderAt('/');

    const gateHeading = screen.getByRole('heading', {
      level: 1,
      name: 'Authentication required',
    });
    expect(gateHeading.closest('main')?.id).toBe('main-content');
    expect(screen.queryByText('Authenticate to load Semantix workspaces.')).toBeNull();
    expect(screen.queryByText('Probe the cache')).toBeNull();
  });

  it('shows the destination skeleton without authentication UI while policy loads', () => {
    vi.mocked(useAuth).mockReturnValue({
      authenticate: vi.fn(async () => false),
      error: null,
      lockedUntil: null,
      logout: vi.fn(),
      retryAccessPolicy: vi.fn(),
      session: null,
      status: 'loading',
    });

    const { container } = renderAt('/evaluations');

    expect(screen.getByLabelText('Loading workspace')).toBeTruthy();
    expect(
      container.querySelector('[data-workspace-skeleton="benchmark"]'),
    ).toBeTruthy();
    expect(screen.queryByText('Confirming workspace access')).toBeNull();
    expect(
      screen.queryByRole('heading', { name: 'Authentication required' }),
    ).toBeNull();
    expect(screen.queryByLabelText('Access token')).toBeNull();
  });

  it('keeps workspace queries unmounted when session verification fails', () => {
    vi.mocked(useAuth).mockReturnValue({
      authenticate: vi.fn(async () => false),
      error:
        'Session verification unavailable. Semantix could not verify the ' +
        'current authentication session. Please wait a moment and try again.',
      lockedUntil: null,
      logout: vi.fn(),
      retryAccessPolicy: vi.fn(),
      session: null,
      status: 'session-error',
    });

    renderAt('/cache');

    expect(
      screen.getByRole('heading', {
        name: 'Session verification paused',
      }),
    ).toBeTruthy();
    expect(screen.queryByLabelText('Access token')).toBeNull();
    expect(getCacheStats).not.toHaveBeenCalled();
    expect(listCacheEntries).not.toHaveBeenCalled();
  });

  it('loads the workspace directly when authentication is disabled', async () => {
    renderAt('/');

    expect(
      await screen.findByRole('heading', {
        level: 1,
        name: 'Probe the cache',
      }),
    ).toBeTruthy();
    expect(
      screen.queryByRole('heading', {
        name: 'Authentication required',
      }),
    ).toBeNull();
    expect(screen.queryByLabelText('Access token')).toBeNull();
  });

  it.each<AuthRole>(['viewer', 'operator', 'admin'])(
    'hides metrics and denies a direct route for a scoped %s',
    async (role) => {
      useAuthenticatedPrincipal(role, ['tenant-alpha']);

      renderAt('/observability');

      expect(screen.queryByRole('link', { name: 'Observability' })).toBeNull();
      expect(
        await screen.findByRole('heading', {
          level: 1,
          name: 'Global administrator access required',
        }),
      ).toBeTruthy();
      expect(getRuntimeMetrics).not.toHaveBeenCalled();
      expect(getRuntimeDiagnostics).not.toHaveBeenCalled();
    },
  );

  it('allows a global administrator to navigate directly to metrics', async () => {
    useAuthenticatedPrincipal('admin', ['*']);

    renderAt('/observability');

    expect(
      await screen.findByRole('heading', {
        level: 1,
        name: 'Observability',
      }),
    ).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Observability' })).toBeTruthy();
    await waitFor(() => expect(getRuntimeMetrics).toHaveBeenCalledOnce());
    await waitFor(() => expect(getRuntimeDiagnostics).toHaveBeenCalledOnce());
  });

  it.each([
    ['viewer', ['default'], false, false],
    ['operator', ['default'], true, false],
    ['admin', ['default'], true, false],
    ['admin', ['*'], true, true],
  ] as const)(
    'applies Monitor capabilities for %s with namespaces %s',
    async (role, namespaces, canQuery, canApplyThreshold) => {
      useAuthenticatedPrincipal(role, [...namespaces]);
      renderAt('/');

      const queryButton = screen.getByRole('button', {
        name: canQuery ? 'Run query' : 'Operator access required',
      });
      expect((queryButton as HTMLButtonElement).disabled).toBe(!canQuery);
      await screen.findByText('Backend applied 0.90');

      if (canApplyThreshold) {
        expect(screen.getByRole('button', { name: 'Apply to cache' })).toBeTruthy();
      } else {
        expect(screen.queryByRole('button', { name: 'Apply to cache' })).toBeNull();
        expect(screen.getByText(/Preview only/)).toBeTruthy();
      }
    },
  );

  it('clears Monitor-local evidence when the principal changes', async () => {
    useAuthenticatedPrincipal('operator', ['tenant-one'], 'first');
    const view = renderAt('/');

    fireEvent.change(await screen.findByLabelText('Query text'), {
      target: { value: 'First principal content' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Run query' }));
    expect(await screen.findByText('First principal content')).toBeTruthy();

    useAuthenticatedPrincipal('operator', ['tenant-two'], 'second');
    view.rerender(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>,
    );

    expect((screen.getByLabelText('Query text') as HTMLTextAreaElement).value).toBe('');
    expect(screen.queryByText('First principal content')).toBeNull();
    expect(screen.getByText(/namespace tenant-two/i)).toBeTruthy();
  });

  it('does not move focus on initial route rendering', async () => {
    renderAt('/cache');

    await screen.findByRole('heading', {
      level: 1,
      name: 'Cache inspector',
    });

    expect(document.activeElement).not.toBe(screen.getByRole('main'));
  });

  it('moves focus to main after link navigation', async () => {
    renderAt('/');
    await screen.findByRole('heading', {
      level: 1,
      name: 'Probe the cache',
    });

    const queryInput = screen.getByLabelText('Query text');
    const main = screen.getByRole('main');
    const focus = vi.spyOn(main, 'focus');
    queryInput.focus();
    fireEvent.click(screen.getByRole('link', { name: 'Cache' }));

    await screen.findByRole('heading', {
      level: 1,
      name: 'Cache inspector',
    });
    expect(document.activeElement).toBe(main);
    expect(focus).toHaveBeenCalledWith({ preventScroll: true });
    expect(window.scrollTo).toHaveBeenCalledOnce();
    expect(window.scrollTo).toHaveBeenCalledWith({
      behavior: 'auto',
      left: 0,
      top: 0,
    });
  });

  it('replaces the legacy route, preserves URL state, and focuses main once', async () => {
    const focus = vi.spyOn(HTMLElement.prototype, 'focus');
    const { router } = renderLegacyRouteWithHistory();
    const main = screen.getByRole('main');

    expect(
      await screen.findByRole('heading', {
        level: 1,
        name: 'Evaluation laboratory',
      }),
    ).toBeTruthy();
    expect(router.state.location.pathname).toBe('/evaluations');
    expect(router.state.location.search).toBe('?dataset=quick');
    expect(router.state.location.hash).toBe('#results');
    expect(document.title).toBe('Evaluations | Semantix');
    expect(document.activeElement).toBe(main);
    expect(focus).toHaveBeenCalledOnce();
    expect(focus).toHaveBeenCalledWith({ preventScroll: true });
    expect(window.scrollTo).toHaveBeenCalledOnce();

    await act(async () => {
      await router.navigate(-1);
    });

    expect(
      await screen.findByRole('heading', {
        level: 1,
        name: 'Probe the cache',
      }),
    ).toBeTruthy();
    expect(router.state.location.pathname).toBe('/');
    expect(focus).toHaveBeenCalledOnce();
  });

  it('preserves focus during browser history navigation', async () => {
    const { router } = renderWithHistory();
    await screen.findByRole('heading', {
      level: 1,
      name: 'Cache inspector',
    });

    const menuButton = screen.getByRole('button', {
      name: 'Open primary menu',
    });
    menuButton.focus();

    await act(async () => {
      await router.navigate(-1);
    });
    await screen.findByRole('heading', {
      level: 1,
      name: 'Probe the cache',
    });

    expect(document.activeElement).toBe(menuButton);
    expect(window.scrollTo).not.toHaveBeenCalled();
  });

  it('does not load evaluation data until its route mounts', async () => {
    renderAt('/');

    const evaluationLink = screen.getByRole('link', {
      name: 'Evaluations',
    });
    fireEvent.pointerEnter(evaluationLink);
    expect(getBenchmarkDatasets).not.toHaveBeenCalled();

    fireEvent.click(evaluationLink);

    expect(
      await screen.findByRole('heading', {
        level: 1,
        name: 'Evaluation laboratory',
      }),
    ).toBeTruthy();
    await waitFor(() => expect(getBenchmarkDatasets).toHaveBeenCalledOnce());
  });

  it('opens the mobile menu and closes it after route navigation', async () => {
    renderAt('/');

    const menuButton = screen.getByRole('button', {
      name: 'Open primary menu',
    });
    expect(menuButton.getAttribute('aria-expanded')).toBe('false');

    fireEvent.click(menuButton);
    expect(
      screen
        .getByRole('button', { name: 'Close primary menu' })
        .getAttribute('aria-expanded'),
    ).toBe('true');

    fireEvent.click(screen.getByRole('link', { name: 'Cache' }));

    await screen.findByRole('heading', {
      level: 1,
      name: 'Cache inspector',
    });
    expect(
      screen
        .getByRole('button', { name: 'Open primary menu' })
        .getAttribute('aria-expanded'),
    ).toBe('false');
  });

  it('returns focus from an open compact menu when Escape closes it', () => {
    renderAt('/');

    const menuButton = screen.getByRole('button', {
      name: 'Open primary menu',
    });
    fireEvent.click(menuButton);
    const cacheLink = screen.getByRole('link', { name: 'Cache' });
    cacheLink.focus();

    fireEvent.keyDown(window, { key: 'Escape' });

    expect(
      screen
        .getByRole('button', { name: 'Open primary menu' })
        .getAttribute('aria-expanded'),
    ).toBe('false');
    expect(document.activeElement).toBe(menuButton);
  });

  it('does not steal focus when Escape closes a menu focused elsewhere', () => {
    renderAt('/');

    const menuButton = screen.getByRole('button', {
      name: 'Open primary menu',
    });
    fireEvent.click(menuButton);
    const queryInput = screen.getByLabelText('Query text');
    queryInput.focus();

    fireEvent.keyDown(window, { key: 'Escape' });

    expect(menuButton.getAttribute('aria-expanded')).toBe('false');
    expect(document.activeElement).toBe(queryInput);
  });

  it('closes the compact menu when the viewport reaches the expanded breakpoint', () => {
    const originalInnerWidth = window.innerWidth;
    Object.defineProperty(window, 'innerWidth', {
      configurable: true,
      value: 820,
    });

    try {
      renderAt('/');

      const menuButton = screen.getByRole('button', {
        name: 'Open primary menu',
      });
      fireEvent.click(menuButton);
      expect(
        screen
          .getByRole('button', { name: 'Close primary menu' })
          .getAttribute('aria-expanded'),
      ).toBe('true');

      Object.defineProperty(window, 'innerWidth', {
        configurable: true,
        value: 1024,
      });
      fireEvent(window, new Event('resize'));

      expect(
        screen
          .getByRole('button', { name: 'Open primary menu' })
          .getAttribute('aria-expanded'),
      ).toBe('false');
    } finally {
      Object.defineProperty(window, 'innerWidth', {
        configurable: true,
        value: originalInnerWidth,
      });
    }
  });

  it('renders exactly four workspace links when authentication is disabled', () => {
    renderAt('/');

    expect(
      within(
        screen.getByRole('navigation', {
          name: 'Primary navigation',
        }),
      ).getAllByRole('link'),
    ).toHaveLength(4);
  });

  it('preserves monitor traces and threshold preview during navigation', async () => {
    renderAt('/');

    fireEvent.change(screen.getByLabelText('Query text'), {
      target: { value: cacheEntry.prompt },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Run query' }));
    await screen.findByText('01 records');

    fireEvent.change(screen.getByLabelText('Projection threshold'), {
      target: { value: '0.8' },
    });

    fireEvent.click(screen.getByRole('link', { name: 'Cache' }));
    await screen.findByRole('heading', {
      level: 1,
      name: 'Cache inspector',
    });
    fireEvent.click(screen.getByRole('link', { name: 'Monitor' }));

    expect(await screen.findByText('01 records')).toBeTruthy();
    expect(screen.getAllByText(cacheEntry.prompt).length).toBeGreaterThan(0);
    expect(
      (screen.getByLabelText('Projection threshold') as HTMLInputElement).value,
    ).toBe('0.8');
    expect(screen.getByText('Backend applied 0.90')).toBeTruthy();
  });

  it('restores the server threshold and clears a failed update error', async () => {
    vi.mocked(updateCacheThreshold).mockResolvedValueOnce({
      ok: false,
      error: {
        code: 'threshold_update_failed',
        detail: 'Threshold rejected.',
        status: 500,
      },
    });
    renderAt('/');

    await screen.findByText('Backend applied 0.90');
    fireEvent.change(screen.getByLabelText('Projection threshold'), {
      target: { value: '0.8' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Apply to cache' }));

    expect((await screen.findByRole('alert')).textContent).toContain(
      'THRESHOLD UPDATE FAILED; THE SERVER VALUE WAS RESTORED',
    );
    await waitFor(() =>
      expect(
        (screen.getByLabelText('Projection threshold') as HTMLInputElement).value,
      ).toBe('0.9'),
    );

    fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }));
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('refreshes stats after a deletion without clearing monitor traces', async () => {
    renderAt('/');

    fireEvent.change(screen.getByLabelText('Query text'), {
      target: { value: cacheEntry.prompt },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Run query' }));
    await screen.findByText('01 records');

    fireEvent.click(screen.getByRole('link', { name: 'Cache' }));
    await screen.findByText(cacheEntry.prompt);
    const statsCallsBeforeDelete = vi.mocked(getCacheStats).mock.calls.length;

    fireEvent.click(
      screen.getByRole('button', {
        name: `Delete ${cacheEntry.prompt}`,
      }),
    );
    fireEvent.click(
      screen.getByRole('button', {
        name: `Confirm delete ${cacheEntry.prompt}`,
      }),
    );

    await waitFor(() =>
      expect(getCacheStats).toHaveBeenCalledTimes(statsCallsBeforeDelete + 1),
    );

    fireEvent.click(screen.getByRole('link', { name: 'Monitor' }));
    expect(await screen.findByText('01 records')).toBeTruthy();
  });

  it('clears monitor traces after clearing every cache entry', async () => {
    renderAt('/');

    fireEvent.change(screen.getByLabelText('Query text'), {
      target: { value: cacheEntry.prompt },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Run query' }));
    await screen.findByText('01 records');

    fireEvent.click(screen.getByRole('link', { name: 'Cache' }));
    await screen.findByText(cacheEntry.prompt);

    fireEvent.click(screen.getByRole('button', { name: 'Clear all entries' }));
    fireEvent.click(screen.getByRole('button', { name: 'Confirm clear cache' }));
    await waitFor(() => expect(clearCache).toHaveBeenCalledOnce());

    fireEvent.click(screen.getByRole('link', { name: 'Monitor' }));
    expect(await screen.findByText('00 records')).toBeTruthy();
  });
});
