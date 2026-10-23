import type { QueryClient } from '@tanstack/react-query';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { StrictMode, useContext, useEffect, type JSX } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { QueryTestProvider } from '../QueryTestProvider';
import { createTestQueryClient } from '../queryClient';
import { getAuthConfig, getAuthSession } from '@/features/auth/api/authApi';
import { AuthPanel } from '@/features/auth/components/AuthPanel';
import {
  AuthContext,
  type AuthContextValue,
} from '@/features/auth/context/AuthContext';
import { AuthProvider } from '@/features/auth/context/AuthProvider';
import { useAuth } from '@/features/auth/hooks/useAuth';
import type { AuthConfig, AuthSession } from '@/features/auth/types';
import { getAuthToken, setAuthToken } from '@/shared/api/authToken';
import type { ApiResult } from '@/shared/api/types';
import {
  benchmarkDatasetKeys,
  benchmarkHistoryKeys,
  cacheEntryKeys,
  runtimeDiagnosticsKeys,
  runtimeMetricsKeys,
} from '@/shared/query/queryKeys';

const actualHook = await vi.importActual<{ useAuth: typeof useAuth }>(
  '@/features/auth/hooks/useAuth',
);
const protectedKeys = [
  benchmarkDatasetKeys.catalog(),
  benchmarkHistoryKeys.all,
  cacheEntryKeys.all,
  runtimeDiagnosticsKeys.live(),
  runtimeMetricsKeys.live(),
];
const publicKey = ['public-preference'];
const clients: QueryClient[] = [];
let currentAuth: AuthContextValue | null = null;

function deferred<T>() {
  let resolvePromise: ((value: T) => void) | undefined;
  const promise = new Promise<T>((resolve) => {
    resolvePromise = resolve;
  });
  return {
    promise,
    resolve(value: T): void {
      if (resolvePromise === undefined) {
        throw new Error('Deferred response is not initialized');
      }
      resolvePromise(value);
    },
  };
}

function AuthProbe(): JSX.Element {
  const value = useContext(AuthContext);
  useEffect(() => {
    currentAuth = value;
    return () => {
      currentAuth = null;
    };
  }, [value]);
  return (
    <output aria-label="Current authentication">
      {JSON.stringify({
        status: value?.status,
        session: value?.session,
        error: value?.error,
        lockedUntil: value?.lockedUntil,
      })}
    </output>
  );
}

function auth(): AuthContextValue {
  if (currentAuth === null) {
    throw new Error('AuthProvider is not mounted');
  }
  return currentAuth;
}

function expectAuthenticated(name: string): void {
  expect(auth().status).toBe('authenticated');
  expect(auth().session?.name).toBe(name);
  expect(auth().error).toBeNull();
  expect(auth().lockedUntil).toBeNull();
  expect(screen.getByLabelText('Current authentication').textContent).toContain(name);
}

function newClient(): QueryClient {
  const client = createTestQueryClient();
  clients.push(client);
  client.setQueryData(publicKey, 'public value');
  return client;
}

function seedProtected(client: QueryClient, value: string): void {
  for (const key of protectedKeys) {
    client.setQueryData(key, value);
  }
}

function expectProtected(client: QueryClient, value: string): void {
  for (const key of protectedKeys) {
    expect(client.getQueryData(key)).toBe(value);
  }
  expect(client.getQueryData(publicKey)).toBe('public value');
}

async function mount(client: QueryClient, strict = false) {
  const provider = (
    <QueryTestProvider client={client}>
      <AuthProvider>
        <AuthProbe />
        <AuthPanel />
      </AuthProvider>
    </QueryTestProvider>
  );
  let view: ReturnType<typeof render> | undefined;
  await act(async () => {
    view = render(strict ? <StrictMode>{provider}</StrictMode> : provider);
  });
  if (view === undefined) {
    throw new Error('AuthProvider did not render');
  }
  return view;
}

function authenticate(token: string): Promise<boolean> {
  let operation: Promise<boolean> | undefined;
  act(() => {
    operation = auth().authenticate(token);
  });
  if (operation === undefined) {
    throw new Error('Verification did not start');
  }
  return operation;
}

