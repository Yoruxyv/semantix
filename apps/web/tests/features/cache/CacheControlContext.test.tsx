import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { StrictMode, type JSX } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  getCacheStats,
  getCacheThreshold,
  updateCacheThreshold,
} from '@/features/cache/api/cacheApi';
import { CacheControlProvider } from '@/features/cache/context/CacheControlContext';
import { useCacheControl } from '@/features/cache/hooks/useCacheControl';
import { deferred } from '../support';

vi.mock('@/features/cache/api/cacheApi');

const initialStats = {
  size: 1,
  hits: 2,
  misses: 3,
  hit_rate: 0.4,
};

function CacheControlProbe(): JSX.Element {
  const {
    cacheState,
    commitThreshold,
    previewThreshold,
    isRefreshingCacheState,
    refreshCacheState,
  } = useCacheControl();
  let stateLabel = 'loading';
  if (cacheState.status === 'ready') {
    stateLabel = `${cacheState.data.appliedThreshold}:${cacheState.data.cacheStats.size}:${previewThreshold}`;
  } else if (cacheState.status === 'error') {
    stateLabel = cacheState.error;
  }

  return (
    <div>
      <output data-testid="cache-state">{stateLabel}</output>
      <output data-testid="cache-refresh-state">
        {isRefreshingCacheState ? 'refreshing' : 'idle'}
      </output>
      <button type="button" onClick={() => void refreshCacheState(false)}>
        Refresh cache state
      </button>
      <button type="button" onClick={() => void commitThreshold(0.97)}>
        Apply threshold
      </button>
    </div>
  );
}

function renderProbe(strict = false): ReturnType<typeof render> {
  const content = (
    <CacheControlProvider>
      <CacheControlProbe />
    </CacheControlProvider>
  );

  return render(strict ? <StrictMode>{content}</StrictMode> : content);
}

describe('CacheControlProvider', () => {
  beforeEach(() => {
    vi.mocked(getCacheStats).mockResolvedValue({
      ok: true,
      data: initialStats,
    });
    vi.mocked(getCacheThreshold).mockResolvedValue({
      ok: true,
      data: { threshold: 0.92 },
    });
    vi.mocked(updateCacheThreshold).mockResolvedValue({
      ok: true,
      data: { threshold: 0.97 },
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('ignores an older initial read that resolves last', async () => {
    const olderStats = deferred<Awaited<ReturnType<typeof getCacheStats>>>();
    const newerStats = deferred<Awaited<ReturnType<typeof getCacheStats>>>();
    const olderThreshold = deferred<Awaited<ReturnType<typeof getCacheThreshold>>>();
    const newerThreshold = deferred<Awaited<ReturnType<typeof getCacheThreshold>>>();
    vi.mocked(getCacheStats)
      .mockReturnValueOnce(olderStats.promise)
      .mockReturnValueOnce(newerStats.promise);
    vi.mocked(getCacheThreshold)
      .mockReturnValueOnce(olderThreshold.promise)
      .mockReturnValueOnce(newerThreshold.promise);

    renderProbe(true);

    await waitFor(() => {
      expect(getCacheStats).toHaveBeenCalledTimes(2);
      expect(getCacheThreshold).toHaveBeenCalledTimes(2);
    });

    await act(async () => {
      newerStats.resolve({
        ok: true,
        data: { ...initialStats, size: 9 },
      });
      newerThreshold.resolve({
        ok: true,
        data: { threshold: 0.96 },
      });
    });

    expect((await screen.findByTestId('cache-state')).textContent).toBe('0.96:9:0.96');

    await act(async () => {
      olderStats.resolve({ ok: true, data: initialStats });
      olderThreshold.resolve({
        ok: true,
        data: { threshold: 0.8 },
      });
    });

    expect(screen.getByTestId('cache-state').textContent).toBe('0.96:9:0.96');
  });

  it('keeps a threshold write authoritative over an older refresh', async () => {
    const staleStats = deferred<Awaited<ReturnType<typeof getCacheStats>>>();
    const staleThreshold = deferred<Awaited<ReturnType<typeof getCacheThreshold>>>();
    vi.mocked(getCacheStats)
      .mockResolvedValueOnce({ ok: true, data: initialStats })
      .mockReturnValueOnce(staleStats.promise);
    vi.mocked(getCacheThreshold)
      .mockResolvedValueOnce({
        ok: true,
        data: { threshold: 0.92 },
      })
      .mockReturnValueOnce(staleThreshold.promise);

    renderProbe();
    await waitFor(() => {
      expect(screen.getByTestId('cache-state').textContent).toBe('0.92:1:0.92');
    });

    fireEvent.click(screen.getByRole('button', { name: 'Refresh cache state' }));
    await waitFor(() => expect(getCacheThreshold).toHaveBeenCalledTimes(2));
    fireEvent.click(screen.getByRole('button', { name: 'Apply threshold' }));

    await waitFor(() => {
      expect(screen.getByTestId('cache-state').textContent).toBe('0.97:1:0.97');
    });

    await act(async () => {
      staleStats.resolve({
        ok: true,
        data: { ...initialStats, size: 99 },
      });
      staleThreshold.resolve({
        ok: true,
        data: { threshold: 0.75 },
      });
    });

    expect(screen.getByTestId('cache-state').textContent).toBe('0.97:1:0.97');
  });

  it('surfaces an initial read failure without a default threshold', async () => {
    vi.mocked(getCacheStats).mockResolvedValue({
      ok: false,
      error: {
        code: 'network_error',
        detail: 'Cache backend unavailable',
        status: null,
      },
    });

    renderProbe();

    await waitFor(() => {
      expect(screen.getByTestId('cache-state').textContent).toBe(
        'Cache backend unavailable',
      );
    });
    expect(screen.queryByText(/0\.92/)).toBeNull();
  });

  it('keeps confirmed cache readings visible during a background refresh', async () => {
    renderProbe();
    await waitFor(() => {
      expect(screen.getByTestId('cache-state').textContent).toBe('0.92:1:0.92');
    });

    const refreshedStats = deferred<Awaited<ReturnType<typeof getCacheStats>>>();
    const refreshedThreshold =
      deferred<Awaited<ReturnType<typeof getCacheThreshold>>>();
    vi.mocked(getCacheStats).mockReturnValueOnce(refreshedStats.promise);
    vi.mocked(getCacheThreshold).mockReturnValueOnce(refreshedThreshold.promise);

    fireEvent.click(screen.getByRole('button', { name: 'Refresh cache state' }));

    await waitFor(() => {
      expect(screen.getByTestId('cache-refresh-state').textContent).toBe('refreshing');
    });
    expect(screen.getByTestId('cache-state').textContent).toBe('0.92:1:0.92');

    await act(async () => {
      refreshedStats.resolve({
        ok: true,
        data: { ...initialStats, size: 4 },
      });
      refreshedThreshold.resolve({
        ok: true,
        data: { threshold: 0.94 },
      });
    });

    expect(screen.getByTestId('cache-state').textContent).toBe('0.94:4:0.92');
    expect(screen.getByTestId('cache-refresh-state').textContent).toBe('idle');
  });
});
