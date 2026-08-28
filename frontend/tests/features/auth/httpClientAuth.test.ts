import { afterEach, describe, expect, it, vi } from 'vitest';

import { clearAuthToken, setAuthToken } from '@/shared/api/authToken';
import { request } from '@/shared/api/httpClient';

interface Payload {
  ok: boolean;
}

function createFetchMock() {
  return vi.fn(
    async (_input: RequestInfo | URL, _init?: RequestInit): Promise<Response> =>
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
  );
}

describe('authenticated HTTP requests', () => {
  afterEach(() => {
    clearAuthToken();
    vi.unstubAllGlobals();
  });

  it('adds the runtime bearer token without bundling it into configuration', async () => {
    const fetchMock = createFetchMock();
    vi.stubGlobal('fetch', fetchMock);
    setAuthToken('runtime-secret');

    const result = await request<Payload>(
      '/api/v1/auth/session',
      (value) => value as Payload,
      { method: 'GET' },
    );

    expect(result.ok).toBe(true);
    expect(fetchMock).toHaveBeenCalledOnce();

    const firstCall = fetchMock.mock.calls.at(0);
    const headers = new Headers(firstCall?.[1]?.headers);

    expect(headers.get('Authorization')).toBe('Bearer runtime-secret');
  });

  it('does not add Authorization when no session token exists', async () => {
    const fetchMock = createFetchMock();
    vi.stubGlobal('fetch', fetchMock);

    await request<Payload>('/api/v1/auth/config', (value) => value as Payload, {
      method: 'GET',
    });

    expect(fetchMock).toHaveBeenCalledOnce();

    const firstCall = fetchMock.mock.calls.at(0);
    const headers = new Headers(firstCall?.[1]?.headers);

    expect(headers.has('Authorization')).toBe(false);
  });

  it('exposes a valid Retry-After response header on API errors', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              error: 'authentication_temporarily_locked',
              detail:
                'Too many failed authentication attempts. Please try again later.',
            }),
            {
              status: 429,
              headers: {
                'Content-Type': 'application/json',
                'Retry-After': '30',
              },
            },
          ),
      ),
    );

    const result = await request<Payload>(
      '/api/v1/auth/session',
      (value) => value as Payload,
      { method: 'GET' },
    );

    expect(result).toEqual({
      ok: false,
      error: {
        code: 'authentication_temporarily_locked',
        detail: 'Too many failed authentication attempts. Please try again later.',
        retryAfterSeconds: 30,
        status: 429,
      },
    });
  });

  it('ignores a malformed Retry-After response header', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              error: 'authentication_temporarily_locked',
              detail:
                'Too many failed authentication attempts. Please try again later.',
            }),
            {
              status: 429,
              headers: { 'Retry-After': 'later' },
            },
          ),
      ),
    );

    const result = await request<Payload>(
      '/api/v1/auth/session',
      (value) => value as Payload,
      { method: 'GET' },
    );

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.retryAfterSeconds).toBeUndefined();
    }
  });
});
