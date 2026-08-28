import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';

const TOKEN = process.env.SEMANTIX_E2E_TOKEN;

if (!TOKEN) {
  throw new Error('SEMANTIX_E2E_TOKEN is required for authenticated E2E tests.');
}

test('authenticated keyboard workflow crosses Nginx and FastAPI', async ({ page }) => {
  await page.goto('/');

  await page.getByLabel('Access token').fill(TOKEN);
  await page.getByRole('button', { name: 'Authenticate' }).click();
  await expect(page.getByText('Authenticated access')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Probe the cache' })).toBeVisible();

  await page.reload();
  await expect(page.getByText('Authenticated access')).toBeVisible();
  await page.keyboard.press('Tab');
  const skipLink = page.getByRole('link', { name: 'Skip to content' });
  await expect(skipLink).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.locator('#main-content')).toBeFocused();

  const prompt = `Phase B browser workflow ${Date.now()}`;
  await page.getByLabel('Query text').fill(prompt);
  const submit = page.getByRole('button', { name: 'Run query' });
  await submit.focus();
  await page.keyboard.press('Enter');
  await expect(page.getByText('FRESH RESPONSE', { exact: true })).toBeVisible();

  await page.getByLabel('Query text').fill(prompt);
  await page.getByRole('button', { name: 'Run query' }).click();
  await expect(page.getByText('CACHE HIT', { exact: true })).toBeVisible();

  await expect(
    page.getByRole('navigation', { name: 'Primary navigation' }),
  ).toBeVisible();
  await expect(page.getByRole('main')).toHaveCount(1);

  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations).toEqual([]);
});
