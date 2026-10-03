import type { ReactNode, JSX } from 'react';
import { Link } from 'react-router';
import { APP_PATHS } from '@/app/navigation/navigationConfig';
import { MarkdownContent } from '@/shared/components/markdown/MarkdownContent';
import {
  formatCompactDuration,
  formatLatency,
  formatSimilarity,
} from '@/shared/lib/formatters';
import { hasSimilarityScore } from '@/shared/domain/similarity';
import { QUERY_POLICY_LABELS, type QueryEvidence, type QueryResponse } from '../types';

interface ResponseCardProps {
  evidence?: QueryEvidence | null;
  result: QueryResponse;
}

interface EvidenceItem {
  className: string;
  label: string;
  value: ReactNode;
  valueClassName: string;
}

function explainDecision(result: QueryResponse): string {
  const score = formatSimilarity(result.similarity_score);
  const threshold = formatSimilarity(result.similarity_threshold);

  if (result.cache_hit && hasSimilarityScore(result.similarity_score)) {
    return `Reused a cached response because similarity ${score} met the ${threshold} threshold.`;
  }

  if (result.generation_skipped && !result.provider_called) {
    return 'Awaited an identical in-flight request instead of making a duplicate provider call.';
  }

  if (!hasSimilarityScore(result.similarity_score)) {
    return 'Generated a fresh response because no cached entry was available to compare.';
  }

  if (result.similarity_score < result.similarity_threshold) {
    return `Generated a fresh response because the nearest similarity ${score} was below the ${threshold} threshold.`;
  }

  return 'Generated a fresh response because the nearest candidate was unavailable at reuse time.';
}

function EvidenceMetric({
  className,
  label,
  value,
  valueClassName,
}: Readonly<EvidenceItem>): JSX.Element {
  return (
    <div className={className}>
      <dt className="ui-label text-(--text-faint)">{label}</dt>
      <dd className={valueClassName}>{value}</dd>
    </div>
  );
}

export function ResponseCard({
  evidence = null,
  result,
}: Readonly<ResponseCardProps>): JSX.Element {
  const similarity = formatSimilarity(result.similarity_score);
  const threshold = formatSimilarity(result.similarity_threshold);
  const cacheAge = formatCompactDuration(result.cache_entry_age_seconds, {
    secondFractionDigits: 1,
  });
  const explanation = explainDecision(result);
  const isCoalesced =
    !result.cache_hit && result.generation_skipped && !result.provider_called;
  let verdict = {
    accentColor: 'var(--coral)',
    label: 'FRESH RESPONSE',
    textColor: 'var(--coral-text)',
  };

  if (result.cache_hit) {
    verdict = {
      accentColor: 'var(--teal)',
      label: 'CACHE HIT',
      textColor: 'var(--teal)',
    };
  } else if (isCoalesced) {
    verdict = {
      accentColor: 'var(--gold)',
      label: 'COALESCED RESPONSE',
      textColor: 'var(--gold)',
    };
  }
  const cacheAgeValue =
    result.cache_entry_created_at === null ? (
      cacheAge
    ) : (
      <time
        dateTime={result.cache_entry_created_at}
        title={`Created ${result.cache_entry_created_at}`}
      >
        {cacheAge}
      </time>
    );
  const evidenceItems = [
    {
      className: 'py-3 min-[520px]:border-r min-[520px]:border-(--hairline)',
      label: 'Similarity',
      value: similarity,
      valueClassName: 'font-data mt-1 text-xs tabular-nums text-(--teal)',
    },
    {
      className:
        'border-t border-(--hairline) py-3 min-[520px]:border-t-0 min-[520px]:pl-4 min-[860px]:border-r min-[860px]:border-(--hairline)',
      label: 'Threshold used',
      value: threshold,
      valueClassName: 'font-data mt-1 text-xs tabular-nums text-(--text-soft)',
    },
    {
      className:
        'border-t border-(--hairline) py-3 min-[520px]:border-r min-[520px]:border-(--hairline) min-[860px]:border-t-0 min-[860px]:pl-4',
      label: 'Generation',
      value: result.generation_skipped ? 'Skipped' : 'Ran',
      valueClassName: 'font-data mt-1 text-xs tabular-nums text-(--text-soft)',
    },
    {
      className:
        'border-t border-(--hairline) py-3 min-[520px]:pl-4 min-[860px]:border-t-0',
      label: 'Provider',
      value: result.provider_called ? 'Called' : 'Not called',
      valueClassName: 'font-data mt-1 text-xs tabular-nums text-(--text-soft)',
    },
    {
      className:
        'border-t border-(--hairline) py-3 min-[520px]:col-span-2 min-[520px]:border-r min-[520px]:border-(--hairline) min-[860px]:col-span-2',
      label: 'Matched cached prompt',
      value: result.matched_prompt ?? 'No cached entry reused',
      valueClassName:
        'mt-1 whitespace-pre-wrap wrap-break-word text-sm text-(--text-soft)',
    },
    {
      className:
        'border-t border-(--hairline) py-3 min-[520px]:border-r min-[520px]:border-(--hairline) min-[520px]:pl-4',
      label: 'Cache entry age',
      value: cacheAgeValue,
      valueClassName: 'font-data mt-1 text-xs tabular-nums text-(--text-soft)',
    },
    {
      className: 'border-t border-(--hairline) py-3 min-[520px]:pl-4',
      label: 'Request latency',
      value: formatLatency(result.latency_ms),
      valueClassName: 'font-data mt-1 text-xs tabular-nums text-(--text-soft)',
    },
  ] satisfies EvidenceItem[];

  return (
    <article
      aria-live="polite"
      className="border-y border-l-2 border-(--hairline) bg-(--surface) px-4 py-5 sm:px-6"
      style={{ borderLeftColor: verdict.accentColor }}
    >
      <header className="mb-5 flex flex-wrap items-center justify-between gap-3 border-b border-(--hairline) pb-4">
        <h2 className="font-display text-xl italic">Latest response</h2>

        <span
          className="ui-label border px-2 py-1"
          style={{
            borderColor: verdict.accentColor,
            color: verdict.textColor,
          }}
        >
          {verdict.label}
        </span>
      </header>

      <MarkdownContent
        className="text-sm text-(--text-soft)"
        markdown={result.response}
      />

      <section
        aria-label="Cache decision explanation"
        className="mt-6 border-t border-(--hairline) pt-4"
      >
        <p className="ui-label text-(--text-faint)">Decision evidence</p>
        <p className="mt-2 text-sm/6 text-(--text-soft)">{explanation}</p>

        {evidence !== null && (
          <p className="font-data mt-3 wrap-break-word text-[11px]/5 text-(--text-muted)">
            Effective namespace: {evidence.namespace} · Policy:{' '}
            {QUERY_POLICY_LABELS[evidence.policyMode]}.
          </p>
        )}

        <dl className="mt-4 grid grid-cols-1 border-t border-(--hairline) min-[520px]:grid-cols-2 min-[860px]:grid-cols-4">
          {evidenceItems.map((item) => (
            <EvidenceMetric key={item.label} {...item} />
          ))}
        </dl>

        {result.cache_hit && result.matched_cache_key !== null && (
          <Link
            className="ui-label mt-5 inline-flex min-h-11 items-center border-b border-(--teal) text-(--teal) focus-visible:outline-2 focus-visible:outline-offset-3 focus-visible:outline-(--teal)"
            to={`${APP_PATHS.cache}/entries/${encodeURIComponent(result.matched_cache_key)}`}
          >
            Open matched live cache entry
          </Link>
        )}
      </section>
    </article>
  );
}
