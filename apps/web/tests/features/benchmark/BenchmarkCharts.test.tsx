import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { LineChart } from '@/features/benchmark/components/charts/LineChart';
import { SimilarityDistribution } from '@/features/benchmark/components/charts/SimilarityDistribution';
import { benchmarkResult } from './support';

describe('benchmark chart accessibility', () => {
  it('provides the complete line-series data in a semantic table', () => {
    render(
      <LineChart
        series={[
          {
            color: 'var(--gold)',
            label: 'Hit rate',
            points: [
              { kind: 'measured', x: 0.8, y: 0.5 },
              { kind: 'projected', x: 0.95, y: 0 },
            ],
          },
        ]}
        title="Hit rate vs. threshold"
        valueLabel={(value) => `${value * 100}%`}
      />,
    );

    const table = screen.getByRole('table', {
      name: 'Hit rate vs. threshold data',
    });
    expect(within(table).getByText('Series')).toBeTruthy();
    expect(within(table).getByText('Value kind')).toBeTruthy();
    expect(within(table).getByText('Measured threshold')).toBeTruthy();
    expect(within(table).getByText('Frozen-candidate projection')).toBeTruthy();
    expect(within(table).getByText('0.80')).toBeTruthy();
    expect(within(table).getByText('50%')).toBeTruthy();
    expect(within(table).getByText('0.95')).toBeTruthy();
    expect(within(table).getByText('0%')).toBeTruthy();
  });

  it('renders empty histogram bins at zero height and exposes every count', () => {
    const { container } = render(
      <SimilarityDistribution results={benchmarkResult.query_results} />,
    );
    const titledBins = container.querySelectorAll<HTMLDivElement>('[title]');
    const emptyBin = Array.from(titledBins).find((bin) => bin.title.endsWith(': 0'));

    expect(emptyBin?.firstElementChild?.getAttribute('style')).toContain('height: 0%');

    const table = screen.getByRole('table', {
      name: 'Similarity-score distribution data',
    });
    expect(within(table).getAllByRole('row')).toHaveLength(12);
    expect(within(table).getByText('Unscored')).toBeTruthy();
  });
});
