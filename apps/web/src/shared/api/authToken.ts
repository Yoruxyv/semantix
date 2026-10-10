/**
 * Store the original bearer credential in browser sessionStorage. It survives
 * reloads within the page session and remains readable by same-origin JavaScript.
 * AuthProvider owns verification and removal policy; these helpers neither trim
 * nor validate tokens, and browser storage exceptions propagate to their callers.
 */
const AUTH_TOKEN_KEY = 'semantix.auth.token';

export function getAuthToken(): string | null {
  return window.sessionStorage.getItem(AUTH_TOKEN_KEY);
}

export function setAuthToken(token: string): void {
  window.sessionStorage.setItem(AUTH_TOKEN_KEY, token);
}

export function clearAuthToken(): void {
  window.sessionStorage.removeItem(AUTH_TOKEN_KEY);
}
