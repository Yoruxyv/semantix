import { useQuery } from '@tanstack/react-query';
import { useState, type JSX } from 'react';

import { Alert, EmptyState } from '@/shared/components/ui';
import { formatDecimal, formatPercent } from '@/shared/lib/formatters';
import { LineChart } from '../components/charts/LineChart';
import {
  fetchQualitySummary,
  type QualityMetrics,
  type QualitySummary,
} from './qualitySummary';

const METHODOLOGY_URL =
  'https://github.com/Yoruxyv/semantix/blob/main/packages/cache/benchmarks/reuse_quality/README.md';

function Evidence({ summary }: Readonly<{ summary: QualitySummary }>): JSX.Element {
  const [identity, setIdentity] = useState(
    summary.runs.find(
      (item) =>
        item.embedding.kind === 'pretrained-semantic' &&
        item.embedding.normalization === 'raw',
    )?.embedding.identity ??
      summary.runs[0]?.embedding.identity ??
      '',
  );
  const run = summary.runs.find((item) => item.embedding.identity === identity);
  const point = run?.sweep.find((item) => item.threshold === run.calibrated_threshold);
  if (run === undefined || point === undefined) {
    return (
      <EmptyState
        className="py-5"
        title="Reuse quality unavailable"
        description="The selected static evidence is incompatible."
      />
    );
  }
  const metrics: Array<{ label: string; key: keyof QualityMetrics; formula: string }> =
    [
      { label: 'Reuse precision', key: 'reuse_precision', formula: 'TP / (TP + FP)' },
      {
        label: 'False acceptance rate',
        key: 'false_accept_rate',
        formula: 'FP / (FP + TN)',
      },
      { label: 'Reuse recall', key: 'reuse_recall', formula: 'TP / (TP + FN)' },
      {
        label: 'Missed reuse / false rejection rate',
        key: 'false_reject_rate',
        formula: 'FN / (TP + FN)',
      },
      {
        label: 'Generation avoidance',
        key: 'generation_avoidance',
        formula: '(TP + FP) / total',
      },
    ];
  const series = [
    {
      label: 'False acceptance rate / negatives',
      color: 'var(--coral)',
      key: 'false_accept_rate',
    },
    {
      label: 'False rejection rate / positives',
      color: 'var(--gold)',
      key: 'false_reject_rate',
    },
    {
      label: 'Generation avoidance',
      color: 'var(--teal)',
      key: 'generation_avoidance',
    },
  ] as const;
  return (
    <>
      <label className="mt-5 block text-sm" htmlFor="quality-configuration">
        Embedding / normalization ablation
      </label>
      <select
        className="mt-2 min-h-11 w-full min-w-0 max-w-xl border border-(--hairline) bg-(--surface) px-3 py-2 text-sm text-(--text) focus-visible:outline-2 focus-visible:outline-offset-3 focus-visible:outline-(--gold)"
        id="quality-configuration"
        value={identity}
        onChange={(event) => setIdentity(event.target.value)}
      >
        {[
          { label: 'Pretrained semantic baseline', kind: 'pretrained-semantic' },
          { label: 'Lexical controls / stress baselines', kind: 'lexical-control' },
        ].map((group) => (
          <optgroup label={group.label} key={group.kind}>
            {summary.runs
              .filter((item) => item.embedding.kind === group.kind)
              .map((item) => (
                <option key={item.embedding.identity} value={item.embedding.identity}>
                  {item.embedding.baseline} / {item.embedding.normalization}
                </option>
              ))}
          </optgroup>
        ))}
      </select>
      <p className="mt-2 text-sm text-(--text-muted)">
        {run.embedding.kind === 'pretrained-semantic'
          ? 'Pretrained semantic baseline'
          : 'Lexical control'}
      </p>
      <h3 className="mt-6 text-base font-semibold">
        Held-out results at calibration-selected threshold{' '}
        {formatDecimal(run.calibrated_threshold, 2)}
      </h3>
      <dl className="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {metrics.map(({ label, key, formula }) => (
          <div className="border-t border-(--hairline) pt-3" key={key}>
            <dt className="text-sm text-(--text-muted)">{label}</dt>
            <dd className="font-data mt-2 text-xl">
              {formatPercent(point.held_out[key])}
              <span className="mt-2 block text-xs font-normal text-(--text-muted)">
                {formula}
              </span>
            </dd>
          </div>
        ))}
      </dl>
      <p className="mt-5 text-sm/6">
        Held-out confusion matrix: TP {point.held_out.true_positive}, FP{' '}
        {point.held_out.false_positive}, FN {point.held_out.false_negative}, TN{' '}
        {point.held_out.true_negative}. False acceptance rate: FP / (FP + TN). Wrong
        among accepted: FP / (TP + FP) ={' '}
        {formatPercent(point.held_out.wrong_among_accepted)}. False rejection rate: FN /
        (TP + FN). Generation avoidance includes wrong reuse. Undefined denominators
        display n/a.
      </p>
      <dl className="mt-5 grid gap-3 text-sm/6 sm:grid-cols-2">
        <div>
          <dt>Calibration-selected threshold</dt>
          <dd>{formatDecimal(run.calibrated_threshold, 2)}</dd>
        </div>
        <div>
          <dt>Library default threshold (unchanged)</dt>
          <dd>{formatDecimal(summary.default_threshold, 2)}</dd>
        </div>
        <div>
          <dt>Corpus version / size</dt>
          <dd>
            {summary.corpus.version} /{' '}
            {summary.calibration_cases + summary.held_out_cases} cases
          </dd>
        </div>
        <div>
          <dt>Calibration / held-out</dt>
          <dd>
            {summary.calibration_cases} / {summary.held_out_cases} cases
          </dd>
        </div>
        <div>
          <dt>Embedding identity / dimensions</dt>
          <dd className="break-all">
            {run.embedding.identity} / {run.embedding.dimensions}
          </dd>
        </div>
        <div>
          <dt>Model revision / preprocessing</dt>
          <dd className="break-all">
            {run.embedding.revision} / {run.embedding.model_preprocessing}
          </dd>
        </div>
        <div>
          <dt>Benchmark date (UTC)</dt>
          <dd>
            <time dateTime={summary.generated_at_utc}>{summary.generated_at_utc}</time>
          </dd>
        </div>
        <div>
          <dt>Source commit SHA</dt>
          <dd className="break-all">{summary.source_sha}</dd>
        </div>
        <div>
          <dt>Source state</dt>
          <dd>Clean source</dd>
        </div>
        <div>
          <dt>Corpus SHA256</dt>
          <dd className="break-all">{summary.corpus.sha256}</dd>
        </div>
        <div>
          <dt>Additional preprocessing cost (local)</dt>
          <dd>{formatDecimal(run.preprocessing_ns_per_prompt, 0)} ns / prompt</dd>
        </div>
      </dl>
      <div className="mt-7 max-w-2xl">
        <LineChart
          title="Held-out threshold tradeoffs (static projections)"
          valueLabel={(value) => formatPercent(value)}
          series={series.map((item) => ({
            color: item.color,
            label: item.label,
            points: run.sweep.flatMap((row) => {
              const value = row.held_out[item.key];
              return value === null
                ? []
                : [{ kind: 'projected' as const, x: row.threshold, y: value }];
            }),
          }))}
        />
      </div>
      <p className="mt-4 text-sm/6 text-(--text-muted)">
        Threshold selection minimizes calibration wrong reuse, then maximizes correct
        reuse. Held-out sweep is descriptive, never used for tuning. Default and
        calibrated decisions were replayed through the public cache API. Higher
        thresholds can reduce wrong reuse while increasing generation. Neither 0.92 nor
        1.0 guarantees safe reuse, and this synthetic corpus does not establish
        production quality. Normalization is an ablation; runtime defaults are
        unchanged.
      </p>
      <details className="mt-6 text-sm/6">
        <summary className="min-h-11 cursor-pointer py-3 focus-visible:outline-2 focus-visible:outline-offset-3 focus-visible:outline-(--gold)">
          Detailed threshold results
        </summary>
        <section
          className="mt-4 overflow-x-auto focus-visible:outline-2 focus-visible:outline-offset-3 focus-visible:outline-(--gold)"
          aria-label="Threshold results, scroll horizontally for all columns"
          // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- WCAG 2.1.1: a named scroll region must accept keyboard focus, including when it has no focusable content.
          tabIndex={0}
        >
          <table className="w-full min-w-max text-left text-sm/6">
            <caption className="mb-3 text-left">
              Held-out threshold sweep; calibration FP / TP shown separately
            </caption>
            <thead>
              <tr>
                {[
                  'Threshold',
                  'Calibration FP / TP',
                  'Precision',
                  'Recall',
                  'FP / false acceptance rate',
                  'Wrong among accepted',
                  'FN / false rejection rate',
                  'Avoidance',
                ].map((heading) => (
                  <th className="p-2" key={heading} scope="col">
                    {heading}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {run.sweep.map((row) => (
                <tr className="border-t border-(--hairline)" key={row.threshold}>
                  <th className="p-2" scope="row">
                    {formatDecimal(row.threshold, 2)}
                    {row.threshold === summary.default_threshold ? ' (default)' : ''}
                    {row.threshold === run.calibrated_threshold ? ' (calibrated)' : ''}
                  </th>
                  <td className="p-2">
                    {row.calibration.false_positive} / {row.calibration.true_positive}
                  </td>
                  <td className="p-2">{formatPercent(row.held_out.reuse_precision)}</td>
                  <td className="p-2">{formatPercent(row.held_out.reuse_recall)}</td>
                  <td className="p-2">
                    {row.held_out.false_positive} (
                    {formatPercent(row.held_out.false_accept_rate)})
                  </td>
                  <td className="p-2">
                    {formatPercent(row.held_out.wrong_among_accepted)}
                  </td>
                  <td className="p-2">
                    {row.held_out.false_negative} (
                    {formatPercent(row.held_out.false_reject_rate)})
                  </td>
                  <td className="p-2">
                    {formatPercent(row.held_out.generation_avoidance)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </details>
      <details className="mt-6 text-sm/6">
        <summary className="min-h-11 cursor-pointer py-3 focus-visible:outline-2 focus-visible:outline-offset-3 focus-visible:outline-(--gold)">
          Evidence limitations
        </summary>
        <ul className="mt-3 list-disc pl-5">
          {summary.limitations.map((limitation) => (
            <li key={limitation}>{limitation}</li>
          ))}
        </ul>
        <a
          className="mt-3 inline-block underline underline-offset-4 focus-visible:outline-2 focus-visible:outline-offset-3 focus-visible:outline-(--gold)"
          href={import.meta.env.BASE_URL + 'benchmarks/reuse-quality-summary.json'}
        >
          Reviewed machine-readable manifest
        </a>
      </details>
    </>
  );
}

export function ReuseQuality(): JSX.Element {
  const query = useQuery({
    queryKey: ['certified-static-reuse-quality'],
    queryFn: ({ signal }) => fetchQualitySummary(signal),
    retry: false,
    staleTime: 0,
  });
  let content: JSX.Element;
  if (query.data !== undefined) {
    content = (
      <>
        {query.isError && (
          <Alert
            aria-live="polite"
            className="mb-4 border-l border-(--coral) pl-4 text-sm/6"
            title="Static evidence refresh failed"
            tone="error"
          >
            Showing the last validated reviewed receipt. It may be stale; its source,
            corpus, and generation timestamp remain recorded below.
          </Alert>
        )}
        <Evidence summary={query.data} />
      </>
    );
  } else if (query.isPending) {
    content = (
      <output aria-live="polite">Loading static reuse-quality evidence…</output>
    );
  } else {
    content = (
      <EmptyState
        className="py-5"
        title="Reuse quality unavailable"
        description="The reviewed static benchmark manifest is missing or incompatible. No fallback metrics are shown."
      />
    );
  }
  return (
    <section aria-labelledby="reuse-quality-heading">
      <h2 className="font-display text-2xl italic" id="reuse-quality-heading">
        Reuse quality
      </h2>
      <p className="mt-2 max-w-3xl text-sm/6 text-(--text-muted)">
        Reviewed static benchmark evidence — not live telemetry. The pretrained semantic
        baseline is primary; lexical controls are separate stress tests. Calibration
        selects the threshold; held-out cases evaluate that choice.
      </p>
      <a
        className="mt-3 inline-flex min-h-11 items-center text-sm text-(--teal) underline underline-offset-4 focus-visible:outline-2 focus-visible:outline-offset-3 focus-visible:outline-(--gold)"
        href={METHODOLOGY_URL}
      >
        Read the reuse-quality methodology
      </a>
      <div className="mt-4">{content}</div>
    </section>
  );
}
