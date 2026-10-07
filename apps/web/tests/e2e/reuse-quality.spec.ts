import AxeBuilder from '@axe-core/playwright';
import { readFileSync } from 'node:fs';

import { expect, test } from '@playwright/test';

// Renderer fixture only; the actual public receipt requires maintainer approval.
const receipt = readFileSync(
  'tests/features/benchmark/qualitySummary.fixture.json',
  'utf8',
);

const widths = [320, 744, 768, 820, 834, 1024, 1280, 1133, 1366, 1180, 1194];

test('static quality evidence is accessible, responsive and keyboard operable', async ({
  page,
}) => {
  await page.route('**/api/v1/**', async (route) => {
    if (route.request().url().endsWith('/auth/config')) {
      await route.fulfill({ json: { authentication_required: false } });
    } else {
      await route.fulfill({
        status: 503,
        json: { detail: 'No live server in static evidence test' },
      });
    }
  });
  await page.route('**/benchmarks/reuse-quality-summary.json', async (route) => {
    await route.fulfill({ contentType: 'application/json', body: receipt });
  });
  await page.goto('/evaluations');
  const quality = page.getByRole('link', { name: 'Reuse quality', exact: true });
  await quality.focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('heading', { name: 'Reuse quality' })).toBeVisible();
  await expect(page.getByText(/not live telemetry/)).toBeVisible();
  await expect(page.getByText('False acceptance rate', { exact: true })).toBeVisible();
  await expect(
    page.getByText(/Wrong among accepted: FP \/ \(TP \+ FP\)/),
  ).toBeVisible();
  await expect(page.getByRole('combobox')).toHaveValue(
    'semantix-quality:minilm-l6-v2:1110a243fdf4706b3f48f1d95db1a4f5529b4d41:d384:raw',
  );
  const detailed = page.getByText('Detailed threshold results', { exact: true });
  await expect(detailed.locator('..')).not.toHaveAttribute('open');
  await detailed.focus();
  await page.keyboard.press('Enter');
  await expect(
    page.getByRole('table', { name: /Held-out threshold sweep/ }),
  ).toBeVisible();
  await detailed.press('Enter');
  await page.setViewportSize({ width: 320, height: 900 });
  await detailed.press('Enter');
  const tableRegion = page.getByRole('region', {
    name: 'Threshold results, scroll horizontally for all columns',
  });
  await tableRegion.focus();
  await tableRegion.press('ArrowRight');
  await expect
    .poll(() => tableRegion.evaluate((element) => element.scrollLeft))
    .toBeGreaterThan(0);
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth),
  ).toBeLessThanOrEqual(1);
  await detailed.press('Enter');
  const configuration = page.getByLabel('Embedding / normalization ablation');
  await configuration.focus();
  await page.keyboard.press('End');
  await page.keyboard.press('Enter');
  await expect(configuration).toBeFocused();
  for (const width of widths) {
    await page.setViewportSize({ width, height: width < 1024 ? 1024 : 744 });
    await expect(configuration).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth - window.innerWidth,
      ),
    ).toBeLessThanOrEqual(1);
  }
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.evaluate(() => {
    document.documentElement.style.fontSize = '200%';
  });
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth),
  ).toBeLessThanOrEqual(1);
  const result = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa'])
    .analyze();
  expect(result.violations).toEqual([]);
});

test('missing manifest never shows fallback evidence', async ({ page }) => {
  await page.route('**/api/v1/**', async (route) => {
    await route.fulfill({ json: { authentication_required: false } });
  });
  await page.route('**/benchmarks/reuse-quality-summary.json', async (route) => {
    await route.fulfill({ status: 404, body: 'missing' });
  });
  await page.goto('/evaluations');
  await page.getByRole('link', { name: 'Reuse quality', exact: true }).click();
  await expect(page.getByText('Reuse quality unavailable')).toBeVisible();
  await expect(page.getByText(/No fallback metrics/)).toBeVisible();
  await expect(page.getByText('Source commit SHA')).toHaveCount(0);
});
