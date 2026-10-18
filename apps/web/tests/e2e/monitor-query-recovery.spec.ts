import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';

const SAMPLE_PROMPTS = [
  'Explain semantic caching in simple terms',
  'How does cosine similarity work?',
] as const;
const PROVIDER_MESSAGE =
  "The AI provider couldn't complete your request. Check its availability, configuration, or billing status, then try again.";
const NETWORK_MESSAGE =
  "Couldn't reach the server. Check your connection and try again.";
const SENSITIVE_DETAIL = 'SENSITIVE_PROVIDER_DETAIL_DO_NOT_RENDER';
const FRESH_RESPONSE = {
  response: 'Synthetic successful provider response',
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
};

async function installWorkspaceFixtures(page: Page): Promise<void> {
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/auth/config')) {
      await route.fulfill({ json: { authentication_required: false } });
    } else if (path.endsWith('/cache/stats')) {
      await route.fulfill({ json: { size: 0, hits: 0, misses: 0, hit_rate: 0 } });
    } else if (path.endsWith('/cache/threshold')) {
      await route.fulfill({ json: { threshold: 0.92 } });
    } else {
      await route.fulfill({
        status: 503,
        json: { error: 'fixture_unavailable', detail: null },
      });
    }
  });
}

async function expectNoOverflow(page: Page): Promise<void> {
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth),
  ).toBeLessThanOrEqual(1);
}

