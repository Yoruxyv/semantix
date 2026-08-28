import { Button } from '@/shared/components/ui';
import { cacheDecisionLabel } from '@/shared/domain/similarity';
import { formatSimilarity } from '@/shared/lib/formatters';
import type { BenchmarkQueryResult } from '@/features/benchmark/types';
import { BENCHMARK_RESULT_COLUMNS } from '@/features/benchmark/lib/resultColumns';

import type { JSX } from 'react';

interface BenchmarkResultsTableProps {
  onSelectCase: (result: BenchmarkQueryResult, trigger: HTMLButtonElement) => void;
  results: BenchmarkQueryResult[];
  selectedCase: BenchmarkQueryResult | null;
}

export function BenchmarkResultsTable({
  onSelectCase,
  results,
  selectedCase,
}: Readonly<BenchmarkResultsTableProps>): JSX.Element {
  return (
    <section aria-labelledby="benchmark-results-heading" className="mt-6">
      <h3 className="ui-label text-(--text-muted)" id="benchmark-results-heading">
        Filtered measured cases
      </h3>
      <ul
        aria-label="Compact measured case results"
        className="mt-4 grid gap-3 min-[960px]:hidden"
      >
        {results.map((result) => (
          <li
            className={`border p-4 ${
              selectedCase === result
                ? 'border-(--gold) bg-[rgba(214,168,79,0.06)]'
                : 'border-(--hairline)'
            }`}
            key={`${result.sequence}-${result.repetition}-${result.case_id}`}
          >
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="font-data wrap-break-word text-sm text-(--text-soft)">
                  {result.case_id}
                </p>
                <p className="font-data mt-1 text-[10px]/5 text-(--text-faint)">
                  Sequence {result.sequence}, repetition {result.repetition}
                </p>
              </div>
              <span
                className={`ui-label ${
                  result.correct ? 'text-(--teal)' : 'text-(--coral-text)'
                }`}
              >
                {result.outcome.replaceAll('_', ' ')}
              </span>
            </div>
            <dl className="font-data mt-4 grid grid-cols-3 gap-3 text-[10px]/5">
              <div>
                <dt className="text-(--text-faint)">Expected</dt>
                <dd className="mt-1 text-(--text-soft)">
                  {cacheDecisionLabel(result.expected_cache_hit)}
                </dd>
              </div>
              <div>
                <dt className="text-(--text-faint)">Actual</dt>
                <dd className="mt-1 text-(--text-soft)">
                  {cacheDecisionLabel(result.actual_cache_hit)}
                </dd>
              </div>
              <div>
                <dt className="text-(--text-faint)">Score</dt>
                <dd className="mt-1 text-(--text-soft)">
                  {formatSimilarity(result.similarity_score)}
                </dd>
              </div>
            </dl>
            <Button
              aria-controls={
                selectedCase === result ? 'benchmark-case-detail' : undefined
              }
              aria-expanded={selectedCase === result}
              className="mt-4 border-(--hairline) text-(--text-soft) hover:border-(--teal) hover:text-(--teal)"
              onClick={(event) => onSelectCase(result, event.currentTarget)}
              size="compact"
              variant="secondary"
            >
              View details for case {result.case_id}, repetition {result.repetition}
            </Button>
          </li>
        ))}
      </ul>
      <p className="font-data mt-3 hidden text-[10px] text-(--text-faint) min-[960px]:block">
        The table remains horizontally scrollable for dense comparison. Every row has
        the same detail alternative as the compact list.
      </p>
      <section
        aria-label="Scrollable per-query benchmark evidence"
        className="scrollbar-thin mt-5 hidden overflow-x-auto border-y border-(--hairline) min-[960px]:block"
        // The overflow region must be keyboard-focusable so non-pointer users can scroll it.
        // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
        tabIndex={0}
      >
        <table className="w-full min-w-[1120px] border-collapse text-left">
          <caption className="sr-only">Per-query benchmark results</caption>
          <thead className="bg-(--ink)">
            <tr className="ui-label text-(--text-faint)">
              {BENCHMARK_RESULT_COLUMNS.map((column) => (
                <th
                  className={`p-3 font-medium ${column.headerClassName ?? ''}`}
                  key={column.id}
                  scope="col"
                >
                  {column.header}
                </th>
              ))}
              <th className="p-3 font-medium" scope="col">
                Inspect
              </th>
            </tr>
          </thead>
          <tbody className="font-data text-[11px]">
            {results.map((result) => (
              <tr
                className="border-t border-(--hairline) align-top transition-colors hover:bg-[rgba(234,230,221,0.025)]"
                key={`${result.repetition}-${result.case_id}`}
              >
                {BENCHMARK_RESULT_COLUMNS.map((column) => (
                  <td
                    className={
                      typeof column.cellClassName === 'function'
                        ? column.cellClassName(result)
                        : column.cellClassName
                    }
                    key={column.id}
                  >
                    {column.render(result)}
                  </td>
                ))}
                <td className="px-3 py-4">
                  <Button
                    aria-controls={
                      selectedCase === result ? 'benchmark-case-detail' : undefined
                    }
                    aria-expanded={selectedCase === result}
                    className="whitespace-nowrap border-(--hairline) text-(--text-soft) hover:border-(--teal) hover:text-(--teal)"
                    onClick={(event) => onSelectCase(result, event.currentTarget)}
                    size="compact"
                    variant="secondary"
                  >
                    View details for case {result.case_id}, repetition{' '}
                    {result.repetition}
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </section>
  );
}
