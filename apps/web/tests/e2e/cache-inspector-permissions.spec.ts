import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';

const cacheKey = 'a'.repeat(64);
const entry = {
  cache_key: cacheKey,
  namespace: 'tenant-alpha',
  prompt: 'Synthetic Inspector permissions',
  response_preview: 'Synthetic cached response',
  response_preview_truncated: false,
  response: null,
  created_at: '2026-10-23T00:00:00Z',
  expires_at: null,
  remaining_ttl_seconds: null,
  hit_count: 1,
  last_accessed_at: null,
  recency_rank: 1,
  is_expired: false,
};

for (const width of [320, 1280]) {
  for (const role of [
    'viewer',
    'operator',
    'admin',
    'disabled',
    'restricted',
  ] as const) {
    test(`Inspector ${role} permissions and keyboard controls at ${width}px`, async ({
      page,
    }) => {
      let deletes = 0;
      const clears: string[] = [];
      await page.setViewportSize({ width, height: 900 });
      await page.addInitScript(() => {
        sessionStorage.setItem('semantix.auth.token', 'synthetic-browser-token');
      });
      await page.route('**/api/v1/**', async (route) => {
        const url = new URL(route.request().url());
        let json: unknown;
        switch (url.pathname) {
          case '/api/v1/auth/config':
            json = { authentication_required: role !== 'disabled' };
            break;
          case '/api/v1/auth/session':
            json = {
              name: 'synthetic-browser-user',
              role: role === 'restricted' || role === 'disabled' ? 'admin' : role,
              namespaces: role === 'admin' ? ['*'] : ['tenant-alpha'],
            };
            break;
          case '/api/v1/cache/stats':
            json = { size: 1, hits: 1, misses: 0, hit_rate: 1 };
            break;
          case '/api/v1/cache/threshold':
            json = { threshold: 0.92 };
            break;
          case '/api/v1/cache/entries':
            json = { items: [entry], total: 1, offset: 0, limit: 10, has_more: false };
            break;
          case `/api/v1/cache/entries/${cacheKey}`:
            if (route.request().method() === 'DELETE') {
              deletes += 1;
              json = { deleted: true, cache_key: cacheKey };
            } else {
              json = { ...entry, response: entry.response_preview };
            }
            break;
          case '/api/v1/cache':
            expect(route.request().method()).toBe('DELETE');
            clears.push(url.searchParams.get('namespace') ?? 'omitted');
            json = { cleared: true };
            break;
          default:
            await route.abort('blockedbyclient');
            return;
        }
        await route.fulfill({ contentType: 'application/json', json });
      });
      await page.goto('/cache');
      await expect(page.getByRole('heading', { name: entry.prompt })).toBeVisible();
      await page.getByLabel('Search cached prompts').fill('Synthetic');
      await page.getByLabel('Sort cache entries').selectOption('oldest');
      await page.getByRole('button', { name: 'Refresh' }).click();

      if (role === 'viewer' || role === 'operator') {
        await expect(page.getByRole('button', { name: /^(Delete|Clear)/ })).toHaveCount(
          0,
        );
        await page.getByRole('link', { name: 'View entry details' }).click();
        await expect(
          page.getByRole('heading', { name: 'Cache entry detail' }),
        ).toBeVisible();
        await expect(
          page.getByRole('button', { name: 'Delete cache entry' }),
        ).toHaveCount(0);
        expect(deletes).toBe(0);
        expect(clears).toEqual([]);
      } else {
        const remove = page.getByRole('button', { name: `Delete ${entry.prompt}` });
        await remove.focus();
        await remove.press('Enter');
        const confirmDelete = page.getByRole('button', {
          name: `Confirm delete ${entry.prompt}`,
        });
        await confirmDelete.focus();
        await confirmDelete.press('Enter');
        await expect.poll(() => deletes).toBe(1);
        const clear = page.getByRole('button', {
          name: role === 'restricted' ? 'Clear cache' : 'Clear all entries',
        });
        await clear.focus();
        await clear.press('Enter');
        if (role === 'restricted') {
          await expect(
            page.getByText(
              'Clear every cache entry and reset all backend cache statistics?',
            ),
          ).toHaveCount(0);
        }
        const confirmClear = page.getByRole('button', { name: 'Confirm clear cache' });
        await confirmClear.focus();
        await confirmClear.press('Enter');
        await expect.poll(() => clears).toEqual(['omitted']);
        await expect(page.getByRole('group', { name: /^Confirm/ })).toHaveCount(0);
      }
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - innerWidth,
      );
      expect(overflow).toBeLessThanOrEqual(1);
      const accessibility = await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa'])
        .analyze();
      expect(accessibility.violations).toEqual([]);
    });
  }
}
