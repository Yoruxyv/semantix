import { useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useMemo, useState, type JSX } from 'react';
import type { ReactNode } from 'react';

import { clearAuthToken, getAuthToken, setAuthToken } from '@/shared/api/authToken';
import { isProtectedQueryKey } from '@/shared/query/queryKeys';

import { getAuthConfig, getAuthSession } from '../api/authApi';
import type { AuthSession } from '../types';
import { AuthContext } from './AuthContext';
import type { AuthContextValue, AuthStatus } from './AuthContext';

const DEFAULT_LOCKOUT_SECONDS = 30;
const LOCKOUT_ERROR = 'Too many failed authentication attempts.';
const ACCESS_POLICY_ERROR =
  'Access policy unavailable. Semantix could not determine the current ' +
  'authentication policy. Please wait a moment and try again.';
const SESSION_VERIFICATION_ERROR =
  'Session verification unavailable. Semantix could not verify the current ' +
  'authentication session. Please wait a moment and try again.';

interface AuthProviderProps {
  children: ReactNode;
}

export function AuthProvider({ children }: Readonly<AuthProviderProps>): JSX.Element {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<AuthStatus>('loading');
  const [session, setSession] = useState<AuthSession | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lockedUntil, setLockedUntil] = useState<number | null>(null);
  const [policyRequest, setPolicyRequest] = useState(0);

  const clearProtectedQueries = useCallback((): void => {
    queryClient.removeQueries({
      predicate: (query) => isProtectedQueryKey(query.queryKey),
    });
  }, [queryClient]);

  const authenticate = useCallback(
    async (token: string): Promise<boolean> => {
      const normalized = token.trim();

      if (normalized === '') {
        setError('Enter an access token.');
        return false;
      }

      setAuthToken(normalized);
      setError(null);

      const response = await getAuthSession();

      if (!response.ok) {
        clearProtectedQueries();
        setSession(null);

        if (response.error.code === 'authentication_temporarily_locked') {
          const retryAfter =
            response.error.retryAfterSeconds ?? DEFAULT_LOCKOUT_SECONDS;
          setLockedUntil(Date.now() + retryAfter * 1_000);
          setError(LOCKOUT_ERROR);
          setStatus('unauthenticated');
          return false;
        }

        setLockedUntil(null);
        if (response.error.code === 'authentication_required') {
          clearAuthToken();
          setError('The access token was rejected.');
          setStatus('unauthenticated');
          return false;
        }

        setError(SESSION_VERIFICATION_ERROR);
        setStatus('session-error');
        return false;
      }

      clearProtectedQueries();
      setLockedUntil(null);
      setError(null);
      setSession(response.data);
      setStatus('authenticated');
      return true;
    },
    [clearProtectedQueries],
  );

  const logout = useCallback((): void => {
    clearAuthToken();
    clearProtectedQueries();
    setSession(null);
    setError(null);
    setLockedUntil(null);
    setStatus('unauthenticated');
  }, [clearProtectedQueries]);

  const retryAccessPolicy = useCallback((): void => {
    setError(null);
    setSession(null);
    setLockedUntil(null);
    setStatus('loading');
    setPolicyRequest((request) => request + 1);
  }, []);

  useEffect(() => {
    let active = true;

    async function initialize(): Promise<void> {
      const config = await getAuthConfig();

      if (!active) {
        return;
      }

      if (!config.ok) {
        clearProtectedQueries();
        setSession(null);
        setLockedUntil(null);
        setStatus('error');
        setError(ACCESS_POLICY_ERROR);
        return;
      }

      if (!config.data.authentication_required) {
        clearProtectedQueries();
        setError(null);
        setSession(null);
        setLockedUntil(null);
        setStatus('disabled');
        return;
      }

      const storedToken = getAuthToken();

      if (storedToken === null) {
        setError(null);
        setLockedUntil(null);
        setStatus('unauthenticated');
        return;
      }

      await authenticate(storedToken);
    }

    void initialize();

    return () => {
      active = false;
    };
  }, [authenticate, clearProtectedQueries, policyRequest]);

  const value = useMemo<AuthContextValue>(
    () => ({
      authenticate,
      error,
      lockedUntil,
      logout,
      retryAccessPolicy,
      session,
      status,
    }),
    [authenticate, error, lockedUntil, logout, retryAccessPolicy, session, status],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
