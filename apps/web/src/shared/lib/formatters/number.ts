type NumericValue = number | null | undefined;

const COUNT_FORMATTER = new Intl.NumberFormat();

function isFiniteNumber(value: NumericValue): value is number {
  return value !== null && value !== undefined && Number.isFinite(value);
}

export function formatCount(value: NumericValue, fallback = 'n/a'): string {
  return isFiniteNumber(value) ? COUNT_FORMATTER.format(value) : fallback;
}

export function formatBytes(value: NumericValue, fallback = 'n/a'): string {
  if (!isFiniteNumber(value) || value < 0) {
    return fallback;
  }
  if (value < 1_024) {
    return `${formatCount(value)} B`;
  }
  const units = ['KB', 'MB', 'GB'];
  let scaled = value;
  let unit = -1;
  do {
    scaled /= 1_024;
    unit += 1;
  } while (scaled >= 1_024 && unit < units.length - 1);
  return `${scaled.toFixed(scaled >= 10 ? 0 : 1)} ${units[unit]}`;
}

export function formatDecimal(
  value: NumericValue,
  fractionDigits = 1,
  fallback = 'n/a',
): string {
  return isFiniteNumber(value) ? value.toFixed(fractionDigits) : fallback;
}

export function formatPercent(
  value: NumericValue,
  fractionDigits = 1,
  fallback = 'n/a',
): string {
  return isFiniteNumber(value) ? `${(value * 100).toFixed(fractionDigits)}%` : fallback;
}

export function formatLatency(
  value: NumericValue,
  fractionDigits = 1,
  fallback = 'n/a',
): string {
  return isFiniteNumber(value) ? `${value.toFixed(fractionDigits)} ms` : fallback;
}

export function formatSimilarity(
  value: NumericValue,
  fractionDigits = 3,
  fallback = 'n/a',
): string {
  return formatDecimal(value, fractionDigits, fallback);
}

export function formatUsd(
  value: NumericValue,
  fractionDigits = 4,
  fallback = 'n/a',
): string {
  return isFiniteNumber(value) ? `$${value.toFixed(fractionDigits)}` : fallback;
}
