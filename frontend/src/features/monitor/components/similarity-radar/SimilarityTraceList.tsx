import { formatSimilarity } from '@/shared/lib/formatters';
import { cacheDecisionLabel } from '@/shared/domain/similarity';
import { formatPrompt, type PlotPoint } from './model';

import type { JSX } from 'react';

interface SimilarityTraceListProps {
  activePointId: string | null;
  onActivePointChange: (pointId: string | null) => void;
  points: PlotPoint[];
}

const TRACE_HEADERS = ['Recent scored query', 'Score', 'Preview'] as const;

export function SimilarityTraceList({
  activePointId,
  onActivePointChange,
  points,
}: Readonly<SimilarityTraceListProps>): JSX.Element | null {
  if (points.length === 0) {
    return null;
  }

  return (
    <div className="mt-4">
      <div className="ui-label grid grid-cols-[minmax(0,1fr)_58px_52px] gap-3 border-b border-(--hairline) pb-2 text-(--text-faint)">
        {TRACE_HEADERS.map((header) => (
          <span
            className={header === 'Recent scored query' ? undefined : 'text-right'}
            key={header}
          >
            {header}
          </span>
        ))}
      </div>

      {points.map((point) => {
        const isActive = point.id === activePointId;
        const previewColor = point.isProjectedHit ? 'var(--gold)' : 'var(--coral-text)';

        return (
          <button
            aria-label={`Inspect ${point.prompt}. Similarity ${formatSimilarity(
              point.similarity,
            )}. Projected ${cacheDecisionLabel(point.isProjectedHit)}.`}
            className={`font-data grid min-h-10 w-full grid-cols-[minmax(0,1fr)_58px_52px] gap-3 border-b border-[rgba(234,230,221,0.05)] py-2.5 text-left text-[10px] outline-none transition-colors hover:bg-[rgba(234,230,221,0.025)] focus-visible:bg-[rgba(91,156,148,0.08)] ${
              isActive ? 'bg-[rgba(91,156,148,0.08)]' : ''
            }`}
            data-active={isActive ? 'true' : 'false'}
            key={point.id}
            type="button"
            onBlur={() => onActivePointChange(null)}
            onClick={() => onActivePointChange(point.id)}
            onFocus={() => onActivePointChange(point.id)}
            onMouseEnter={() => onActivePointChange(point.id)}
            onMouseLeave={() => onActivePointChange(null)}
          >
            <span
              className={
                isActive ? 'truncate text-(--text)' : 'truncate text-(--text-muted)'
              }
              title={point.prompt}
            >
              {formatPrompt(point.prompt)}
            </span>
            <span className="text-right text-(--teal)">
              {formatSimilarity(point.similarity)}
            </span>
            <span className="text-right" style={{ color: previewColor }}>
              {cacheDecisionLabel(point.isProjectedHit)}
            </span>
          </button>
        );
      })}
    </div>
  );
}
