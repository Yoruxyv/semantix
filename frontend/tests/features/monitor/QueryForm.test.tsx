import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { useAuth } from '@/features/auth/hooks/useAuth';
import { QueryForm } from '@/features/monitor/components/QueryForm';
import type { AuthRole } from '@/features/auth/types';
import type { QueryPolicyMode } from '@/features/monitor/types';

function authenticateAs(name: string, role: AuthRole, namespaces: string[]): void {
  vi.mocked(useAuth).mockReturnValue({
    authenticate: vi.fn(async () => true),
    error: null,
    lockedUntil: null,
    logout: vi.fn(),
    retryAccessPolicy: vi.fn(),
    session: { name, role, namespaces },
    status: 'authenticated',
  });
}

const MODE_CASES = [
  ['normal', 'Normal read and write', true, true, true, false],
  ['read-only', 'Read only', true, true, false, false],
  ['refresh', 'Refresh and write', true, false, true, false],
  ['bypass', 'Bypass cache', false, false, false, false],
  ['private', 'Private request', false, false, false, true],
] as const satisfies ReadonlyArray<
  readonly [QueryPolicyMode, string, boolean, boolean, boolean, boolean]
>;

describe('QueryForm', () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it.each(MODE_CASES)(
    'maps %s mode to the existing query policy fields',
    async (mode, label, cacheEnabled, readEnabled, writeEnabled, isPrivate) => {
      const onSubmit = vi.fn(async () => undefined);
      render(<QueryForm isLoading={false} onSubmit={onSubmit} />);

      fireEvent.change(screen.getByLabelText('Query text'), {
        target: { value: 'Policy probe' },
      });
      fireEvent.click(screen.getByRole('radio', { name: new RegExp(`^${label}`) }));
      fireEvent.click(screen.getByRole('button', { name: 'Run query' }));

      await waitFor(() =>
        expect(onSubmit).toHaveBeenCalledWith({
          policyMode: mode,
          request: {
            prompt: 'Policy probe',
            namespace: 'default',
            cache_enabled: cacheEnabled,
            cache_read_enabled: readEnabled,
            cache_write_enabled: writeEnabled,
            private: isPrivate,
          },
        }),
      );
    },
  );

  it('preselects one namespace and requires a choice from multiple namespaces', async () => {
    const onSubmit = vi.fn(async () => undefined);
    authenticateAs('single', 'operator', ['tenant-one']);
    const view = render(<QueryForm isLoading={false} onSubmit={onSubmit} />);

    expect(screen.getByText(/namespace tenant-one/i)).toBeTruthy();

    view.unmount();
    authenticateAs('multiple', 'operator', ['tenant-one', 'tenant-two']);
    render(<QueryForm isLoading={false} onSubmit={onSubmit} />);

    await waitFor(() =>
      expect(
        (screen.getByRole('button', { name: 'Run query' }) as HTMLButtonElement)
          .disabled,
      ).toBe(true),
    );
    fireEvent.change(screen.getByLabelText('Authorized namespace'), {
      target: { value: 'tenant-two' },
    });
    fireEvent.change(screen.getByLabelText('Query text'), {
      target: { value: 'Scoped probe' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Run query' }));

    await waitFor(() =>
      expect(onSubmit).toHaveBeenCalledWith(
        expect.objectContaining({
          request: expect.objectContaining({ namespace: 'tenant-two' }),
        }),
      ),
    );
  });

  it('requires wildcard principals to provide one valid explicit namespace', () => {
    authenticateAs('global', 'admin', ['*']);
    render(<QueryForm isLoading={false} onSubmit={vi.fn()} />);

    const namespace = screen.getByLabelText('Explicit namespace');
    expect((namespace as HTMLInputElement).value).toBe('default');

    fireEvent.change(namespace, { target: { value: 'not allowed' } });
    expect(
      (screen.getByRole('button', { name: 'Run query' }) as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(screen.getByText(/namespace not selected/i)).toBeTruthy();
  });

  it('prevents a Viewer from submitting a live query', () => {
    const onSubmit = vi.fn();
    authenticateAs('reader', 'viewer', ['tenant-one']);
    render(<QueryForm isLoading={false} onSubmit={onSubmit} />);

    const submit = screen.getByRole('button', {
      name: 'Operator access required',
    });
    expect((submit as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(submit);
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
