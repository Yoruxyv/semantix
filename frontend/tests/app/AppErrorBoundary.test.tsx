import { lazy, Suspense, type JSX } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AppErrorBoundary, type AppErrorReport } from '@/app/errors/AppErrorBoundary';

const SENSITIVE_ERROR = 'Bearer phase-b-secret-token upstream={"api_key":"private"}';

function sensitiveFailure(): Error {
  const error = new Error('Unexpected render failure');
  Object.defineProperty(error, 'payload', {
    configurable: false,
    enumerable: false,
    value: SENSITIVE_ERROR,
  });
  return error;
}

beforeEach(() => {
  vi.spyOn(console, 'error').mockImplementation(() => undefined);
});

afterEach(() => {
  vi.restoreAllMocks();
});

function BrokenChild(): JSX.Element {
  throw sensitiveFailure();
}

function renderBoundary(child: JSX.Element): {
  onError: ReturnType<typeof vi.fn<(report: AppErrorReport) => void>>;
  reload: ReturnType<typeof vi.fn>;
} {
  const onError = vi.fn<(report: AppErrorReport) => void>();
  const reload = vi.fn();
  render(
    <AppErrorBoundary onError={onError} reloadApplication={reload}>
      {child}
    </AppErrorBoundary>,
  );
  return { onError, reload };
}

describe('AppErrorBoundary', () => {
  it('contains an unexpected child render without exposing its payload', () => {
    const { onError } = renderBoundary(<BrokenChild />);

    const heading = screen.getByRole('heading', {
      name: 'Semantix could not finish loading',
    });
    expect(heading.isConnected).toBe(true);
    expect(screen.queryByText(SENSITIVE_ERROR)).toBeNull();
    expect(onError).toHaveBeenCalledWith({
      componentStackAvailable: true,
      errorName: 'Error',
    });
    expect(JSON.stringify(onError.mock.calls)).not.toContain('phase-b-secret-token');
  });

  it('contains a rejected lazy module and keeps recovery keyboard-operable', async () => {
    const RejectedPage = lazy(async () => Promise.reject(sensitiveFailure()));
    const { reload } = renderBoundary(
      <Suspense fallback={<p>Loading route</p>}>
        <RejectedPage />
      </Suspense>,
    );
    const button = await screen.findByRole('button', {
      name: 'Reload application',
    });

    button.focus();
    expect(document.activeElement).toBe(button);
    fireEvent.keyDown(button, { key: 'Enter' });
    fireEvent.click(button);

    expect(reload).toHaveBeenCalledOnce();
    expect(screen.queryByText(SENSITIVE_ERROR)).toBeNull();
  });
});
