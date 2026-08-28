import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { BenchmarkAnalysis } from '@/features/benchmark/components/results/BenchmarkAnalysis';
import { benchmarkAnalysisResult, benchmarkResult } from './support';

function measuredRows(): HTMLElement[] {
  return within(
    screen.getByRole('table', {
      name: 'Per-query benchmark results',
    }),
  ).getAllByRole('row');
}

describe('BenchmarkAnalysis', () => {
  afterEach(cleanup);

  it('filters every confusion outcome and resets to all cases', () => {
    render(<BenchmarkAnalysis result={benchmarkAnalysisResult} />);

    for (const label of [
      'True positive: 1 case',
      'True negative: 1 case',
      'False positive: 1 case',
      'False negative: 1 case',
    ]) {
      fireEvent.click(screen.getByRole('button', { name: label }));
      expect(measuredRows()).toHaveLength(2);
      expect(screen.getByText(/Showing 1 of 4 cases/)).toBeTruthy();
    }

    fireEvent.click(screen.getByRole('button', { name: 'All cases' }));
    expect(measuredRows()).toHaveLength(5);
    expect(screen.getByText(/Showing 4 of 4 cases/)).toBeTruthy();
  });

  it('supports false-positive, false-negative, search, and empty quick paths', () => {
    const { rerender } = render(<BenchmarkAnalysis result={benchmarkAnalysisResult} />);

    fireEvent.click(screen.getByRole('button', { name: 'False positives' }));
    expect(
      within(measuredRows()[1] as HTMLElement).getByText('shared-miss'),
    ).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'False negatives' }));
    expect(
      within(measuredRows()[1] as HTMLElement).getByText('shared-hit'),
    ).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'All cases' }));
    fireEvent.change(screen.getByLabelText('Search measured cases'), {
      target: { value: '@expected-reuse' },
    });
    expect(measuredRows()).toHaveLength(2);
    expect(
      within(measuredRows()[1] as HTMLElement).getByText('false negative'),
    ).toBeTruthy();

    rerender(<BenchmarkAnalysis result={benchmarkResult} />);
    fireEvent.click(screen.getByRole('button', { name: 'False positive: 0 cases' }));
    expect(
      screen.getByText(
        'No measured cases match the current outcome and search filters.',
      ),
    ).toBeTruthy();
  });

  it('shows complete escaped case evidence and restores trigger focus', () => {
    render(<BenchmarkAnalysis result={benchmarkAnalysisResult} />);

    fireEvent.click(screen.getByRole('button', { name: 'False positives' }));
    const detailTrigger = screen.getAllByRole('button', {
      name: 'View details for case shared-miss, repetition 2',
    })[0] as HTMLButtonElement;
    fireEvent.click(detailTrigger);

    const detail = screen
      .getByRole('heading', {
        name: 'Case shared-miss',
      })
      .closest('section') as HTMLElement;
    expect(within(detail).getByText('=SUM(A1:A2)')).toBeTruthy();
    expect(within(detail).getByText('+cached formula-looking prompt')).toBeTruthy();
    expect(within(detail).getByText('e'.repeat(64))).toBeTruthy();
    expect(within(detail).getByText(/run-local evaluation cache/)).toBeTruthy();
    expect(within(detail).queryByRole('link')).toBeNull();
    expect(document.querySelector('script')).toBeNull();

    fireEvent.click(
      within(detail).getByRole('button', {
        name: 'Close case details',
      }),
    );
    expect(document.activeElement).toBe(detailTrigger);

    fireEvent.click(screen.getByRole('button', { name: 'False negatives' }));
    fireEvent.click(
      screen.getAllByRole('button', {
        name: 'View details for case shared-hit, repetition 2',
      })[0] as HTMLButtonElement,
    );
    expect(
      screen.getByText('No matched prompt: this measured case was a cache miss.'),
    ).toBeTruthy();
    expect(
      screen.getByText('No matched key: this measured case was a cache miss.'),
    ).toBeTruthy();
  });

  it('distinguishes repeated case IDs by repetition', () => {
    render(<BenchmarkAnalysis result={benchmarkAnalysisResult} />);

    expect(
      screen.getAllByRole('button', {
        name: 'View details for case shared-miss, repetition 1',
      }),
    ).toHaveLength(2);
    expect(
      screen.getAllByRole('button', {
        name: 'View details for case shared-miss, repetition 2',
      }),
    ).toHaveLength(2);
  });
});
