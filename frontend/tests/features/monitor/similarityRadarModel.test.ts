import { describe, expect, it } from 'vitest';

import {
  PLOT_LEFT,
  PLOT_RIGHT,
  scoreToX,
} from '@/features/monitor/components/similarity-radar/model';

describe('similarity radar model', () => {
  it('maps the full cosine-similarity domain to distinct positions', () => {
    expect(scoreToX(-1)).toBe(PLOT_LEFT);
    expect(scoreToX(1)).toBe(PLOT_RIGHT);
    expect(scoreToX(-0.5)).toBeGreaterThan(scoreToX(-1));
    expect(scoreToX(-0.01)).toBeLessThan(scoreToX(0));
    expect(scoreToX(0)).toBe((PLOT_LEFT + PLOT_RIGHT) / 2);
  });

  it('clamps only values outside the documented score domain', () => {
    expect(scoreToX(-2)).toBe(PLOT_LEFT);
    expect(scoreToX(2)).toBe(PLOT_RIGHT);
  });
});
