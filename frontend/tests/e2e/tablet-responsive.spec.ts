import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';

import {
  benchmarkAnalysisResult,
  benchmarkDataset,
  persistedDataset,
} from '../features/benchmark/support';

const VIEWPORTS = [
  { name: 'minimum', width: 320, height: 720 },
  { name: 'tablet-744', width: 744, height: 1_024 },
  { name: 'tablet-768', width: 768, height: 1_024 },
  { name: 'tablet-820', width: 820, height: 1_180 },
  { name: 'tablet-834', width: 834, height: 1_194 },
  { name: 'landscape-1133', width: 1_133, height: 744 },
  { name: 'landscape-1366', width: 1_366, height: 768 },
  { name: 'desktop-1024', width: 1_024, height: 900 },
  { name: 'desktop-1280', width: 1_280, height: 900 },
  {
    name: 'zoom-200-equivalent-at-1280',
    width: 640,
    height: 900,
  },
] as const;

const HISTORY_NAMESPACE =
  'tenant-responsive-history-with-a-long-name-for-layout';

function retainedHistoryRun(runId: string) {
  return {
    run_id: runId,
    namespace: HISTORY_NAMESPACE,
    terminal_state: 'completed' as const,
    accepted_at: '2026-07-17T09:59:58Z',
    started_at: benchmarkAnalysisResult.started_at,
    completed_at: benchmarkAnalysisResult.completed_at,
    expires_at: '2026-08-16T10:00:02Z',
    source_dataset_expires_at: null,
    dataset: {
      ...benchmarkAnalysisResult.dataset,
      name: `${benchmarkAnalysisResult.dataset.name} with an intentionally long retained-history label`,
    },
    reproducibility: benchmarkAnalysisResult.reproducibility,
    metrics: benchmarkAnalysisResult.metrics,
    failure_code: null,
    safe_failure_detail: null,
    threshold_evaluation_mode:
      benchmarkAnalysisResult.threshold_evaluation_mode,
    threshold_evaluations: benchmarkAnalysisResult.threshold_evaluations,
  };
}

const retainedBaseline = retainedHistoryRun('a'.repeat(32));
const retainedCandidate = retainedHistoryRun('b'.repeat(32));

const comparisonMetricDeltas = {
  measured_threshold: 0,
  total_queries: 0,
  cache_hits: 0,
  cache_misses: 0,
  provider_calls: 0,
  provider_calls_avoided: 0,
  hit_rate: 0,
  average_latency_ms: 0,
  median_latency_ms: 0,
  p95_latency_ms: 0,
  average_cache_hit_latency_ms: 0,
  average_cache_miss_latency_ms: 0,
  estimated_latency_saved_ms: 0,
  estimated_provider_cost_saved_usd: 0,
  estimated_tokens_saved: 0,
  true_positive_hits: 0,
  true_negative_misses: 0,
  false_positive_hits: 0,
  false_negative_misses: 0,
  precision: 0,
  recall: 0,
  f1_score: 0,
};

const comparisonThresholdDeltas =
  benchmarkAnalysisResult.threshold_evaluations.map((evaluation) => ({
    threshold: evaluation.threshold,
    baseline_result_kind: evaluation.result_kind,
    candidate_result_kind: evaluation.result_kind,
    hit_rate: 0,
    precision: 0,
    recall: 0,
    f1_score: 0,
    average_latency_ms: 0,
    provider_calls_avoided: 0,
    true_positive_hits: 0,
    true_negative_misses: 0,
    false_positive_hits: 0,
    false_negative_misses: 0,
  }));

function compatibleComparison() {
  return {
    baseline: retainedBaseline,
    candidate: retainedCandidate,
    compatibility: {
      status: 'compatible' as const,
      can_compare: true,
      incompatibilities: [],
      warnings: [],
      case_evidence: 'not_retained' as const,
      opaque_configuration_fingerprint_matches: true,
    },
    metric_deltas: comparisonMetricDeltas,
    threshold_deltas: comparisonThresholdDeltas,
  };
}

