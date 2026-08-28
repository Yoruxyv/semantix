import { act, renderHook } from '@testing-library/react';
import type { MockedFunction } from 'vitest';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useQuery } from '@/features/monitor/hooks/useQuery';

describe('useQuery', () => {
  let fetchMock: MockedFunction<typeof fetch>;

  beforeEach(() => {
    fetchMock = vi.fn<typeof fetch>();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('stores a successful query response', async () => {
    fetchMock.mockResolvedValue(
      new Response(
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
      ),
    );

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
