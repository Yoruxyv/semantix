import type { MockedFunction } from 'vitest';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  clearCache,
  deleteCacheEntry,
  getCacheEntry,
  listCacheEntries,
} from '@/features/cache/api/cacheApi';

describe('cache inspector API client', () => {
  let fetchMock: MockedFunction<typeof fetch>;

  beforeEach(() => {
    fetchMock = vi.fn<typeof fetch>();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('requests and decodes a searched, sorted inspector page', async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          items: [
            {
              cache_key: 'a'.repeat(64),
              namespace: 'tenant-alpha',
              prompt: 'Explain semantic caching',
              response_preview: 'A safe response preview',
              response_preview_truncated: false,
              response: null,
              created_at: '2026-07-17T10:00:00Z',
              expires_at: '2026-07-17T11:00:00Z',
              remaining_ttl_seconds: 120,
              hit_count: 3,
              last_accessed_at: '2026-07-17T10:30:00Z',
              recency_rank: 1,
              is_expired: false,
            },
          ],
          total: 1,
          offset: 0,
          limit: 10,
          has_more: false,
        }),
        { status: 200 },
      ),
    );

    const result = await listCacheEntries({
      offset: 0,
      limit: 10,
      namespace: 'tenant-alpha',
      search: 'semantic cache',
      sort: 'most_hit',
    });

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data.items[0]?.hit_count).toBe(3);
    }
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining(
        '/api/v1/cache/entries?offset=0&limit=10&sort=most_hit&namespace=tenant-alpha&search=semantic+cache',
      ),
      expect.objectContaining({ method: 'GET' }),
    );
  });

  it('requests and strictly decodes one complete cache entry', async () => {
    const cacheKey = 'c'.repeat(64);
    const controller = new AbortController();
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          cache_key: cacheKey,
          namespace: 'tenant-alpha',
          prompt: 'Explain semantic caching',
          response_preview:
            'Response exceeds the preview limit. Inspect the complete response.',
          response_preview_truncated: true,
          response: '**Complete cached response**',
          created_at: '2026-07-17T10:00:00Z',
          expires_at: null,
          remaining_ttl_seconds: null,
          hit_count: 3,
          last_accessed_at: null,
          recency_rank: 1,
          is_expired: false,
        }),
        { status: 200 },
      ),
    );

    const result = await getCacheEntry(cacheKey, controller.signal);

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data.response).toBe('**Complete cached response**');
      expect(result.data.response_preview_truncated).toBe(true);
    }
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining(`/api/v1/cache/entries/${cacheKey}`),
      expect.objectContaining({ method: 'GET', signal: controller.signal }),
    );
  });

  it('decodes a successful single-entry deletion', async () => {
    const cacheKey = 'b'.repeat(64);
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ deleted: true, cache_key: cacheKey }), {
        status: 200,
      }),
    );

    const result = await deleteCacheEntry(cacheKey);

    expect(result).toEqual({
      ok: true,
      data: { deleted: true, cache_key: cacheKey },
    });
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining(`/api/v1/cache/entries/${cacheKey}`),
      expect.objectContaining({ method: 'DELETE' }),
    );
  });

  it('targets one namespace when clearing cache entries', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ cleared: true }), { status: 200 }),
    );

    const result = await clearCache('tenant-alpha');

    expect(result).toEqual({
      ok: true,
      data: { cleared: true },
    });
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/v1/cache?namespace=tenant-alpha'),
      expect.objectContaining({ method: 'DELETE' }),
    );
  });
});
