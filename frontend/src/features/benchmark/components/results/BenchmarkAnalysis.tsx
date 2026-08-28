import { useMemo, useRef, useState } from 'react';
import type { JSX } from 'react';

import { Alert, Button } from '@/shared/components/ui';
import type {
  BenchmarkMetrics,
  BenchmarkOutcome,
  BenchmarkQueryResult,
  BenchmarkRunResponse,
} from '@/features/benchmark/types';
import { BenchmarkCaseDetail } from './BenchmarkCaseDetail';
import { BenchmarkResultsTable } from './BenchmarkResultsTable';

type OutcomeFilter = BenchmarkOutcome | 'all';

interface OutcomeOption {
  description: string;
  label: string;
  metric: keyof Pick<
    BenchmarkMetrics,
    | 'true_positive_hits'
    | 'true_negative_misses'
    | 'false_positive_hits'
    | 'false_negative_misses'
  >;
  outcome: BenchmarkOutcome;
  shortLabel: string;
}

const OUTCOME_OPTIONS: readonly OutcomeOption[] = [
  {
    description: 'Expected reuse served from cache.',
    label: 'True positive',
    metric: 'true_positive_hits',
    outcome: 'true_positive',
    shortLabel: 'TP',
  },
  {
    description: 'Expected miss called the provider.',
    label: 'True negative',
    metric: 'true_negative_misses',
    outcome: 'true_negative',
    shortLabel: 'TN',
  },
  {
    description: 'Unexpected reuse served from cache.',
    label: 'False positive',
    metric: 'false_positive_hits',
    outcome: 'false_positive',
    shortLabel: 'FP',
  },
  {
    description: 'Expected reuse called the provider.',
    label: 'False negative',
    metric: 'false_negative_misses',
    outcome: 'false_negative',
    shortLabel: 'FN',
  },
];

function includesSearch(
  query: BenchmarkQueryResult,
  normalizedSearch: string,
): boolean {
  if (normalizedSearch === '') {
    return true;
  }
  return [
    query.case_id,
    query.category,
    query.outcome,
    query.prompt,
    query.matched_prompt,
    query.matched_cache_key,
  ].some((value) => value?.toLowerCase().includes(normalizedSearch));
}

function filterLabel(filter: OutcomeFilter): string {
  if (filter === 'all') {
    return 'All cases';
  }
  return OUTCOME_OPTIONS.find((option) => option.outcome === filter)?.label ?? filter;
}

