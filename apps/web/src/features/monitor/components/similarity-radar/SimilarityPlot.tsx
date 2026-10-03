import { PlotBackdrop } from './PlotBackdrop';
import { SimilarityTooltip } from './SimilarityTooltip';
import { VIEW_HEIGHT, VIEW_WIDTH, type PlotPoint } from './model';
import { formatSimilarity } from '@/shared/lib/formatters';
import { cacheDecisionLabel } from '@/shared/domain/similarity';

import type { JSX } from 'react';

interface SimilarityPlotProps {
  activePointId: string | null;
  appliedThreshold: number;
  onActivePointChange: (pointId: string | null) => void;
  points: PlotPoint[];
  previewThreshold: number;
  totalTraces: number;
}

function pointLabel(point: PlotPoint): string {
  return [
    `Prompt: ${point.prompt}.`,
    `Similarity ${formatSimilarity(point.similarity)}.`,
    `Projected ${cacheDecisionLabel(point.isProjectedHit).toLowerCase()}.`,
    `Actual ${cacheDecisionLabel(point.actualCacheHit).toLowerCase()}.`,
  ].join(' ');
}

export function SimilarityPlot({
  activePointId,
  appliedThreshold,
  onActivePointChange,
  points,
  previewThreshold,
  totalTraces,
}: Readonly<SimilarityPlotProps>): JSX.Element {
  const activePoint = points.find((point) => point.id === activePointId) ?? null;

  return (
    <section
      aria-label="Scrollable similarity threshold plot"
      className="scrollbar-thin mt-3 overflow-x-auto pb-1"
    >
      <svg
        aria-label={`${points.length} of ${totalTraces} recent traces plotted on a minus-one-to-one similarity scale`}
        className="block w-full min-w-[500px]"
        viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
      >
        <PlotBackdrop
          appliedThreshold={appliedThreshold}
          previewThreshold={previewThreshold}
        />

        {points.map((point, index) => {
          const isActive = point.id === activePointId;
          const color = point.isProjectedHit ? 'var(--gold)' : 'var(--coral)';
          const baseRadius = index === 0 ? '7' : '5';
          const radius = isActive ? '8' : baseRadius;

          return (
            <g key={point.id} data-active={isActive ? 'true' : 'false'}>
              {isActive && (
                <circle
                  aria-hidden="true"
                  cx={point.x}
                  cy={point.y}
                  fill="none"
                  pointerEvents="none"
                  r="12"
                  stroke={color}
                  strokeOpacity="0.45"
                  strokeWidth="3"
                />
              )}
              <circle
                cx={point.x}
                cy={point.y}
                data-testid="similarity-point"
                data-trace-id={point.id}
                fill={color}
                r={radius}
                stroke={isActive ? 'var(--text)' : 'var(--ink)'}
                strokeWidth={isActive ? '3' : '2'}
              />
              <foreignObject height="24" width="24" x={point.x - 12} y={point.y - 12}>
                <button
                  aria-label={pointLabel(point)}
                  className="size-6 cursor-pointer bg-transparent p-0"
                  type="button"
                  onBlur={() => onActivePointChange(null)}
                  onClick={() => onActivePointChange(point.id)}
                  onFocus={() => onActivePointChange(point.id)}
                  onMouseEnter={() => onActivePointChange(point.id)}
                  onMouseLeave={() => onActivePointChange(null)}
                />
              </foreignObject>
            </g>
          );
        })}

        {activePoint !== null && <SimilarityTooltip point={activePoint} />}
      </svg>
    </section>
  );
}
