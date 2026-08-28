import type { JSX } from 'react';

import type { EvaluationRunComparisonResponse } from '@/features/benchmark/comparisonTypes';
import { Alert } from '@/shared/components/ui';
import { formatTimestamp } from '@/shared/lib/formatters';

import { EvaluationRunComparisonMetrics } from './EvaluationRunComparisonMetrics';
import { EvaluationRunComparisonThresholds } from './EvaluationRunComparisonThresholds';

function RunContext({
  label,
  run,
}: Readonly<{
  label: 'Baseline' | 'Candidate';
  run: EvaluationRunComparisonResponse['baseline'];
}>): JSX.Element {
  return (
    <article className="min-w-0 border border-(--hairline) p-4">
      <p className="ui-label text-(--gold)">{label}</p>
      <h4 className="mt-2 wrap-break-word text-base text-(--text)">
        {run.dataset.name}
      </h4>
      <code
        className="font-data mt-1 block wrap-break-word text-[10px] text-(--text-faint)"
        title={run.run_id}
      >
        {run.run_id}
      </code>
      <dl className="font-data mt-4 grid gap-3 text-[10px]/5 sm:grid-cols-2">
        <div>
          <dt className="text-(--text-faint)">Namespace</dt>
          <dd className="mt-1 wrap-break-word text-(--text-soft)">{run.namespace}</dd>
        </div>
        <div>
          <dt className="text-(--text-faint)">State</dt>
          <dd className="mt-1 text-(--text-soft)">{run.terminal_state}</dd>
        </div>
        <div>
          <dt className="text-(--text-faint)">Measured threshold</dt>
          <dd className="mt-1 text-(--text-soft)">
            {run.reproducibility.measured_threshold.toFixed(2)}
          </dd>
        </div>
        <div>
          <dt className="text-(--text-faint)">Completed</dt>
          <dd className="mt-1 text-(--text-soft)" title={run.completed_at}>
            {formatTimestamp(run.completed_at)}
          </dd>
        </div>
      </dl>
    </article>
  );
}

function CompatibilitySummary({
  comparison,
}: Readonly<{
  comparison: EvaluationRunComparisonResponse;
}>): JSX.Element {
  const { compatibility } = comparison;

  if (compatibility.status === 'incompatible') {
    return (
      <Alert role="alert" title="Comparison blocked" tone="error">
        <p className="font-data mt-1 text-[10px]/5 text-(--text-soft)">
          These retained runs are not directly comparable. No metric deltas are shown.
        </p>
        <ul className="font-data mt-3 list-disc space-y-2 pl-5 text-[10px]/5 text-(--text-soft)">
          {compatibility.incompatibilities.map((issue) => (
            <li key={issue.code}>
              <strong>{issue.code}</strong>: {issue.detail}
            </li>
          ))}
        </ul>
      </Alert>
    );
  }

  if (compatibility.status === 'warning') {
    return (
      <Alert title="Comparison caveats" tone="warning">
        <p className="font-data mt-1 text-[10px]/5 text-(--text-soft)">
          Aggregate deltas are available, but interpret them with these explicit
          run-configuration differences.
        </p>
        <ul className="font-data mt-3 list-disc space-y-2 pl-5 text-[10px]/5 text-(--text-soft)">
          {compatibility.warnings.map((issue) => (
            <li key={issue.code}>
              <strong>{issue.code}</strong>: {issue.detail}
            </li>
          ))}
        </ul>
      </Alert>
    );
  }

  return (
    <div className="border-l-2 border-(--teal) px-4 py-3">
      <p className="ui-label text-(--teal)">Compatible comparison</p>
      <p className="font-data mt-1 text-[10px]/5 text-(--text-muted)">
        No server compatibility blockers or caveats were reported.
      </p>
    </div>
  );
}

export function EvaluationRunComparisonResult({
  comparison,
}: Readonly<{
  comparison: EvaluationRunComparisonResponse;
}>): JSX.Element {
  const baselineMetrics = comparison.baseline.metrics;
  const candidateMetrics = comparison.candidate.metrics;

  return (
    <section aria-labelledby="comparison-result-heading" className="mt-6">
      <header className="border-y border-(--hairline) py-4">
        <p className="ui-label text-(--teal)">Server-backed compatibility assessment</p>
        <h3
          className="font-display mt-2 text-xl italic text-(--text)"
          id="comparison-result-heading"
        >
          Comparison result
        </h3>
      </header>

      <div className="mt-5">
        <CompatibilitySummary comparison={comparison} />
      </div>

      <div className="mt-5 grid gap-4 lg:grid-cols-2">
        <RunContext label="Baseline" run={comparison.baseline} />
        <RunContext label="Candidate" run={comparison.candidate} />
      </div>

      {!comparison.compatibility.opaque_configuration_fingerprint_matches && (
        <p className="font-data mt-4 border-l border-(--hairline) pl-3 text-[10px]/5 text-(--text-faint)">
          The opaque overall configuration fingerprint differs. This value is
          explanatory only; the server uses explicit compatibility fields for blocking
          and warning decisions.
        </p>
      )}

      <p className="font-data mt-4 border-l border-(--hairline) pl-3 text-[10px]/5 text-(--text-faint)">
        Historical case evidence is{' '}
        {comparison.compatibility.case_evidence.replace('_', ' ')}. Comparison uses
        retained aggregate metrics only; no prompts, generated responses, or matched
        cache keys are exposed.
      </p>

      {comparison.metric_deltas !== null &&
        baselineMetrics !== null &&
        candidateMetrics !== null && (
          <>
            <EvaluationRunComparisonMetrics
              baseline={baselineMetrics}
              baselineThreshold={comparison.baseline.reproducibility.measured_threshold}
              candidate={candidateMetrics}
              candidateThreshold={
                comparison.candidate.reproducibility.measured_threshold
              }
              deltas={comparison.metric_deltas}
            />
            <EvaluationRunComparisonThresholds
              baseline={comparison.baseline.threshold_evaluations}
              candidate={comparison.candidate.threshold_evaluations}
              deltas={comparison.threshold_deltas}
            />
          </>
        )}
    </section>
  );
}
