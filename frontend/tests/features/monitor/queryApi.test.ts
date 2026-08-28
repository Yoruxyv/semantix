import type { MockedFunction } from 'vitest';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { submitQuery } from '@/features/monitor/api/queryApi';

describe('query API client', () => {
  let fetchMock: MockedFunction<typeof fetch>;

  beforeEach(() => {
    fetchMock = vi.fn<typeof fetch>();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('accepts explainability metadata for a coalesced miss', async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          response: 'Shared in-flight response',
          cache_hit: false,
          similarity_score: null,
          similarity_threshold: 0.92,
          matched_prompt: null,
          matched_cache_key: null,
          cache_entry_created_at: null,
          cache_entry_age_seconds: null,
          generation_skipped: true,
          provider_called: false,
          latency_ms: 15,
        }),
        { status: 200 },
      ),
    );

    const result = await submitQuery({ prompt: 'same prompt' });

    expect(result).toEqual({
      ok: true,
      data: {
        response: 'Shared in-flight response',
        cache_hit: false,
        similarity_score: null,
        similarity_threshold: 0.92,
        matched_prompt: null,
        matched_cache_key: null,
        cache_entry_created_at: null,
        cache_entry_age_seconds: null,
        generation_skipped: true,
        provider_called: false,
        latency_ms: 15,
      },
    });
  });
});
