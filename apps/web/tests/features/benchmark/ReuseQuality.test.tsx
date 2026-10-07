import { QueryClientProvider } from '@tanstack/react-query';
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ReuseQuality } from '@/features/benchmark/quality/ReuseQuality';
import {
  decodeQualitySummary,
  fetchQualitySummary,
} from '@/features/benchmark/quality/qualitySummary';
import { isRecord } from '@/shared/api/validators';
import { formatPercent } from '@/shared/lib/formatters';
import { createTestQueryClient } from '../queryClient';
import { deferred } from '../support';

// Test-only receipt; this does not approve or certify the actual corpus.
const receipt: unknown = JSON.parse(
  readFileSync('tests/features/benchmark/qualitySummary.fixture.json', 'utf8'),
);
const summary = decodeQualitySummary(receipt);
if (!isRecord(receipt)) {
  throw new Error('Invalid receipt fixture');
}
const rawReceipt = receipt;

function renderEvidence(client = createTestQueryClient()): void {
  render(
    <QueryClientProvider client={client}>
      <ReuseQuality />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('static reuse quality', () => {
  it('renders reviewed evidence with its scope, source and calibrated metrics', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: true, json: async () => receipt }),
    );
    renderEvidence();
    expect(await screen.findByRole('heading', { name: 'Reuse quality' })).toBeTruthy();
    expect(screen.getByText(/not live telemetry/)).toBeTruthy();
    expect(await screen.findByText(summary.source_sha)).toBeTruthy();
    expect(
      screen
        .getByRole('link', { name: 'Read the reuse-quality methodology' })
        .getAttribute('href'),
    ).toBe(
      'https://github.com/Yoruxyv/semantix/blob/main/packages/cache/benchmarks/reuse_quality/README.md',
    );
    expect(screen.getByText(/Neither 0.92 nor 1.0 guarantees safe reuse/)).toBeTruthy();
    expect(screen.getByText('TP / (TP + FP)')).toBeTruthy();
    expect(screen.getByText('FP / (FP + TN)')).toBeTruthy();
    expect(screen.getByText('(TP + FP) / total')).toBeTruthy();
    expect(screen.getByText(summary.corpus.sha256)).toBeTruthy();
    expect(screen.getByText(summary.generated_at_utc)).toBeTruthy();
    const run = summary.runs.find(
      (item) =>
        item.embedding.kind === 'pretrained-semantic' &&
        item.embedding.normalization === 'raw',
    );
    expect(run).toBeDefined();
    if (run === undefined) {
      throw new Error('Missing fixture run');
    }
    const selected = run.sweep.find(
      (point) => point.threshold === run.calibrated_threshold,
    );
    expect(selected).toBeDefined();
    if (selected === undefined) {
      throw new Error('Missing fixture threshold');
    }
    expect(
      screen.getByText(run.embedding.identity + ' / ' + run.embedding.dimensions),
    ).toBeTruthy();
    expect(
      screen.getAllByText(formatPercent(selected.held_out.reuse_precision)).length,
    ).toBeGreaterThan(0);
    expect(
      screen.getAllByText(run.calibrated_threshold.toFixed(2)).length,
    ).toBeGreaterThan(0);
    expect(
      screen.getAllByText(summary.default_threshold.toFixed(2)).length,
    ).toBeGreaterThan(0);
    expect(screen.getByRole('combobox')).toHaveProperty(
      'value',
      run.embedding.identity,
    );
    expect(
      screen.getByRole('group', { name: 'Pretrained semantic baseline' }),
    ).toBeTruthy();
    expect(screen.getByText('False acceptance rate')).toBeTruthy();
    expect(screen.getByText(/False acceptance rate: FP \/ \(FP \+ TN\)/)).toBeTruthy();
    expect(screen.getByText(/Wrong among accepted: FP \/ \(TP \+ FP\)/)).toBeTruthy();
    const alternate = summary.runs.at(-1);
    if (alternate === undefined) {
      throw new Error('Missing alternate fixture run');
    }
    fireEvent.change(screen.getByLabelText('Embedding / normalization ablation'), {
      target: { value: alternate.embedding.identity },
    });
    expect(
      screen.getByText(
        alternate.embedding.identity + ' / ' + alternate.embedding.dimensions,
      ),
    ).toBeTruthy();
    expect(screen.getByText('Clean source')).toBeTruthy();
    expect(screen.getByText('Calibration-selected threshold')).toBeTruthy();
    expect(screen.getByText('Lexical control')).toBeTruthy();
    expect(
      screen.getByRole('group', { name: 'Lexical controls / stress baselines' }),
    ).toBeTruthy();
    const detailed = screen.getByText('Detailed threshold results').closest('details');
    const limitations = screen.getByText('Evidence limitations').closest('details');
    expect(detailed?.open).toBe(false);
    expect(limitations?.open).toBe(false);
    fireEvent.click(screen.getByText('Detailed threshold results'));
    fireEvent.click(screen.getByText('Evidence limitations'));
    expect(
      screen
        .getByRole('link', { name: 'Reviewed machine-readable manifest' })
        .getAttribute('href'),
    ).toContain('benchmarks/reuse-quality-summary.json');
  });

  it.each(['http', 'invalid', 'network'])(
    'shows an honest unavailable state for %s failure',
    async (failure) => {
      const fetcher =
        failure === 'network'
          ? vi.fn().mockRejectedValue(new Error('offline'))
          : vi.fn().mockResolvedValue({
              ok: failure !== 'http',
              json: async () => ({ schema_version: -1 }),
            });
      vi.stubGlobal('fetch', fetcher);
      renderEvidence();
      expect(screen.getByText(/Loading static/)).toBeTruthy();
      expect(await screen.findByText('Reuse quality unavailable')).toBeTruthy();
      expect(screen.queryByText(summary.source_sha)).toBeNull();
      expect(screen.getByText(/No fallback metrics/)).toBeTruthy();
    },
  );

  it('retains validated evidence and selection during refetch failure, then recovers', async () => {
    const client = createTestQueryClient();
    const key = ['certified-static-reuse-quality'];
    client.setQueryData(key, summary);
    const request = deferred<{ ok: boolean; json: () => Promise<unknown> }>();
    const fetcher = vi.fn().mockReturnValueOnce(request.promise);
    vi.stubGlobal('fetch', fetcher);
    renderEvidence(client);
    const source = screen.getByText(summary.source_sha);
    const alternate = summary.runs.at(-1);
    if (alternate === undefined) throw new Error('Missing alternate fixture run');
    fireEvent.change(screen.getByLabelText('Embedding / normalization ablation'), {
      target: { value: alternate.embedding.identity },
    });
    expect(screen.queryByText(/Loading static/)).toBeNull();
    expect(screen.queryByText('Reuse quality unavailable')).toBeNull();
    await act(async () => {
      request.resolve({ ok: false, json: async () => receipt });
    });
    expect(await screen.findByText('Static evidence refresh failed')).toBeTruthy();
    expect(screen.getByText(summary.source_sha)).toBe(source);
    expect(screen.getByRole('combobox')).toHaveProperty(
      'value',
      alternate.embedding.identity,
    );
    expect(screen.queryByText('Reuse quality unavailable')).toBeNull();
    fetcher.mockResolvedValue({ ok: true, json: async () => receipt });
    await act(async () => {
      await client.invalidateQueries({ queryKey: key });
    });
    await waitFor(() =>
      expect(screen.queryByText('Static evidence refresh failed')).toBeNull(),
    );
    expect(screen.getByText(summary.source_sha)).toBe(source);
    expect(screen.getByRole('combobox')).toHaveProperty(
      'value',
      alternate.embedding.identity,
    );
  });
  it('fetches static content without API credentials and forwards cancellation', async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => receipt });
    vi.stubGlobal('fetch', fetcher);
    const controller = new AbortController();
    await fetchQualitySummary(controller.signal);
    expect(String(fetcher.mock.calls[0]?.[0])).toContain(
      '/benchmarks/reuse-quality-summary.json',
    );
    const options: unknown = fetcher.mock.calls[0]?.[1];
    expect(options).toMatchObject({ cache: 'no-store' });
    expect(options).not.toHaveProperty('headers');
    expect(options).not.toHaveProperty('credentials');
    controller.abort();
  });

  it.each([
    null,
    {},
    { ...summary, schema_version: 2 },
    { ...rawReceipt, held_out_cases: -1 },
    { ...rawReceipt, source_sha: 'invalid' },
    { ...rawReceipt, source_dirty: true },
    { ...rawReceipt, generated_at_utc: '2026-10-05' },
    { ...rawReceipt, corpus: { ...summary.corpus, sha256: 'invalid' } },
    { ...rawReceipt, certification: 'unreviewed' },
    { ...rawReceipt, evidence_kind: 'development-benchmark' },
    { ...rawReceipt, corpus: { ...summary.corpus, label_review: 'unreviewed' } },
    { ...rawReceipt, runs: [] },
    { ...rawReceipt, threshold_grid: [] },
    { ...rawReceipt, limitations: [] },
  ])('rejects missing or incompatible evidence', (invalid) => {
    expect(() => decodeQualitySummary(invalid)).toThrow();
  });

  it.each(['baseline', 'normalization'])('rejects non-text embedding %s', (field) => {
    const runs = summary.runs.map((run) => ({
      ...run,
      embedding: { ...run.embedding, [field]: [run.embedding.baseline] },
    }));
    expect(() => decodeQualitySummary({ ...rawReceipt, runs })).toThrow();
  });

  it('rejects corrupted accounting and split totals', () => {
    const data = structuredClone(summary.runs);
    const first = data[0]?.sweep[0];
    if (first === undefined) {
      throw new Error('Missing fixture metrics');
    }
    first.held_out.true_positive += 1;
    expect(() => decodeQualitySummary({ ...rawReceipt, runs: data })).toThrow();
    expect(() =>
      decodeQualitySummary({
        ...rawReceipt,
        held_out_cases: summary.held_out_cases + 1,
      }),
    ).toThrow();
    expect(formatPercent(null)).toBe('n/a');
  });
  it('distinguishes false acceptance from wrong among accepted', () => {
    const data = structuredClone(summary.runs);
    const run = data[0];
    if (run === undefined) {
      throw new Error('Missing fixture run');
    }
    const distinct = {
      cases: 4,
      true_positive: 1,
      false_positive: 1,
      false_negative: 0,
      true_negative: 2,
      reuse_precision: 0.5,
      reuse_recall: 1,
      false_accept_rate: 1 / 3,
      wrong_among_accepted: 0.5,
      false_reject_rate: 0,
      generation_avoidance: 0.5,
    };
    run.sweep.forEach((point) => {
      point.held_out = { ...distinct };
    });
    expect(() => decodeQualitySummary({ ...rawReceipt, runs: data })).not.toThrow();
    run.sweep.forEach((point) => {
      point.held_out.wrong_among_accepted = 1 / 3;
    });
    expect(() => decodeQualitySummary({ ...rawReceipt, runs: data })).toThrow();
  });

  it('rejects control-only or malformed semantic evidence', () => {
    expect(() =>
      decodeQualitySummary({
        ...rawReceipt,
        runs: summary.runs.filter((run) => run.embedding.kind === 'lexical-control'),
      }),
    ).toThrow();
    for (const [field, value] of [
      ['revision', 'main'],
      ['dimensions', 2048],
      ['model_id', 'unknown/model'],
    ]) {
      const runs = summary.runs.map((run) =>
        run.embedding.kind === 'pretrained-semantic'
          ? { ...run, embedding: { ...run.embedding, [String(field)]: value } }
          : run,
      );
      expect(() => decodeQualitySummary({ ...rawReceipt, runs })).toThrow();
    }
  });
});
