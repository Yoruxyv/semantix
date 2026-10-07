import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';

const namespaces = ['tenant-primary-' + 'a'.repeat(40), 'tenant-secondary'] as const;

test('required namespace is visible, keyboard actionable, and never silently selected', async ({
  page,
}, testInfo) => {
  let queries = 0;
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/auth/config')) {
      await route.fulfill({ json: { authentication_required: true } });
    } else if (path.endsWith('/auth/session')) {
      await route.fulfill({
        json: { name: 'synthetic-operator', role: 'operator', namespaces },
      });
    } else if (path.endsWith('/cache/stats')) {
      await route.fulfill({ json: { size: 0, hits: 0, misses: 0, hit_rate: 0 } });
    } else if (path.endsWith('/cache/threshold')) {
      await route.fulfill({ json: { threshold: 0.92 } });
    } else if (path.endsWith('/query')) {
      queries += 1;
      expect(route.request().postDataJSON()).toMatchObject({
        namespace: namespaces[1],
        private: false,
        cache_enabled: true,
      });
      await route.fulfill({
        json: {
          response: 'Synthetic offline response',
          cache_hit: false,
          similarity_score: null,
          similarity_threshold: 0.92,
          matched_prompt: null,
          matched_cache_key: null,
          cache_entry_created_at: null,
          cache_entry_age_seconds: null,
          generation_skipped: false,
          provider_called: true,
          latency_ms: 8,
        },
      });
    } else {
      await route.fulfill({
        status: 503,
        json: { detail: 'Synthetic offline endpoint unavailable' },
      });
    }
  });
  await page.goto('/');
  await page.getByLabel('Access token').fill('phase9-synthetic-browser-token');
  await page.getByRole('button', { name: 'Authenticate' }).click();
  const selector = page.getByLabel('Authorized namespace');
  const submit = page.getByRole('button', { name: 'Run query' });
  await expect(selector).toBeVisible();
  await expect(selector).toHaveValue('');
  await expect(
    page.getByText(/Choose one authorized cache namespace before running a query/),
  ).toBeVisible();
  await expect(submit).toBeDisabled();
  await expect(
    page.getByRole('link', { name: 'Observability', exact: true }),
  ).toHaveCount(0);
  await page.getByLabel('Query text').fill('Synthetic namespace probe');
  const widths = [320, 390, 744, 768, 820, 834, 1024, 1280, 1133, 1366, 1180, 1194];
  for (const width of widths) {
    await page.setViewportSize({ width, height: 1024 });
    await expect(selector).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth - window.innerWidth,
      ),
    ).toBeLessThanOrEqual(1);
  }
  expect(queries).toBe(0);
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.screenshot({
    path: testInfo.outputPath('monitor-required-namespace.png'),
    fullPage: true,
  });
  await selector.focus();
  await page.keyboard.press('End');
  await page.keyboard.press('Enter');
  await expect(selector).toHaveValue(namespaces[1]);
  await expect(submit).toBeEnabled();
  await submit.focus();
  await page.keyboard.press('Enter');
  await expect(page.getByText('FRESH RESPONSE', { exact: true })).toBeVisible();
  expect(queries).toBe(1);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.evaluate(() => {
    document.documentElement.style.fontSize = '200%';
  });
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth),
  ).toBeLessThanOrEqual(1);
  const plot = page.getByRole('region', { name: 'Similarity score visualization' });
  expect(
    await plot.evaluate((element) => element.scrollWidth - element.clientWidth),
  ).toBeLessThanOrEqual(1);
  await expect(plot.getByText('-1.00', { exact: true })).toBeVisible();
  await expect(plot.getByText('1.00', { exact: true })).toBeVisible();
  const result = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa'])
    .analyze();
  expect(result.violations).toEqual([]);
});
