import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { AuthPanel } from '@/features/auth/components/AuthPanel';
import { useAuth } from '@/features/auth/hooks/useAuth';

describe('AuthPanel', () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  it('renders no authentication UI when authentication is disabled', () => {
    vi.mocked(useAuth).mockReturnValue({
      authenticate: vi.fn(async () => false),
      error: null,
      lockedUntil: null,
      logout: vi.fn(),
      retryAccessPolicy: vi.fn(),
      session: null,
      status: 'disabled',
    });

    const { container } = render(<AuthPanel />);

    expect(container.firstChild).toBeNull();
  });

  it('renders no authentication UI while the access policy is loading', () => {
    vi.mocked(useAuth).mockReturnValue({
      authenticate: vi.fn(async () => false),
      error: null,
      lockedUntil: null,
      logout: vi.fn(),
      retryAccessPolicy: vi.fn(),
      session: null,
      status: 'loading',
    });

    const { container } = render(<AuthPanel />);

    expect(container.firstChild).toBeNull();
  });

  it('shows a policy error with Retry and no token form', () => {
    const retryAccessPolicy = vi.fn();
    vi.mocked(useAuth).mockReturnValue({
      authenticate: vi.fn(async () => false),
      error:
        'Access policy unavailable. Semantix could not determine the current ' +
        'authentication policy. Please wait a moment and try again.',
      lockedUntil: null,
      logout: vi.fn(),
      retryAccessPolicy,
      session: null,
      status: 'error',
    });

    render(<AuthPanel />);

    expect(screen.getByRole('alert').textContent).toBe(
      'Access policy unavailable. Semantix could not determine the current ' +
        'authentication policy. Please wait a moment and try again.',
    );
    expect(screen.queryByLabelText('Access token')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(retryAccessPolicy).toHaveBeenCalledOnce();
  });

  it('shows a session-verification error with Retry and no token form', () => {
    const retryAccessPolicy = vi.fn();
    vi.mocked(useAuth).mockReturnValue({
      authenticate: vi.fn(async () => false),
      error:
        'Session verification unavailable. Semantix could not verify the ' +
        'current authentication session. Please wait a moment and try again.',
      lockedUntil: null,
      logout: vi.fn(),
      retryAccessPolicy,
      session: null,
      status: 'session-error',
    });

    render(<AuthPanel />);

    expect(
      screen.getByRole('heading', {
        name: 'Session verification paused',
      }),
    ).toBeTruthy();
    expect(screen.queryByLabelText('Access token')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(retryAccessPolicy).toHaveBeenCalledOnce();
  });

  it('shows principal, role, namespaces, and sign-out in the access bar', () => {
    const logout = vi.fn();
    vi.mocked(useAuth).mockReturnValue({
      authenticate: vi.fn(async () => true),
      error: null,
      lockedUntil: null,
      logout,
      retryAccessPolicy: vi.fn(),
      session: {
        name: 'Ada',
        role: 'admin',
        namespaces: ['alpha', 'beta'],
      },
      status: 'authenticated',
    });

    render(<AuthPanel />);

    expect(screen.getByText('Authenticated access')).toBeTruthy();
    expect(screen.getByText('Ada')).toBeTruthy();
    expect(screen.getByText('admin')).toBeTruthy();
    expect(screen.getByText('Namespaces: alpha, beta')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Sign out' }));
    expect(logout).toHaveBeenCalledOnce();
  });

  it('displays wildcard namespace access as all namespaces', () => {
    vi.mocked(useAuth).mockReturnValue({
      authenticate: vi.fn(async () => true),
      error: null,
      lockedUntil: null,
      logout: vi.fn(),
      retryAccessPolicy: vi.fn(),
      session: {
        name: 'Global administrator',
        role: 'admin',
        namespaces: ['*'],
      },
      status: 'authenticated',
    });

    render(<AuthPanel />);

    expect(screen.getByText('Namespaces: All')).toBeTruthy();
    expect(screen.queryByText('Namespaces: *')).toBeNull();
  });

  it('updates only inline feedback after a rejected token', () => {
    const authenticate = vi.fn(async () => false);
    vi.mocked(useAuth).mockReturnValue({
      authenticate,
      error: null,
      lockedUntil: null,
      logout: vi.fn(),
      retryAccessPolicy: vi.fn(),
      session: null,
      status: 'unauthenticated',
    });
    const { rerender } = render(<AuthPanel />);
    const heading = screen.getByRole('heading', {
      name: 'Authentication required',
    });
    const gate = heading.closest('section');

    vi.mocked(useAuth).mockReturnValue({
      authenticate,
      error: 'The access token was rejected.',
      lockedUntil: null,
      logout: vi.fn(),
      retryAccessPolicy: vi.fn(),
      session: null,
      status: 'unauthenticated',
    });
    rerender(<AuthPanel />);

    expect(screen.getByRole('alert').textContent).toBe(
      'The access token was rejected.',
    );
    expect(
      screen
        .getByRole('heading', { name: 'Authentication required' })
        .closest('section'),
    ).toBe(gate);
    expect(screen.getByLabelText('Access token')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Authenticate' })).toBeTruthy();
    expect(
      screen.getByText('Enter your Semantix access token to continue.'),
    ).toBeTruthy();
  });

  it('disables controls and counts down from the absolute lock timestamp', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-07-29T05:00:00Z'));
    vi.mocked(useAuth).mockReturnValue({
      authenticate: vi.fn(async () => false),
      error: 'Too many failed authentication attempts.',
      lockedUntil: Date.now() + 30_000,
      logout: vi.fn(),
      retryAccessPolicy: vi.fn(),
      session: null,
      status: 'unauthenticated',
    });

    render(<AuthPanel />);

    const input = screen.getByLabelText('Access token') as HTMLInputElement;
    const button = screen.getByRole('button', {
      name: 'Authenticate',
    }) as HTMLButtonElement;
    expect(input.disabled).toBe(true);
    expect(button.disabled).toBe(true);
    expect(screen.getByText('Try again in 00:30.')).toBeTruthy();

    act(() => {
      vi.advanceTimersByTime(1_000);
    });
    expect(screen.getByText('Try again in 00:29.')).toBeTruthy();

    act(() => {
      vi.advanceTimersByTime(29_000);
    });
    expect(input.disabled).toBe(false);
    expect(button.disabled).toBe(false);
    expect(screen.queryByText(/Try again in/)).toBeNull();
  });

  it('announces when authentication is being verified', async () => {
    let resolveAuthentication: ((accepted: boolean) => void) | undefined;
    const authenticate = vi.fn(
      () =>
        new Promise<boolean>((resolve) => {
          resolveAuthentication = resolve;
        }),
    );
    vi.mocked(useAuth).mockReturnValue({
      authenticate,
      error: null,
      lockedUntil: null,
      logout: vi.fn(),
      retryAccessPolicy: vi.fn(),
      session: null,
      status: 'unauthenticated',
    });
    render(<AuthPanel />);

    const tokenInput = screen.getByLabelText('Access token');
    expect((tokenInput as HTMLInputElement).type).toBe('password');
    fireEvent.change(tokenInput, {
      target: { value: 'test-token' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Authenticate' }));

    expect(
      (
        screen.getByRole('button', {
          name: 'Verifying…',
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);

    await act(async () => {
      if (resolveAuthentication === undefined) {
        throw new Error('Authentication promise was not created');
      }
      resolveAuthentication(false);
    });
  });
});
