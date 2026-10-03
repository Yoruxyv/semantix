import { describe, expect, it } from 'vitest';

import {
  formatClockDuration,
  formatCompactDuration,
  formatCount,
  formatDecimal,
  formatHoursMinutesDuration,
  formatLatency,
  formatPercent,
  formatSimilarity,
  formatTimestamp,
  formatUsd,
} from '@/shared/lib/formatters';

describe('shared formatters', () => {
  it('formats counts using the runtime locale', () => {
    expect(formatCount(1_000)).toBe(new Intl.NumberFormat().format(1_000));
  });

  it('formats missing and invalid numeric values with fallbacks', () => {
    expect(formatCount(null)).toBe('n/a');
    expect(formatDecimal(undefined, 2)).toBe('n/a');
    expect(formatPercent(Number.NaN)).toBe('n/a');
    expect(formatLatency(null)).toBe('n/a');
    expect(formatSimilarity(undefined)).toBe('n/a');
    expect(formatUsd(Number.NaN)).toBe('n/a');
  });

  it('formats decimals and domain measurements', () => {
    expect(formatDecimal(0.9234, 2)).toBe('0.92');
    expect(formatPercent(0.5)).toBe('50.0%');
    expect(formatLatency(12)).toBe('12.0 ms');
    expect(formatSimilarity(0.94567)).toBe('0.946');
    expect(formatUsd(0.01025)).toBe('$0.0103');
  });

  it('formats compact duration boundaries', () => {
    expect(formatCompactDuration(null)).toBe('n/a');
    expect(formatCompactDuration(-1)).toBe('n/a');
    expect(
      formatCompactDuration(null, {
        fallback: 'No expiry',
      }),
    ).toBe('No expiry');

    expect(formatCompactDuration(0)).toBe('<1 s');
    expect(formatCompactDuration(0.5)).toBe('<1 s');
    expect(formatCompactDuration(12)).toBe('12 s');
    expect(
      formatCompactDuration(12.34, {
        secondFractionDigits: 1,
      }),
    ).toBe('12.3 s');

    expect(formatCompactDuration(59)).toBe('59 s');
    expect(formatCompactDuration(60)).toBe('1m 0s');
    expect(formatCompactDuration(3_600)).toBe('1h 0m');
    expect(formatCompactDuration(86_400)).toBe('1d 0h');
  });

  it('formats hours and minutes', () => {
    expect(formatHoursMinutesDuration(3_660)).toBe('1h 1m');
    expect(formatHoursMinutesDuration(undefined)).toBe('n/a');
  });

  it('formats clock durations without wrapping hours', () => {
    expect(formatClockDuration(0)).toBe('00:00:00');
    expect(formatClockDuration(999)).toBe('00:00:00');
    expect(formatClockDuration(3_661_999)).toBe('01:01:01');
    expect(formatClockDuration(90_061_000)).toBe('25:01:01');
    expect(formatClockDuration(null, 'unavailable')).toBe('unavailable');
    expect(formatClockDuration(undefined)).toBe('00:00:00');
    expect(formatClockDuration(Number.NaN)).toBe('00:00:00');
    expect(formatClockDuration(-1)).toBe('00:00:00');
  });

  it('uses timestamp fallbacks without locale-sensitive assertions', () => {
    expect(formatTimestamp(null)).toBe('Never');
    expect(formatTimestamp(undefined)).toBe('Never');
    expect(formatTimestamp(null, 'No expiry')).toBe('No expiry');
    expect(formatTimestamp('invalid-date')).toBe('Never');
    expect(formatTimestamp('2026-07-17T10:00:00Z')).not.toBe('Never');
  });
});