test.beforeEach(async ({ page }) => {
  await page.route('**/api/v1/auth/config', async (route) => {
    await route.fulfill({
      contentType: 'application/json',
      json: { authentication_required: false },
    });
  });
  await page.route('**/api/v1/cache/stats**', async (route) => {
    await route.fulfill({
      contentType: 'application/json',
      json: { size: 1, hits: 1, misses: 0, hit_rate: 1 },
    });
  });
  await page.route('**/api/v1/cache/threshold', async (route) => {
    await route.fulfill({
      contentType: 'application/json',
      json: { threshold: 0.92 },
    });
  });
  await page.route('**/api/v1/metrics', async (route) => {
    await route.fulfill({
      contentType: 'application/json',
      json: {
        observed_at: '2026-08-21T08:00:00Z',
        uptime_seconds: 3_600,
        request_count: 12,
        error_count: 1,
        cache_hits: 7,
        cache_misses: 4,
        provider_calls: 4,
        in_flight_coalesced_requests: 0,
        average_latency_ms: 25.5,
        p95_latency_ms: 80.25,
        latency_sample_size: 12,
        cache_size: 5,
        evictions: 3,
        expirations: 2,
      },
    });
  });
  await page.route('**/api/v1/diagnostics', async (route) => {
    await route.fulfill({
      contentType: 'application/json',
      json: {
        observed_at: '2026-08-21T08:00:00Z',
        process_scope: 'single_backend_process',
        application_version: '1.0.0',
        embedding_provider_category: 'mock',
        generation_provider_category: 'mock',
        embedding_dimensions: 384,
        embedding_space_fingerprint: 'a'.repeat(64),
        generation_configuration_fingerprint: 'b'.repeat(64),
        cache_backend: 'pgvector',
        cache_readiness: 'ready',
        normalization_mode: 'typo_correction',
        normalization_algorithm_version: 'symspell-compound-v1',
        normalization_fingerprint: 'c'.repeat(64),
        evaluation_timeout_seconds: 300,
        evaluation_max_cases: 50,
        evaluation_max_repetitions: 5,
        evaluation_max_thresholds: 15,
        evaluation_max_request_bytes: 65_536,
        evaluation_dataset_persistence_enabled: true,
        evaluation_history_persistence_enabled: true,
      },
    });
  });
  await page.route('**/api/v1/evaluations/datasets', async (route) => {
    await route.fulfill({
      contentType: 'application/json',
      json: {
        datasets: [
          {
            ...benchmarkDataset,
            name: `${benchmarkDataset.name} with an intentionally long responsive label`,
          },
        ],
        default_dataset_id: 'quick',
      },
    });
  });
  await page.route('**/api/v1/evaluations/runs', async (route) => {
    await route.fulfill({
      contentType: 'application/json',
      json: benchmarkAnalysisResult,
    });
  });
  await page.route('**/api/v1/evaluations/runs?*', async (route) => {
    await route.fulfill({
      contentType: 'application/json',
      json: {
        storage_mode: 'postgres',
        retention_enabled: true,
        items: [retainedBaseline, retainedCandidate],
        total: 2,
        offset: 0,
        limit: 12,
        has_more: false,
      },
    });
  });
  await page.route(
    '**/api/v1/evaluations/runs/compare',
    async (route) => {
      await route.fulfill({
        contentType: 'application/json',
        json: compatibleComparison(),
      });
    },
  );
  await page.route(
    `**/api/v1/evaluations/datasets/persisted/${persistedDataset.dataset_id}`,
    async (route) => {
      await route.fulfill({
        contentType: 'application/json',
        json: {
          ...persistedDataset,
          name: `${persistedDataset.name} with an intentionally long responsive label`,
          description:
            '<script>alert("catalog")</script> remains inert dataset text.',
        },
      });
    },
  );
  await page.route(
    '**/api/v1/evaluations/datasets/persisted?*',
    async (route) => {
      await route.fulfill({
        contentType: 'application/json',
        json: {
          storage_mode: 'postgres',
          persistence_enabled: true,
          items: [
            {
              ...persistedDataset,
              name: `${persistedDataset.name} with an intentionally long responsive label`,
              description:
                '<script>alert("catalog")</script> remains inert dataset text.',
              cases: undefined,
            },
          ],
          total: 1,
          offset: 0,
          limit: 12,
          has_more: false,
          limits: {
            default_retention_days: 30,
            max_retention_days: 365,
            max_persisted_per_namespace: 100,
          },
        },
      });
    },
  );
  await page.route(
    '**/api/v1/evaluations/datasets/validate',
    async (route) => {
      await route.fulfill({
        contentType: 'application/json',
        json: {
          schema_version: 1,
          dataset_id: 'custom:1234567890abcdef',
          digest: '9'.repeat(64),
          name: 'Imported responsive dataset with a long readable name',
          description: 'Synthetic session-local dataset.',
          case_count: 1,
          expected_hits: 0,
          expected_misses: 1,
          categories: ['uncategorized'],
          decoded_bytes: 180,
          warnings: [
            {
              code: 'uncategorized_cases',
              detail:
                'Cases without a category are grouped as uncategorized.',
              count: 1,
            },
          ],
          query_executions: 1,
          threshold_projection_evaluations: 7,
          maximum_provider_calls: 1,
          provider_calls_made: 0,
          limits: {
            max_cases: 50,
            max_decoded_bytes: 49_152,
            max_workload_queries: 250,
          },
        },
      });
    },
  );
});

