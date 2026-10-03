import { Suspense, type JSX } from 'react';
import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { defineLazyPathRoute } from '@/app/router/lazyPage';
import { deferred } from '../features/support';

afterEach(cleanup);

describe('lazy page definitions', () => {
  it('deduplicates an intent preload and reuses it when the page mounts', async () => {
    const pageModule = deferred<{
      TestPage: () => JSX.Element;
    }>();
    const importer = vi.fn(() => pageModule.promise);
    const route = defineLazyPathRoute('test', 'test', importer, 'TestPage');

    const firstPreload = route.preload?.();
    const secondPreload = route.preload?.();

    expect(importer).toHaveBeenCalledOnce();

    await act(async () => {
      pageModule.resolve({
        TestPage: () => <h1>Preloaded page</h1>,
      });
      await Promise.all([firstPreload, secondPreload]);
    });

    const Component = route.component;
    render(
      <Suspense fallback={<p>Loading test route</p>}>
        <Component />
      </Suspense>,
    );

    expect(
      await screen.findByRole('heading', {
        name: 'Preloaded page',
      }),
    ).toBeTruthy();
    expect(importer).toHaveBeenCalledOnce();
  });
});
