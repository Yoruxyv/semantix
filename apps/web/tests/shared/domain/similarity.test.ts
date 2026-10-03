import { describe, expect, it } from 'vitest';

import {
  cacheDecisionLabel,
  hasSimilarityScore,
  meetsSimilarityThreshold,
  SIMILARITY_MAX,
  SIMILARITY_MIN,
  THRESHOLD_MAX,
  THRESHOLD_MIN,
} from '@/shared/domain/similarity';

describe('similarity domain helpers', () => {
  it('exposes backend score and threshold bounds', () => {
    expect(SIMILARITY_MIN).toBe(-1);
    expect(SIMILARITY_MAX).toBe(1);
    expect(THRESHOLD_MIN).toBe(0);
    expect(THRESHOLD_MAX).toBe(1);
  });

  it('distinguishes missing scores from numeric scores', () => {
    expect(hasSimilarityScore(null)).toBe(false);
    expect(hasSimilarityScore(0)).toBe(true);
    expect(hasSimilarityScore(-0.5)).toBe(true);
  });

  it('uses an inclusive similarity threshold', () => {
    expect(meetsSimilarityThreshold(null, 0.9)).toBe(false);
    expect(meetsSimilarityThreshold(0.9, 0.9)).toBe(true);
    expect(meetsSimilarityThreshold(0.899, 0.9)).toBe(false);
  });

  it('formats cache decision labels', () => {
    expect(cacheDecisionLabel(true)).toBe('HIT');
    expect(cacheDecisionLabel(false)).toBe('MISS');
  });
});