test('runtime diagnostics remain readable, bounded, and accessible', async ({
  page,
}) => {
  for (const viewport of VIEWPORTS) {
    await test.step(`diagnostics-${viewport.name}`, async () => {
      await page.setViewportSize(viewport);
      await page.goto('/observability');
      await expect(
        page.getByRole('heading', { name: 'Runtime diagnostics' }),
      ).toBeVisible();
      await expect(page.getByText('One backend process')).toBeVisible();
      await expect(page.getByText('Ready', { exact: true })).toBeVisible();

      const columns = await page
        .locator('[data-runtime-diagnostics-grid]')
        .evaluate((element) =>
          getComputedStyle(element).gridTemplateColumns.split(' ').length,
        );
      expect(columns).toBe(viewport.width >= 1_024 ? 2 : 1);

      const overflow = await page.evaluate(
        () =>
          document.documentElement.scrollWidth -
          document.documentElement.clientWidth,
      );
      expect(overflow).toBeLessThanOrEqual(1);
    });
  }

  await test.step('diagnostics-increased-text-and-keyboard-refresh', async () => {
    await page.setViewportSize({ width: 1_280, height: 900 });
    await page.goto('/observability');
    await page.locator('html').evaluate((element) => {
      element.style.fontSize = '200%';
    });

    const refresh = page.getByRole('button', { name: 'Refresh diagnostics' });
    await refresh.focus();
    await page.keyboard.press('Enter');
    await expect(refresh).toBeEnabled();

    const overflow = await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);
  });

  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations).toEqual([]);
});

