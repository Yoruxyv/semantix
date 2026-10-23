import { useQueryClient } from '@tanstack/react-query';
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type JSX,
  type ReactNode,
} from 'react';

import { clearAuthToken, getAuthToken, setAuthToken } from '@/shared/api/authToken';
import { isProtectedQueryKey } from '@/shared/query/queryKeys';

import { getAuthConfig, getAuthSession } from '../api/authApi';
import type { AuthSession } from '../types';
import { AuthContext, type AuthContextValue, type AuthStatus } from './AuthContext';

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

/**
 * Own browser auth state and protected-query cleanup under the app QueryClient.
 * Public policy discovery gates the workspace; the server authorizes operations.
 * Storage/header setup rejections are not converted into auth error state here.
 */
export function AuthProvider({ children }: Readonly<AuthProviderProps>): JSX.Element {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<AuthStatus>('loading');
  const [session, setSession] = useState<AuthSession | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lockedUntil, setLockedUntil] = useState<number | null>(null);
  const [policyRequest, setPolicyRequest] = useState(0);
  const operationGeneration = useRef(0);

  /** Remove only registered protected query roots; feature-local state is separate. */
  const clearProtectedQueries = useCallback((): void => {
    queryClient.removeQueries({
      predicate: (query) => isProtectedQueryKey(query.queryKey),
    });
  }, [queryClient]);

  /**
   * Trim and store the bearer credential before server verification. Accepted
   * verification sets the principal and clears protected queries; handled failures
   * clear that principal/queries. Only authentication_required removes the token;
   * lockout and transient failures retain it. Retry-After or 30 seconds supplies
   * the local lockout deadline, not the server's authoritative clock.
   * Only the current operation may apply a verification result, including token
   * removal and query cleanup. Storage/header setup rejections still propagate.
   */
  const authenticate = useCallback(
    async (token: string): Promise<boolean> => {
      const operation = ++operationGeneration.current;
      const normalized = token.trim();

      if (normalized === '') {
        setError('Enter an access token.');
        return false;
      }

      setAuthToken(normalized);
      setError(null);

      const response = await getAuthSession();

      if (operation !== operationGeneration.current) {
        return false;
      }

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

  /** Invalidate pending work and clear credential, protected queries and auth state. */
  const logout = useCallback((): void => {
    operationGeneration.current += 1;
    clearAuthToken();
    clearProtectedQueries();
    setSession(null);
    setError(null);
    setLockedUntil(null);
    setStatus('unauthenticated');
  }, [clearProtectedQueries]);

  /** Re-enter loading and rediscover policy with the stored token retained. */
  const retryAccessPolicy = useCallback((): void => {
    operationGeneration.current += 1;
    setError(null);
    setSession(null);
    setLockedUntil(null);
    setStatus('loading');
    setPolicyRequest((request) => request + 1);
  }, []);

  /**
   * Discover policy first: disabled mode permits configured local access; token
   * mode verifies a stored credential or shows the unauthenticated gate. A handled
   * config failure becomes error. Discovery and delegated verification lose
   * ownership on a newer operation or effect cleanup, including StrictMode replay.
   */
  useEffect(() => {
    const operation = ++operationGeneration.current;

    async function initialize(): Promise<void> {
      const config = await getAuthConfig();

      if (operation !== operationGeneration.current) {
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
      operationGeneration.current += 1;
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
