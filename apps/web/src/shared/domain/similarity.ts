export const SIMILARITY_MIN = -1;
export const SIMILARITY_MAX = 1;
export const THRESHOLD_MIN = 0;
export const THRESHOLD_MAX = 1;

export type CacheDecisionLabel = 'HIT' | 'MISS';

export function hasSimilarityScore(score: number | null): score is number {
  return score !== null;
}

export function meetsSimilarityThreshold(
  score: number | null,
  threshold: number,
): boolean {
  return hasSimilarityScore(score) && score >= threshold;
}

export function cacheDecisionLabel(isHit: boolean): CacheDecisionLabel {
  return isHit ? 'HIT' : 'MISS';
}
