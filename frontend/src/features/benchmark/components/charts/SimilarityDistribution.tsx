import { formatCount, formatDecimal } from '@/shared/lib/formatters';
import type { BenchmarkQueryResult } from '@/features/benchmark/types';

import type { JSX } from 'react';

interface SimilarityDistributionProps {
  results: BenchmarkQueryResult[];
}

interface Bin {
  count: number;
  label: string;
}

const BIN_COUNT = 10;
const AXIS_LABELS = ['−1.0', '0.0', '1.0'] as const;

function buildBins(results: BenchmarkQueryResult[]): Bin[] {
  const bins = Array.from({ length: BIN_COUNT }, (_, index) => {
    const minimum = -1 + (index * 2) / BIN_COUNT;
    const maximum = minimum + 2 / BIN_COUNT;

    return {
      count: 0,
      label: `${formatDecimal(minimum, 1)}–${formatDecimal(maximum, 1)}`,
    };
  });

  for (const result of results) {
    if (result.similarity_score === null) {
      continue;
    }

    const index = Math.min(
      BIN_COUNT - 1,
      Math.max(0, Math.floor(((result.similarity_score + 1) / 2) * BIN_COUNT)),
    );
    const bin = bins[index];

    if (bin !== undefined) {
      bin.count += 1;
    }
  }

  return bins;
}

export function SimilarityDistribution({
  results,
}: Readonly<SimilarityDistributionProps>): JSX.Element {
  const bins = buildBins(results);
  const maxCount = Math.max(1, ...bins.map((bin) => bin.count));
  const unscored = results.filter((result) => result.similarity_score === null).length;
  const unscoredCount = formatCount(unscored);

  return (
    <figure className="border-t border-(--hairline) pt-4">
      <figcaption className="ui-label text-(--text-muted)">
        Similarity-score distribution
      </figcaption>
      <div className="mt-5 flex h-32 items-end gap-1">
        {bins.map((bin) => {
          const height =
            bin.count === 0 ? '0%' : `${Math.max(2, (bin.count / maxCount) * 100)}%`;

          return (
            <div
              className="group relative flex h-full min-w-0 flex-1 items-end"
              key={bin.label}
              title={`${bin.label}: ${formatCount(bin.count)}`}
            >
              <div className="w-full bg-(--teal) opacity-75" style={{ height }} />
            </div>
          );
        })}
      </div>
      <div className="font-data mt-2 flex justify-between text-[8px] text-(--text-faint)">
        {AXIS_LABELS.map((label) => (
          <span key={label}>{label}</span>
        ))}
      </div>
      <p className="font-data mt-3 text-[9px] text-(--text-faint)">
        {unscoredCount} unscored seed quer{unscored === 1 ? 'y' : 'ies'} excluded from
        the histogram.
      </p>
      <div className="sr-only">
        <table>
          <caption>Similarity-score distribution data</caption>
          <thead>
            <tr>
              <th scope="col">Score range</th>
              <th scope="col">Queries</th>
            </tr>
          </thead>
          <tbody>
            {bins.map((bin) => (
              <tr key={bin.label}>
                <th scope="row">{bin.label}</th>
                <td>{formatCount(bin.count)}</td>
              </tr>
            ))}
            <tr>
              <th scope="row">Unscored</th>
              <td>{unscoredCount}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </figure>
  );
}