export function BenchmarkAnalysis({
  result,
}: Readonly<{ result: BenchmarkRunResponse }>): JSX.Element {
  const [outcomeFilter, setOutcomeFilter] = useState<OutcomeFilter>('all');
  const [search, setSearch] = useState('');
  const [selectedCase, setSelectedCase] = useState<BenchmarkQueryResult | null>(null);
  const returnFocusRef = useRef<HTMLButtonElement | null>(null);

  const orderedResults = useMemo(
    () =>
      [...result.query_results].sort(
        (left, right) =>
          left.sequence - right.sequence || left.repetition - right.repetition,
      ),
    [result.query_results],
  );
  const evidenceCounts = useMemo(
    () =>
      Object.fromEntries(
        OUTCOME_OPTIONS.map((option) => [
          option.outcome,
          orderedResults.filter((query) => query.outcome === option.outcome).length,
        ]),
      ) as Record<BenchmarkOutcome, number>,
    [orderedResults],
  );
  const countsReconcile = OUTCOME_OPTIONS.every(
    (option) => evidenceCounts[option.outcome] === result.metrics[option.metric],
  );
  const normalizedSearch = search.trim().toLowerCase();
  const filteredResults = orderedResults.filter(
    (query) =>
      (outcomeFilter === 'all' || query.outcome === outcomeFilter) &&
      includesSearch(query, normalizedSearch),
  );

  function updateOutcomeFilter(filter: OutcomeFilter): void {
    setOutcomeFilter(filter);
    setSelectedCase(null);
    returnFocusRef.current = null;
  }

  function openCase(query: BenchmarkQueryResult, trigger: HTMLButtonElement): void {
    returnFocusRef.current = trigger;
    setSelectedCase(query);
  }

  function closeCase(): void {
    const returnFocus = returnFocusRef.current;
    setSelectedCase(null);
    returnFocus?.focus();
  }

  if (!countsReconcile) {
    return (
      <Alert
        className="mt-10 border-l-2 border-(--coral) bg-[rgba(194,96,74,0.06)] px-4 py-3"
        role="alert"
        title="Case analysis unavailable"
        tone="error"
      >
        <p className="font-data mt-1 text-[11px]/5 text-(--text-soft)">
          The aggregate confusion matrix does not match the decoded case evidence.
        </p>
      </Alert>
    );
  }

  return (
    <section aria-labelledby="benchmark-analysis-heading" className="mt-12">
      <div className="max-w-3xl">
        <p className="ui-label text-(--teal)">Correctness analysis</p>
        <h2
          className="font-display mt-1 text-2xl italic"
          id="benchmark-analysis-heading"
        >
          Confusion matrix and case evidence
        </h2>
        <p className="font-data mt-3 text-[11px]/5 text-(--text-muted)">
          Filter the measured run by exact outcome, then inspect one case. False
          positives are unexpected cache reuse; false negatives are missed reuse
          opportunities. Counts describe this dataset and threshold only.
        </p>
      </div>

      <fieldset
        className="mt-6 grid grid-cols-2 gap-3 min-[960px]:grid-cols-4"
        data-confusion-matrix
      >
        <legend className="sr-only">Measured run confusion matrix</legend>
        {OUTCOME_OPTIONS.map((option) => {
          const count = evidenceCounts[option.outcome];
          const selected = outcomeFilter === option.outcome;
          return (
            <button
              aria-label={`${option.label}: ${count} ${count === 1 ? 'case' : 'cases'}`}
              aria-pressed={selected}
              className={`min-h-28 border p-4 text-left transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--gold) ${
                selected
                  ? 'border-(--gold) bg-[rgba(214,168,79,0.08)]'
                  : 'border-(--hairline) hover:border-(--text-faint)'
              }`}
              key={option.outcome}
              onClick={() => updateOutcomeFilter(option.outcome)}
              type="button"
            >
              <span className="flex items-start justify-between gap-3">
                <span>
                  <span className="ui-label block text-(--text-soft)">
                    {option.label}
                  </span>
                  <span className="font-data mt-1 block text-[10px] text-(--text-faint)">
                    {option.shortLabel}
                  </span>
                </span>
                <span className="font-data text-2xl tabular-nums text-(--text)">
                  {count}
                </span>
              </span>
              <span className="font-data mt-3 block text-[10px]/4 text-(--text-faint)">
                {option.description}
              </span>
            </button>
          );
        })}
      </fieldset>

      <div className="mt-6 flex flex-wrap items-end gap-3">
        <Button
          aria-pressed={outcomeFilter === 'all'}
          className="border-(--hairline) text-(--text-soft) hover:border-(--teal) hover:text-(--teal)"
          onClick={() => updateOutcomeFilter('all')}
          size="compact"
          variant="secondary"
        >
          All cases
        </Button>
        <Button
          aria-pressed={outcomeFilter === 'false_positive'}
          className="border-(--hairline) text-(--coral-text) hover:border-(--coral-text)"
          onClick={() => updateOutcomeFilter('false_positive')}
          size="compact"
          variant="secondary"
        >
          False positives
        </Button>
        <Button
          aria-pressed={outcomeFilter === 'false_negative'}
          className="border-(--hairline) text-(--coral-text) hover:border-(--coral-text)"
          onClick={() => updateOutcomeFilter('false_negative')}
          size="compact"
          variant="secondary"
        >
          False negatives
        </Button>
        <label className="ml-0 min-w-0 flex-1 sm:ml-auto sm:max-w-sm">
          <span className="ui-label block text-(--text-muted)">
            Search measured cases
          </span>
          <input
            className="font-data mt-2 min-h-11 w-full border border-(--hairline) bg-(--ink) px-3 py-2 text-sm text-(--text) outline-none placeholder:text-(--text-faint) focus-visible:border-(--gold) focus-visible:ring-1 focus-visible:ring-(--gold)"
            onChange={(event) => {
              setSearch(event.target.value);
              setSelectedCase(null);
              returnFocusRef.current = null;
            }}
            placeholder="Case ID, category, prompt, outcome, or match"
            type="search"
            value={search}
          />
        </label>
      </div>

      <output
        aria-live="polite"
        className="font-data mt-4 block text-[10px]/5 text-(--text-muted)"
      >
        Showing {filteredResults.length} of {orderedResults.length} cases. Filter:{' '}
        {filterLabel(outcomeFilter)}
        {normalizedSearch === '' ? '.' : `; search: ${search.trim()}.`}
      </output>

      <BenchmarkResultsTable
        onSelectCase={openCase}
        results={filteredResults}
        selectedCase={selectedCase}
      />

      {filteredResults.length === 0 && (
        <output className="font-data mt-6 block w-full border-y border-(--hairline) py-6 text-center text-[11px]/5 text-(--text-muted)">
          No measured cases match the current outcome and search filters.
        </output>
      )}

      {selectedCase !== null && (
        <BenchmarkCaseDetail onClose={closeCase} query={selectedCase} result={result} />
      )}
    </section>
  );
}
