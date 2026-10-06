import { useQuery } from '@tanstack/react-query';
import { useState, type JSX } from 'react';

import { EmptyState } from '@/shared/components/ui';
import { formatDecimal, formatPercent } from '@/shared/lib/formatters';
import { LineChart } from '../components/charts/LineChart';
import {
  fetchQualitySummary,
  type QualityMetrics,
  type QualitySummary,
} from './qualitySummary';

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
  const metrics: Array<{ label: string; key: keyof QualityMetrics }> = [
    { label: 'Reuse precision', key: 'reuse_precision' },
    { label: 'False acceptance rate', key: 'false_accept_rate' },
    { label: 'Reuse recall', key: 'reuse_recall' },
    { label: 'Missed reuse / false rejection rate', key: 'false_reject_rate' },
    {
      label: 'Generation avoidance',
      key: 'generation_avoidance',
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
    <section aria-labelledby="reuse-quality-heading">
      <h2 className="font-display text-2xl" id="reuse-quality-heading">
        Reuse quality
      </h2>
      <p className="mt-2 text-sm/6 text-(--text-muted)">
        Reviewed static benchmark evidence — not live telemetry. The pretrained semantic
        baseline is primary; lexical controls are separate stress tests.
      </p>
      <label className="mt-5 block text-sm" htmlFor="quality-configuration">
        Embedding / normalization ablation
      </label>
      <select
        className="mt-2 w-full max-w-xl border border-(--hairline) bg-(--surface) p-2"
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
      <dl className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {metrics.map(({ label, key }) => (
          <div className="border-t border-(--hairline) pt-3" key={key}>
            <dt className="text-sm text-(--text-muted)">{label}</dt>
            <dd className="font-data mt-2 text-xl">
              {formatPercent(point.held_out[key])}
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
            points: run.sweep.map((row) => ({
              kind: 'projected',
              x: row.threshold,
              y: row.held_out[item.key] ?? 0,
            })),
          }))}
        />
      </div>
      <p className="mt-4 text-sm/6 text-(--text-muted)">
        Threshold selection minimizes calibration wrong reuse, then maximizes correct
        reuse. Held-out sweep is descriptive, never used for tuning. Default and
        calibrated decisions were replayed through the public cache API. Higher
        thresholds can reduce wrong reuse while increasing generation. Runtime
        normalization is unchanged.
      </p>
      <details className="mt-6 text-sm/6">
        <summary className="cursor-pointer">Detailed threshold results</summary>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-left text-sm/6">
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
        </div>
      </details>
      <details className="mt-6 text-sm/6">
        <summary className="cursor-pointer">Evidence limitations</summary>
        <ul className="mt-3 list-disc pl-5">
          {summary.limitations.map((limitation) => (
            <li key={limitation}>{limitation}</li>
          ))}
        </ul>
        <a
          className="mt-3 inline-block underline"
          href={import.meta.env.BASE_URL + 'benchmarks/reuse-quality-summary.json'}
        >
          Reviewed machine-readable manifest
        </a>
      </details>
    </section>
  );
}

export function ReuseQuality(): JSX.Element {
  const query = useQuery({
    queryKey: ['certified-static-reuse-quality'],
    queryFn: ({ signal }) => fetchQualitySummary(signal),
    retry: false,
    staleTime: 0,
  });
  if (query.isPending) {
    return <output aria-live="polite">Loading static reuse-quality evidence…</output>;
  }
  if (query.isError) {
    return (
      <EmptyState
        className="py-5"
        title="Reuse quality unavailable"
        description="The reviewed static benchmark manifest is missing or incompatible. No fallback metrics are shown."
      />
    );
  }
  return <Evidence summary={query.data} />;
}
