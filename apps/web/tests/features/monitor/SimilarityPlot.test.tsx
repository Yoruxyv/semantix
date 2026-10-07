import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { SimilarityPlot } from '@/features/monitor/components/similarity-radar/SimilarityPlot';
import {
  scoreToX,
  VIEW_HEIGHT,
  VIEW_WIDTH,
} from '@/features/monitor/components/similarity-radar/model';

const props = {
  activePointId: null,
  appliedThreshold: 0.92,
  onActivePointChange: vi.fn(),
  points: [],
  previewThreshold: 0.92,
  totalTraces: 0,
};

describe('SimilarityPlot', () => {
  afterEach(cleanup);

  it('keeps the full scale, major axis labels, and band geometry', () => {
    const { container } = render(<SimilarityPlot {...props} />);
    expect(
      screen.getByRole('region', { name: 'Similarity score visualization' }),
    ).toBeTruthy();
    expect(container.querySelector('svg')?.getAttribute('viewBox')).toBe(
      `0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`,
    );
    expect(container.querySelectorAll('svg rect')).toHaveLength(3);
    const bands = container.querySelectorAll('svg rect');
    expect(Number(bands[0]?.getAttribute('x'))).toBe(scoreToX(-1));
    expect(Number(bands[1]?.getAttribute('x'))).toBe(scoreToX(0.75));
    expect(Number(bands[2]?.getAttribute('x'))).toBe(scoreToX(0.9));
    for (const tick of ['-1.00', '-0.50', '0.00', '0.50', '1.00']) {
      expect(screen.getByText(tick, { exact: true })).toBeTruthy();
    }
    expect(
      screen.getByRole('list', { name: 'Score reference bands' }).textContent,
    ).toContain('STRONG');
    expect(
      screen.getByRole('list', { name: 'Score reference bands' }).textContent,
    ).toContain('WEAK');
    expect(
      screen.getByRole('list', { name: 'Score reference bands' }).textContent,
    ).toContain('REVIEW');
    expect(
      screen.getByRole('list', { name: 'Score reference bands' }).textContent,
    ).toContain('STRONG');
    expect(screen.getByText('BACKEND 0.92')).toBeTruthy();
    expect(screen.queryByText(/PREVIEW /)).toBeNull();
  });

  it('keeps backend and preview marker positions independent without changing the bands', () => {
    const { container, rerender } = render(<SimilarityPlot {...props} />);
    const bandGeometry = () =>
      Array.from(container.querySelectorAll('svg rect'), (rect) => [
        rect.getAttribute('x'),
        rect.getAttribute('width'),
      ]);
    const originalBands = bandGeometry();
    rerender(<SimilarityPlot {...props} previewThreshold={1} />);
    expect(screen.getByText('BACKEND 0.92')).toBeTruthy();
    expect(screen.getByText('PREVIEW 1.00')).toBeTruthy();
    expect(
      Number(container.querySelector('line[stroke="var(--gold)"]')?.getAttribute('x1')),
    ).toBe(scoreToX(0.92));
    expect(
      Number(container.querySelector('line[stroke="var(--teal)"]')?.getAttribute('x1')),
    ).toBe(scoreToX(1));
    expect(bandGeometry()).toEqual(originalBands);
  });
});