test('Monitor policy evidence remains accessible and bounded at required widths', async ({
  page,
}) => {
  const cacheKey = 'c'.repeat(64);
  const namespace = 'tenant-responsive-with-a-long-but-valid-namespace';
  let submittedRequest: unknown;
  await page.route('**/api/v1/query', async (route) => {
    submittedRequest = route.request().postDataJSON();
    await route.fulfill({
      contentType: 'application/json',
      json: {
        response: '**Cached policy response**',
        cache_hit: true,
        similarity_score: 0.98,
        similarity_threshold: 0.92,
        matched_prompt: 'Long responsive policy prompt',
        matched_cache_key: cacheKey,
        cache_entry_created_at: '2026-07-17T10:00:00Z',
        cache_entry_age_seconds: 5,
        generation_skipped: true,
        provider_called: false,
        latency_ms: 8,
      },
    });
  });
  await page.route(`**/api/v1/cache/entries/${cacheKey}`, async (route) => {
    await route.fulfill({
      contentType: 'application/json',
      json: {
        cache_key: cacheKey,
        namespace,
        prompt: 'Long responsive policy prompt',
        response_preview: 'Cached policy response',
        response_preview_truncated: false,
        response: null,
        created_at: '2026-07-17T10:00:00Z',
        expires_at: '2026-07-17T11:00:00Z',
        remaining_ttl_seconds: 3_595,
        hit_count: 1,
        last_accessed_at: '2026-07-17T10:00:05Z',
        recency_rank: 1,
        is_expired: false,
      },
    });
  });

  await page.setViewportSize({ width: 820, height: 1_180 });
  await page.goto('/');
  const disclosure = page.getByText('Advanced cache policy', {
    exact: true,
  });
  await disclosure.focus();
  await page.keyboard.press('Enter');
  await expect(page.locator('details')).toHaveAttribute('open', '');
  await page.getByLabel('Explicit namespace').fill(namespace);
  const refreshMode = page.getByRole('radio', {
    name: /^Refresh and write/,
  });
  await refreshMode.focus();
  await page.keyboard.press('Space');
  await expect(refreshMode).toBeChecked();

  for (const viewport of VIEWPORTS) {
    await test.step(`monitor-${viewport.name}`, async () => {
      await page.setViewportSize(viewport);
      await expect(page.getByLabel('Query text')).toBeVisible();
      await expect(page.getByText(`namespace ${namespace}`, {
        exact: false,
      })).toBeVisible();
      await expect(
        page.getByRole('button', { name: 'Run query' }),
      ).toBeVisible();
      const overflow = await page.evaluate(
        () =>
          document.documentElement.scrollWidth -
          document.documentElement.clientWidth,
      );
      expect(overflow).toBeLessThanOrEqual(1);

      if ([744, 768, 820, 834].includes(viewport.width)) {
        const advancedColumns = await page
          .locator('details > div')
          .evaluate((element) => getComputedStyle(element).gridTemplateColumns);
        expect(advancedColumns.trim().split(/\s+/)).toHaveLength(1);
      }
    });
  }

  await page.setViewportSize({ width: 820, height: 1_180 });
  const normalMode = page.getByRole('radio', {
    name: /^Normal read and write/,
  });
  await normalMode.focus();
  await page.keyboard.press('Space');
  await page.getByLabel('Query text').fill('Long responsive policy prompt');
  await page.getByRole('button', { name: 'Run query' }).click();
  await expect(
    page.getByText(
      `Effective namespace: ${namespace} · Policy: Normal read and write.`,
    ),
  ).toBeVisible();
  expect(submittedRequest).toEqual({
    prompt: 'Long responsive policy prompt',
    namespace,
    cache_enabled: true,
    cache_read_enabled: true,
    cache_write_enabled: true,
    private: false,
  });

  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations).toEqual([]);

  await page
    .getByRole('link', { name: 'Open matched live cache entry' })
    .click();
  await expect(
    page.getByRole('heading', { level: 1, name: 'Cache entry detail' }),
  ).toBeVisible();
});

test('persistent catalog remains readable and bounded at required widths', async ({
  page,
}) => {
  await page.setViewportSize({ width: 820, height: 1_180 });
  await page.goto('/evaluations');

  const datasetsView = page.getByRole('button', { name: 'Datasets' });
  await datasetsView.focus();
  await page.keyboard.press('Enter');
  await expect(datasetsView).toHaveAttribute('aria-pressed', 'true');
  await expect(
    page.getByRole('heading', { name: 'Evaluation datasets' }),
  ).toBeVisible();
  await expect(page.getByText('<script>alert("catalog")</script>', {
    exact: false,
  })).toBeVisible();
  await expect(
    page.locator('script').filter({ hasText: 'alert("catalog")' }),
  ).toHaveCount(0);

  for (const width of [320, 744, 768, 820, 834, 1_024, 1_280]) {
    await test.step(`catalog-${width}`, async () => {
      await page.setViewportSize({ width, height: 1_180 });
      await expect(
        page.getByRole('heading', { name: 'Persisted catalog' }),
      ).toBeVisible();
      const overflow = await page.evaluate(
        () =>
          document.documentElement.scrollWidth -
          document.documentElement.clientWidth,
      );
      expect(overflow).toBeLessThanOrEqual(1);
    });
  }

  const detailTrigger = page.getByRole('button', { name: 'View details' });
  await detailTrigger.focus();
  await page.keyboard.press('Enter');
  await expect(
    page.getByRole('heading', { name: 'Dataset detail' }),
  ).toBeVisible();
  await expect(
    page.getByText('Expected repeat.', { exact: true }),
  ).toBeVisible();

  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations).toEqual([]);
});

