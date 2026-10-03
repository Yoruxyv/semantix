import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { Alert, Button, InlineConfirmation } from '@/shared/components/ui';

afterEach(cleanup);

describe('shared UI primitives', () => {
  it('defaults buttons to button type and forwards native state', () => {
    render(<Button disabled>Action</Button>);

    const button = screen.getByRole<HTMLButtonElement>('button', {
      name: 'Action',
    });
    expect(button.type).toBe('button');
    expect(button.disabled).toBe(true);
  });

  it('preserves explicit submit button semantics', () => {
    render(<Button type="submit">Submit</Button>);

    const button = screen.getByRole<HTMLButtonElement>('button', {
      name: 'Submit',
    });
    expect(button.type).toBe('submit');
  });

  it('renders alert roles, titles, and content supplied by callers', () => {
    render(
      <Alert role="alert" title="Request failed" tone="error">
        Provider unavailable
      </Alert>,
    );

    expect(screen.getByRole('alert').textContent).toContain('Request failed');
    expect(screen.getByRole('alert').textContent).toContain('Provider unavailable');
  });

  it('runs inline confirmation callbacks', () => {
    const onCancel = vi.fn();
    const onConfirm = vi.fn();
    render(
      <InlineConfirmation
        ariaLabel="Confirm action"
        confirmLabel="Confirm"
        isPending={false}
        message="Continue?"
        pendingLabel="Working"
        onCancel={onCancel}
        onConfirm={onConfirm}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }));
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it('disables confirmation actions while pending', () => {
    render(
      <InlineConfirmation
        ariaLabel="Confirm action"
        confirmLabel="Confirm"
        isPending
        message="Continue?"
        pendingLabel="Working"
        onCancel={vi.fn()}
        onConfirm={vi.fn()}
      />,
    );

    expect(
      screen.getByRole<HTMLButtonElement>('button', { name: 'Working' }).disabled,
    ).toBe(true);
    expect(
      screen.getByRole<HTMLButtonElement>('button', { name: 'Cancel' }).disabled,
    ).toBe(true);
  });
});
