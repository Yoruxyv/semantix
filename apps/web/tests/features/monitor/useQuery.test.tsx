import { act, renderHook } from '@testing-library/react';
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  type MockedFunction,
  vi,
} from 'vitest';

import { useQuery } from '@/features/monitor/hooks/useQuery';

function successfulResponse(): Response {
  return new Response(
    JSON.stringify({
      response: 'Cached',
      cache_hit: true,
      similarity_score: 0.97,
      similarity_threshold: 0.92,
      matched_prompt: 'Hello',
      matched_cache_key: 'a'.repeat(64),
      cache_entry_created_at: '2026-07-17T10:00:00Z',
      cache_entry_age_seconds: 2,
      generation_skipped: true,
      provider_called: false,
      latency_ms: 4,
    }),
    { status: 200 },
  );
}

describe('useQuery', () => {
  let fetchMock: MockedFunction<typeof fetch>;

  beforeEach(() => {
    fetchMock = vi.fn<typeof fetch>();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('ends loading after a provider failure and accepts another request', async () => {
    fetchMock
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            error: 'upstream_error',
            detail: 'The AI service could not process the request.',
          }),
          { status: 502 },
        ),
      )
      .mockResolvedValueOnce(successfulResponse());
    const { result } = renderHook(() => useQuery());
    await act(async () => {
      expect(await result.current.submit({ prompt: 'Recovery probe' })).toBeNull();
    });
    expect(result.current.state).toMatchObject({
      status: 'error',
      error: { code: 'upstream_error', status: 502 },
    });
    await act(async () => {
      expect(await result.current.submit({ prompt: 'Recovery probe' })).not.toBeNull();
    });
    expect(result.current.state.status).toBe('success');
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it.each(['TypeError', 'TimeoutError'])('ends loading after a %s', async (name) => {
    fetchMock.mockRejectedValueOnce(
      new DOMException('Synthetic transport failure', name),
    );
    const { result } = renderHook(() => useQuery());
    await act(async () => {
      expect(await result.current.submit({ prompt: 'Transport probe' })).toBeNull();
    });
    expect(result.current.state).toMatchObject({
      status: 'error',
      error: { code: 'network_error', status: null },
    });
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it('contains unexpected request rejection and allows recovery without exposing its detail', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementationOnce(() => {
      throw new DOMException(
        'SENSITIVE_STORAGE_FAILURE_DO_NOT_RENDER',
        'SecurityError',
      );
    });
    fetchMock.mockResolvedValue(successfulResponse());
    const { result } = renderHook(() => useQuery());
    await act(async () => {
      expect(await result.current.submit({ prompt: 'Recovery probe' })).toBeNull();
    });
    expect(result.current.state).toEqual({
      status: 'error',
      error: { code: 'query_failed', status: null, detail: null },
    });
    expect(fetchMock).not.toHaveBeenCalled();
    await act(async () => {
      expect(await result.current.submit({ prompt: 'Recovery probe' })).not.toBeNull();
    });
    expect(result.current.state.status).toBe('success');
  });

  it('ignores an obsolete failure after a newer request succeeds', async () => {
    let resolveFirst = (_response: Response): void => undefined;
    fetchMock
      .mockReturnValueOnce(
        new Promise<Response>((resolve) => {
          resolveFirst = resolve;
        }),
      )
      .mockResolvedValueOnce(successfulResponse());
    const { result } = renderHook(() => useQuery());
    let obsoleteRequest: Promise<unknown> | undefined;
    act(() => {
      obsoleteRequest = result.current.submit({ prompt: 'Obsolete query' });
    });
    await act(async () => {
      await result.current.submit({ prompt: 'Current query' });
    });
    expect(fetchMock.mock.calls[0]?.[1]?.signal?.aborted).toBe(true);
    await act(async () => {
      resolveFirst(
        new Response(JSON.stringify({ error: 'upstream_error', detail: null }), {
          status: 502,
        }),
      );
      expect(await obsoleteRequest).toBeNull();
    });
    expect(result.current.state.status).toBe('success');
  });

  it('aborts on unmount and ignores a late result', async () => {
    let resolveRequest = (_response: Response): void => undefined;
    fetchMock.mockReturnValueOnce(
      new Promise<Response>((resolve) => {
        resolveRequest = resolve;
      }),
    );
    const { result, unmount } = renderHook(() => useQuery());
    let pending: Promise<unknown> | undefined;
    act(() => {
      pending = result.current.submit({ prompt: 'Unmounted query' });
    });
    unmount();
    expect(fetchMock.mock.calls[0]?.[1]?.signal?.aborted).toBe(true);
    resolveRequest(successfulResponse());
    expect(await pending).toBeNull();
  });

  it('stores a successful query response', async () => {
    fetchMock.mockResolvedValue(successfulResponse());

    const { result } = renderHook(() => useQuery());

    await act(async () => {
      const response = await result.current.submit({
        prompt: 'Hello',
        namespace: 'tenant-a',
        cache_enabled: true,
        cache_read_enabled: false,
        cache_write_enabled: true,
        private: false,
      });
      expect(response?.response).toBe('Cached');
    });

    expect(result.current.state.status).toBe('success');
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/v1/query'),
      expect.objectContaining({
        body: JSON.stringify({
          prompt: 'Hello',
          namespace: 'tenant-a',
          cache_enabled: true,
          cache_read_enabled: false,
          cache_write_enabled: true,
          private: false,
        }),
      }),
    );
  });
});
