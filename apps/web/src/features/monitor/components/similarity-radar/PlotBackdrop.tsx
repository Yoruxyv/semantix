import {
  AXIS_Y,
  FIXED_TICKS,
  PLOT_BOTTOM,
  PLOT_LEFT,
  PLOT_RIGHT,
  PLOT_TOP,
  scoreToX,
} from './model';

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

      {FIXED_TICKS.map((tick) => {
        const x = scoreToX(tick);

        return (
          <g key={tick}>
            <line stroke="var(--hairline)" x1={x} x2={x} y1={PLOT_TOP} y2={AXIS_Y} />
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
        </>
      )}
    </>
  );
}
