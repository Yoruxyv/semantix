import { PlotBackdrop } from './PlotBackdrop';
import { SimilarityTooltip } from './SimilarityTooltip';
import {
  scoreToX,
  VIEW_HEIGHT,
  VIEW_WIDTH,
  type PlotPoint,
} from './model';
import { formatDecimal, formatSimilarity } from '@/shared/lib/formatters';
import { cacheDecisionLabel } from '@/shared/domain/similarity';

import type { JSX } from 'react';

const AXIS_LABEL_TICKS = [-1, -0.5, 0, 0.5, 1];

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
  const hasPendingThreshold = Math.abs(previewThreshold - appliedThreshold) >= 0.001;
  const markerLabelLeft = (score: number): string =>
    `clamp(0px, calc(${(scoreToX(score) / VIEW_WIDTH) * 100}% - 6.5ch), calc(100% - 13ch))`;

  return (
    <section aria-label="Similarity score visualization" className="mt-3 min-w-0">
      <div className="font-data mb-3">
        <div className="relative h-5 text-[11px]/5 text-(--gold)">
          <span
            className="absolute whitespace-nowrap"
            style={{ left: markerLabelLeft(appliedThreshold) }}
          >
            BACKEND {formatDecimal(appliedThreshold, 2)}
          </span>
        </div>

        <ul
          aria-label="Score reference bands"
          className="mt-2 flex flex-wrap justify-center gap-2 text-[11px]/5"
        >
          <li className="border border-white/10 bg-white/3 px-2 py-1 text-(--text-faint)">
            <span className="text-(--text-muted)">WEAK</span>{' '}
            <span>−1.00–0.75</span>
          </li>
          <li className="border border-(--gold)/20 bg-(--gold)/5 px-2 py-1 text-(--gold)">
            <span>REVIEW</span>{' '}
            <span>0.75–0.90</span>
          </li>
          <li className="border border-(--teal)/20 bg-(--teal)/5 px-2 py-1 text-(--teal)">
            <span>STRONG</span>{' '}
            <span>0.90–1.00</span>
          </li>
        </ul>
      </div>
      <svg
        aria-label={`${points.length} of ${totalTraces} recent traces plotted on a minus-one-to-one similarity scale`}
        className="block w-full"
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
      <div className="font-data relative -mt-3 h-5 text-[10px]/5 tracking-normal text-(--text-muted)">
        {AXIS_LABEL_TICKS.map((tick) => {
          const transform = 'translateX(-50%)';
          return (
            <span
              className="absolute top-0 whitespace-nowrap"
              key={tick}
              style={{ left: `${(scoreToX(tick) / VIEW_WIDTH) * 100}%`, transform }}
            >
              {formatDecimal(tick, 2)}
            </span>
          );
        })}
      </div>
      {hasPendingThreshold && (
        <div className="font-data relative mt-1 h-5 text-[11px]/5 text-(--teal)">
          <span
            className="absolute whitespace-nowrap"
            style={{ left: markerLabelLeft(previewThreshold) }}
          >
            PREVIEW {formatDecimal(previewThreshold, 2)}
          </span>
        </div>
      )}
    </section>
  );
}