async function authenticateCurrent(token: string): Promise<boolean> {
  let result = false;
  await act(async () => {
    result = await auth().authenticate(token);
  });
  return result;
}

function accepted(name: string): ApiResult<AuthSession> {
  return { ok: true, data: { name, role: 'viewer', namespaces: ['team-a'] } };
}

beforeEach(() => {
  currentAuth = null;
  window.sessionStorage.clear();
  vi.mocked(useAuth).mockImplementation(actualHook.useAuth);
  vi.mocked(getAuthConfig).mockResolvedValue({
    ok: true,
    data: { authentication_required: true },
  });
  vi.mocked(getAuthSession).mockReset();
});

afterEach(() => {
  cleanup();
  for (const client of clients) {
    client.clear();
  }
  clients.length = 0;
  window.sessionStorage.clear();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe('authentication verification ownership', () => {
  it('ignores a stored-token success after logout', async () => {
    setAuthToken('token-a');
    const pending = deferred<ApiResult<AuthSession>>();
    vi.mocked(getAuthSession).mockReturnValue(pending.promise);
    const client = newClient();
    await mount(client);
    expect(getAuthSession).toHaveBeenCalledTimes(1);
    act(() => auth().logout());
    seedProtected(client, 'post-logout data');

    await act(async () => pending.resolve(accepted('old principal')));

    expect(auth().status).toBe('unauthenticated');
    expect(auth().session).toBeNull();
    expect(auth().error).toBeNull();
    expect(auth().lockedUntil).toBeNull();
    expect(getAuthToken()).toBeNull();
    expectProtected(client, 'post-logout data');
    expect(getAuthConfig).toHaveBeenCalledTimes(1);
    expect(getAuthSession).toHaveBeenCalledTimes(1);
  });

  it.each([
    'success',
    'authentication_required',
    'internal_error',
    'authentication_temporarily_locked',
  ] as const)(
    'ignores obsolete %s after a newer principal succeeds',
    async (outcome) => {
      const older = deferred<ApiResult<AuthSession>>();
      vi.mocked(getAuthSession)
        .mockReturnValueOnce(older.promise)
        .mockResolvedValueOnce(accepted('new principal'));
      const client = newClient();
      await mount(client);
      const oldOperation = authenticate('token-a');
      expect(await authenticateCurrent('token-b')).toBe(true);
      expectAuthenticated('new principal');
      seedProtected(client, 'new principal data');

      await act(async () => {
        if (outcome === 'success') {
          older.resolve(accepted('old principal'));
        } else {
          older.resolve({
            ok: false,
            error: {
              code: outcome,
              detail: 'Synthetic failure.',
              status: {
                authentication_required: 401,
                internal_error: 500,
                authentication_temporarily_locked: 429,
              }[outcome],
              retryAfterSeconds: 30,
            },
          });
        }
      });

      expect(await oldOperation).toBe(false);
      expectAuthenticated('new principal');
      expect(getAuthToken()).toBe('token-b');
      expectProtected(client, 'new principal data');
      expect(getAuthSession).toHaveBeenCalledTimes(2);
      expect(vi.mocked(getAuthSession).mock.invocationCallOrder[0]).toBeGreaterThan(
        vi.mocked(getAuthConfig).mock.invocationCallOrder[0] ?? 0,
      );
    },
  );

  it('distinguishes operations that use the same credential', async () => {
    const older = deferred<ApiResult<AuthSession>>();
    vi.mocked(getAuthSession)
      .mockReturnValueOnce(older.promise)
      .mockResolvedValueOnce(accepted('current principal'));
    const client = newClient();
    await mount(client);
    const oldOperation = authenticate('same-token');
    expect(await authenticateCurrent('same-token')).toBe(true);
    seedProtected(client, 'current data');
    await act(async () => {
      older.resolve({
        ok: false,
        error: { code: 'network_error', detail: 'Temporary failure.', status: null },
      });
    });
    expect(await oldOperation).toBe(false);
    expectAuthenticated('current principal');
    expect(getAuthToken()).toBe('same-token');
    expectProtected(client, 'current data');
    expect(getAuthSession).toHaveBeenCalledTimes(2);
  });

  it.each([true, false])(
    'keeps ownership with policy retry when disabled=%s',
    async (disabled) => {
      setAuthToken('token-a');
      const older = deferred<ApiResult<AuthSession>>();
      const policy = deferred<ApiResult<AuthConfig>>();
      vi.mocked(getAuthSession).mockReturnValueOnce(older.promise);
      const client = newClient();
      await mount(client);
      vi.mocked(getAuthConfig).mockReturnValueOnce(policy.promise);
      act(() => auth().retryAccessPolicy());
      if (disabled) {
        await act(async () => {
          policy.resolve({ ok: true, data: { authentication_required: false } });
        });
      }
      seedProtected(client, 'current policy data');
      await act(async () => older.resolve(accepted('old principal')));
      expect(auth().status).toBe(disabled ? 'disabled' : 'loading');
      expect(auth().session).toBeNull();
      expect(auth().error).toBeNull();
      expect(auth().lockedUntil).toBeNull();
      expect(getAuthToken()).toBe('token-a');
      expectProtected(client, 'current policy data');
      if (!disabled) {
        await act(async () => {
          policy.resolve({ ok: true, data: { authentication_required: false } });
        });
        expect(auth().status).toBe('disabled');
      }
      expect(getAuthConfig).toHaveBeenCalledTimes(2);
      expect(getAuthSession).toHaveBeenCalledTimes(1);
    },
  );

  it.each(['disabled', 'required', 'failure'])(
    'ignores old %s policy discovery after a manual verification succeeds',
    async (outcome) => {
      const policy = deferred<ApiResult<AuthConfig>>();
      vi.mocked(getAuthConfig).mockReturnValueOnce(policy.promise);
      vi.mocked(getAuthSession).mockResolvedValue(accepted('current principal'));
      const client = newClient();
      await mount(client);
      expect(await authenticateCurrent('current-token')).toBe(true);
      seedProtected(client, 'current data');
      await act(async () => {
        policy.resolve(
          outcome === 'failure'
            ? {
                ok: false,
                error: {
                  code: 'internal_error',
                  detail: 'Policy outage.',
                  status: 503,
                },
              }
            : { ok: true, data: { authentication_required: outcome === 'required' } },
        );
      });
      expectAuthenticated('current principal');
      expect(getAuthToken()).toBe('current-token');
      expectProtected(client, 'current data');
      expect(getAuthSession).toHaveBeenCalledTimes(1);
    },
  );

  it('keeps blank-token feedback after an older pending success', async () => {
    const older = deferred<ApiResult<AuthSession>>();
    vi.mocked(getAuthSession).mockReturnValueOnce(older.promise);
    const client = newClient();
    await mount(client);
    const oldOperation = authenticate('token-a');
    expect(await authenticateCurrent('  ')).toBe(false);
    await act(async () => older.resolve(accepted('old principal')));
    expect(await oldOperation).toBe(false);
    expect(auth().status).toBe('unauthenticated');
    expect(auth().session).toBeNull();
    expect(auth().error).toBe('Enter an access token.');
    expect(auth().lockedUntil).toBeNull();
    expect(getAuthToken()).toBe('token-a');
    expect(getAuthSession).toHaveBeenCalledTimes(1);
  });

  it('does not clear the old query client when verification succeeds after unmount', async () => {
    setAuthToken('token-a');
    const older = deferred<ApiResult<AuthSession>>();
    vi.mocked(getAuthSession).mockReturnValueOnce(older.promise);
    const client = newClient();
    const view = await mount(client);
    seedProtected(client, 'retained data');
    view.unmount();
    await act(async () => older.resolve(accepted('old principal')));
    expectProtected(client, 'retained data');
    expect(getAuthToken()).toBe('token-a');
    expect(screen.queryByLabelText('Current authentication')).toBeNull();
    expect(getAuthSession).toHaveBeenCalledTimes(1);
  });

  it('restores only the active StrictMode bootstrap', async () => {
    setAuthToken('stored-token');
    const obsoletePolicy = deferred<ApiResult<AuthConfig>>();
    const currentPolicy = deferred<ApiResult<AuthConfig>>();
    vi.mocked(getAuthConfig)
      .mockReturnValueOnce(obsoletePolicy.promise)
      .mockReturnValueOnce(currentPolicy.promise);
    vi.mocked(getAuthSession).mockResolvedValueOnce(accepted('restored principal'));
    const client = newClient();
    await mount(client, true);
    expect(getAuthConfig).toHaveBeenCalledTimes(2);
    await act(async () => {
      obsoletePolicy.resolve({ ok: true, data: { authentication_required: true } });
    });
    expect(getAuthSession).not.toHaveBeenCalled();
    await act(async () => {
      currentPolicy.resolve({ ok: true, data: { authentication_required: true } });
    });
    expectAuthenticated('restored principal');
    expect(getAuthToken()).toBe('stored-token');
    expect(getAuthSession).toHaveBeenCalledTimes(1);
  });

  it('cannot remove a credential accepted by a new instance through AuthPanel', async () => {
    const realApi = await vi.importActual<{
      getAuthConfig: typeof getAuthConfig;
      getAuthSession: typeof getAuthSession;
    }>('@/features/auth/api/authApi');
    vi.mocked(getAuthConfig).mockImplementation(realApi.getAuthConfig);
    vi.mocked(getAuthSession).mockImplementation(realApi.getAuthSession);
    const requests: {
      path: string;
      bearer: string | null;
      response: ReturnType<typeof deferred<Response>>;
    }[] = [];
    vi.stubGlobal(
      'fetch',
      vi.fn((input: string, init?: RequestInit) => {
        const response = deferred<Response>();
        requests.push({
          path: new URL(input).pathname,
          bearer: new Headers(init?.headers).get('Authorization'),
          response,
        });
        return response.promise;
      }),
    );
    async function respond(
      index: number,
      payload: object,
      status = 200,
    ): Promise<void> {
      const request = requests[index];
      if (request === undefined) {
        throw new Error('Expected auth request was not issued');
      }
      await act(async () => {
        request.response.resolve(
          new Response(JSON.stringify(payload), {
            status,
            headers: { 'Content-Type': 'application/json' },
          }),
        );
      });
    }
    setAuthToken('old-token');
    const oldClient = newClient();
    const oldView = await mount(oldClient);
    await respond(0, { authentication_required: true });
    seedProtected(oldClient, 'old client data');
    oldView.unmount();
    const client = newClient();
    await mount(client);
    await respond(2, { authentication_required: true });
    await respond(
      3,
      { error: 'authentication_required', detail: 'A valid bearer token is required.' },
      401,
    );
    const input = screen.getByLabelText<HTMLInputElement>('Access token');
    fireEvent.change(input, { target: { value: 'new-token' } });
    fireEvent.click(screen.getByRole('button', { name: 'Authenticate' }));
    expect(input.disabled).toBe(true);
    fireEvent.submit(input.closest('form') ?? input);
    expect(requests).toHaveLength(5);
    await respond(4, { name: 'new principal', role: 'viewer', namespaces: ['team-b'] });
    seedProtected(client, 'new client data');
    await respond(
      1,
      { error: 'authentication_required', detail: 'A valid bearer token is required.' },
      401,
    );
    expectAuthenticated('new principal');
    expect(getAuthToken()).toBe('new-token');
    expectProtected(client, 'new client data');
    expectProtected(oldClient, 'old client data');
    expect(requests.map(({ path, bearer }) => [path, bearer])).toEqual([
      ['/api/v1/auth/config', 'Bearer old-token'],
      ['/api/v1/auth/session', 'Bearer old-token'],
      ['/api/v1/auth/config', 'Bearer old-token'],
      ['/api/v1/auth/session', 'Bearer old-token'],
      ['/api/v1/auth/session', 'Bearer new-token'],
    ]);
    expect(getAuthConfig).toHaveBeenCalledTimes(2);
    expect(getAuthSession).toHaveBeenCalledTimes(3);
  });
});
