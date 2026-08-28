import type { QueryTrace } from '@/features/monitor/types';
import {
  hasSimilarityScore,
  meetsSimilarityThreshold,
  SIMILARITY_MAX,
  SIMILARITY_MIN,
} from '@/shared/domain/similarity';

export const VIEW_WIDTH = 640;
export const VIEW_HEIGHT = 230;
export const PLOT_LEFT = 34;
export const PLOT_RIGHT = 606;
export const PLOT_TOP = 58;
export const PLOT_BOTTOM = 178;
export const AXIS_Y = 190;
export const FIXED_TICKS = [-1, -0.5, 0, 0.5, 0.75, 0.9, 1];

type ScoredTrace = QueryTrace & { similarity: number };

export interface PlotPoint extends ScoredTrace {
  isProjectedHit: boolean;
  x: number;
  y: number;
}

function clampScore(score: number): number {
  return Math.max(SIMILARITY_MIN, Math.min(SIMILARITY_MAX, score));
}

function isScoredTrace(trace: QueryTrace): trace is ScoredTrace {
  return hasSimilarityScore(trace.similarity);
}

export function scoreToX(score: number): number {
  const normalizedScore =
    (clampScore(score) - SIMILARITY_MIN) / (SIMILARITY_MAX - SIMILARITY_MIN);
  return PLOT_LEFT + normalizedScore * (PLOT_RIGHT - PLOT_LEFT);
}

function stableJitter(id: string): number {
  let hash = 0;

  for (const character of id) {
    hash = (hash * 31 + character.charCodeAt(0)) >>> 0;
  }

  return PLOT_TOP + (hash % (PLOT_BOTTOM - PLOT_TOP));
}

export function buildPlotPoints(traces: QueryTrace[], threshold: number): PlotPoint[] {
  return traces.filter(isScoredTrace).map((trace) => ({
    ...trace,
    isProjectedHit: meetsSimilarityThreshold(trace.similarity, threshold),
    x: scoreToX(trace.similarity),
    y: stableJitter(trace.id),
  }));
}

export function formatPrompt(prompt: string): string {
  return prompt.length <= 52 ? prompt : `${prompt.slice(0, 49)}…`;
}
