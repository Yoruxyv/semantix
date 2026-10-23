import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';

import { benchmarkDataset } from '../features/benchmark/support';

const widths = [320, 744, 768, 820, 834, 1024, 1280, 1133, 1366, 640];
const cacheKey = 'a'.repeat(64);
const entry = {
  cache_key: cacheKey,
  namespace: 'default',
  prompt: 'Synthetic deletion evidence',
  response_preview: 'Readable synthetic response.',
  response_preview_truncated: false,
  response: null,
  created_at: '2026-10-23T10:00:00Z',
  expires_at: null,
  remaining_ttl_seconds: null,
  hit_count: 0,
  last_accessed_at: null,
  recency_rank: 1,
  is_expired: false,
};

async function checkAccess(page: Page) {
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth - innerWidth),
  ).toBeLessThanOrEqual(1);
  const result = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa'])
    .analyze();
  expect(result.violations).toEqual([]);
}

for (const width of widths) {
  test(`evaluation limit guidance is accessible and keyboard operable at ${width}px`, async ({
    page,
  }, info) => {
    await page.setViewportSize({ width, height: 900 });
    let runs = 0;
    await page.route('**/api/v1/**', async (route) => {
      const path = new URL(route.request().url()).pathname;
      switch (path) {
        case '/api/v1/auth/config':
          await route.fulfill({ json: { authentication_required: false } });
          return;
        case '/api/v1/cache/stats':
          await route.fulfill({ json: { size: 0, hits: 0, misses: 0, hit_rate: 0 } });
          return;
        case '/api/v1/cache/threshold':
          await route.fulfill({ json: { threshold: 0.92 } });
          return;
        case '/api/v1/evaluations/datasets':
          await route.fulfill({
            json: { datasets: [benchmarkDataset], default_dataset_id: 'quick' },
          });
          return;
        case '/api/v1/evaluations/runs':
          runs += 1;
          await route.fulfill({
            status: 422,
            json: {
              error: 'evaluation_workload_limit_exceeded',
              detail: 'Configured query budget exceeded.',
              traceback: 'PrivateException /srv/private.py',
            },
          });
          return;
        default:
          await route.abort('blockedbyclient');
      }
    });
    await page.goto('/evaluations');
    await page.getByLabel('Benchmark history namespace').fill('default');
    const review = page.getByRole('button', { name: 'Review benchmark run' });
    await review.focus();
    await review.press('Enter');
    const confirm = page.getByRole('button', { name: 'Run benchmark now' });
    await confirm.focus();
    await confirm.press('Enter');
    const alert = page.getByRole('alert');
    await expect(
      alert.getByText('Evaluation limit reached', { exact: true }),
    ).toBeVisible();
    await expect(
      alert.getByText(
        'This evaluation exceeds the maximum number of queries allowed per run.',
      ),
    ).toBeVisible();
    await expect(
      alert.getByText(
        'Reduce the number of repetitions or select a smaller dataset, then try again.',
      ),
    ).toBeVisible();
    await expect(page.getByText('Evaluation failed', { exact: true })).toHaveCount(0);
    await expect(page.getByText(/PrivateException|srv\/private/)).toHaveCount(0);
    expect(runs).toBe(1);
    await checkAccess(page);
    if (width === 320 || width === 1280)
      await page.screenshot({
        path: info.outputPath(`evaluation-limit-${width}.png`),
        fullPage: true,
      });
  });
}

for (const width of [320, 1280]) {
  for (const action of ['detail', 'clear'] as const) {
    test(`confirmed ${action} keeps success and reports refresh warning at ${width}px`, async ({
      page,
    }, info) => {
      await page.setViewportSize({ width, height: 900 });
      let writes = 0;
      await page.route('**/api/v1/**', async (route) => {
        const path = new URL(route.request().url()).pathname;
        if (route.request().method() === 'DELETE') {
          writes += 1;
          await route.fulfill({
            json:
              action === 'detail'
                ? { deleted: true, cache_key: cacheKey }
                : { cleared: true },
          });
          return;
        }
        switch (path) {
          case '/api/v1/auth/config':
            await route.fulfill({ json: { authentication_required: false } });
            return;
          case '/api/v1/cache/stats':
            if (writes > 0)
              await route.fulfill({
                status: 503,
                json: { error: 'unavailable', detail: 'Statistics unavailable.' },
              });
            else
              await route.fulfill({
                json: { size: 1, hits: 0, misses: 0, hit_rate: 0 },
              });
            return;
          case '/api/v1/cache/threshold':
            await route.fulfill({ json: { threshold: 0.92 } });
            return;
          case '/api/v1/cache/entries':
            await route.fulfill({
              json: {
                items: writes > 0 ? [] : [entry],
                total: writes > 0 ? 0 : 1,
                offset: 0,
                limit: 10,
                has_more: false,
              },
            });
            return;
          case `/api/v1/cache/entries/${cacheKey}`:
            await route.fulfill({ json: entry });
            return;
          default:
            await route.abort('blockedbyclient');
        }
      });
      await page.goto(action === 'detail' ? `/cache/entries/${cacheKey}` : '/cache');
      const request = page.getByRole('button', {
        name: action === 'detail' ? 'Delete cache entry' : 'Clear all entries',
      });
      await request.focus();
      await request.press('Enter');
      const confirm = page.getByRole('button', {
        name: action === 'detail' ? 'Confirm delete' : 'Confirm clear cache',
      });
      await confirm.focus();
      await confirm.press('Enter');
      await expect(
        page.getByText(
          'Cache statistics and threshold could not be refreshed. Showing the last confirmed readings.',
        ),
      ).toBeVisible();
      await expect(page.getByText('The cache is empty.')).toBeVisible();
      if (action === 'detail')
        await expect(
          page.getByText('Cache entry deleted.', { exact: true }),
        ).toBeVisible();
      await expect(page.getByText(/was not deleted|was not cleared/)).toHaveCount(0);
      expect(writes).toBe(1);
      await checkAccess(page);
      await page.screenshot({
        path: info.outputPath(`${action}-warning-${width}.png`),
        fullPage: true,
      });
    });
  }
}
