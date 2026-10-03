import { formatSimilarity } from '@/shared/lib/formatters';
import { cacheDecisionLabel } from '@/shared/domain/similarity';
import { PLOT_TOP, VIEW_HEIGHT, VIEW_WIDTH, type PlotPoint } from './model';

import type { JSX } from 'react';

const TOOLTIP_WIDTH = 270;
const TOOLTIP_HEIGHT = 104;
const TOOLTIP_GAP = 12;

interface SimilarityTooltipProps {
  point: PlotPoint;
}

interface TooltipItem {
  color: string;
  label: string;
  value: string;
}

function tooltipPosition(point: PlotPoint): {
  x: number;
  y: number;
} {
  const desiredX = point.x - TOOLTIP_WIDTH / 2;
  const x = Math.max(4, Math.min(VIEW_WIDTH - TOOLTIP_WIDTH - 4, desiredX));
  const desiredY =
    point.y > PLOT_TOP + TOOLTIP_HEIGHT
      ? point.y - TOOLTIP_HEIGHT - TOOLTIP_GAP
      : point.y + TOOLTIP_GAP;
  const y = Math.max(4, Math.min(VIEW_HEIGHT - TOOLTIP_HEIGHT - 4, desiredY));

  return { x, y };
}

export function SimilarityTooltip({
  point,
}: Readonly<SimilarityTooltipProps>): JSX.Element {
  const position = tooltipPosition(point);
  const tooltipItems = [
    {
      color: 'var(--text)',
      label: 'Score',
      value: formatSimilarity(point.similarity),
    },
    {
      color: point.isProjectedHit ? 'var(--gold)' : 'var(--coral-text)',
      label: 'Preview',
      value: cacheDecisionLabel(point.isProjectedHit),
    },
    {
      color: point.actualCacheHit ? 'var(--teal)' : 'var(--coral-text)',
      label: 'Actual',
      value: cacheDecisionLabel(point.actualCacheHit),
    },
  ] satisfies TooltipItem[];

  return (
    <foreignObject
      height={TOOLTIP_HEIGHT}
      pointerEvents="none"
      width={TOOLTIP_WIDTH}
      x={position.x}
      y={position.y}
    >
      <div
        className="h-full border border-(--teal) bg-(--surface) px-3 py-2.5 text-(--text) shadow-lg"
        role="tooltip"
      >
        <p className="ui-label text-(--teal)">Selected trace</p>
        <p className="mt-1 max-h-[34px] overflow-hidden wrap-break-word text-[11px] leading-[17px]">
          {point.prompt}
        </p>
        <div className="font-data mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[9px]">
          {tooltipItems.map((item) => (
            <span key={item.label} style={{ color: item.color }}>
              {item.label} {item.value}
            </span>
          ))}
        </div>
      </div>
    </foreignObject>
  );
}
