import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { useAuth } from '@/features/auth/hooks/useAuth';
import {
  CACHE_NAMESPACE_PATTERN_SOURCE,
  isCacheNamespace,
} from '@/features/cache/namespace';
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

  it('uses the same namespace alphabet in native HTML and request validation', () => {
    const nativePattern = new RegExp(`^${CACHE_NAMESPACE_PATTERN_SOURCE}$`, 'v');
    for (const [value, valid] of [
      ['tenant.one_two:three-four', true],
      ['a'.repeat(64), true],
      ['a'.repeat(65), false],
      ['*', false],
      ['-tenant', false],
      ['tenant space', false],
      ['tenant/other', false],
    ] as const) {
      expect(nativePattern.test(value)).toBe(valid);
      expect(isCacheNamespace(value)).toBe(valid);
    }
  });

  it('keeps Advanced visible and shows only the selected mode description', () => {
    const onSubmit = vi.fn();
    render(<QueryForm isLoading={false} onSubmit={onSubmit} />);
    const trigger = screen.getByRole('button', { name: /Request cache mode/ });
    expect(screen.getByRole('heading', { name: 'Advanced cache policy' })).toBeTruthy();
    expect(document.querySelectorAll('details')).toHaveLength(0);
    expect(trigger.getAttribute('aria-expanded')).toBe('false');
    expect(trigger.getAttribute('aria-haspopup')).toBe('listbox');
    expect(screen.queryByRole('listbox')).toBeNull();
    const description = document.getElementById(
      trigger.getAttribute('aria-describedby') ?? '',
    );
    expect(description?.textContent).toBe(
      'Read an eligible match or store a newly generated response.',
    );
    expect(screen.queryByText(/Prompt and response content are omitted/)).toBeNull();
    fireEvent.click(trigger);
    expect(screen.getByRole('listbox', { name: 'Request cache mode' })).toBeTruthy();
    expect(
      screen
        .getAllByRole('option')
        .map((option) => option.textContent?.replace('✓', '').trim()),
    ).toEqual(MODE_CASES.map(([, label]) => label));
    fireEvent.click(screen.getByRole('option', { name: 'Private request' }));
    expect(screen.queryByRole('listbox')).toBeNull();
    expect(document.activeElement).toBe(trigger);
    expect(trigger.textContent).toBe('Private request');
    expect(description?.textContent).toBe(
      'Skip cache reads and writes. Prompt and response content are omitted from the recent query trace.',
    );
    expect(description?.classList.contains('text-(--gold)')).toBe(true);
    expect(
      screen.queryByText('Read an eligible match or store a newly generated response.'),
    ).toBeNull();
    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole('option', { name: 'Read only' }));
    expect(description?.textContent).toBe(
      'Read an eligible match but never store a generated response.',
    );
    expect(description?.classList.contains('text-(--gold)')).toBe(false);
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('moves listbox focus separately from selection and cancels with Escape', () => {
    render(<QueryForm isLoading={false} onSubmit={vi.fn()} />);
    const trigger = screen.getByRole('button', { name: /Request cache mode/ });
    fireEvent.click(trigger);
    const list = screen.getByRole('listbox');
    const normal = screen.getByRole('option', { name: 'Normal read and write' });
    expect(document.activeElement).toBe(normal);
    expect(normal.getAttribute('aria-selected')).toBe('true');
    fireEvent.keyDown(list, { key: 'ArrowDown' });
    const readOnly = screen.getByRole('option', { name: 'Read only' });
    expect(document.activeElement).toBe(readOnly);
    expect(readOnly.getAttribute('aria-selected')).toBe('false');
    expect(trigger.textContent).toBe('Normal read and write');
    fireEvent.keyDown(list, { key: 'End' });
    expect(document.activeElement).toBe(
      screen.getByRole('option', { name: 'Private request' }),
    );
    fireEvent.keyDown(list, { key: 'ArrowUp' });
    expect(document.activeElement).toBe(
      screen.getByRole('option', { name: 'Bypass cache' }),
    );
    fireEvent.keyDown(list, { key: 'Home' });
    expect(document.activeElement).toBe(normal);
    fireEvent.keyDown(list, { key: 'Escape' });
    expect(screen.queryByRole('listbox')).toBeNull();
    expect(document.activeElement).toBe(trigger);
    expect(trigger.textContent).toBe('Normal read and write');
  });

  it('dismisses the popup on outside interaction, blur, and Tab without selecting', () => {
    const onSubmit = vi.fn();
    render(<QueryForm isLoading={false} onSubmit={onSubmit} />);
    const trigger = screen.getByRole('button', { name: /Request cache mode/ });
    fireEvent.click(trigger);
    fireEvent.pointerDown(screen.getByLabelText('Query text'));
    expect(screen.queryByRole('listbox')).toBeNull();
    fireEvent.click(trigger);
    fireEvent.blur(screen.getByRole('option', { name: 'Normal read and write' }), {
      relatedTarget: screen.getByLabelText('Query text'),
    });
    expect(screen.queryByRole('listbox')).toBeNull();
    fireEvent.click(trigger);
    fireEvent.keyDown(screen.getByRole('listbox'), { key: 'End' });
    fireEvent.keyDown(screen.getByRole('listbox'), { key: 'Tab' });
    expect(screen.queryByRole('listbox')).toBeNull();
    expect(document.activeElement).toBe(trigger);
    expect(trigger.textContent).toBe('Normal read and write');
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it.each(MODE_CASES)(
    'maps %s mode to the existing query policy fields',
    async (mode, label, cacheEnabled, readEnabled, writeEnabled, isPrivate) => {
      const onSubmit = vi.fn(async () => undefined);
      render(<QueryForm isLoading={false} onSubmit={onSubmit} />);

      fireEvent.change(screen.getByLabelText('Query text'), {
        target: { value: 'Policy probe' },
      });
      const trigger = screen.getByRole('button', { name: /Request cache mode/ });
      fireEvent.click(trigger);
      fireEvent.click(screen.getByRole('option', { name: label }));
      expect(trigger.textContent).toBe(label);
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
        screen.getByRole<HTMLButtonElement>('button', { name: 'Run query' }).disabled,
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

  it('labels only the built-in namespace while submitting its canonical value', async () => {
    authenticateAs('multiple', 'operator', [
      'default',
      'DEFAULT',
      'default-tenant',
      'tenant.Mixed',
    ]);
    const onSubmit = vi.fn(async () => undefined);
    const view = render(<QueryForm isLoading={false} onSubmit={onSubmit} />);
    const namespace = screen.getByRole<HTMLSelectElement>('combobox', {
      name: 'Authorized namespace',
    });
    expect(
      Array.from(namespace.options, (option) => [option.value, option.text]),
    ).toEqual([
      ['', 'Choose a namespace'],
      ['default', 'Default'],
      ['DEFAULT', 'DEFAULT'],
      ['default-tenant', 'default-tenant'],
      ['tenant.Mixed', 'tenant.Mixed'],
    ]);
    fireEvent.change(namespace, { target: { value: 'default' } });
    fireEvent.change(screen.getByLabelText('Query text'), {
      target: { value: 'Namespace probe' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Run query' }));
    await waitFor(() =>
      expect(onSubmit).toHaveBeenCalledWith(
        expect.objectContaining({
          request: expect.objectContaining({ namespace: 'default' }),
        }),
      ),
    );
    expect(screen.getByText(/Effective request: namespace default/)).toBeTruthy();
    view.unmount();
    authenticateAs('single', 'operator', ['default']);
    render(<QueryForm isLoading={false} onSubmit={onSubmit} />);
    expect(screen.getByText('Default', { exact: true })).toBeTruthy();
    expect(screen.getByText(/Effective request: namespace default/)).toBeTruthy();
  });

  it('requires wildcard principals to provide one valid explicit namespace', () => {
    authenticateAs('global', 'admin', ['*']);
    render(<QueryForm isLoading={false} onSubmit={vi.fn()} />);

    const namespace = screen.getByLabelText('Explicit namespace');
    expect((namespace as HTMLInputElement).value).toBe('default');

    fireEvent.change(namespace, { target: { value: 'not allowed' } });
    expect(
      screen.getByRole<HTMLButtonElement>('button', { name: 'Run query' }).disabled,
    ).toBe(true);
    expect(screen.getByText(/namespace not selected/i)).toBeTruthy();
  });

  it('surfaces required namespace selection alongside visible policy controls', async () => {
    authenticateAs('multiple', 'operator', ['tenant-one', 'tenant-two']);
    const onSubmit = vi.fn(async () => undefined);
    render(<QueryForm isLoading={false} onSubmit={onSubmit} />);
    const selector = screen.getByLabelText<HTMLSelectElement>('Authorized namespace');
    expect(selector.value).toBe('');
    expect(selector.closest('details')).toBeNull();
    expect(document.querySelector('details')).toBeNull();
    expect(screen.getByRole('button', { name: /Request cache mode/ })).toBeTruthy();
    expect(
      screen.getByText(/Choose one authorized cache namespace before running a query/),
    ).toBeTruthy();
    const submit = screen.getByRole<HTMLButtonElement>('button', { name: 'Run query' });
    expect(submit.disabled).toBe(true);
    expect(submit.getAttribute('aria-describedby')).toBe('query-namespace-required');
    fireEvent.change(screen.getByLabelText('Query text'), {
      target: { value: 'Namespace probe' },
    });
    fireEvent.click(submit);
    expect(onSubmit).not.toHaveBeenCalled();
    fireEvent.change(selector, { target: { value: 'tenant-two' } });
    expect(submit.disabled).toBe(false);
    expect(
      screen.queryByText(
        /Choose one authorized cache namespace before running a query/,
      ),
    ).toBeNull();
    fireEvent.click(submit);
    await waitFor(() =>
      expect(onSubmit).toHaveBeenCalledWith(
        expect.objectContaining({
          request: expect.objectContaining({ namespace: 'tenant-two' }),
        }),
      ),
    );
  });

  it('keeps zero-authorized and invalid wildcard namespaces blocked with an explanation', () => {
    authenticateAs('none', 'operator', []);
    const onSubmit = vi.fn();
    const view = render(<QueryForm isLoading={false} onSubmit={onSubmit} />);
    expect(screen.getByText('No authorized namespace')).toBeTruthy();
    expect(
      screen.getByRole<HTMLButtonElement>('button', { name: 'Run query' }).disabled,
    ).toBe(true);
    expect(
      screen.getByText(/Choose one authorized cache namespace before running a query/),
    ).toBeTruthy();
    view.unmount();
    authenticateAs('wildcard', 'admin', ['*']);
    render(<QueryForm isLoading={false} onSubmit={onSubmit} />);
    const namespace = screen.getByLabelText('Explicit namespace');
    expect(namespace.closest('details')).toBeNull();
    fireEvent.change(namespace, { target: { value: '*' } });
    expect(namespace.getAttribute('aria-invalid')).toBe('true');
    expect(
      screen.getByRole<HTMLButtonElement>('button', { name: 'Run query' }).disabled,
    ).toBe(true);
    expect(onSubmit).not.toHaveBeenCalled();
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
