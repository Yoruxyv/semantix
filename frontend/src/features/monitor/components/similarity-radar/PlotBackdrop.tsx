import {
  AXIS_Y,
  FIXED_TICKS,
  PLOT_BOTTOM,
  PLOT_LEFT,
  PLOT_RIGHT,
  PLOT_TOP,
  scoreToX,
} from './model';
import { formatDecimal } from '@/shared/lib/formatters';

import type { JSX } from 'react';

interface PlotBackdropProps {
  appliedThreshold: number;
  previewThreshold: number;
}

export function PlotBackdrop({
  appliedThreshold,
  previewThreshold,
}: Readonly<PlotBackdropProps>): JSX.Element {
  const appliedThresholdX = scoreToX(appliedThreshold);
  const previewThresholdX = scoreToX(previewThreshold);
  const hasPendingThreshold = Math.abs(previewThreshold - appliedThreshold) >= 0.001;

  return (
    <>
      <rect
        fill="rgba(194, 96, 74, 0.07)"
        height={PLOT_BOTTOM - PLOT_TOP}
        width={scoreToX(0.75) - PLOT_LEFT}
        x={PLOT_LEFT}
        y={PLOT_TOP}
      />
      <rect
        fill="rgba(234, 230, 221, 0.025)"
        height={PLOT_BOTTOM - PLOT_TOP}
        width={scoreToX(0.9) - scoreToX(0.75)}
        x={scoreToX(0.75)}
        y={PLOT_TOP}
      />
      <rect
        fill="rgba(212, 161, 90, 0.07)"
        height={PLOT_BOTTOM - PLOT_TOP}
        width={PLOT_RIGHT - scoreToX(0.9)}
        x={scoreToX(0.9)}
        y={PLOT_TOP}
      />

      <text
        fill="var(--text-faint)"
        fontFamily="IBM Plex Mono"
        fontSize="9"
        x={PLOT_LEFT + 8}
        y={PLOT_TOP + 15}
      >
        WEAK
      </text>
      <text
        fill="var(--text-faint)"
        fontFamily="IBM Plex Mono"
        fontSize="9"
        x={scoreToX(0.75) + 8}
        y={PLOT_TOP + 15}
      >
        REVIEW
      </text>
      <text
        fill="var(--text-faint)"
        fontFamily="IBM Plex Mono"
        fontSize="9"
        x={scoreToX(0.9) + 8}
        y={PLOT_TOP + 15}
      >
        STRONG
      </text>

      {FIXED_TICKS.map((tick) => {
        const x = scoreToX(tick);

        return (
          <g key={tick}>
            <line stroke="var(--hairline)" x1={x} x2={x} y1={PLOT_TOP} y2={AXIS_Y} />
            <text
              fill="var(--text-faint)"
              fontFamily="IBM Plex Mono"
              fontSize="9"
              textAnchor="middle"
              x={x}
              y={AXIS_Y + 18}
            >
              {formatDecimal(tick, 2)}
            </text>
          </g>
        );
      })}

      <line
        stroke="var(--text-muted)"
        strokeWidth="1"
        x1={PLOT_LEFT}
        x2={PLOT_RIGHT}
        y1={AXIS_Y}
        y2={AXIS_Y}
      />
      <line
        stroke="var(--gold)"
        strokeWidth="2"
        x1={appliedThresholdX}
        x2={appliedThresholdX}
        y1={PLOT_TOP - 13}
        y2={AXIS_Y}
      />
      <text
        fill="var(--gold)"
        fontFamily="IBM Plex Mono"
        fontSize="9"
        textAnchor="middle"
        x={appliedThresholdX}
        y={PLOT_TOP - 20}
      >
        BACKEND {formatDecimal(appliedThreshold, 2)}
      </text>

      {hasPendingThreshold && (
        <>
          <line
            stroke="var(--teal)"
            strokeDasharray="5 4"
            strokeWidth="2"
            x1={previewThresholdX}
            x2={previewThresholdX}
            y1={PLOT_TOP}
            y2={AXIS_Y}
          />
          <text
            fill="var(--teal)"
            fontFamily="IBM Plex Mono"
            fontSize="9"
            textAnchor="middle"
            x={previewThresholdX}
            y={AXIS_Y + 32}
          >
            PREVIEW {formatDecimal(previewThreshold, 2)}
          </text>
        </>
      )}
    </>
  );
}