test('query context precedes the prompt, submit stays adjacent, and samples never submit', async ({
  page,
}, testInfo) => {
  test.setTimeout(60_000);
  await installWorkspaceFixtures(page);
  let queries = 0;
  await page.route('**/api/v1/query', async (route) => {
    queries += 1;
    await route.fulfill({ json: FRESH_RESPONSE });
  });
  await page.goto('/');
  const prompt = page.getByLabel('Query text', { exact: true });
  const samples = page.getByRole('group', { name: 'Sample probes' });
  await expect(samples).toHaveCount(1);
  const widths = [320, 744, 768, 820, 834, 1024, 1280, 1133, 1366, 1180, 1194, 640];
  for (const width of widths) {
    await page.setViewportSize({ width, height: 900 });
    await expectNoOverflow(page);
    const promptBox = await prompt.boundingBox();
    const samplesBox = await samples.boundingBox();
    const namespaceBox = await page.getByLabel('Explicit namespace').boundingBox();
    expect(promptBox).not.toBeNull();
    expect(samplesBox).not.toBeNull();
    expect(namespaceBox).not.toBeNull();
    expect(samplesBox!.y).toBeGreaterThanOrEqual(promptBox!.y + promptBox!.height);
    const runBox = await page
      .getByRole('button', { name: 'Run query', exact: true })
      .boundingBox();
    const modeBox = await page
      .getByRole('button', { name: /Request cache mode/ })
      .boundingBox();
    expect(runBox).not.toBeNull();
    expect(modeBox).not.toBeNull();
    expect(namespaceBox!.y + namespaceBox!.height).toBeLessThan(promptBox!.y);
    expect(modeBox!.y + modeBox!.height).toBeLessThan(promptBox!.y);
    expect(runBox!.y).toBeGreaterThanOrEqual(promptBox!.y + promptBox!.height);
    expect(runBox!.y - promptBox!.y - promptBox!.height).toBeLessThan(100);
    expect(samplesBox!.y).toBeGreaterThanOrEqual(runBox!.y + runBox!.height);
    if (width >= 1024) expect(runBox!.y + runBox!.height).toBeLessThanOrEqual(900);
    for (const example of SAMPLE_PROMPTS) {
      await expect(samples.getByRole('button', { name: example })).toBeVisible();
    }
  }
  for (const width of [320, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    const accessibility = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'])
      .analyze();
    expect(accessibility.violations).toEqual([]);
    const path = testInfo.outputPath(`monitor-samples-${width}.png`);
    await page.screenshot({ path, fullPage: true });
    await testInfo.attach(`Monitor samples at ${width}px`, {
      path,
      contentType: 'image/png',
    });
  }
  await prompt.focus();
  await page.keyboard.press('Tab');
  await expect(
    page.getByRole('button', { name: 'Run query', exact: true }),
  ).toBeFocused();
  await page.keyboard.press('Tab');
  const first = samples.getByRole('button', { name: SAMPLE_PROMPTS[0] });
  await expect(first).toBeFocused();
  await expect(first).toHaveCSS('outline-width', '2px');
  await page.keyboard.press('Enter');
  await expect(prompt).toBeFocused();
  await expect(prompt).toHaveValue(SAMPLE_PROMPTS[0]);
  await page.keyboard.type(' with an edited detail');
  await expect(prompt).toHaveValue(`${SAMPLE_PROMPTS[0]} with an edited detail`);
  await page.keyboard.press('Tab');
  await page.keyboard.press('Tab');
  await page.keyboard.press('Tab');
  await expect(samples.getByRole('button', { name: SAMPLE_PROMPTS[1] })).toBeFocused();
  await page.keyboard.press('Space');
  await expect(prompt).toBeFocused();
  await expect(prompt).toHaveValue(SAMPLE_PROMPTS[1]);
  await page.keyboard.press('Enter');
  await expect(prompt).toHaveValue(`${SAMPLE_PROMPTS[1]}\n`);
  expect(queries).toBe(0);
  await page.evaluate(() => {
    document.documentElement.style.fontSize = '200%';
  });
  await expectNoOverflow(page);
  const zoomAccessibility = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa'])
    .analyze();
  expect(zoomAccessibility.violations).toEqual([]);
});

for (const failure of ['provider', 'network', 'timeout'] as const) {
  test(`recovers from ${failure} failure without losing form state or adding success evidence`, async ({
    page,
  }, testInfo) => {
    await installWorkspaceFixtures(page);
    let queries = 0;
    let releaseFailure = (): void => undefined;
    const failureReady = new Promise<void>((resolve) => {
      releaseFailure = resolve;
    });
    await page.route('**/api/v1/query', async (route) => {
      queries += 1;
      expect(route.request().postDataJSON()).toMatchObject({
        prompt: 'Synthetic recovery probe',
        namespace: 'monitor-recovery',
        cache_read_enabled: true,
        cache_write_enabled: false,
        private: false,
      });
      if (queries === 2) {
        await failureReady;
        if (failure === 'provider') {
          await route.fulfill({
            status: 502,
            json: {
              error: 'upstream_error',
              detail: SENSITIVE_DETAIL,
              authorization: 'Synthetic authorization data',
              traceback: 'Synthetic internal trace',
            },
          });
        } else {
          await route.abort(failure === 'timeout' ? 'timedout' : 'failed');
        }
      } else if (queries === 1) {
        await route.fulfill({
          json: {
            ...FRESH_RESPONSE,
            response: 'Synthetic cached response',
            cache_hit: true,
            similarity_score: 0.97,
            matched_prompt: 'Synthetic recovery probe',
            matched_cache_key: 'a'.repeat(64),
            cache_entry_created_at: '2026-07-17T10:00:00Z',
            cache_entry_age_seconds: 2,
            generation_skipped: true,
            provider_called: false,
          },
        });
      } else {
        await route.fulfill({ json: FRESH_RESPONSE });
      }
    });
    await page.goto('/');
    const prompt = page.getByLabel('Query text', { exact: true });
    const namespace = page.getByLabel('Explicit namespace');
    await prompt.fill('Synthetic recovery probe');
    await namespace.fill('monitor-recovery');
    await page.getByRole('button', { name: /Request cache mode/ }).click();
    await page.getByRole('option', { name: 'Read only', exact: true }).click();
    const run = page.getByRole('button', { name: 'Run query', exact: true });
    await run.click();
    await expect(page.getByText('CACHE HIT', { exact: true })).toBeVisible();
    const trace = page
      .getByRole('heading', { name: 'Recent query trace' })
      .locator('..')
      .locator('..');
    await expect(trace.getByText('01 records', { exact: true })).toBeVisible();
    await run.click();
    await expect(page.getByLabel('Loading query response')).toBeVisible();
    await expect(prompt).toBeDisabled();
    await expect(
      page.getByRole('group', { name: 'Sample probes' }).getByRole('button').first(),
    ).toBeDisabled();
    releaseFailure();
    const alert = page.getByRole('alert');
    await expect(alert).toContainText(
      failure === 'provider' ? PROVIDER_MESSAGE : NETWORK_MESSAGE,
    );
    await expect(page.getByRole('heading', { name: 'Latest response' })).toHaveCount(0);
    await expect(page.getByText('CACHE HIT', { exact: true })).toHaveCount(0);
    await expect(page.getByLabel('Loading query response')).toHaveCount(0);
    await expect(trace.getByText('01 records', { exact: true })).toBeVisible();
    await expect(prompt).toHaveValue('Synthetic recovery probe');
    await expect(namespace).toHaveValue('monitor-recovery');
    await expect(
      page.getByRole('button', { name: /Request cache mode/ }),
    ).toContainText('Read only');
    await expect(run).toBeEnabled();
    await expect(page.locator('body')).not.toContainText(SENSITIVE_DETAIL);
    await expect(page.locator('body')).not.toContainText(
      'Synthetic authorization data',
    );
    await expect(page.locator('body')).not.toContainText('Synthetic internal trace');
    expect(queries).toBe(2);
    if (failure === 'provider') {
      await page.evaluate(() => window.scrollTo(0, 0));
      const path = testInfo.outputPath('monitor-provider-error.png');
      await page.screenshot({ path, fullPage: true });
      await testInfo.attach('Safe provider failure', {
        path,
        contentType: 'image/png',
      });
      const accessibility = await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa'])
        .analyze();
      expect(accessibility.violations).toEqual([]);
    }
    await run.click();
    await expect(page.getByText('FRESH RESPONSE', { exact: true })).toBeVisible();
    await expect(
      page.getByText(FRESH_RESPONSE.response, { exact: true }),
    ).toBeVisible();
    await expect(page.getByRole('alert')).toHaveCount(0);
    await expect(trace.getByText('02 records', { exact: true })).toBeVisible();
    expect(queries).toBe(3);
  });
}

test('does not classify an unrecognized 502 as a provider or billing failure', async ({
  page,
}) => {
  await installWorkspaceFixtures(page);
  await page.route('**/api/v1/query', async (route) => {
    await route.fulfill({
      status: 502,
      json: { error: 'http_error', detail: SENSITIVE_DETAIL },
    });
  });
  await page.goto('/');
  await page
    .getByLabel('Query text', { exact: true })
    .fill('Synthetic gateway failure');
  await page.getByRole('button', { name: 'Run query', exact: true }).click();
  const alert = page.getByRole('alert');
  await expect(alert).toContainText(
    "Your query couldn't be completed. Check your request and try again.",
  );
  await expect(alert).not.toContainText('billing');
  await expect(alert).not.toContainText('AI provider');
  await expect(page.locator('body')).not.toContainText(SENSITIVE_DETAIL);
  await expect(page.getByText('00 records', { exact: true })).toBeVisible();
});
