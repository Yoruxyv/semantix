import { useMemo, useState, type JSX } from "react";

import type { QueryTrace } from "@/features/monitor/types";
import { buildPlotPoints } from "./model";
import { SimilarityPlot } from "./SimilarityPlot";
import { SimilarityStats } from "./SimilarityStats";
import { SimilarityTraceList } from "./SimilarityTraceList";
import { ThresholdControls } from "./ThresholdControls";

interface SimilarityRadarProps {
  appliedThreshold: number;
  canApplyThreshold: boolean;
  isApplyingThreshold: boolean;
  traces: QueryTrace[];
  threshold: number;
  onThresholdChange: (threshold: number) => void;
  onThresholdApply: (threshold: number) => void;
}

export function SimilarityRadar({
  appliedThreshold,
  canApplyThreshold,
  isApplyingThreshold,
  traces,
  threshold,
  onThresholdChange,
  onThresholdApply,
}: Readonly<SimilarityRadarProps>): JSX.Element {
  const [selectedPointId, setSelectedPointId] =
    useState<string | null>(null);
  const points = useMemo(
    () => buildPlotPoints(traces, threshold),
    [threshold, traces],
  );
  const activePointId = points.some(
    (point) => point.id === selectedPointId,
  )
    ? selectedPointId
    : null;
  const projectedHits = points.filter(
    (point) => point.isProjectedHit,
  ).length;
  const projectedMisses =
    points.length - projectedHits;
  const recentPoints = points.slice(0, 5);

  return (
    <section aria-labelledby="radar-heading">
      <header className="mb-5">
        <h2
          className="font-display text-2xl italic"
          id="radar-heading"
        >
          Similarity threshold plot
        </h2>
        <p className="ui-label mt-1 text-(--text-faint)">
          Position carries meaning / left −1.0 / right 1.0
        </p>
      </header>

      <SimilarityStats
        projectedHits={projectedHits}
        projectedMisses={projectedMisses}
        scoredCount={points.length}
      />

      <p className="font-data mt-4 text-[10px] text-(--text-faint)">
        {points.length} of {traces.length} traces plotted
      </p>

      {points.length === 0 && (
        <p className="mt-3 border-l border-(--gold) pl-3 text-xs/5  text-(--text-muted)">
          No scored comparison yet. The first query seeds the cache; the
          next query is the first one that can produce a similarity
          score.
        </p>
      )}

      <SimilarityPlot
        activePointId={activePointId}
        appliedThreshold={appliedThreshold}
        points={points}
        previewThreshold={threshold}
        totalTraces={traces.length}
        onActivePointChange={setSelectedPointId}
      />
      <p className="font-data mt-2 text-[9px] text-(--text-faint) min-[520px]:hidden">
        Scroll the plot horizontally to inspect the −1.0 to 1.0 score range.
      </p>

      <SimilarityTraceList
        activePointId={activePointId}
        points={recentPoints}
        onActivePointChange={setSelectedPointId}
      />

      <ThresholdControls
        appliedThreshold={appliedThreshold}
        canApplyThreshold={canApplyThreshold}
        isApplyingThreshold={isApplyingThreshold}
        threshold={threshold}
        onThresholdApply={onThresholdApply}
        onThresholdChange={onThresholdChange}
      />
    </section>
  );
}
