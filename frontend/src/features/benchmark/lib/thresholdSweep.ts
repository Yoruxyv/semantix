export const MIN_EVALUATION_THRESHOLDS = 2;
export const MAX_EVALUATION_THRESHOLDS = 15;

const SCALE = 10_000;

export interface ThresholdSweep {
  error: string | null;
  thresholds: number[];
}

function scaled(value: number): number {
  return Math.round(value * SCALE);
}

export function compileThresholdSweep(
  start: number,
  end: number,
  step: number,
  measuredThreshold: number,
): ThresholdSweep {
  if (
    ![start, end, step, measuredThreshold].every(Number.isFinite) ||
    start < 0 ||
    end > 1 ||
    measuredThreshold < 0 ||
    measuredThreshold > 1 ||
    start > end ||
    step <= 0
  ) {
    return {
      error: 'Use thresholds from 0 to 1, with start no greater than end.',
      thresholds: [],
    };
  }

  const startValue = scaled(start);
  const endValue = scaled(end);
  const stepValue = scaled(step);
  if (stepValue < 1) {
    return {
      error: 'Sweep step is too small.',
      thresholds: [],
    };
  }

  const values = new Set<number>([startValue, endValue, scaled(measuredThreshold)]);
  for (
    let value = startValue;
    value <= endValue && values.size <= MAX_EVALUATION_THRESHOLDS;
    value += stepValue
  ) {
    values.add(value);
  }

  const thresholds = [...values]
    .sort((left, right) => left - right)
    .map((value) => value / SCALE);
  if (thresholds.length > MAX_EVALUATION_THRESHOLDS) {
    return {
      error: `Choose at most ${MAX_EVALUATION_THRESHOLDS} thresholds, including the measured threshold.`,
      thresholds,
    };
  }
  if (thresholds.length < MIN_EVALUATION_THRESHOLDS) {
    return {
      error: `Choose at least ${MIN_EVALUATION_THRESHOLDS} unique thresholds, including the measured threshold.`,
      thresholds,
    };
  }

  return { error: null, thresholds };
}
