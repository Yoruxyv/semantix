import type { JSX } from 'react';
interface SimilarityStatsProps {
  projectedHits: number;
  projectedMisses: number;
  scoredCount: number;
}

interface SimilarityStat {
  className: string;
  label: string;
  value: number;
  valueClassName: string;
}

export function SimilarityStats({
  projectedHits,
  projectedMisses,
  scoredCount,
}: Readonly<SimilarityStatsProps>): JSX.Element {
  const stats = [
    {
      className: 'border-r border-(--hairline) p-3',
      label: 'Scored',
      value: scoredCount,
      valueClassName: 'font-data mt-1 text-lg',
    },
    {
      className: 'border-r border-(--hairline) p-3',
      label: 'Projected hits',
      value: projectedHits,
      valueClassName: 'font-data mt-1 text-lg text-(--gold)',
    },
    {
      className: 'p-3',
      label: 'Projected misses',
      value: projectedMisses,
      valueClassName: 'font-data mt-1 text-lg text-(--coral-text)',
    },
  ] satisfies SimilarityStat[];

  return (
    <div className="grid grid-cols-3 border-y border-(--hairline)">
      {stats.map((stat) => (
        <div className={stat.className} key={stat.label}>
          <p className="ui-label text-(--text-faint)">{stat.label}</p>
          <p className={stat.valueClassName}>{stat.value}</p>
        </div>
      ))}
    </div>
  );
}
