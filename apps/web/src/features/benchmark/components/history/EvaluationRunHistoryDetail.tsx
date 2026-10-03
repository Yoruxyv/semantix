import type { JSX } from 'react';

import { Button } from '@/shared/components/ui';
import {
  formatCount,
  formatLatency,
  formatPercent,
  formatTimestamp,
  formatUsd,
} from '@/shared/lib/formatters';

import type { EvaluationRunHistoryDetail } from '@/features/benchmark/types';

function fingerprint(value: string): JSX.Element {
  return (
    <code className="font-data text-[10px] text-(--text-faint)" title={value}>
      {value.slice(0, 12)}...
    </code>
  );
}

function TerminalEvidence({
  detail,
}: Readonly<{ detail: EvaluationRunHistoryDetail }>): JSX.Element {
  if (detail.terminal_state !== 'completed' || detail.metrics === null) {
    return (
      <section aria-labelledby="history-failure-heading" className="mt-6">
        <h4 className="ui-label text-(--coral)" id="history-failure-heading">
          Terminal failure
        </h4>
        <dl className="font-data mt-3 grid gap-3 text-[10px]/5 sm:grid-cols-2">
          <div>
            <dt className="text-(--text-faint)">Failure code</dt>
            <dd className="mt-1 wrap-break-word text-(--text-soft)">
              {detail.failure_code ?? 'unknown'}
            </dd>
          </div>
          <div>
            <dt className="text-(--text-faint)">Safe detail</dt>
            <dd className="mt-1 wrap-break-word text-(--text-soft)">
              {detail.safe_failure_detail ?? 'No public detail was retained.'}
            </dd>
          </div>
        </dl>
      </section>
    );
  }

  return (
    <>
      <section aria-labelledby="history-metrics-heading" className="mt-6">
        <h4 className="ui-label text-(--teal)" id="history-metrics-heading">
          Aggregate metrics
        </h4>
        <dl className="font-data mt-3 grid grid-cols-2 gap-4 text-[10px]/5 sm:grid-cols-3">
          <div>
            <dt className="text-(--text-faint)">Hit rate</dt>
            <dd className="mt-1 text-sm text-(--text)">
              {formatPercent(detail.metrics.hit_rate)}
            </dd>
          </div>
          <div>
            <dt className="text-(--text-faint)">F1</dt>
            <dd className="mt-1 text-sm text-(--text)">
              {formatPercent(detail.metrics.f1_score)}
            </dd>
          </div>
          <div>
            <dt className="text-(--text-faint)">Average latency</dt>
            <dd className="mt-1 text-sm text-(--text)">
              {formatLatency(detail.metrics.average_latency_ms)}
            </dd>
          </div>
          <div>
            <dt className="text-(--text-faint)">Provider calls avoided</dt>
            <dd className="mt-1 text-sm text-(--text)">
              {formatCount(detail.metrics.provider_calls_avoided)}
            </dd>
          </div>
          <div>
            <dt className="text-(--text-faint)">Estimated cost saved</dt>
            <dd className="mt-1 text-sm text-(--text)">
              {formatUsd(detail.metrics.estimated_provider_cost_saved_usd)}
            </dd>
          </div>
          <div>
            <dt className="text-(--text-faint)">Queries</dt>
            <dd className="mt-1 text-sm text-(--text)">
              {formatCount(detail.metrics.total_queries)}
            </dd>
          </div>
        </dl>
      </section>

      <section aria-labelledby="history-threshold-heading" className="mt-6">
        <h4 className="ui-label text-(--gold)" id="history-threshold-heading">
          Retained threshold aggregates
        </h4>
        <div className="mt-3 overflow-x-auto">
          <table
            aria-label="Retained threshold evaluations"
            className="w-full min-w-160 border-collapse text-left"
          >
            <thead>
              <tr className="border-b border-(--hairline)">
                {[
                  'Threshold',
                  'Kind',
                  'Hit rate',
                  'Precision',
                  'Recall',
                  'F1',
                  'Latency',
                  'Calls avoided',
                ].map((heading) => (
                  <th
                    className="ui-label px-3 py-2 text-(--text-faint)"
                    key={heading}
                    scope="col"
                  >
                    {heading}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="font-data text-[10px]/5 text-(--text-soft)">
              {detail.threshold_evaluations.map((evaluation) => (
                <tr
                  className="border-b border-(--hairline)"
                  key={`${evaluation.threshold}-${evaluation.result_kind}`}
                >
                  <td className="px-3 py-2">{evaluation.threshold.toFixed(2)}</td>
                  <td className="px-3 py-2">{evaluation.result_kind}</td>
                  <td className="px-3 py-2">{formatPercent(evaluation.hit_rate)}</td>
                  <td className="px-3 py-2">{formatPercent(evaluation.precision)}</td>
                  <td className="px-3 py-2">{formatPercent(evaluation.recall)}</td>
                  <td className="px-3 py-2">{formatPercent(evaluation.f1_score)}</td>
                  <td className="px-3 py-2">
                    {formatLatency(evaluation.average_latency_ms)}
                  </td>
                  <td className="px-3 py-2">
                    {formatCount(evaluation.provider_calls_avoided)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

export function EvaluationRunHistoryDetailPanel({
  detail,
  onClose,
}: Readonly<{
  detail: EvaluationRunHistoryDetail;
  onClose: () => void;
}>): JSX.Element {
  return (
    <aside
      aria-labelledby="history-detail-heading"
      className="mt-6 border border-(--hairline) p-4 sm:p-5"
    >
      <header className="flex flex-wrap items-start justify-between gap-4 border-b border-(--hairline) pb-4">
        <div className="min-w-0">
          <p className="ui-label text-(--gold)">Retained aggregate</p>
          <h3
            className="font-display mt-2 wrap-break-word text-xl italic text-(--text)"
            id="history-detail-heading"
          >
            {detail.dataset.name}
          </h3>
          <code
            className="font-data mt-2 block wrap-break-word text-[10px] text-(--text-faint)"
            title={detail.run_id}
          >
            {detail.run_id}
          </code>
        </div>
        <Button size="compact" variant="secondary" onClick={onClose}>
          Close detail
        </Button>
      </header>

      <dl className="font-data mt-5 grid gap-4 text-[10px]/5 sm:grid-cols-2 lg:grid-cols-3">
        <div>
          <dt className="text-(--text-faint)">State / namespace</dt>
          <dd className="mt-1 wrap-break-word text-(--text-soft)">
            {detail.terminal_state} · {detail.namespace}
          </dd>
        </div>
        <div>
          <dt className="text-(--text-faint)">Completed</dt>
          <dd className="mt-1 text-(--text-soft)" title={detail.completed_at}>
            {formatTimestamp(detail.completed_at)}
          </dd>
        </div>
        <div>
          <dt className="text-(--text-faint)">Expires</dt>
          <dd className="mt-1 text-(--gold)" title={detail.expires_at}>
            {formatTimestamp(detail.expires_at)}
          </dd>
        </div>
        <div>
          <dt className="text-(--text-faint)">Dataset digest</dt>
          <dd className="mt-1">{fingerprint(detail.dataset.digest)}</dd>
        </div>
        <div>
          <dt className="text-(--text-faint)">Embedding space</dt>
          <dd className="mt-1">
            {fingerprint(detail.reproducibility.embedding_space_fingerprint)}
          </dd>
        </div>
        <div>
          <dt className="text-(--text-faint)">Generation configuration</dt>
          <dd className="mt-1">
            {fingerprint(detail.reproducibility.generation_configuration_fingerprint)}
          </dd>
        </div>
        <div>
          <dt className="text-(--text-faint)">Application / contract</dt>
          <dd className="mt-1 text-(--text-soft)">
            {detail.reproducibility.application_version} · comparison v
            {detail.reproducibility.comparison_contract_version}
          </dd>
        </div>
        <div>
          <dt className="text-(--text-faint)">Embedding dimensions</dt>
          <dd className="mt-1 text-(--text-soft)">
            {formatCount(detail.reproducibility.embedding_dimensions)}
          </dd>
        </div>
        <div>
          <dt className="text-(--text-faint)">Normalization</dt>
          <dd className="mt-1 text-(--text-soft)">
            {detail.reproducibility.normalization_mode}
          </dd>
        </div>
      </dl>

      <p className="font-data mt-5 border-l border-(--hairline) pl-3 text-[10px]/5 text-(--text-faint)">
        Durable history is aggregate-only. Per-query prompts, generated responses,
        matched cache keys, and other query-level evidence are not retained.
      </p>

      <TerminalEvidence detail={detail} />
    </aside>
  );
}
