type DurationValue = number | null | undefined;

export interface FormatCompactDurationOptions {
  fallback?: string;
  secondFractionDigits?: number;
}

const DATE_TIME_FORMATTER = new Intl.DateTimeFormat(undefined, {
  dateStyle: 'medium',
  timeStyle: 'medium',
});

function isValidDuration(value: DurationValue): value is number {
  return value !== null && value !== undefined && Number.isFinite(value) && value >= 0;
}

export function formatCompactDuration(
  seconds: DurationValue,
  options: FormatCompactDurationOptions = {},
): string {
  const { fallback = 'n/a', secondFractionDigits = 0 } = options;

  if (!isValidDuration(seconds)) {
    return fallback;
  }

  if (seconds < 1) {
    return '<1 s';
  }

  if (seconds < 60) {
    return `${seconds.toFixed(secondFractionDigits)} s`;
  }

  const totalSeconds = Math.floor(seconds);
  const days = Math.floor(totalSeconds / 86_400);
  const hours = Math.floor((totalSeconds % 86_400) / 3_600);
  const minutes = Math.floor((totalSeconds % 3_600) / 60);
  const remainingSeconds = totalSeconds % 60;

  if (days > 0) {
    return `${days}d ${hours}h`;
  }

  if (hours > 0) {
    return `${hours}h ${minutes}m`;
  }

  return `${minutes}m ${remainingSeconds}s`;
}

export function formatHoursMinutesDuration(
  seconds: DurationValue,
  fallback = 'n/a',
): string {
  if (!isValidDuration(seconds)) {
    return fallback;
  }

  const totalSeconds = Math.floor(seconds);
  const hours = Math.floor(totalSeconds / 3_600);
  const minutes = Math.floor((totalSeconds % 3_600) / 60);

  return `${hours}h ${minutes}m`;
}

export function formatClockDuration(
  milliseconds: DurationValue,
  fallback = '00:00:00',
): string {
  if (!isValidDuration(milliseconds)) {
    return fallback;
  }

  const totalSeconds = Math.floor(milliseconds / 1_000);
  const hours = Math.floor(totalSeconds / 3_600);
  const minutes = Math.floor((totalSeconds % 3_600) / 60);
  const seconds = totalSeconds % 60;

  return [hours, minutes, seconds]
    .map((value) => value.toString().padStart(2, '0'))
    .join(':');
}

export function formatTimestamp(
  value: string | null | undefined,
  fallback = 'Never',
): string {
  if (value === null || value === undefined) {
    return fallback;
  }

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return fallback;
  }

  return DATE_TIME_FORMATTER.format(date);
}

export function formatTimeOfDay(value: Date, fallback = 'n/a'): string {
  if (Number.isNaN(value.getTime())) {
    return fallback;
  }

  return value.toLocaleTimeString([], {
    hour12: false,
  });
}