test('session-local import remains readable and bounded at required widths', async ({
  page,
}) => {
  await page.setViewportSize({ width: 820, height: 1_180 });
  await page.goto('/evaluations');
  await page.getByLabel('Custom JSON dataset').check();
  const fileInput = page.getByLabel('JSON dataset file');
  await fileInput.setInputFiles({
    name: 'responsive.json',
    mimeType: 'application/json',
    buffer: Buffer.from(
      JSON.stringify({
        schema_version: 1,
        name: 'Imported responsive dataset with a long readable name',
        cases: [
          {
            case_id: 'synthetic',
            prompt: '<strong>=SUM(A1:A2)</strong>',
            expected_cache_hit: false,
          },
        ],
      }),
    ),
  });

  await expect(page.getByText('Validated preview')).toBeVisible();
  await expect(page.getByText(/Validation made 0 provider calls/)).toBeVisible();

  for (const width of [320, 744, 768, 820, 834, 1_024, 1_280]) {
    await test.step(`import-${width}`, async () => {
      await page.setViewportSize({ width, height: 1_180 });
      await expect(fileInput).toBeVisible();
      await expect(page.getByText('Validated preview')).toBeVisible();
      const overflow = await page.evaluate(
        () =>
          document.documentElement.scrollWidth -
          document.documentElement.clientWidth,
      );
      expect(overflow).toBeLessThanOrEqual(1);
    });
  }

  await page.getByRole('button', { name: 'Review benchmark run' }).click();
  await expect(page.getByRole('alertdialog')).toContainText(
    'Imported prompts may leave this system',
  );
  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations).toEqual([]);

  await page.getByRole('button', { name: 'Cancel' }).click();
  await page.getByRole('button', { name: 'Remove imported dataset' }).click();
  await expect(fileInput).toBeFocused();
  await expect(page.getByText('Validated preview')).toHaveCount(0);
});

