import type { JSX } from 'react';

import { Button } from '@/shared/components/ui';
import { cacheDecisionLabel } from '@/shared/domain/similarity';
import { formatLatency, formatSimilarity } from '@/shared/lib/formatters';
import type {
  BenchmarkQueryResult,
  BenchmarkRunResponse,
} from '@/features/benchmark/types';

interface BenchmarkCaseDetailProps {
  onClose: () => void;
  query: BenchmarkQueryResult;
  result: BenchmarkRunResponse;
}

function formatLabel(value: string): string {
  return value.replaceAll('_', ' ');
}

function EvidenceItem({
  className = '',
  description,
  label,
  value,
  wrap = false,
}: Readonly<{
  className?: string;
  description?: string | undefined;
  label: string;
  value: string;
  wrap?: boolean;
}>): JSX.Element {
  return (
    <div className={`min-w-0 ${className}`}>
      <dt className="ui-label text-(--text-faint)">{label}</dt>
      <dd
        className={`font-data mt-2 text-[11px]/5 text-(--text-soft) ${
          wrap ? 'whitespace-pre-wrap wrap-break-word' : ''
        }`}
      >
        <span className="block">{value}</span>
        {description !== undefined && (
          <span className="mt-2 block text-[10px]/5 text-(--text-faint)">
            {description}
          </span>
        )}
      </dd>
    </div>
  );
}

export function BenchmarkCaseDetail({
  onClose,
  query,
  result,
}: Readonly<BenchmarkCaseDetailProps>): JSX.Element {
  return (
    <section
      aria-labelledby="benchmark-case-detail-heading"
      className="mt-6 border border-(--hairline) bg-[rgba(234,230,221,0.025)] p-4 sm:p-6"
      id="benchmark-case-detail"
    >
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="ui-label text-(--teal)">Measured case evidence</p>
          <h3
            className="font-display mt-1 wrap-break-word text-2xl italic"
            id="benchmark-case-detail-heading"
          >
            Case {query.case_id}
          </h3>
          <p className="font-data mt-2 text-[10px]/5 text-(--text-faint)">
            Sequence {query.sequence}, repetition {query.repetition}
          </p>
        </div>
        <Button
          className="border-(--hairline) text-(--text-soft) hover:border-(--teal) hover:text-(--teal)"
          onClick={onClose}
          size="compact"
          variant="secondary"
        >
          Close case details
        </Button>
      </div>

      <p className="font-data mt-5 text-[11px]/5 text-(--text-muted)">
        This case was measured at threshold{' '}
        {result.reproducibility.measured_threshold.toFixed(2)}. Threshold chart values
        are frozen-candidate projections and do not replay this case or alter the active
        cache threshold.
      </p>

      <dl className="mt-6 grid gap-5 sm:grid-cols-2">
        <EvidenceItem label="Case ID" value={query.case_id} wrap />
        <EvidenceItem label="Category" value={formatLabel(query.category)} />
        <EvidenceItem
          label="Expected decision"
          value={cacheDecisionLabel(query.expected_cache_hit)}
        />
        {query.expected_match_case_id !== null && (
          <EvidenceItem
            label="Expected match case"
            value={query.expected_match_case_id}
            wrap
          />
        )}
        <EvidenceItem
          label="Actual decision"
          value={cacheDecisionLabel(query.actual_cache_hit)}
        />
        <EvidenceItem label="Outcome" value={formatLabel(query.outcome)} />
        <EvidenceItem
          label="Provider called"
          value={query.provider_called ? 'Yes' : 'No'}
        />
        <EvidenceItem
          label="Similarity score"
          value={formatSimilarity(query.similarity_score)}
        />
        <EvidenceItem label="Latency" value={formatLatency(query.latency_ms)} />
        <EvidenceItem
          label="Measured threshold"
          value={result.reproducibility.measured_threshold.toFixed(2)}
        />
        <EvidenceItem
          label="Dataset identity"
          value={`${result.dataset.dataset_id} v${result.dataset.version} - ${result.dataset.digest}`}
          wrap
        />
        <EvidenceItem
          className="sm:col-span-2"
          label="Prompt"
          value={query.prompt}
          wrap
        />
        {query.note !== null && (
          <EvidenceItem
            className="sm:col-span-2"
            label="Dataset note"
            value={query.note}
            wrap
          />
        )}
        <EvidenceItem
          className="sm:col-span-2"
          label="Matched prompt"
          value={
            query.matched_prompt ??
            'No matched prompt: this measured case was a cache miss.'
          }
          wrap
        />
        <EvidenceItem
          className="sm:col-span-2"
          description={
            query.matched_cache_key === null
              ? undefined
              : 'This key identified an entry in the run-local evaluation cache. That cache has been destroyed, so this evidence is intentionally not linked to the live Cache workspace.'
          }
          label="Isolated evaluation matched key"
          value={
            query.matched_cache_key ??
            'No matched key: this measured case was a cache miss.'
          }
          wrap
        />
      </dl>
    </section>
  );
}
