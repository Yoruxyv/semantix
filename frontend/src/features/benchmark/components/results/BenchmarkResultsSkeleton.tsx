import type { JSX } from 'react';

const RESULT_METRICS = Array.from({ length: 18 }, (_, index) => index);
const RESULT_CHARTS = Array.from({ length: 5 }, (_, index) => index);

export function BenchmarkResultsSkeleton(): JSX.Element {
  return (
    <output
      aria-label="Loading benchmark results"
      aria-live="polite"
      className="mt-8 block animate-pulse"
    >
      <span className="ui-label text-(--gold)">Running controlled query sequence</span>
      <span className="mt-5 grid grid-cols-2 gap-x-6 gap-y-5 md:grid-cols-4">
        {RESULT_METRICS.map((item) => (
          <span
            className="border-t border-(--hairline) pt-3"
            data-skeleton-result-metric
            key={item}
          >
            <span className="block h-2 w-20 bg-[rgba(234,230,221,0.05)]" />
            <span className="mt-3 block h-5 w-16 bg-[rgba(234,230,221,0.08)]" />
          </span>
        ))}
      </span>
      <span className="mt-10 grid gap-8 md:grid-cols-2">
        {RESULT_CHARTS.map((item) => (
          <span
            className="border-t border-(--hairline) pt-4"
            data-skeleton-result-chart
            key={item}
          >
            <span className="block h-2 w-44 bg-[rgba(234,230,221,0.05)]" />
            <span className="mt-4 block h-36 bg-[rgba(91,156,148,0.06)]" />
          </span>
        ))}
      </span>
    </output>
  );
}