test('retained history comparison remains usable and accessible at required widths', async ({
  page,
}) => {
  test.setTimeout(60_000);

  await page.setViewportSize({ width: 820, height: 1_180 });
  await page.goto('/evaluations');

  const historyView = page.getByRole('button', { name: 'History' });
  await historyView.focus();
  await page.keyboard.press('Enter');
  await expect(historyView).toHaveAttribute('aria-pressed', 'true');
  await expect(
    page.getByRole('heading', { name: 'Run history' }),
  ).toBeVisible();

  const firstSelection = page
    .getByRole('button', { name: 'Select to compare' })
    .first();
  await firstSelection.focus();
  await page.keyboard.press('Enter');
  await expect(
    page.getByRole('button', { name: 'Baseline selected' }),
  ).toHaveAttribute('aria-pressed', 'true');

  const secondSelection = page.getByRole('button', {
    name: 'Select to compare',
  });
  await secondSelection.focus();
  await page.keyboard.press('Enter');
  await expect(
    page.getByRole('button', { name: 'Candidate selected' }),
  ).toHaveAttribute('aria-pressed', 'true');

  const compare = page.getByRole('button', {
    name: 'Compare selected runs',
  });
  await compare.focus();
  await page.keyboard.press('Enter');

  await expect(
    page.getByRole('heading', { name: 'Comparison result' }),
  ).toBeVisible();
  await expect(page.getByText('Compatible comparison')).toBeVisible();
  await expect(page.getByText('Aggregate metric deltas')).toBeVisible();
  await expect(page.getByText('Shared threshold projections')).toBeVisible();
  await expect(
    page.getByText(HISTORY_NAMESPACE, { exact: true }).first(),
  ).toBeVisible();

  for (const width of [320, 744, 768, 820, 834, 1_024, 1_280]) {
    await test.step(`history-comparison-${width}`, async () => {
      await page.setViewportSize({ width, height: 1_180 });
      await expect(
        page.getByRole('heading', { name: 'Comparison result' }),
      ).toBeVisible();
      await expect(page.getByText('Aggregate metric deltas')).toBeVisible();
      await expect(page.getByText('Shared threshold projections')).toBeVisible();

      const overflow = await page.evaluate(
        () =>
          document.documentElement.scrollWidth -
          document.documentElement.clientWidth,
      );
      expect(overflow).toBeLessThanOrEqual(1);
    });
  }

  await test.step('history-comparison-increased-text-size', async () => {
    await page.setViewportSize({ width: 1_280, height: 900 });
    await page.locator('html').evaluate((element) => {
      element.style.fontSize = '200%';
    });
    await expect(page.getByText('Aggregate metric deltas')).toBeVisible();

    const overflow = await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);
  });

  let accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations).toEqual([]);

  await page.locator('html').evaluate((element) => {
    element.style.fontSize = '';
  });
  await page.setViewportSize({ width: 820, height: 1_180 });

  await page.unroute('**/api/v1/evaluations/runs/compare');
  await page.route(
    '**/api/v1/evaluations/runs/compare',
    async (route) => {
      await route.fulfill({
        contentType: 'application/json',
        json: {
          baseline: retainedBaseline,
          candidate: {
            ...retainedCandidate,
            namespace: 'tenant-responsive-history-other',
          },
          compatibility: {
            status: 'incompatible',
            can_compare: false,
            incompatibilities: [
              {
                code: 'namespace_mismatch',
                detail:
                  'Run namespaces differ; cross-namespace comparison is blocked.',
              },
            ],
            warnings: [],
            case_evidence: 'not_retained',
            opaque_configuration_fingerprint_matches: true,
          },
          metric_deltas: null,
          threshold_deltas: [],
        },
      });
    },
  );

  await page.getByRole('button', { name: 'Clear selection' }).click();

  const incompatibleBaseline = page
    .getByRole('button', { name: 'Select to compare' })
    .first();
  await incompatibleBaseline.click();
  await page.getByRole('button', { name: 'Select to compare' }).click();
  await page.getByRole('button', {
    name: 'Compare selected runs',
  }).click();

  await expect(page.getByText('Comparison blocked')).toBeVisible();
  await expect(page.getByText(/namespace_mismatch/)).toBeVisible();
  await expect(page.getByText('Aggregate metric deltas')).toHaveCount(0);
  await expect(page.getByText('Shared threshold projections')).toHaveCount(0);

  accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations).toEqual([]);
});

