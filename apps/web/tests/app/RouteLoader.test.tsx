import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, describe, expect, it } from 'vitest';

import { RouteLoader } from '@/app/router/RouteLoader';

afterEach(cleanup);

describe('RouteLoader', () => {
  it.each([
    ['/', 'monitor', '[data-skeleton-query-input]', 1],
    ['/cache', 'cache', '[data-skeleton-route-entry]', 2],
    ['/evaluations', 'benchmark', '[data-skeleton-route-control]', 6],
    ['/benchmarks', 'benchmark', '[data-skeleton-route-control]', 6],
    ['/observability', 'observability', '[data-skeleton-route-metric]', 12],
  ])('matches the destination layout for %s', (path, kind, selector, expectedCount) => {
    const { container } = render(
      <MemoryRouter initialEntries={[path]}>
        <RouteLoader />
      </MemoryRouter>,
    );

    expect(screen.getByLabelText('Loading workspace')).toBeTruthy();
    expect(container.querySelector(`[data-workspace-skeleton="${kind}"]`)).toBeTruthy();
    expect(container.querySelectorAll(selector)).toHaveLength(expectedCount);
  });
});
