import { describe, expect, it, vi } from 'vitest';

import type { CacheEntryListParams } from '@/features/cache/types';
import { ApiResultError, dataFromApiResult } from '@/shared/query/apiResult';
import { createAppQueryClient } from '@/shared/query/queryClient';
import { cacheEntryKeys } from '@/shared/query/queryKeys';

describe('query infrastructure', () => {
  it('retains every API error field when a result becomes an Error', () => {
    let captured: unknown;

    try {
      dataFromApiResult({
        ok: false,
        error: {
          code: 'authentication_required',
          detail: 'Sign in again.',
          status: 401,
        },
      });
    } catch (error: unknown) {
      captured = error;
    }

    expect(captured).toBeInstanceOf(ApiResultError);
    expect(captured).toMatchObject({
      code: 'authentication_required',
      detail: 'Sign in again.',
      status: 401,
    });
  });

  it('includes every list parameter in cache-entry query keys', () => {
    const base: CacheEntryListParams = {
      offset: 0,
      limit: 10,
      namespace: 'tenant-alpha',
      search: 'semantic',
      sort: 'newest',
    };
    const variations: CacheEntryListParams[] = [
      { ...base, offset: 10 },
      { ...base, limit: 25 },
      { ...base, namespace: 'tenant-beta' },
      { ...base, search: 'vector' },
      { ...base, sort: 'oldest' },
    ];
    const serializedKeys = new Set(
      [base, ...variations].map((params) =>
        JSON.stringify(cacheEntryKeys.list(params)),
      ),
    );

    expect(serializedKeys.size).toBe(6);
    expect(cacheEntryKeys.list(base)).toEqual([
      'cache-entries',
      'list',
      {
        limit: 10,
        namespace: 'tenant-alpha',
        offset: 0,
        search: 'semantic',
        sort: 'newest',
      },
    ]);
  });

  it('does not retry a deterministic client error', async () => {
    const queryClient = createAppQueryClient();
    const request = vi.fn(async () => {
      throw new ApiResultError({
        code: 'forbidden',
        detail: 'Not allowed.',
        status: 403,
      });
    });

    await expect(
      queryClient.fetchQuery({
        queryKey: ['deterministic-client-error'],
        queryFn: request,
      }),
    ).rejects.toMatchObject({ code: 'forbidden', status: 403 });
    expect(request).toHaveBeenCalledOnce();
    queryClient.clear();
  });
});
