import { describe, expect, it } from 'vitest';

import { compileThresholdSweep } from '@/features/benchmark/lib/thresholdSweep';

describe('compileThresholdSweep', () => {
  it('inserts the measured threshold exactly once and preserves decimal steps', () => {
    expect(compileThresholdSweep(0.8, 0.9, 0.05, 0.92)).toEqual({
      error: null,
      thresholds: [0.8, 0.85, 0.9, 0.92],
    });
    expect(compileThresholdSweep(0.8, 0.9, 0.05, 0.85)).toEqual({
      error: null,
      thresholds: [0.8, 0.85, 0.9],
    });
  });

  it('accepts the minimum and maximum supported sweep sizes', () => {
    expect(compileThresholdSweep(0.9, 0.9, 0.1, 0.92).thresholds).toEqual([0.9, 0.92]);
    expect(compileThresholdSweep(0.86, 1, 0.01, 0.92)).toEqual({
      error: null,
      thresholds: [
        0.86, 0.87, 0.88, 0.89, 0.9, 0.91, 0.92, 0.93, 0.94, 0.95, 0.96, 0.97, 0.98,
        0.99, 1,
      ],
    });
  });

  it('rejects invalid ranges and lists beyond the backend cap', () => {
    expect(compileThresholdSweep(0.95, 0.8, 0.05, 0.92).error).not.toBeNull();
    expect(compileThresholdSweep(0.85, 1, 0.01, 0.92).error).toContain('at most 15');
  });
});