test('evaluation controls and projections remain usable at required viewports', async ({
  page,
}) => {
  test.setTimeout(60_000);

  for (const viewport of VIEWPORTS) {
    await test.step(viewport.name, async () => {
      await page.setViewportSize(viewport);
      await page.goto('/evaluations');
      await expect(
        page.getByRole('heading', { name: 'Evaluation laboratory' }),
      ).toBeVisible();
      await expect(page.getByLabel('Benchmark dataset')).toBeVisible();

      const overflow = await page.evaluate(
        () =>
          document.documentElement.scrollWidth -
          document.documentElement.clientWidth,
      );
      expect(overflow).toBeLessThanOrEqual(1);

      if (
        [744, 768, 820, 834].includes(viewport.width)
      ) {
        const columns = await page
          .locator('[data-benchmark-controls] > label')
          .evaluateAll((labels) => {
            const positions = labels.map((label) =>
              Math.round(label.getBoundingClientRect().left),
            );
            return new Set(positions).size;
          });
        expect(columns).toBeLessThanOrEqual(2);
      }

      const disclosure = page.getByRole('button', {
        name: 'Advanced frozen-candidate sweep',
      });
      await disclosure.focus();
      await page.keyboard.press('Enter');
      await expect(disclosure).toHaveAttribute('aria-expanded', 'true');
      await expect(page.getByLabel('Threshold sweep start')).toBeVisible();
    });
  }

  await test.step('increased text size', async () => {
    await page.setViewportSize({ width: 1_280, height: 900 });
    await page.goto('/evaluations');
    await page.locator('html').evaluate((element) => {
      element.style.fontSize = '200%';
    });
    await expect(page.getByLabel('Benchmark dataset')).toBeVisible();
    await expect(
      page.getByRole('button', { name: 'Review benchmark run' }),
    ).toBeVisible();
    const overflow = await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);
  });

  await page.setViewportSize({ width: 820, height: 1_180 });
  await page.goto('/evaluations');

  await page
    .getByLabel('Benchmark history namespace')
    .fill('responsive-e2e');
  await expect(
    page.getByRole('button', { name: 'Review benchmark run' }),
  ).toBeEnabled();
  await page.getByRole('button', { name: 'Review benchmark run' }).click();
  await expect(page.getByRole('alertdialog')).toContainText(
    'may make at most',
  );
  await page.getByRole('button', { name: 'Run benchmark now' }).click();
  await expect(
    page.getByText('Measured run', { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText('Run identity and safe reproducibility metadata'),
  ).toBeVisible();
  await expect(
    page.getByText(
      'Hit rate vs. threshold (frozen-candidate projection)',
      { exact: true },
    ),
  ).toBeVisible();

  const chartTables = page.getByRole('table', {
    name: /frozen-candidate projection.*data/i,
  });
  await expect(chartTables).toHaveCount(4);

  const falsePositiveFilter = page.getByRole('button', {
    name: 'False positive: 1 case',
  });
  await falsePositiveFilter.focus();
  await page.keyboard.press('Enter');
  await expect(falsePositiveFilter).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByText(/Showing 1 of 4 cases/)).toBeVisible();

  const detailTrigger = page.getByRole('button', {
    name: 'View details for case shared-miss, repetition 2',
  });
  await detailTrigger.focus();
  await page.keyboard.press('Enter');
  await expect(
    page.getByRole('heading', { name: 'Case shared-miss' }),
  ).toBeVisible();
  await expect(
    page.getByText(/run-local evaluation cache/),
  ).toBeVisible();
  await expect(
    page.locator('#benchmark-case-detail a'),
  ).toHaveCount(0);

  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations).toEqual([]);

  await page.getByRole('button', { name: 'Close case details' }).click();
  await expect(detailTrigger).toBeFocused();

  for (const viewport of VIEWPORTS) {
    await test.step(`analysis-${viewport.name}`, async () => {
      await page.setViewportSize(viewport);
      await expect(
        page.getByRole('group', {
          name: 'Measured run confusion matrix',
        }),
      ).toBeVisible();
      const overflow = await page.evaluate(
        () =>
          document.documentElement.scrollWidth -
          document.documentElement.clientWidth,
      );
      const overflowSources = await page.evaluate(() =>
        [...document.querySelectorAll<HTMLElement>('body *')]
          .filter(
            (element) =>
              element.getBoundingClientRect().right >
              document.documentElement.clientWidth + 1,
          )
          .slice(0, 10)
          .map((element) => ({
            className: element.className,
            right: Math.round(element.getBoundingClientRect().right),
            tag: element.tagName,
            text: element.textContent?.trim().slice(0, 80),
          })),
      );
      expect(
        overflow,
        JSON.stringify(overflowSources),
      ).toBeLessThanOrEqual(1);

      if ([744, 768, 820, 834].includes(viewport.width)) {
        const columns = await page
          .locator('[data-confusion-matrix] > button')
          .evaluateAll((buttons) => {
            const positions = buttons.map((button) =>
              Math.round(button.getBoundingClientRect().left),
            );
            return new Set(positions).size;
          });
        expect(columns).toBeLessThanOrEqual(2);
      }
    });
  }

  await page.setViewportSize({ width: 320, height: 720 });
  await page.getByRole('button', {
    name: 'View details for case shared-miss, repetition 2',
  }).click();
  await expect(
    page.getByRole('heading', { name: 'Case shared-miss' }),
  ).toBeVisible();
  const detailOverflow = await page.evaluate(
    () =>
      document.documentElement.scrollWidth -
      document.documentElement.clientWidth,
  );
  expect(detailOverflow).toBeLessThanOrEqual(1);
});
